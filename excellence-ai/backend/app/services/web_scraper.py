"""
web_scraper.py — Structured URL scraping with multi-table detection.
Returns TableCandidate objects; never raw text blobs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TableCandidate:
    index: int
    caption: str
    headers: List[str]
    rows: List[List[str]]
    row_count: int

    def preview(self, n: int = 3) -> List[List[str]]:
        return self.rows[:n]

    def to_dict(self) -> dict:
        return {
            "index":       self.index,
            "caption":     self.caption,
            "headers":     self.headers,
            "preview_rows": self.preview(3),
            "row_count":   self.row_count,
        }


@dataclass
class ScrapeResult:
    url: str
    page_title: str
    tables: List[TableCandidate]
    page_text: str           # fallback for LLM when no <table> found
    error: Optional[str] = None

    @property
    def has_tables(self) -> bool:
        return bool(self.tables)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _parse_tables(soup) -> List[TableCandidate]:
    """Extract every <table> element as a normalised TableCandidate."""
    candidates: List[TableCandidate] = []

    for table_el in soup.find_all("table"):
        # Caption: explicit <caption>, otherwise nearest preceding heading
        cap_el = table_el.find("caption")
        if cap_el:
            caption = _clean(cap_el.get_text())
        else:
            prev_h = table_el.find_previous(["h1", "h2", "h3", "h4"])
            caption = (_clean(prev_h.get_text())[:80] if prev_h else "") or f"Table {len(candidates) + 1}"

        all_rows: List[List[str]] = []
        header_row_idx: int = -1

        for tr in table_el.find_all("tr"):
            cells: List[str] = []
            for cell in tr.find_all(["th", "td"]):
                try:
                    colspan = max(1, int(cell.get("colspan", 1)))
                except (TypeError, ValueError):
                    colspan = 1
                cells.extend([_clean(cell.get_text())] * colspan)

            if any(c for c in cells):
                if header_row_idx == -1 and tr.find("th"):
                    header_row_idx = len(all_rows)
                all_rows.append(cells)

        if not all_rows:
            continue

        # Separate header from data
        if header_row_idx >= 0:
            headers   = all_rows[header_row_idx]
            data_rows = [r for i, r in enumerate(all_rows) if i != header_row_idx]
        else:
            headers   = all_rows[0]
            data_rows = all_rows[1:]

        # Skip degenerate tables (< 2 columns or no data rows)
        if len(headers) < 2 or not data_rows:
            continue

        # Normalise every row to the same column count
        ncols = len(headers)
        norm: List[List[str]] = []
        for row in data_rows:
            if len(row) < ncols:
                row = row + [""] * (ncols - len(row))
            norm.append(row[:ncols])

        candidates.append(TableCandidate(
            index=len(candidates),
            caption=caption,
            headers=headers,
            rows=norm,
            row_count=len(norm),
        ))

    return candidates


# ── Public API ────────────────────────────────────────────────────────────────

def scrape_url(url: str) -> ScrapeResult:
    """
    Fetch URL, extract structured tables, return ScrapeResult.
    Falls back to page_text if no HTML tables found.
    """
    try:
        import requests
        from bs4 import BeautifulSoup

        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=20,
            allow_redirects=True,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        title_el = soup.find("title")
        page_title = title_el.get_text(strip=True) if title_el else url

        # Strip noise before table extraction
        for tag in soup(["script", "style", "nav", "footer", "aside", "noscript", "iframe"]):
            tag.decompose()

        tables = _parse_tables(soup)

        # Fallback text (used when no <table> elements exist — bullet-point data etc.)
        page_text = soup.get_text(separator="\n", strip=True)
        page_text = re.sub(r"\n{3,}", "\n\n", page_text)

        return ScrapeResult(
            url=url,
            page_title=page_title,
            tables=tables,
            page_text=page_text[:15_000],
        )

    except Exception as exc:
        return ScrapeResult(
            url=url,
            page_title="",
            tables=[],
            page_text="",
            error=str(exc),
        )


def table_to_tsv(candidate: TableCandidate, max_rows: int = 200) -> str:
    """Serialise a TableCandidate to tab-separated text for the LLM."""
    lines = ["\t".join(candidate.headers)]
    for row in candidate.rows[:max_rows]:
        lines.append("\t".join(str(c) for c in row))
    return "\n".join(lines)
