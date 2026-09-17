"""
preview_store.py — Shared in-memory preview store.
Used by both chat.py and extract.py so all previews confirm via one endpoint.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

_store: Dict[str, Dict[str, Any]] = {}
TTL = 600  # 10 minutes


def put(preview_id: str, data: Dict[str, Any]) -> None:
    _store[preview_id] = {"ts": time.time(), **data}


def get(preview_id: str) -> Optional[Dict[str, Any]]:
    entry = _store.get(preview_id)
    if not entry:
        return None
    if time.time() - entry["ts"] > TTL:
        del _store[preview_id]
        return None
    return entry


def delete(preview_id: str) -> None:
    _store.pop(preview_id, None)


def prune() -> None:
    now = time.time()
    expired = [k for k, v in _store.items() if now - v["ts"] > TTL]
    for k in expired:
        del _store[k]
