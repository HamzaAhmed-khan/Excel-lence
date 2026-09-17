"""
filewatcher.py — Link a local .xlsx file to a workbook for two-way sync.
POST /api/filewatcher/link       — register path, import its content
POST /api/filewatcher/sync       — re-read from local path, overwrite workbook
POST /api/filewatcher/save-back  — write workbook back to local file
GET  /api/filewatcher/status/{workbook}
DELETE /api/filewatcher/unlink/{workbook}
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.routes.auth import require_auth
from app.services.excel_engine import ExcelEngine

router = APIRouter(prefix="/api/filewatcher", tags=["filewatcher"])

_REGISTRY_FILE = settings.workbook_dir.parent / "filewatcher.json"
_registry: dict = {}


def _load():
    global _registry
    if _REGISTRY_FILE.exists():
        try:
            _registry = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            _registry = {}


def _save():
    _REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY_FILE.write_text(json.dumps(_registry, indent=2), encoding="utf-8")


_load()


class LinkRequest(BaseModel):
    workbook: str
    local_path: str


class SyncRequest(BaseModel):
    workbook: str
    sheet: str = "Sheet1"


@router.post("/link")
async def link_file(body: LinkRequest, request: Request):
    require_auth(request)
    local = Path(body.local_path)
    if not local.exists():
        raise HTTPException(404, f"File not found: {body.local_path}")
    if local.suffix.lower() != ".xlsx":
        raise HTTPException(400, "Only .xlsx files can be linked")
    dest = settings.workbook_dir / body.workbook
    shutil.copy2(local, dest)
    _registry[body.workbook] = str(local)
    _save()
    try:
        eng = ExcelEngine.open(body.workbook)
        sheets = eng.list_sheets()
        refreshed = eng.read_sheet(sheets[0]) if sheets else None
        return {
            "ok": True,
            "workbook": body.workbook,
            "local_path": str(local),
            "sheets": sheets,
            "refreshed_sheet": refreshed.model_dump() if refreshed else None,
        }
    except Exception as exc:
        raise HTTPException(500, f"Linked but could not read: {exc}")


@router.post("/sync")
async def sync_from_file(body: SyncRequest, request: Request):
    require_auth(request)
    local_path = _registry.get(body.workbook)
    if not local_path:
        raise HTTPException(404, "No linked file for this workbook")
    local = Path(local_path)
    if not local.exists():
        raise HTTPException(404, f"Linked file no longer exists: {local_path}")
    dest = settings.workbook_dir / body.workbook
    shutil.copy2(local, dest)
    eng = ExcelEngine.open(body.workbook)
    sheets = eng.list_sheets()
    sheet = body.sheet if body.sheet in sheets else (sheets[0] if sheets else "Sheet1")
    refreshed = eng.read_sheet(sheet)
    return {"ok": True, "refreshed_sheet": refreshed.model_dump(), "sheets": sheets}


@router.post("/save-back")
async def save_back(body: SyncRequest, request: Request):
    require_auth(request)
    local_path = _registry.get(body.workbook)
    if not local_path:
        raise HTTPException(404, "No linked file for this workbook. Use Link File first.")
    source = settings.workbook_dir / body.workbook
    local = Path(local_path)
    try:
        shutil.copy2(source, local)
        return {"ok": True, "saved_to": str(local)}
    except PermissionError:
        raise HTTPException(403, f"Permission denied writing to: {local_path}")
    except Exception as exc:
        raise HTTPException(500, f"Save-back failed: {exc}")


@router.get("/status/{workbook}")
async def watch_status(workbook: str, request: Request):
    require_auth(request)
    local_path = _registry.get(workbook)
    if not local_path:
        return {"linked": False}
    return {
        "linked": True,
        "local_path": local_path,
        "filename": Path(local_path).name,
        "file_exists": Path(local_path).exists(),
    }


@router.delete("/unlink/{workbook}")
async def unlink_file(workbook: str, request: Request):
    require_auth(request)
    _registry.pop(workbook, None)
    _save()
    return {"ok": True}
