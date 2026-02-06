"""Extract tables from PDF pages using Camelot.

Camelot reads text-based PDF tables (not scanned images) and returns
structured rows/columns/cells.  It requires Ghostscript as a system
dependency.

This provider is opt-in via ``EXTRACT_TABLES=1`` and fails gracefully
if Camelot or Ghostscript is unavailable.

Usage::

    from app.providers.table_extract import extract_tables

    tables = extract_tables("/path/to.pdf", page_numbers=[1, 3])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Try importing camelot; if missing, the provider is a no-op.
try:
    import camelot  # type: ignore[import-untyped]

    _CAMELOT_AVAILABLE = True
except ImportError:
    _CAMELOT_AVAILABLE = False
    logger.info("camelot-py not installed — table extraction disabled")


def is_available() -> bool:
    """Return True if Camelot and its dependencies are importable."""
    return _CAMELOT_AVAILABLE


def extract_tables(
    pdf_path: str | Path,
    page_numbers: list[int] | None = None,
    flavor: str = "lattice",
) -> dict[int, list[dict[str, Any]]]:
    """Extract tables from specified pages.

    Parameters
    ----------
    pdf_path:
        Path to the PDF file.
    page_numbers:
        1-based page numbers to process.  ``None`` means all pages
        (Camelot default behaviour — may be slow on large PDFs).
    flavor:
        ``"lattice"`` (grid-based) or ``"stream"`` (whitespace-based).
        Lattice is more accurate for tables with visible cell borders.

    Returns
    -------
    dict mapping page_number -> list of table dicts, each with keys:
        ``headers``, ``rows``, ``csv_text``, ``accuracy``, ``bbox``.
    """
    if not _CAMELOT_AVAILABLE:
        return {}

    pdf_str = str(pdf_path)
    pages_str = ",".join(str(p) for p in page_numbers) if page_numbers else "all"

    try:
        tables = camelot.read_pdf(
            pdf_str,
            pages=pages_str,
            flavor=flavor,
            suppress_stdout=True,
        )
    except Exception as exc:
        logger.warning("Camelot failed on %s (pages=%s): %s", pdf_str, pages_str, exc)
        # Try stream flavor as fallback if lattice failed
        if flavor == "lattice":
            try:
                tables = camelot.read_pdf(
                    pdf_str,
                    pages=pages_str,
                    flavor="stream",
                    suppress_stdout=True,
                )
            except Exception:
                return {}
        else:
            return {}

    result: dict[int, list[dict[str, Any]]] = {}

    for table in tables:
        page_num = table.page
        df = table.df

        # Extract headers (first row) and data rows
        if df.empty:
            continue

        all_rows = df.values.tolist()
        headers = all_rows[0] if all_rows else []
        data_rows = all_rows[1:] if len(all_rows) > 1 else []

        # Build CSV-style text representation
        csv_lines = []
        for row in all_rows:
            csv_lines.append(" | ".join(str(cell).strip() for cell in row))
        csv_text = "\n".join(csv_lines)

        # Bounding box from Camelot (x1, y1, x2, y2 in PDF coordinates)
        camelot_bbox = table._bbox if hasattr(table, "_bbox") else None
        bbox = None
        if camelot_bbox:
            x1, y1, x2, y2 = camelot_bbox
            bbox = {
                "x": round(x1, 2),
                "y": round(y1, 2),
                "w": round(x2 - x1, 2),
                "h": round(y2 - y1, 2),
            }

        table_dict: dict[str, Any] = {
            "headers": [str(h).strip() for h in headers],
            "rows": [[str(cell).strip() for cell in row] for row in data_rows],
            "csv_text": csv_text,
            "accuracy": round(table.accuracy, 2) if hasattr(table, "accuracy") else None,
            "bbox": bbox,
            "num_rows": len(all_rows),
            "num_cols": len(headers) if headers else 0,
        }

        result.setdefault(page_num, []).append(table_dict)

    return result
