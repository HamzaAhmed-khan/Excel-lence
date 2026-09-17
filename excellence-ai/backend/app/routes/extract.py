"""
extract.py — Phase I extraction endpoints.
  POST /api/extract/pdf        — PDF text → context for AI chat
  POST /api/extract/image      — Image → OCR/vision → preview
  POST /api/extract/url        — URL → scrape → preview (or multi-table disambiguation)
  POST /api/extract/url/select — User selects from multiple scraped tables → preview
All previews are confirmed via POST /api/chat/confirm.
"""
from __future__ import annotations

import io
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.models import (
    MultiTableResponse,
    Phase1Output,
    PreviewResponse,
    TableCandidateModel,
    UrlExtractRequest,
    UrlSelectRequest,
)
from app.routes.auth import require_auth
from app.services import preview_store
from app.services.groq_client import (
    SYSTEM_PHASE1_FROM_IMAGE,
    SYSTEM_PHASE1_FROM_OCR,
    SYSTEM_PHASE1_FROM_SCRAPED,
    chat_completion,
    vision_completion,
)
from app.services.type_inferrer import coerce_rows, infer_formats
from app.services.web_scraper import TableCandidate, scrape_url, table_to_tsv

router = APIRouter(prefix="/api/extract", tags=["extract"])

# ── Scrape session store (separate from preview_store) ────────────────────────
# Holds raw TableCandidate lists keyed by scrape_id until the user picks one.
_scrape_sessions: Dict[str, Dict[str, Any]] = {}
_SCRAPE_TTL = 600  # 10 min


def _prune_scrapes() -> None:
    now = time.time()
    stale = [k for k, v in _scrape_sessions.items() if now - v["ts"] > _SCRAPE_TTL]
    for k in stale:
        del _scrape_sessions[k]


# ── Shared helper: Groq → Phase1Output → preview ────────────────────────────

def _groq_to_preview(
    raw: Dict[str, Any],
    workbook: str,
    sheet: str,
    user_prompt: str,
    source_label: str,
) -> PreviewResponse:
    """
    Validate Groq output, run type inference, store preview, return PreviewResponse.
    Raises HTTPException on validation failure.
    """
    from pydantic import ValidationError

    if "clarify" in raw and raw["clarify"]:
        raise HTTPException(200, detail=raw["clarify"])  # caller handles clarify

    try:
        output = Phase1Output(**raw)
    except ValidationError as exc:
        raise HTTPException(422, f"AI response validation failed: {exc}")

    if output.clarify:
        raise HTTPException(200, detail=output.clarify)  # caller handles clarify

    # Auto-infer number formats if not already set
    if not output.num_formats:
        output.num_formats = infer_formats(output.headers, output.rows)

    # Coerce string values to proper Python types
    if output.num_formats:
        output.rows = coerce_rows(output.headers, output.rows, output.num_formats)

    preview_id = str(uuid.uuid4())
    preview_store.put(preview_id, {
        "phase":       "phase1",
        "workbook":    workbook,
        "sheet":       sheet,
        "output":      output.model_dump(),
        "user_prompt": user_prompt,
    })

    conf_pct = int(output.confidence * 100)
    return PreviewResponse(
        phase="phase1",
        preview_id=preview_id,
        proposed={
            "headers":     output.headers,
            "rows":        output.rows[:10],
            "total_rows":  len(output.rows),
            "sheet_name":  output.sheet_name,
            "table_name":  output.table_name,
            "confidence":  output.confidence,
            "num_formats": output.num_formats or {},
            "notes":       output.notes,
            "source":      source_label,
        },
        audit=f"Extract {len(output.rows)} rows ({conf_pct}% confidence) from {source_label}",
    )


# ── PDF ───────────────────────────────────────────────────────────────────────

