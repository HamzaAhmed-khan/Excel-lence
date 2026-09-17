"""
chat.py — AI orchestration endpoint.
Phase I → II → III pipeline with preview-before-write and backup-before-write.
All previews share preview_store so /confirm works for chat AND extract endpoints.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.models import (
    AppliedResponse,
    ChatRequest,
    ConfirmRequest,
    Phase1Output,
    Phase2Output,
    Phase3Output,
    PreviewResponse,
    SheetData,
    CellEdit,
)
from app.routes.auth import require_auth
from app.services import audit, preview_store
from app.services.excel_engine import ExcelEngine
from app.services.groq_client import (
    SYSTEM_PHASE1_EXTRACT,
    SYSTEM_PHASE2_CALC,
    SYSTEM_PHASE3_CHART,
    chat_completion,
)
from app.services.intent_router import classify
from app.services.type_inferrer import coerce_rows, infer_formats
from app.services.web_scraper import scrape_url, table_to_tsv

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _build_sheet_context(sheet_data: SheetData) -> str:
    lines = [
        f"Sheet: {sheet_data.name}",
        f"Headers: {sheet_data.headers}",
        f"Row count: {len(sheet_data.rows)}",
        "Sample rows (first 5):",
    ]
    for row in sheet_data.rows[:5]:
        lines.append(f"  {row}")
    if sheet_data.tables:
        lines.append(f"Named tables: {sheet_data.tables}")
    return "\n".join(lines)


def _numeric_checksum_ok(proposed_rows: list, existing_rows: list, headers: list) -> bool:
    """Phase II guard: proposed numeric column sums must not deviate > 0.5% from source."""
    try:
        import pandas as pd
        if not existing_rows or not headers:
            return True
        df_e = pd.DataFrame(existing_rows, columns=headers)
        df_p = pd.DataFrame(proposed_rows, columns=headers)
        for col in headers:
            ex = pd.to_numeric(df_e[col], errors="coerce").dropna()
            pr = pd.to_numeric(df_p[col], errors="coerce").dropna()
            if len(ex) > 0 and len(pr) > 0:
                ex_sum = float(ex.sum())
                pr_sum = float(pr.sum())
                if ex_sum != 0 and abs((pr_sum - ex_sum) / ex_sum) > 0.005:
                    return False
        return True
    except Exception:
        return True


@router.post("")
async def chat(body: ChatRequest, request: Request):
    user = require_auth(request)
    preview_store.prune()

    try:
        eng = ExcelEngine.open(body.workbook)
    except FileNotFoundError:
        raise HTTPException(404, f"Workbook '{body.workbook}' not found")

    try:
        sheet_data = eng.read_sheet(body.sheet)
    except Exception as exc:
        raise HTTPException(400, f"Cannot read sheet '{body.sheet}': {exc}")

    # Optional URL attachment — scrape and inject as structured context
    extra_context = ""
    if body.attachment_url:
        result = scrape_url(body.attachment_url)
        if result.error:
            extra_context = f"[URL fetch failed: {result.error}]"
        elif result.has_tables:
            # Give the LLM the best table (most rows)
            best = max(result.tables, key=lambda t: t.row_count)
            extra_context = (
                f"[Scraped table '{best.caption}' from {body.attachment_url}]\n"
                + table_to_tsv(best, max_rows=200)
            )
        else:
            extra_context = f"[Page content from {body.attachment_url}]\n{result.page_text}"

    phase = classify(body.message)
    sheet_ctx = _build_sheet_context(sheet_data)

    user_content = body.message
    if extra_context:
        user_content += f"\n\n{extra_context[:10_000]}"
    user_content += f"\n\n[Current sheet context]\n{sheet_ctx}"

    # ── Phase I: Extract ──────────────────────────────────────────────────────
    if phase == "phase1":
        raw = chat_completion(
            system=SYSTEM_PHASE1_EXTRACT,
            user=user_content,
            json_mode=True,
        )
        try:
            output = Phase1Output(**raw)  # type: ignore[arg-type]
        except ValidationError as exc:
            raise HTTPException(422, f"AI response validation failed: {exc}")

        if output.clarify:
            return {"status": "clarify", "question": output.clarify}

        # Auto-infer number formats
        if not output.num_formats:
            output.num_formats = infer_formats(output.headers, output.rows)
        if output.num_formats:
            output.rows = coerce_rows(output.headers, output.rows, output.num_formats)

        preview_id = str(uuid.uuid4())
        preview_store.put(preview_id, {
            "phase":       "phase1",
            "workbook":    body.workbook,
            "sheet":       body.sheet,
            "output":      output.model_dump(),
            "user_prompt": body.message,
        })
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
            },
            audit=f"Extract {len(output.rows)} rows into '{output.sheet_name}'",
        )

    # ── Phase II: Calculate ───────────────────────────────────────────────────
    elif phase == "phase2":
        # Allow on empty sheet only for new_table — everything else needs data
        if not sheet_data.tables and not sheet_data.rows:
            # Ask Groq first to see if it picks new_table action
            raw_check = chat_completion(
                system=SYSTEM_PHASE2_CALC,
                user=user_content,
                json_mode=True,
            )
            if isinstance(raw_check, dict) and raw_check.get("action") not in ("new_table", None):
                raise HTTPException(
                    400,
                    "No data found on this sheet. Please extract or import data first (Phase I).",
                )
            # Fall through with already-fetched raw response
            raw = raw_check
        else:
            raw = chat_completion(
                system=SYSTEM_PHASE2_CALC,
                user=user_content,
                json_mode=True,
            )
        try:
            output = Phase2Output(**raw)  # type: ignore[arg-type]
        except ValidationError as exc:
            raise HTTPException(422, f"AI response validation failed: {exc}")

        if output.clarify:
            return {"status": "clarify", "question": output.clarify}

        if output.formulas:
            from app.services.excel_engine import _is_safe_formula
            for f in output.formulas:
                safe, reason = _is_safe_formula(f.formula)
                if not safe:
                    raise HTTPException(400, f"Unsafe formula rejected: {reason}")

        if output.action == "new_table" and output.new_table:
            nt = output.new_table
            if not _numeric_checksum_ok(nt.rows, sheet_data.rows, nt.headers):
                raise HTTPException(
                    409,
                    "Numeric checksum failed: proposed totals differ from source data by >0.5%. "
                    "Please review the AI output before applying.",
                )

        preview_id = str(uuid.uuid4())
        preview_store.put(preview_id, {
            "phase":       "phase2",
            "workbook":    body.workbook,
            "sheet":       body.sheet,
            "output":      output.model_dump(),
            "user_prompt": body.message,
        })
        proposed: Dict[str, Any] = {"action": output.action, "explanation": output.explanation}
        if output.formulas:
            proposed["formulas"] = [f.model_dump() for f in output.formulas]
        if output.new_table:
            proposed["new_table"] = {
                "headers":    output.new_table.headers,
                "rows":       output.new_table.rows[:5],
                "total_rows": len(output.new_table.rows),
                "sheet_name": output.new_table.sheet_name,
            }
        if output.cell_edits:
            proposed["cell_edits"] = [e.model_dump() for e in output.cell_edits]
        if output.row_indices:
            proposed["row_indices"] = output.row_indices
        if output.col_names:
            proposed["col_names"] = output.col_names
        if output.sort_by:
            proposed["sort_by"] = output.sort_by
            proposed["sort_ascending"] = output.sort_ascending
        return PreviewResponse(
            phase="phase2",
            preview_id=preview_id,
            proposed=proposed,
            audit=f"Phase II: {output.action} — {output.explanation[:100]}",
        )

    # ── Phase III: Chart ──────────────────────────────────────────────────────
    elif phase == "phase3":
        if not sheet_data.rows:
            raise HTTPException(
                400,
                "No data found on this sheet. Please extract or import data first (Phase I).",
            )

        raw = chat_completion(
            system=SYSTEM_PHASE3_CHART,
            user=user_content,
            json_mode=True,
        )
        try:
            output = Phase3Output(**raw)  # type: ignore[arg-type]
        except ValidationError as exc:
            raise HTTPException(422, f"AI response validation failed: {exc}")

        if output.clarify:
            return {"status": "clarify", "question": output.clarify}

        preview_id = str(uuid.uuid4())
        preview_store.put(preview_id, {
            "phase":       "phase3",
            "workbook":    body.workbook,
            "sheet":       body.sheet,
            "output":      output.model_dump(),
            "user_prompt": body.message,
        })
        return PreviewResponse(
            phase="phase3",
            preview_id=preview_id,
            proposed=output.model_dump(),
            audit=f"Phase III: {output.chart_type} chart — {output.title}",
        )

    # ── General ───────────────────────────────────────────────────────────────
    else:
        answer = chat_completion(
            system=(
                "You are ExcelLence AI, a helpful Excel assistant. "
                "Answer the user's question about their spreadsheet concisely."
            ),
            user=f"{body.message}\n\n[Sheet context]\n{sheet_ctx}",
            json_mode=False,
        )
        return {"status": "answer", "message": str(answer)}


@router.post("/confirm")
async def confirm(body: ConfirmRequest, request: Request):
    require_auth(request)

    entry = preview_store.get(body.preview_id)
    if not entry:
        raise HTTPException(404, "Preview not found or expired. Please re-submit your request.")

    try:
        eng = ExcelEngine.open(body.workbook)
    except FileNotFoundError:
        raise HTTPException(404, f"Workbook '{body.workbook}' not found")

    phase       = entry["phase"]
    output_data = entry["output"]
    user_prompt = entry.get("user_prompt", "")

    # ── Apply Phase I ─────────────────────────────────────────────────────────
    if phase == "phase1":
        output = Phase1Output(**output_data)
        eng.write_table(
            headers=output.headers,
            rows=output.rows,
            sheet_name=output.sheet_name,
            table_name=output.table_name,
            replace_sheet=False,
            num_formats=output.num_formats,
        )
        audit.log_action(
            eng, "phase1", user_prompt,
            f"Wrote table '{output.table_name}' with {len(output.rows)} rows",
            str(output.headers),
        )
        refreshed = eng.read_sheet(output.sheet_name)

    # ── Apply Phase II ────────────────────────────────────────────────────────
    elif phase == "phase2":
        output = Phase2Output(**output_data)
        sheet = entry["sheet"]
        if output.action == "formula" and output.formulas:
            eng.write_formulas_batch(sheet, [f.model_dump() for f in output.formulas])
            audit.log_action(
                eng, "phase2", user_prompt,
                f"Wrote {len(output.formulas)} formula(s)",
                str([f.model_dump() for f in output.formulas]),
            )
        elif output.action == "new_table" and output.new_table:
            nt = output.new_table
            eng.write_table(
                headers=nt.headers,
                rows=nt.rows,
                sheet_name=nt.sheet_name,
                start_cell=nt.start_cell,
                table_name=nt.table_name,
            )
            audit.log_action(
                eng, "phase2", user_prompt,
                f"Wrote calculated table '{nt.table_name}' on '{nt.sheet_name}'",
                str(nt.headers),
            )
            sheet = nt.sheet_name
        elif output.action == "edit_cells" and output.cell_edits:
            eng.edit_cells_batch(sheet, [e.model_dump() for e in output.cell_edits])
            audit.log_action(eng, "phase2", user_prompt,
                             f"Edited {len(output.cell_edits)} cell(s)", "")
        elif output.action == "delete_rows" and output.row_indices:
            eng.delete_rows_by_index(sheet, output.row_indices)
            audit.log_action(eng, "phase2", user_prompt,
                             f"Deleted rows {output.row_indices}", "")
        elif output.action == "delete_cols" and output.col_names:
            eng.delete_cols_by_name(sheet, output.col_names)
            audit.log_action(eng, "phase2", user_prompt,
                             f"Deleted columns {output.col_names}", "")
        elif output.action == "sort_table" and output.sort_by:
            eng.sort_sheet(sheet, output.sort_by, output.sort_ascending)
            audit.log_action(eng, "phase2", user_prompt,
                             f"Sorted by '{output.sort_by}' {'asc' if output.sort_ascending else 'desc'}", "")
        refreshed = eng.read_sheet(sheet)

    # ── Apply Phase III ───────────────────────────────────────────────────────
    elif phase == "phase3":
        output = Phase3Output(**output_data)
        sheet = entry["sheet"]
        eng.add_chart(
            sheet=sheet,
            chart_type=output.chart_type,
            data_range=output.data_range,
            title=output.title,
            anchor_cell=output.anchor_cell,
        )
        audit.log_action(
            eng, "phase3", user_prompt,
            f"Added {output.chart_type} chart '{output.title}'",
            output.data_range,
        )
        refreshed = eng.read_sheet(sheet)

    else:
        raise HTTPException(400, f"Unknown phase: {phase}")

    preview_store.delete(body.preview_id)

    chart_spec = output_data if phase == "phase3" else None
    return AppliedResponse(
        summary="Applied successfully.",
        refreshed_sheet=refreshed,
        chart_spec=chart_spec,
    )


@router.post("/undo")
async def undo_last(request: Request):
    import json as _json
    body_bytes = await request.body()
    body_data = _json.loads(body_bytes)
    require_auth(request)
    try:
        eng = ExcelEngine.open(body_data["workbook"])
    except FileNotFoundError:
        raise HTTPException(404, "Workbook not found")
    ok = eng.undo()
    if not ok:
        raise HTTPException(409, "No backup available to restore.")
    refreshed = eng.read_sheet(body_data["sheet"])
    return {"status": "applied", "summary": "Undo applied — previous state restored.", "refreshed_sheet": refreshed}
