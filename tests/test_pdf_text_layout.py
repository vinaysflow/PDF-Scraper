"""Tests for layout block extraction in app.pdf_text."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.pdf_text import extract_layout_blocks, extract_page_dimensions


def _make_pdf(tmp_path: Path) -> Path:
    """Create a simple 2-page PDF with text."""
    pdf_path = tmp_path / "layout_test.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), f"Page {i + 1} heading", fontsize=16)
        page.insert_text((72, 150), f"Body text on page {i + 1}.", fontsize=10)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestExtractPageDimensions:
    def test_returns_dimensions_for_all_pages(self, tmp_path: Path):
        pdf_path = _make_pdf(tmp_path)
        dims = extract_page_dimensions(pdf_path)

        assert len(dims) == 2
        assert dims[1] == (612.0, 792.0)
        assert dims[2] == (612.0, 792.0)


class TestExtractLayoutBlocks:
    def test_returns_text_blocks_with_bbox(self, tmp_path: Path):
        pdf_path = _make_pdf(tmp_path)
        result = extract_layout_blocks(pdf_path)

        assert 1 in result
        assert 2 in result
        assert len(result[1]) >= 2  # at least heading + body

        block = result[1][0]
        assert block["type"] == "text"
        assert "bbox" in block
        assert "x" in block["bbox"]
        assert block["text"] is not None
        assert block["font"] is not None
        assert block["size"] is not None

    def test_selective_pages(self, tmp_path: Path):
        pdf_path = _make_pdf(tmp_path)
        result = extract_layout_blocks(pdf_path, page_numbers=[2])

        assert 2 in result
        assert 1 not in result

    def test_empty_page(self, tmp_path: Path):
        pdf_path = tmp_path / "empty.pdf"
        doc = fitz.open()
        doc.new_page(width=612, height=792)  # blank page
        doc.save(str(pdf_path))
        doc.close()

        result = extract_layout_blocks(pdf_path)
        assert 1 in result
        assert result[1] == []  # no text blocks on blank page