@router.post("/pdf")
async def extract_pdf(
    request: Request,
    file: UploadFile = File(...),
    workbook: str = Form(default=""),
    sheet: str = Form(default="Sheet1"),
):
    """
    Extract text from a PDF, pass it to Groq to structure into a table,
    and return a Phase1 PreviewResponse — same flow as image extraction.
    workbook/sheet are optional; if omitted, returns just the text for the
    legacy chat-sendMessage path.
    """
    require_auth(request)
    preview_store.prune()

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are accepted")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "PDF too large — maximum 20 MB")

    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages_text: list[str] = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages_text.append(f"[Page {i + 1}]\n{text.strip()}")

        full_text = "\n\n".join(pages_text)
        if not full_text.strip():
            raise HTTPException(
                422,
                "No extractable text found in this PDF. "
                "It may be a scanned image — try uploading it as an image instead.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"PDF extraction failed: {exc}")

    # If no workbook provided, return raw text for backward compat
    if not workbook:
        return {
            "ok": True,
            "filename": file.filename,
            "pages": len(reader.pages),
            "text": full_text[:40_000],
            "truncated": len(full_text) > 40_000,
        }

    # Run Groq to structure the PDF content as a table
    user_msg = (
        f"PDF filename: {file.filename} ({len(reader.pages)} page(s))\n\n"
        f"Extracted text:\n{full_text[:12_000]}"
        + ("\n\n[Note: text was truncated to 12,000 chars]" if len(full_text) > 12_000 else "")
    )

    raw = chat_completion(
        system=SYSTEM_PHASE1_FROM_OCR,
        user=user_msg,
        json_mode=True,
    )

    if isinstance(raw, dict) and raw.get("clarify"):
        return {"status": "clarify", "question": raw["clarify"]}

    try:
        response = _groq_to_preview(
            raw=raw,
            workbook=workbook,
            sheet=sheet,
            user_prompt=f"Extract table from PDF: {file.filename}",
            source_label=f"PDF '{file.filename}'",
        )
        return response
    except HTTPException as exc:
        if exc.status_code == 200:
            return {"status": "clarify", "question": exc.detail}
        raise


# ── Image → table ─────────────────────────────────────────────────────────────

@router.post("/image")
async def extract_image(
    request: Request,
    file: UploadFile = File(...),
    workbook: str = Form(...),
    sheet: str = Form(...),
):
    """
    OCR an uploaded image, then use Groq (vision or text) to structure it
    into a Phase1Output preview that the user can confirm.
    """
    require_auth(request)
    preview_store.prune()

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
    ct = (file.content_type or "").lower()
    fname = (file.filename or "").lower()
    if ct not in allowed_types and not any(fname.endswith(e) for e in (".jpg", ".jpeg", ".png", ".webp", ".bmp")):
        raise HTTPException(400, "Unsupported image type. Upload a JPG, PNG, WEBP, or BMP file.")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(413, "Image too large — maximum 15 MB")

    # ── Try Groq vision first; fall back to OCR → text LLM ──────────────────
    from app.services.ocr_engine import image_data_url, run_ocr

    data_url = image_data_url(content)
    vision_prompt = (
        "Extract the complete table from this image into the required JSON format. "
        "Preserve all rows and columns exactly as shown."
    )

    try:
        raw = vision_completion(
            system=SYSTEM_PHASE1_FROM_IMAGE,
            text_prompt=vision_prompt,
            image_data_url=data_url,
            json_mode=True,
        )
    except Exception:
        # Vision unavailable — fall back to OCR + text LLM
        raw = None

    if raw is None or not isinstance(raw, dict) or "headers" not in raw:
        # OCR fallback
        ocr = run_ocr(content)
        if not ocr.text:
            raise HTTPException(
                422,
                ocr.error or "Could not extract text from the image. Try a clearer image.",
            )
        ocr_prompt = (
            f"OCR confidence: {ocr.confidence_label} ({int(ocr.confidence * 100)}%)\n\n"
            f"OCR text:\n{ocr.text[:8_000]}"
        )
        raw = chat_completion(
            system=SYSTEM_PHASE1_FROM_OCR,
            user=ocr_prompt,
            json_mode=True,
        )

    # Handle clarify response
    if isinstance(raw, dict) and raw.get("clarify"):
        return {"status": "clarify", "question": raw["clarify"]}

    try:
        response = _groq_to_preview(
            raw=raw,
            workbook=workbook,
            sheet=sheet,
            user_prompt=f"Extract table from image: {file.filename}",
            source_label=f"image '{file.filename}'",
        )
        return response
    except HTTPException as exc:
        if exc.status_code == 200:
            return {"status": "clarify", "question": exc.detail}
        raise


# ── URL → table(s) ────────────────────────────────────────────────────────────

@router.post("/url")
async def extract_url(body: UrlExtractRequest, request: Request):
    """
    Scrape a URL, detect tables.
    - Single table found  → Groq cleans it → returns preview
    - Multiple tables     → returns multi_table response for disambiguation
    - No HTML tables      → Groq uses page text → returns preview
    """
    require_auth(request)
    _prune_scrapes()
    preview_store.prune()

    result = scrape_url(body.url)

    if result.error:
        raise HTTPException(502, f"Could not fetch URL: {result.error}")

    # ── No HTML tables — try to extract from page text ────────────────────────
    if not result.has_tables:
        if not result.page_text.strip():
            raise HTTPException(422, "No tables or extractable content found at that URL.")

        user_msg = (
            f"URL: {body.url}\n"
            f"Page title: {result.page_title}\n\n"
            f"Page content (no HTML tables found — extract structured data from the text below):\n"
            f"{result.page_text}"
        )
        raw = chat_completion(
            system=SYSTEM_PHASE1_FROM_SCRAPED,
            user=user_msg,
            json_mode=True,
        )
        if isinstance(raw, dict) and raw.get("clarify"):
            return {"status": "clarify", "question": raw["clarify"]}

        try:
            response = _groq_to_preview(
                raw=raw,
                workbook=body.workbook,
                sheet=body.sheet,
                user_prompt=f"Extract table from URL: {body.url}",
                source_label=f"URL '{body.url}'",
            )
            return response
        except HTTPException as exc:
            if exc.status_code == 200:
                return {"status": "clarify", "question": exc.detail}
            raise

    # ── Single table — auto-select and run Groq ───────────────────────────────
    if len(result.tables) == 1:
        return await _process_selected_table(
            table=result.tables[0],
            workbook=body.workbook,
            sheet=body.sheet,
            url=body.url,
        )

    # ── Multiple tables — return disambiguation response ──────────────────────
    scrape_id = str(uuid.uuid4())
    _scrape_sessions[scrape_id] = {
        "ts":     time.time(),
        "url":    body.url,
        "tables": [t.to_dict() | {"_rows_full": t.rows} for t in result.tables],
    }

    return MultiTableResponse(
        scrape_id=scrape_id,
        page_title=result.page_title,
        url=body.url,
        tables=[
            TableCandidateModel(**t.to_dict())
            for t in result.tables
        ],
    )


@router.post("/url/select")
async def select_table(body: UrlSelectRequest, request: Request):
    """
    User selected a specific table from the multi-table disambiguation card.
    Run Groq to clean it and return a preview.
    """
    require_auth(request)

    session = _scrape_sessions.get(body.scrape_id)
    if not session:
        raise HTTPException(404, "Scrape session not found or expired. Please re-scrape the URL.")
    if time.time() - session["ts"] > _SCRAPE_TTL:
        del _scrape_sessions[body.scrape_id]
        raise HTTPException(410, "Scrape session expired. Please re-scrape the URL.")

    tables = session["tables"]
    if body.table_index < 0 or body.table_index >= len(tables):
        raise HTTPException(400, f"Invalid table index {body.table_index}. Found {len(tables)} tables.")

    raw_table = tables[body.table_index]
    tc = TableCandidate(
        index=raw_table["index"],
        caption=raw_table["caption"],
        headers=raw_table["headers"],
        rows=raw_table["_rows_full"],
        row_count=raw_table["row_count"],
    )

    return await _process_selected_table(
        table=tc,
        workbook=body.workbook,
        sheet=body.sheet,
        url=session["url"],
    )


async def _process_selected_table(
    table: TableCandidate,
    workbook: str,
    sheet: str,
    url: str,
) -> PreviewResponse:
    """Run Groq to clean a scraped TableCandidate and return a PreviewResponse."""
    tsv = table_to_tsv(table, max_rows=300)
    user_msg = (
        f"Table caption: {table.caption}\n"
        f"Source URL: {url}\n\n"
        f"Raw scraped data (tab-separated, {table.row_count} rows):\n"
        f"{tsv}"
    )
    raw = chat_completion(
        system=SYSTEM_PHASE1_FROM_SCRAPED,
        user=user_msg,
        json_mode=True,
    )

    if isinstance(raw, dict) and raw.get("clarify"):
        return {"status": "clarify", "question": raw["clarify"]}

    try:
        response = _groq_to_preview(
            raw=raw,
            workbook=workbook,
            sheet=sheet,
            user_prompt=f"Scraped '{table.caption}' from {url}",
            source_label=f"'{table.caption}' ({url})",
        )
        return response
    except HTTPException as exc:
        if exc.status_code == 200:
            return {"status": "clarify", "question": exc.detail}
        raise
