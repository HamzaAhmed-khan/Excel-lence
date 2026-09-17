"""
ocr_engine.py — Image-to-text OCR with preprocessing and per-image confidence scoring.
Uses pytesseract + Pillow. Provides base64 encoding for Groq vision API.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Optional


@dataclass
class OcrResult:
    text: str
    confidence: float          # 0.0 – 1.0 overall OCR confidence
    error: Optional[str] = None

    @property
    def is_reliable(self) -> bool:
        """True when OCR produced usable text with decent confidence."""
        return self.confidence >= 0.55 and bool(self.text.strip())

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.80:
            return "high"
        if self.confidence >= 0.55:
            return "medium"
        return "low"


# ── Image pre-processing ──────────────────────────────────────────────────────

def _preprocess(image_bytes: bytes):
    """
    Return (original_rgb, enhanced_gray) PIL Images.
    Upscales small images, boosts contrast, sharpens — all OCR-friendliness.
    """
    from PIL import Image, ImageEnhance, ImageFilter

    img = Image.open(io.BytesIO(image_bytes))

    # Normalise mode
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Scale up if too small (OCR accuracy degrades below ~1000 px wide)
    w, h = img.size
    if w < 1000:
        scale = 1000 / w
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    gray = img.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(2.0)
    gray = ImageEnhance.Sharpness(gray).enhance(2.0)
    gray = gray.filter(ImageFilter.SHARPEN)

    return img, gray


# ── OCR ───────────────────────────────────────────────────────────────────────

def run_ocr(image_bytes: bytes) -> OcrResult:
    """
    Run tesseract on image bytes.
    Uses PSM 6 (assume a single uniform block of text / tabular data).
    Returns OcrResult with raw text and 0-1 confidence.
    """
    try:
        import pytesseract
        from pytesseract import Output

        _, gray = _preprocess(image_bytes)

        # Detailed word-level output for confidence scoring
        data = pytesseract.image_to_data(
            gray,
            output_type=Output.DICT,
            config="--psm 6",
        )
        confs = [c for c in data["conf"] if c != -1]
        avg_conf = round(sum(confs) / len(confs) / 100.0, 2) if confs else 0.40

        text = pytesseract.image_to_string(gray, config="--psm 6")
        return OcrResult(text=text.strip(), confidence=avg_conf)

    except ImportError:
        return OcrResult(
            text="",
            confidence=0.0,
            error="pytesseract or Pillow not installed — install them with pip",
        )
    except Exception as exc:
        return OcrResult(text="", confidence=0.0, error=str(exc))


# ── Vision helper ─────────────────────────────────────────────────────────────

def encode_image_b64(image_bytes: bytes) -> str:
    """
    Encode image as a base64 JPEG string suitable for Groq's vision API.
    Converts any mode to RGB, compresses as JPEG quality 85.
    """
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def image_data_url(image_bytes: bytes) -> str:
    """Return a data URL for use in Groq vision message content."""
    b64 = encode_image_b64(image_bytes)
    return f"data:image/jpeg;base64,{b64}"
