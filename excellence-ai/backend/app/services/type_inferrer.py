"""
type_inferrer.py — Infer column data types from raw cell values.
Produces Excel number-format strings and coerces values to proper Python types
so openpyxl writes numbers as numbers, dates as dates, percentages correctly, etc.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Union

# ── Patterns ──────────────────────────────────────────────────────────────────

_CURRENCY_SYMS = set("$£€¥₹")

_PCT_RE   = re.compile(r"^-?\d+(\.\d+)?\s*%$")
_INT_RE   = re.compile(r"^-?\d{1,3}(,\d{3})*$")
_DEC_RE   = re.compile(r"^-?\d+\.\d+$")
_DATE_RE  = re.compile(
    r"^\d{4}-\d{2}-\d{2}$"                      # ISO: 2024-01-15
    r"|^\d{1,2}/\d{1,2}/\d{2,4}$"               # US: 1/15/2024
    r"|^\d{1,2}-[A-Za-z]{3}-\d{2,4}$"           # 15-Jan-2024
)

_EMPTY_VALUES = {"", "-", "—", "n/a", "na", "null", "none", "n.a.", "n.a"}

# Mapping dominant type → Excel number-format string
_EXCEL_FMT: Dict[str, str] = {
    "currency": '$#,##0.00',
    "percent":  '0.00%',
    "integer":  '#,##0',
    "decimal":  '#,##0.00',
    "date":     'YYYY-MM-DD',
}


# ── Cell-level type detection ─────────────────────────────────────────────────

def _cell_type(raw: str) -> str:
    """Return 'currency'|'percent'|'integer'|'decimal'|'date'|'text'|'empty'."""
    v = raw.strip()
    if v.lower() in _EMPTY_VALUES:
        return "empty"
    if _PCT_RE.match(v):
        return "percent"
    if _DATE_RE.match(v):
        return "date"
    if v and v[0] in _CURRENCY_SYMS:
        num_part = v[1:].replace(",", "").strip()
        try:
            float(num_part)
            return "currency"
        except ValueError:
            pass
    if _INT_RE.match(v):
        return "integer"
    clean = v.replace(",", "")
    if _DEC_RE.match(clean):
        return "decimal"
    return "text"


# ── Column-level inference ────────────────────────────────────────────────────

def infer_formats(headers: List[str], rows: List[List[Any]]) -> Dict[str, str]:
    """
    Analyse every column and return {header: excel_format_string} for columns
    where ≥ 70 % of non-empty values agree on a consistent numeric/date type.
    Columns with mixed or text values are left unformatted.
    """
    if not rows or not headers:
        return {}

    ncols = len(headers)
    type_keys = ("currency", "percent", "integer", "decimal", "date", "text", "empty")
    votes: List[Dict[str, int]] = [{k: 0 for k in type_keys} for _ in range(ncols)]

    for row in rows:
        for i in range(ncols):
            cell = row[i] if i < len(row) else ""
            t = _cell_type(str(cell) if cell is not None else "")
            votes[i][t] += 1

    n = len(rows)
    result: Dict[str, str] = {}

    for i, hdr in enumerate(headers):
        v = votes[i]
        non_empty = n - v["empty"]
        if non_empty == 0:
            continue
        # Find dominant non-empty type
        best = max(
            (t for t in type_keys if t not in ("empty", "text")),
            key=lambda t: v[t],
        )
        ratio = v[best] / non_empty
        if ratio >= 0.70 and best in _EXCEL_FMT:
            result[hdr] = _EXCEL_FMT[best]

    return result


# ── Value coercion ────────────────────────────────────────────────────────────

def coerce_value(val: Any, excel_fmt: str) -> Union[float, int, str, Any]:
    """
    Convert a raw cell string to the Python type that openpyxl needs:
    - percent format  → float (0.0-1.0)
    - currency/number → float or int
    - anything else   → original value
    """
    if val is None:
        return ""
    v = str(val).strip()
    if v.lower() in _EMPTY_VALUES:
        return ""

    if excel_fmt == '0.00%':
        clean = v.rstrip("%").strip().replace(",", "")
        try:
            return round(float(clean) / 100, 6)
        except ValueError:
            return v

    if excel_fmt in ('$#,##0.00', '#,##0', '#,##0.00'):
        clean = re.sub(r"[$£€¥₹,\s]", "", v)
        try:
            f = float(clean)
            # Return int when the format is integer and value is whole
            if excel_fmt == '#,##0' and f == int(f):
                return int(f)
            return f
        except ValueError:
            return v

    return val


def coerce_rows(
    headers: List[str],
    rows: List[List[Any]],
    formats: Dict[str, str],
) -> List[List[Any]]:
    """
    Apply coerce_value to every cell in every row according to its column's format.
    Pass formats={} to skip coercion (pure text import).
    """
    if not formats:
        return rows

    result: List[List[Any]] = []
    for row in rows:
        new_row: List[Any] = []
        for i, cell in enumerate(row):
            hdr = headers[i] if i < len(headers) else ""
            fmt = formats.get(hdr, "")
            new_row.append(coerce_value(cell, fmt) if fmt else cell)
        result.append(new_row)
    return result
