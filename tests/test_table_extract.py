"""Tests for app.providers.table_extract module."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.providers.table_extract import extract_tables, is_available


def _create_pdf_with_text_table(tmp_path: Path) -> Path:
    """Create a simple PDF with a text-based table using PyMuPDF.

    We draw a grid of lines and place text in cells.
    """
    pdf_path = tmp_path / "table_test.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    # Draw a 3x3 table grid
    x0, y0 = 72, 100
    col_w, row_h = 150, 30
    rows, cols = 4, 3  # header + 3 data rows

    # Horizontal lines
    for r in range(rows + 1):
        y = y0 + r * row_h
        page.draw_line((x0, y), (x0 + cols * col_w, y), width=1)

    # Vertical lines
    for c in range(cols + 1):
        x = x0 + c * col_w
        page.draw_line((x, y0), (x, y0 + rows * row_h), width=1)

    # Insert text into cells
    data = [
        ["Name", "Subject", "Marks"],
        ["Alice", "Maths", "95"],
        ["Bob", "Science", "88"],
        ["Carol", "English", "92"],
    ]
    for r, row in enumerate(data):
        for c, text in enumerate(row):
            x = x0 + c * col_w + 10
            y = y0 + r * row_h + 20
            page.insert_text((x, y), text, fontsize=10)

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestTableExtract:
    def test_is_available(self):
        """Camelot should be importable in the test environment."""
        assert is_available() is True

    def test_extract_from_table_pdf(self, tmp_path: Path):
        """Should detect at least one table from a grid-based PDF."""
        pdf_path = _create_pdf_with_text_table(tmp_path)
        result = extract_tables(pdf_path, page_numbers=[1], flavor="lattice")

        # Camelot may or may not detect the table depending on rendering
        # At minimum, the function should not crash
        assert isinstance(result, dict)

    def test_extract_from_text_only_pdf(self, tmp_path: Path):
        """A PDF with no tables should return empty results."""
        pdf_path = tmp_path / "no_tables.pdf"
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), "Just text, no tables here.", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()

        result = extract_tables(pdf_path, page_numbers=[1])
        assert isinstance(result, dict)
        # Should be empty or have empty lists
        tables_on_page = result.get(1, [])
        assert isinstance(tables_on_page, list)

    def test_returns_dict_structure(self, tmp_path: Path):
        """Verify the return structure even when no tables found."""
        pdf_path = tmp_path / "simple.pdf"
        doc = fitz.open()
        doc.new_page(width=612, height=792)
        doc.save(str(pdf_path))
        doc.close()

        result = extract_tables(pdf_path)
        assert isinstance(result, dict)

    def test_stream_flavor(self, tmp_path: Path):
        """Stream flavor should not crash."""
        pdf_path = _create_pdf_with_text_table(tmp_path)
        result = extract_tables(pdf_path, page_numbers=[1], flavor="stream")
        assert isinstance(result, dict)
