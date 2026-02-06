"""PaddleOCR engine — drop-in alternative to Tesseract.

PaddleOCR (Apache 2.0) achieves ~96.6% accuracy on invoices vs Tesseract's
~87.7%.  It runs on CPU (slower) or GPU (fast).  Models are downloaded
automatically on first use (~125 MB).

This provider mirrors the output format of the Tesseract OCR path:
each page produces ``{"text", "tokens", "pass_similarity", "layout"}``.

Usage::

    from app.providers.ocr_paddle import ocr_page, is_available

    if is_available():
        result = ocr_page(pil_image, lang="en")
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Lazy-loaded singleton
_ocr_engine = None
_AVAILABLE: bool | None = None


def is_available() -> bool:
    """Return True if paddleocr is importable."""
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import paddleocr  # noqa: F401
            _AVAILABLE = True
        except ImportError:
            _AVAILABLE = False
            logger.info("paddleocr not installed — PaddleOCR engine disabled")
    return _AVAILABLE


def _get_engine(lang: str = "en"):
    """Lazy-load the PaddleOCR engine (downloads models on first use)."""
    global _ocr_engine
    if _ocr_engine is None:
        from paddleocr import PaddleOCR
        _ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang=lang,
            show_log=False,
            use_gpu=False,  # CPU by default — swap to True when GPU available
        )
    return _ocr_engine


def ocr_page(
    image: Image.Image,
    lang: str = "en",
) -> dict[str, Any]:
    """Run PaddleOCR on a single page image.

    Parameters
    ----------
    image:
        PIL Image of the page (RGB or grayscale).
    lang:
        Language code (e.g., "en", "ch", "hi").

    Returns
    -------
    dict with keys matching Tesseract output format:
        ``text``: Full page text.
        ``tokens``: List of token dicts with ``text``, ``bbox``, ``confidence``.
        ``pass_similarity``: Always 1.0 (single-pass engine).
        ``layout``: Always "text" (PaddleOCR doesn't classify layout).
    """
    if not is_available():
        return {"text": "", "tokens": [], "pass_similarity": None, "layout": None}

    engine = _get_engine(lang)

    # PaddleOCR expects numpy array
    img_array = np.array(image.convert("RGB"))
    results = engine.ocr(img_array, cls=True)

    tokens: list[dict[str, Any]] = []
    text_parts: list[str] = []

    if results and results[0]:
        for line in results[0]:
            if not line or len(line) < 2:
                continue
            box_points = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            text_info = line[1]   # (text, confidence)

            if not text_info or len(text_info) < 2:
                continue

            text = str(text_info[0])
            confidence = float(text_info[1]) * 100  # Scale to 0-100 like Tesseract

            # Convert 4-point polygon to axis-aligned bbox
            xs = [p[0] for p in box_points]
            ys = [p[1] for p in box_points]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)

            tokens.append({
                "text": text,
                "bbox": {
                    "x": int(x_min),
                    "y": int(y_min),
                    "w": int(x_max - x_min),
                    "h": int(y_max - y_min),
                },
                "confidence": round(confidence, 2),
            })
            text_parts.append(text)

    full_text = "\n".join(text_parts)

    return {
        "text": full_text,
        "tokens": tokens,
        "pass_similarity": 1.0,  # Single-pass — no dual-pass similarity metric
        "layout": "text",
    }


def ocr_pages(
    images: list[Image.Image],
    lang: str = "en",
    start_page: int = 1,
) -> dict[int, dict[str, Any]]:
    """Run PaddleOCR on multiple page images.

    Parameters
    ----------
    images:
        List of PIL Images (one per page).
    lang:
        Language code.
    start_page:
        1-based page number offset for the first image.

    Returns
    -------
    dict mapping page_number -> ocr result dict.
    """
    results: dict[int, dict[str, Any]] = {}
    for i, img in enumerate(images):
        page_num = start_page + i
        try:
            result = ocr_page(img, lang=lang)
            result["page_number"] = page_num
            results[page_num] = result
        except Exception as exc:
            logger.warning("PaddleOCR failed on page %d: %s", page_num, exc)
            results[page_num] = {
                "page_number": page_num,
                "text": "",
                "tokens": [],
                "pass_similarity": None,
                "layout": None,
            }
    return results
