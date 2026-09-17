"""
audit.py — Thin wrapper that delegates audit writes to ExcelEngine.
Imported by routes/chat.py so audit logic stays out of the route layer.
"""
from __future__ import annotations

from app.services.excel_engine import ExcelEngine


def log_action(
    engine: ExcelEngine,
    phase: str,
    user_prompt: str,
    action_summary: str,
    detail: str = "",
):
    """Append a row to the hidden _Audit sheet. Failures are swallowed."""
    engine.append_audit(phase, user_prompt, action_summary, detail)
