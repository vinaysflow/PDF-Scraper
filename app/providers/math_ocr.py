"""Recognize math equations in images and convert to LaTeX.

Uses Pix2Tex (LaTeX-OCR) — an open-source MIT-licensed model that
converts cropped equation images to LaTeX strings.

This provider is opt-in via ``EXTRACT_MATH=1`` and fails gracefully
if pix2tex is not installed.

Usage::

    from app.providers.math_ocr import recognize_equation, is_available

    if is_available():
        latex = recognize_equation(pil_image)
"""

from __future__ import annotations

import logging
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

# Lazy-loaded model singleton
_model = None
_AVAILABLE: bool | None = None


def is_available() -> bool:
    """Return True if pix2tex is importable."""
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import pix2tex  # noqa: F401
            _AVAILABLE = True
        except ImportError:
            _AVAILABLE = False
            logger.info("pix2tex not installed — math equation recognition disabled")
    return _AVAILABLE


def _get_model():
    """Lazy-load the Pix2Tex model (downloads weights on first use)."""
    global _model
    if _model is None:
        from pix2tex.cli import LatexOCR
        _model = LatexOCR()
    return _model


def recognize_equation(image: Image.Image) -> dict[str, Any]:
    """Convert an equation image to LaTeX.

    Parameters
    ----------
    image:
        A PIL Image of a cropped math equation.

    Returns
    -------
    dict with keys:
        ``latex``: The LaTeX string (e.g., ``"x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}"``).
        ``rendered_text``: A simplified text representation.
        ``error``: Error string if recognition failed.
    """
    if not is_available():
        return {"latex": None, "rendered_text": None, "error": "pix2tex not installed"}

    try:
        model = _get_model()
        latex = model(image)
        # Simple text representation: strip LaTeX commands
        rendered = _latex_to_text(latex)
        return {"latex": latex, "rendered_text": rendered, "error": None}
    except Exception as exc:
        logger.warning("Math OCR failed: %s", exc)
        return {"latex": None, "rendered_text": None, "error": str(exc)}


def recognize_equations_from_page_images(
    page_images: list[dict[str, Any]],
    min_aspect_ratio: float = 1.5,
    max_aspect_ratio: float = 20.0,
) -> list[dict[str, Any]]:
    """Heuristic: detect likely equation images and run math OCR on them.

    Equations tend to be wide and short (high aspect ratio).  This function
    filters page images by aspect ratio as a rough heuristic, then runs
    each through Pix2Tex.

    Parameters
    ----------
    page_images:
        List of PageImage dicts (with ``width``, ``height``, ``base64_data``).
    min_aspect_ratio:
        Minimum width/height ratio to consider as a potential equation.
    max_aspect_ratio:
        Maximum width/height ratio.

    Returns
    -------
    List of equation result dicts with ``bbox``, ``latex``, ``rendered_text``.
    """
    if not is_available():
        return []

    import base64
    from io import BytesIO

    results = []
    for img_data in page_images:
        w = img_data.get("width", 0)
        h = img_data.get("height", 0)
        if h == 0:
            continue
        aspect = w / h
        if aspect < min_aspect_ratio or aspect > max_aspect_ratio:
            continue

        b64 = img_data.get("base64_data")
        if not b64:
            continue

        try:
            img_bytes = base64.b64decode(b64)
            image = Image.open(BytesIO(img_bytes)).convert("RGB")
            result = recognize_equation(image)
            result["bbox"] = img_data.get("bbox")
            results.append(result)
        except Exception as exc:
            logger.debug("Failed to process equation image: %s", exc)

    return results


def _latex_to_text(latex: str) -> str:
    """Best-effort conversion of LaTeX to plain text."""
    if not latex:
        return ""
    text = latex
    # Common replacements
    replacements = [
        ("\\frac", ""),
        ("\\sqrt", "sqrt"),
        ("\\times", " x "),
        ("\\div", " / "),
        ("\\pm", " +/- "),
        ("\\leq", " <= "),
        ("\\geq", " >= "),
        ("\\neq", " != "),
        ("\\infty", "infinity"),
        ("\\pi", "pi"),
        ("\\alpha", "alpha"),
        ("\\beta", "beta"),
        ("\\gamma", "gamma"),
        ("\\theta", "theta"),
        ("\\sum", "SUM"),
        ("\\int", "INTEGRAL"),
        ("\\lim", "lim"),
        ("\\rightarrow", " -> "),
        ("\\leftarrow", " <- "),
        ("\\Rightarrow", " => "),
        ("\\cdot", " . "),
        ("\\ldots", "..."),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    # Strip remaining backslash commands
    import re
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    # Clean up braces and extra whitespace
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text
