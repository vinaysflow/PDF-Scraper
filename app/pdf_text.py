"""Native PDF text extraction using PyMuPDF (fitz).

Replaces Apache Tika: no JVM, per-page text, lightweight.
Also provides layout-block extraction for page reconstruction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


def extract_native_text(pdf_path: str | Path) -> tuple[str, list[dict]]:
    """Extract embedded text from a PDF using PyMuPDF.

    Returns:
        (full_text, pages) where pages is a list of
        ``{"page_number": int, "text": str, "char_count": int}``.
    """
    doc = fitz.open(str(pdf_path))
    pages: list[dict] = []
    full_parts: list[str] = []
    try:
        for i, page in enumerate(doc):
            text = page.get_text()
            pages.append({
                "page_number": i + 1,
                "text": text,
                "char_count": len(text.strip()),
            })
            if text.strip():
                full_parts.append(text.strip())
    finally:
        doc.close()
    return "\n".join(full_parts), pages


def page_has_text(page_dict: dict, min_chars: int = 50) -> bool:
    """Return True if a page has enough native text to skip OCR."""
    return page_dict.get("char_count", 0) >= min_chars


def extract_page_dimensions(pdf_path: str | Path) -> dict[int, tuple[float, float]]:
    """Return {page_number: (width, height)} for every page in the PDF."""
    doc = fitz.open(str(pdf_path))
    dims: dict[int, tuple[float, float]] = {}
    try:
        for i, page in enumerate(doc):
            rect = page.rect
            dims[i + 1] = (round(rect.width, 2), round(rect.height, 2))
    finally:
        doc.close()
    return dims


def extract_layout_blocks(
    pdf_path: str | Path,
    page_numbers: list[int] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """Extract layout blocks (text spans with position, font, size) per page.

    Uses ``page.get_text("dict")`` which gives blocks → lines → spans.
    Each span has text, font name, font size, colour and bounding box.

    Returns:
        dict mapping page_number -> list of block dicts with keys:
        ``type``, ``bbox``, ``text``, ``font``, ``size``, ``color``.
    """
    doc = fitz.open(str(pdf_path))
    result: dict[int, list[dict[str, Any]]] = {}
    try:
        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            if page_numbers is not None and page_num not in page_numbers:
                continue

            blocks: list[dict[str, Any]] = []
            page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

            for block in page_dict.get("blocks", []):
                block_type = block.get("type", 0)
                bbox_raw = block.get("bbox", (0, 0, 0, 0))
                bbox = {
                    "x": round(bbox_raw[0], 2),
                    "y": round(bbox_raw[1], 2),
                    "w": round(bbox_raw[2] - bbox_raw[0], 2),
                    "h": round(bbox_raw[3] - bbox_raw[1], 2),
                }

                if block_type == 1:
                    # Image block
                    blocks.append({
                        "type": "image",
                        "bbox": bbox,
                        "text": None,
                        "font": None,
                        "size": None,
                        "color": None,
                    })
                    continue

                # Text block — flatten lines → spans
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        span_bbox_raw = span.get("bbox", bbox_raw)
                        span_bbox = {
                            "x": round(span_bbox_raw[0], 2),
                            "y": round(span_bbox_raw[1], 2),
                            "w": round(span_bbox_raw[2] - span_bbox_raw[0], 2),
                            "h": round(span_bbox_raw[3] - span_bbox_raw[1], 2),
                        }
                        text = span.get("text", "")
                        if not text.strip():
                            continue
                        blocks.append({
                            "type": "text",
                            "bbox": span_bbox,
                            "text": text,
                            "font": span.get("font"),
                            "size": round(span.get("size", 0), 2),
                            "color": span.get("color"),
                        })

            result[page_num] = blocks
    finally:
        doc.close()
    return result
