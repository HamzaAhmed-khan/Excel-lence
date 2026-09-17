"""
excel_engine.py — The ONLY module that touches .xlsx files directly.
All openpyxl operations live here. Every write is preceded by a backup.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, ScatterChart, Reference
from openpyxl.chart.series import SeriesLabel
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side, numbers
)
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.cell import coordinate_from_string
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.config import settings
from app.models import SheetData

# ── Colours ───────────────────────────────────────────────────────────────────
_GREEN_FILL = PatternFill("solid", fgColor="ECFDF5")
_TOTAL_FILL = PatternFill("solid", fgColor="F1F8E9")
_HEADER_FONT = Font(bold=True, color="047857", name="Calibri", size=11)
_BODY_FONT = Font(name="Calibri", size=11)
_TOTAL_FONT = Font(bold=True, name="Calibri", size=11)
_THIN = Side(style="thin", color="E5E7EB")
_THIN_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_MEDIUM_TOP = Side(style="medium", color="047857")

# Unsafe formula patterns — never write these
_FORBIDDEN_PATTERNS = [
    r"INDIRECT\s*\(", r"WEBSERVICE\s*\(", r"\[.+\]",  # external links
    r"'https?://", r"DDE\s*\(",
]


def _is_safe_formula(formula: str) -> Tuple[bool, str]:
    for pat in _FORBIDDEN_PATTERNS:
        if re.search(pat, formula, re.IGNORECASE):
            return False, f"Forbidden pattern detected: {pat}"
    return True, ""


class ExcelEngine:
    """Wraps a single .xlsx workbook file."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self._wb: Optional[Workbook] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @classmethod
    def create_new(cls, filename: str) -> "ExcelEngine":
        path = settings.workbook_dir / filename
        wb = Workbook()
        wb.save(path)
        return cls(path)

    @classmethod
    def open(cls, filename: str) -> "ExcelEngine":
        path = settings.workbook_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Workbook not found: {filename}")
        return cls(path)

    def _load(self) -> Workbook:
        return openpyxl.load_workbook(self.filepath)

    def _save(self, wb: Workbook):
        wb.save(self.filepath)

    def _backup(self):
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dest = settings.backup_dir / f"{self.filepath.stem}_{ts}.xlsx"
        shutil.copy2(self.filepath, dest)

    # ── Read ──────────────────────────────────────────────────────────────────

    def list_sheets(self) -> List[str]:
        wb = self._load()
        return [s for s in wb.sheetnames if s != "_Audit"]

    def read_sheet(
        self, sheet_name: str, max_rows: int = 200, max_cols: int = 50
    ) -> SheetData:
        wb = self._load()
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"Sheet '{sheet_name}' not found")
        ws = wb[sheet_name]

        all_rows = []
        for row in ws.iter_rows(max_row=max_rows, max_col=max_cols, values_only=False):
            cells = []
            for cell in row:
                val = cell.value
                if val is None:
                    cells.append("")
                elif isinstance(val, (int, float)):
                    cells.append(val)
                else:
                    cells.append(str(val))
            all_rows.append(cells)

        # Trim trailing empty rows
        while all_rows and all(v == "" for v in all_rows[-1]):
            all_rows.pop()

        headers: List[str] = []
        rows: List[List[Any]] = []
        if all_rows:
            headers = [str(h) if h != "" else f"Col{i+1}" for i, h in enumerate(all_rows[0])]
            rows = all_rows[1:]

        # Collect number formats per column letter
        num_formats: Dict[str, str] = {}
        if ws.max_row and ws.max_column:
            for col_idx in range(1, min(ws.max_column + 1, max_cols + 1)):
                for row_idx in range(2, min(ws.max_row + 1, 5)):
                    cell = ws.cell(row_idx, col_idx)
                    if cell.number_format and cell.number_format != "General":
                        num_formats[get_column_letter(col_idx)] = cell.number_format
                        break

        # Table names
        table_names = [t.name for t in ws.tables.values()]

        return SheetData(
            name=sheet_name,
            headers=headers,
            rows=rows,
            num_formats=num_formats,
            tables=table_names,
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    def write_table(
        self,
        headers: List[str],
        rows: List[List[Any]],
        sheet_name: str,
        start_cell: str = "A1",
        table_name: Optional[str] = None,
        replace_sheet: bool = False,
        num_formats: Optional[Dict[str, str]] = None,
    ):
        """
        Write a table to the workbook.
        num_formats: {column_header: excel_format_string} — applied to every data cell
        in that column (e.g. {'Revenue': '$#,##0.00', 'Growth': '0.00%'}).
        """
        self._backup()
        try:
            wb = self._load()
            if replace_sheet and sheet_name in wb.sheetnames:
                del wb[sheet_name]
            if sheet_name not in wb.sheetnames:
                wb.create_sheet(sheet_name)
            ws = wb[sheet_name]

            sc = coordinate_from_string(start_cell)
            start_col = column_index_from_string(sc[0])
            start_row = sc[1]

            # Write header row
            for ci, h in enumerate(headers):
                cell = ws.cell(start_row, start_col + ci, h)
                cell.font = _HEADER_FONT
                cell.fill = _GREEN_FILL
                cell.border = _THIN_BORDER
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Write data rows with optional number formatting
            for ri, row in enumerate(rows):
                for ci, val in enumerate(row):
                    cell = ws.cell(start_row + 1 + ri, start_col + ci, val)
                    cell.border = _THIN_BORDER
                    cell.font = _BODY_FONT

                    # Apply column number format if provided
                    hdr = headers[ci] if ci < len(headers) else ""
                    fmt = (num_formats or {}).get(hdr, "")
                    if fmt:
                        cell.number_format = fmt

                    if isinstance(val, (int, float)):
                        cell.alignment = Alignment(horizontal="right")
                    else:
                        cell.alignment = Alignment(horizontal="left")

            # Auto-fit column widths
            for ci, h in enumerate(headers):
                col_letter = get_column_letter(start_col + ci)
                max_len = len(str(h))
                for ri in range(len(rows)):
                    v = rows[ri][ci] if ci < len(rows[ri]) else ""
                    max_len = max(max_len, len(str(v)))
                ws.column_dimensions[col_letter].width = min(max_len + 4, 40)

            # Register as an Excel ListObject table
            if table_name:
                end_col = get_column_letter(start_col + len(headers) - 1)
                end_row = start_row + len(rows)
                ref = f"{start_cell}:{end_col}{end_row}"
                existing = [t for t in ws.tables if t == table_name]
                for t in existing:
                    del ws.tables[t]
                tbl = Table(displayName=table_name, ref=ref)
                style = TableStyleInfo(
                    name="TableStyleMedium7",
                    showFirstColumn=False,
                    showLastColumn=False,
                    showRowStripes=True,
                    showColumnStripes=False,
                )
                tbl.tableStyleInfo = style
                ws.add_table(tbl)

            self._save(wb)
        except Exception as e:
            self._restore_latest_backup()
            raise RuntimeError(f"write_table failed and was rolled back: {e}") from e

    def write_formula(self, sheet: str, cell: str, formula: str):
        if not formula.startswith("="):
            raise ValueError(f"Formula must start with '=': {formula!r}")
        safe, reason = _is_safe_formula(formula)
        if not safe:
            raise ValueError(f"Unsafe formula rejected: {reason}")

        self._backup()
        try:
            wb = self._load()
            ws = wb[sheet]
            ws[cell] = formula
            self._save(wb)
        except Exception as e:
            self._restore_latest_backup()
            raise RuntimeError(f"write_formula failed: {e}") from e

    def write_formulas_batch(self, sheet: str, formulas: List[Dict[str, str]]):
        for f in formulas:
            if not f["formula"].startswith("="):
                raise ValueError(f"Formula must start with '=': {f['formula']!r}")
            safe, reason = _is_safe_formula(f["formula"])
            if not safe:
                raise ValueError(f"Unsafe formula rejected: {reason}")

        self._backup()
        try:
            wb = self._load()
            ws = wb[sheet]
            for f in formulas:
                ws[f["cell"]] = f["formula"]
                ws[f["cell"]].font = _BODY_FONT
                ws[f["cell"]].border = _THIN_BORDER
            self._save(wb)
        except Exception as e:
            self._restore_latest_backup()
            raise RuntimeError(f"write_formulas_batch failed: {e}") from e

    def edit_cells_batch(self, sheet: str, edits: list):
        """Apply {cell, value} pairs. Formulas must start with '='."""
        self._backup()
        try:
            wb = self._load()
            ws = wb[sheet]
            for e in edits:
                cell_ref = e["cell"]
                val = e["value"]
                if isinstance(val, str) and val.startswith("="):
                    safe, reason = _is_safe_formula(val)
                    if not safe:
                        raise ValueError(f"Unsafe formula: {reason}")
                ws[cell_ref] = val
                ws[cell_ref].font = _BODY_FONT
                ws[cell_ref].border = _THIN_BORDER
            self._save(wb)
        except Exception as exc:
            self._restore_latest_backup()
            raise RuntimeError(f"edit_cells_batch failed: {exc}") from exc

    def delete_rows_by_index(self, sheet: str, row_indices: list):
        """Delete rows by Excel row numbers (1-based; row 1 = header, row 2 = first data row).
        Deletes in reverse order to preserve row positions during deletion."""
        self._backup()
        try:
            wb = self._load()
            ws = wb[sheet]
            for row_num in sorted(row_indices, reverse=True):
                ws.delete_rows(row_num)
            self._save(wb)
        except Exception as exc:
            self._restore_latest_backup()
            raise RuntimeError(f"delete_rows_by_index failed: {exc}") from exc

    def delete_cols_by_name(self, sheet: str, col_names: list):
        """Delete columns identified by their header cell value (case-insensitive match)."""
        self._backup()
        try:
            wb = self._load()
            ws = wb[sheet]
            header_row = [cell.value for cell in ws[1]]
            col_indices = []
            for name in col_names:
                for ci, h in enumerate(header_row, 1):
                    if str(h or "").strip().lower() == name.strip().lower():
                        col_indices.append(ci)
                        break
            for ci in sorted(col_indices, reverse=True):
                ws.delete_cols(ci)
            self._save(wb)
        except Exception as exc:
            self._restore_latest_backup()
            raise RuntimeError(f"delete_cols_by_name failed: {exc}") from exc

    def sort_sheet(self, sheet: str, sort_by: str, ascending: bool = True):
        """Sort all data rows (keeping header row 1 in place) by a named column."""
        self._backup()
        try:
            wb = self._load()
            ws = wb[sheet]
            all_values = list(ws.iter_rows(values_only=True))
            if len(all_values) < 2:
                return
            headers = list(all_values[0])
            data = [list(r) for r in all_values[1:]]
            try:
                col_idx = next(i for i, h in enumerate(headers)
                               if str(h or "").strip().lower() == sort_by.strip().lower())
            except StopIteration:
                raise ValueError(f"Column '{sort_by}' not found in: {headers}")

            def _key(row):
                v = row[col_idx]
                if v is None:
                    return (1, "")
                if isinstance(v, (int, float)):
                    return (0, v)
                return (0, str(v).lower())

            data.sort(key=_key, reverse=not ascending)
            for ri, row in enumerate(data, 2):
                for ci, val in enumerate(row, 1):
                    ws.cell(ri, ci).value = val
            self._save(wb)
        except Exception as exc:
            self._restore_latest_backup()
            raise RuntimeError(f"sort_sheet failed: {exc}") from exc

    def undo(self) -> bool:
        """Restore the most recent backup. Returns True if a backup existed."""
        backups = sorted(settings.backup_dir.glob(f"{self.filepath.stem}_*.xlsx"))
        if not backups:
            return False
        shutil.copy2(backups[-1], self.filepath)
        return True

    def apply_number_format(self, sheet: str, range_str: str, fmt: str):
        wb = self._load()
        ws = wb[sheet]
        for row in ws[range_str]:
            for cell in row:
                cell.number_format = fmt
        self._save(wb)

    def add_chart(
        self,
        sheet: str,
        chart_type: str,
        data_range: str,
        title: str,
        anchor_cell: str = "J2",
    ):
        self._backup()
        try:
            wb = self._load()
            ws = wb[sheet]

            # Parse range like "A1:B10"
            parts = data_range.split(":")
            if len(parts) != 2:
                raise ValueError(f"Invalid data_range: {data_range}")
            tl = coordinate_from_string(parts[0])
            br = coordinate_from_string(parts[1])
            tl_col = column_index_from_string(tl[0])
            br_col = column_index_from_string(br[0])

            chart_map = {
                "bar": BarChart, "column": BarChart,
                "line": LineChart, "pie": PieChart, "scatter": ScatterChart,
            }
            ChartClass = chart_map.get(chart_type, BarChart)
            chart = ChartClass()
            chart.title = title
            chart.style = 10

            if chart_type == "bar":
                chart.type = "bar"
                chart.grouping = "clustered"
            elif chart_type == "column":
                chart.type = "col"
                chart.grouping = "clustered"

            # Data reference (all columns)
            data = Reference(
                ws,
                min_col=tl_col + 1,
                max_col=br_col,
                min_row=tl[1],
                max_row=br[1],
            )
            cats = Reference(
                ws, min_col=tl_col, min_row=tl[1] + 1, max_row=br[1]
            )
            chart.add_data(data, titles_from_data=True)
            if chart_type != "scatter":
                chart.set_categories(cats)

            chart.width = 18
            chart.height = 12
            ws.add_chart(chart, anchor_cell)
            self._save(wb)
        except Exception as e:
            self._restore_latest_backup()
            raise RuntimeError(f"add_chart failed: {e}") from e

    def style_total_row(self, sheet: str, row_num: int, num_cols: int):
        wb = self._load()
        ws = wb[sheet]
        top_border = Side(style="medium", color="047857")
        for ci in range(1, num_cols + 1):
            cell = ws.cell(row_num, ci)
            cell.fill = _TOTAL_FILL
            cell.font = _TOTAL_FONT
            cell.border = Border(
                left=_THIN, right=_THIN,
                top=top_border, bottom=_THIN,
            )
        self._save(wb)

    def ensure_sheet(self, sheet_name: str):
        wb = self._load()
        if sheet_name not in wb.sheetnames:
            wb.create_sheet(sheet_name)
            self._save(wb)

    # ── Audit ─────────────────────────────────────────────────────────────────

    def append_audit(
        self,
        phase: str,
        user_prompt: str,
        action_summary: str,
        formula_or_data: str = "",
    ):
        try:
            wb = self._load()
            if "_Audit" not in wb.sheetnames:
                ws = wb.create_sheet("_Audit")
                ws.append(["Timestamp", "Phase", "User Prompt", "Action", "Detail"])
                ws.sheet_state = "hidden"
            else:
                ws = wb["_Audit"]
            ws.append([
                datetime.utcnow().isoformat(),
                phase,
                user_prompt[:500],
                action_summary[:500],
                formula_or_data[:1000],
            ])
            self._save(wb)
        except Exception:
            pass  # Audit failure must never break the main flow

    # ── Recovery ──────────────────────────────────────────────────────────────

    def _restore_latest_backup(self):
        backups = sorted(settings.backup_dir.glob(f"{self.filepath.stem}_*.xlsx"))
        if backups:
            shutil.copy2(backups[-1], self.filepath)

