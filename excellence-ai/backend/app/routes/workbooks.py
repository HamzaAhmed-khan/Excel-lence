"""
workbooks.py — CRUD endpoints for .xlsx workbook files.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.models import WorkbookInfo, SheetData
from app.routes.auth import require_auth
from app.services.excel_engine import ExcelEngine

router = APIRouter(prefix="/api/workbooks", tags=["workbooks"])

_SAFE_NAME = re.compile(r"^[\w\- .]+\.xlsx$", re.IGNORECASE)


def _validate_name(name: str):
    if not _SAFE_NAME.match(name):
        raise HTTPException(400, "Invalid workbook name. Use letters, digits, hyphens, spaces only.")


@router.get("", response_model=List[WorkbookInfo])
async def list_workbooks(request: Request):
    require_auth(request)
    results = []
    for p in sorted(settings.workbook_dir.glob("*.xlsx")):
        try:
            eng = ExcelEngine.open(p.name)
            sheets = eng.list_sheets()
        except Exception:
            sheets = []
        results.append(
            WorkbookInfo(
                name=p.name,
                size_bytes=p.stat().st_size,
                modified=datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                sheets=sheets,
            )
        )
    return results


@router.post("", response_model=WorkbookInfo)
async def create_workbook(request: Request, body: dict):
    require_auth(request)
    name = body.get("name", "").strip()
    if not name.endswith(".xlsx"):
        name += ".xlsx"
    _validate_name(name)
    path = settings.workbook_dir / name
    if path.exists():
        raise HTTPException(409, f"Workbook '{name}' already exists")
    eng = ExcelEngine.create_new(name)
    # Create default sheet
    import openpyxl
    wb = openpyxl.load_workbook(path)
    if "Sheet" in wb.sheetnames:
        wb["Sheet"].title = "Sheet1"
        wb.save(path)
    return WorkbookInfo(
        name=name,
        size_bytes=path.stat().st_size,
        modified=datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        sheets=["Sheet1"],
    )


@router.post("/upload")
async def upload_workbook(request: Request, file: UploadFile = File(...)):
    require_auth(request)
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(400, "Only .xlsx files are accepted")
    name = Path(file.filename).name
    _validate_name(name)
    dest = settings.workbook_dir / name
    content = await file.read()
    dest.write_bytes(content)
    return {"ok": True, "name": name, "size_bytes": len(content)}


@router.get("/{name}", response_model=SheetData)
async def get_workbook(name: str, request: Request, sheet: str = "Summary"):
    require_auth(request)
    _validate_name(name)
    try:
        eng = ExcelEngine.open(name)
        sheets = eng.list_sheets()
        if sheet not in sheets:
            sheet = sheets[0] if sheets else "Sheet1"
        return eng.read_sheet(sheet)
    except FileNotFoundError:
        raise HTTPException(404, f"Workbook '{name}' not found")
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{name}/download")
async def download_workbook(name: str, request: Request):
    require_auth(request)
    _validate_name(name)
    path = settings.workbook_dir / name
    if not path.exists():
        raise HTTPException(404, f"Workbook '{name}' not found")
    return FileResponse(
        path=str(path),
        filename=name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/{name}/undo")
async def undo_workbook(name: str, request: Request, body: dict):
    require_auth(request)
    _validate_name(name)
    sheet = body.get("sheet", "Sheet1")
    try:
        eng = ExcelEngine.open(name)
        ok = eng.undo()
        if not ok:
            raise HTTPException(409, "No backup found.")
        sheets = eng.list_sheets()
        if sheet not in sheets:
            sheet = sheets[0]
        return eng.read_sheet(sheet)
    except FileNotFoundError:
        raise HTTPException(404, f"Workbook '{name}' not found")
