"""
extractor.py — URL scraping and optional OCR.
Respects ENABLE_WEB_SCRAPING and ENABLE_OCR feature flags from config.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import settings


def fetch_url(url: str) -> str:
    """
    Fetch a URL and return its main text content + any HTML tables as CSV-ish text.
    Returns empty string if scraping is disabled.
    """
    if not settings.enable_web_scraping:
        return ""

    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; ExcelLenceAI/1.0; "
                "+https://excellence-ai.app)"
            )
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        parts: list[str] = []

        # Extract all HTML tables as tab-separated text
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
                if cells:
                    rows.append("\t".join(cells))
            if rows:
                parts.append("\n".join(rows))

        # Main text content
        text = soup.get_text(separator="\n", strip=True)
        # Collapse excessive blank lines
        import re
        text = re.sub(r"\n{3,}", "\n\n", text)
        parts.append(text)

        return "\n\n".join(parts)[:50_000]  # cap at 50k chars

    except Exception as e:
        return f"[URL fetch failed: {e}]"


def ocr_image(path: str | Path) -> str:
    """
    Run OCR on an image file. Returns empty string if OCR is disabled or
    tesseract is not installed.
    """
    if not settings.enable_ocr:
        return ""

    try:
        import pytesseract
        from PIL import Image

        img = Image.open(str(path))
        text = pytesseract.image_to_string(img)
        return text.strip()

    except ImportError:
        return "[OCR unavailable: install pytesseract and Pillow]"
    except Exception as e:
        return f"[OCR failed: {e}]"
