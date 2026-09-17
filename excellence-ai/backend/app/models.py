from __future__ import annotations
from typing import Optional, List, Dict, Any, Union, Literal
from pydantic import BaseModel, Field, field_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def email_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Email is required")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 4:
            raise ValueError("Password must be at least 4 characters")
        return v


# ── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    workbook: str
    sheet: str
    message: str
    attachment_url: Optional[str] = None
    image_b64: Optional[str] = None
    preview_id: Optional[str] = None


class ConfirmRequest(BaseModel):
    preview_id: str
    workbook: str
    sheet: str


# ── Phase I — Extraction ──────────────────────────────────────────────────────

class Phase1Output(BaseModel):
    headers: List[str]
    rows: List[List[Any]]
    sheet_name: str
    table_name: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: Optional[str] = None
    clarify: Optional[str] = None
    # Per-column Excel number-format strings; populated by type_inferrer
    num_formats: Optional[Dict[str, str]] = None


# ── Phase II — Calculation ────────────────────────────────────────────────────

class FormulaItem(BaseModel):
    cell: str
    formula: str

    @field_validator("formula")
    @classmethod
    def formula_starts_with_equals(cls, v: str) -> str:
        if not v.startswith("="):
            raise ValueError(f"Formula must start with '=', got: {v!r}")
        return v


class CellEdit(BaseModel):
    cell: str   # Excel cell ref, e.g. "B3"
    value: Any  # new value; if str starts with "=" it's a formula


class NewTableSpec(BaseModel):
    headers: List[str]
    rows: List[List[Any]]
    sheet_name: str
    start_cell: str = "A1"
    table_name: Optional[str] = None


class Phase2Output(BaseModel):
    action: Literal["formula", "new_table", "edit_cells", "delete_rows", "delete_cols", "sort_table"]
    formulas: Optional[List[FormulaItem]] = None
    new_table: Optional[NewTableSpec] = None
    cell_edits: Optional[List[CellEdit]] = None     # for edit_cells
    row_indices: Optional[List[int]] = None          # for delete_rows (Excel row numbers, row 1=header)
    col_names: Optional[List[str]] = None            # for delete_cols (header text)
    sort_by: Optional[str] = None                    # for sort_table
    sort_ascending: bool = True
    explanation: str
    clarify: Optional[str] = None


# ── Phase III — Chart ─────────────────────────────────────────────────────────

class Phase3Output(BaseModel):
    chart_type: Literal["bar", "column", "line", "pie", "scatter"]
    data_range: str
    title: str
    x_axis: Optional[str] = None
    y_axis: Optional[str] = None
    anchor_cell: str = "J2"
    color: Optional[str] = None
    clarify: Optional[str] = None


# ── Scraping / extraction ─────────────────────────────────────────────────────

class TableCandidateModel(BaseModel):
    """A single table found during URL scraping, sent to the frontend for disambiguation."""
    index: int
    caption: str
    headers: List[str]
    preview_rows: List[List[str]]
    row_count: int


class UrlExtractRequest(BaseModel):
    url: str
    workbook: str
    sheet: str


class UrlSelectRequest(BaseModel):
    scrape_id: str
    table_index: int
    workbook: str
    sheet: str


# ── API Responses ─────────────────────────────────────────────────────────────

class CellData(BaseModel):
    value: Any
    formatted: Optional[str] = None
    formula: Optional[str] = None
    number_format: Optional[str] = None


class SheetData(BaseModel):
    name: str
    headers: List[str]
    rows: List[List[Any]]
    formatted_rows: Optional[List[List[str]]] = None
    col_widths: Optional[List[int]] = None
    num_formats: Optional[Dict[str, str]] = None
    tables: Optional[List[str]] = None


class PreviewResponse(BaseModel):
    status: Literal["preview"] = "preview"
    phase: str
    preview_id: str
    proposed: Dict[str, Any]
    audit: str
    clarify: Optional[str] = None


class MultiTableResponse(BaseModel):
    """Returned when URL scraping finds multiple tables — user must pick one."""
    status: Literal["multi_table"] = "multi_table"
    scrape_id: str
    page_title: str
    url: str
    tables: List[TableCandidateModel]


class AppliedResponse(BaseModel):
    status: Literal["applied"] = "applied"
    summary: str
    refreshed_sheet: SheetData
    chart_spec: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    error: str
    code: str


class WorkbookInfo(BaseModel):
    name: str
    size_bytes: int
    modified: str
    sheets: List[str]


class HealthResponse(BaseModel):
    status: str
    groq_configured: bool
    storage_writable: bool
