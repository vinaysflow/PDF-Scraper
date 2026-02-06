"""Extract figures/diagrams from PDFs using PyMuPDF."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

from .utils import PdfProcessingError, validate_pdf_path

MIN_FIGURE_AREA_DEFAULT = 1000  # pixels² (in point² we use rect.area)


def extract_figures(
    pdf_path: str | Path,
    max_pages: int | None = None,
    min_figure_area: float = MIN_FIGURE_AREA_DEFAULT,
) -> list[dict]:
    """
    Extract embedded images from a PDF with bounding boxes.
    Returns list of dicts: page_number, bbox (x, y, w, h), area, image (PIL Image), ext.
    Filters out images smaller than min_figure_area (in point²).
    """
    try:
        import pymupdf
    except ImportError as e:
        raise PdfProcessingError(
            "PyMuPDF is required for figure extraction. Install with: pip install pymupdf"
        ) from e

    try:
        from PIL import Image
        import io
    except ImportError as e:
        raise PdfProcessingError("Pillow is required for figure extraction.") from e

    validated = validate_pdf_path(pdf_path)
    doc = pymupdf.open(validated)
    try:
        results: list[dict] = []
        seen_xrefs: set[int] = set()
        page_count = len(doc)
        last_page = min(page_count, max_pages) if max_pages else page_count

        for page_number in range(1, last_page + 1):
            page = doc[page_number - 1]
            image_list = page.get_images(full=True)
            for item in image_list:
                xref = item[0]
                if xref in seen_xrefs:
                    continue
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                rect = rects[0]
                area = rect.width * rect.height
                if area < min_figure_area:
                    continue
                try:
                    img_dict = doc.extract_image(xref)
                except Exception:
                    continue
                if not img_dict:
                    continue
                seen_xrefs.add(xref)
                raw = img_dict.get("image")
                ext = (img_dict.get("ext") or "png").lower()
                if not raw:
                    continue
                try:
                    pil_image = Image.open(io.BytesIO(raw)).convert("RGB")
                except Exception:
                    continue
                bbox = {
                    "x": round(rect.x0, 2),
                    "y": round(rect.y0, 2),
                    "w": round(rect.width, 2),
                    "h": round(rect.height, 2),
                }
                results.append({
                    "page_number": page_number,
                    "bbox": bbox,
                    "area": round(area, 2),
                    "image": pil_image,
                    "ext": ext,
                })
        return results
    finally:
        doc.close()
