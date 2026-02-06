"""Extract embedded raster images from PDF pages using PyMuPDF.

This provider pulls images that are *embedded* in the PDF (JPEG, PNG, etc.)
and returns them with bounding-box metadata.  It does **not** rasterise
vector graphics — those remain as text/path data.

Images can optionally be saved to disk and/or base64-encoded.  By default,
base64 encoding is **off** to keep JSON payloads small.

Usage::

    from app.providers.image_extract import extract_page_images

    images = extract_page_images("/path/to.pdf", page_numbers=[1, 5, 11])
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Minimum image area in points² to keep (filters out tiny icons / artefacts)
MIN_IMAGE_AREA_PT2: float = 1_000.0

# Minimum pixel dimensions to keep
MIN_IMAGE_DIM_PX: int = 20


def _bbox_from_rect(rect: fitz.Rect) -> dict[str, float]:
    """Convert a PyMuPDF Rect to a serialisable bbox dict."""
    return {
        "x": round(rect.x0, 2),
        "y": round(rect.y0, 2),
        "w": round(rect.width, 2),
        "h": round(rect.height, 2),
    }


def _image_area(rect: fitz.Rect) -> float:
    return rect.width * rect.height


def extract_page_images(
    pdf_path: str | Path,
    page_numbers: list[int] | None = None,
    min_area: float = MIN_IMAGE_AREA_PT2,
    include_base64: bool = False,
) -> dict[int, list[dict[str, Any]]]:
    """Extract embedded images from selected pages.

    Parameters
    ----------
    pdf_path:
        Path to the PDF file.
    page_numbers:
        1-based page numbers to process.  ``None`` means *all* pages.
    min_area:
        Minimum bounding-box area (in pt²) to keep an image.
    include_base64:
        If True, include the image bytes as a base64-encoded string.
        Defaults to False to keep JSON output small.

    Returns
    -------
    dict mapping page_number -> list of image dicts, each with keys:
        ``bbox``, ``format``, ``width``, ``height``, ``base64_data`` (optional),
        ``xref`` (PDF internal cross-reference id for dedup),
        ``_raw_bytes`` (raw bytes, always present for downstream save-to-disk).
    """
    doc = fitz.open(str(pdf_path))
    result: dict[int, list[dict[str, Any]]] = {}
    seen_xrefs: set[int] = set()  # cross-page dedup

    try:
        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            if page_numbers is not None and page_num not in page_numbers:
                continue

            page_images: list[dict[str, Any]] = []
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref = img_info[0]
                if xref in seen_xrefs:
                    continue  # already captured from another page

                try:
                    base_image = doc.extract_image(xref)
                except Exception:
                    logger.debug("Failed to extract image xref=%d on page %d", xref, page_num)
                    continue

                if not base_image or not base_image.get("image"):
                    continue

                img_bytes: bytes = base_image["image"]
                ext: str = base_image.get("ext", "png")
                width: int = base_image.get("width", 0)
                height: int = base_image.get("height", 0)

                if width < MIN_IMAGE_DIM_PX or height < MIN_IMAGE_DIM_PX:
                    continue

                # Try to find the image's bounding box on the page
                bbox_rect = None
                for img_block in page.get_image_info(xrefs=True):
                    if img_block.get("xref") == xref:
                        bbox_rect = fitz.Rect(img_block["bbox"])
                        break

                if bbox_rect is not None and _image_area(bbox_rect) < min_area:
                    continue

                seen_xrefs.add(xref)

                entry: dict[str, Any] = {
                    "xref": xref,
                    "format": ext,
                    "width": width,
                    "height": height,
                    "bbox": _bbox_from_rect(bbox_rect) if bbox_rect else None,
                    "size_bytes": len(img_bytes),
                    "_raw_bytes": img_bytes,  # kept for save_images_to_disk
                }
                if include_base64:
                    entry["base64_data"] = base64.b64encode(img_bytes).decode("ascii")

                page_images.append(entry)

            result[page_num] = page_images
    finally:
        doc.close()

    return result


def save_images_to_disk(
    all_images: dict[int, list[dict[str, Any]]],
    output_dir: str | Path,
    doc_id: str,
) -> dict[tuple[int, int], str]:
    """Write extracted images to disk and return path mapping.

    Parameters
    ----------
    all_images:
        Output of :func:`extract_page_images` (must include ``_raw_bytes``).
    output_dir:
        Root directory for image storage (e.g. ``IMAGE_STORE_DIR``).
    doc_id:
        Unique document identifier used as the sub-folder name.

    Returns
    -------
    dict mapping ``(page_number, image_index)`` -> absolute file path.
    """
    path_map: dict[tuple[int, int], str] = {}
    base_dir = Path(output_dir) / doc_id

    for page_num, images in sorted(all_images.items()):
        page_dir = base_dir / f"page_{page_num}"
        page_dir.mkdir(parents=True, exist_ok=True)

        for idx, img in enumerate(images):
            raw_bytes = img.get("_raw_bytes")
            if raw_bytes is None:
                logger.warning(
                    "No _raw_bytes for page %d image %d — skipping disk save",
                    page_num, idx,
                )
                continue

            ext = img.get("format", "png")
            filename = f"img_{idx}.{ext}"
            file_path = page_dir / filename
            file_path.write_bytes(raw_bytes)
            path_map[(page_num, idx)] = str(file_path.resolve())
            logger.debug("Saved image: %s", file_path)

    return path_map


def strip_raw_bytes(all_images: dict[int, list[dict[str, Any]]]) -> None:
    """Remove ``_raw_bytes`` from image dicts (call after saving to disk).

    This avoids carrying large byte blobs through the rest of the pipeline.
    """
    for images in all_images.values():
        for img in images:
            img.pop("_raw_bytes", None)
