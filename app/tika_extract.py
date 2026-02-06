"""Apache Tika-based PDF text extraction."""

from __future__ import annotations

from pathlib import Path

from tika import parser

from .utils import PdfProcessingError


def _split_pages(content: str) -> list[str]:
    """Split Tika content into pages using form-feed markers."""

    if not content:
        return []
    pages = content.split("\f")
    if pages and pages[-1].strip() == "":
        pages = pages[:-1]
    return [page.strip() for page in pages]


def extract_with_tika(pdf_path: Path) -> tuple[str, list[dict]]:
    """Extract text using Apache Tika."""

    try:
        parsed = parser.from_file(str(pdf_path))
    except Exception as exc:  # pragma: no cover - depends on Tika runtime
        raise PdfProcessingError(f"Tika extraction failed: {exc}") from exc

    content = parsed.get("content") or ""
    content = content.replace("\r\n", "\n")
    pages = [
        {"page_number": index, "text": page_text}
        for index, page_text in enumerate(_split_pages(content), start=1)
    ]
    return content.strip(), pages
