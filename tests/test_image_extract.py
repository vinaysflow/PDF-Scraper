"""Tests for app.providers.image_extract module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz  # PyMuPDF
import pytest
from PIL import Image

from app.providers.image_extract import extract_page_images


def _create_pdf_with_image(tmp_dir: Path) -> Path:
    """Create a tiny PDF that has an embedded image on page 1."""
    pdf_path = tmp_dir / "test_with_image.pdf"
    doc = fitz.open()

    # Page 1: text + an embedded image
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Hello World", fontsize=12)

    # Create a 100x100 red image and embed it
    img = Image.new("RGB", (100, 100), color="red")
    img_path = tmp_dir / "red.png"
    img.save(str(img_path))
    rect = fitz.Rect(100, 200, 300, 400)
    page.insert_image(rect, filename=str(img_path))

    # Page 2: text only
    page2 = doc.new_page(width=612, height=792)
    page2.insert_text((72, 100), "Page two - no images", fontsize=12)

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _create_pdf_text_only(tmp_dir: Path) -> Path:
    """Create a PDF with no images."""
    pdf_path = tmp_dir / "text_only.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Just text, no images.", fontsize=12)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestExtractPageImages:
    """Tests for extract_page_images."""

    def test_extracts_image_from_page(self, tmp_path: Path):
        pdf_path = _create_pdf_with_image(tmp_path)
        result = extract_page_images(pdf_path)

        # Page 1 should have at least one image
        assert 1 in result
        assert len(result[1]) >= 1

        img = result[1][0]
        assert img["format"] in ("png", "jpeg", "jpg")
        assert img["width"] >= 50
        assert img["height"] >= 50
        assert "base64_data" in img
        assert img["base64_data"]  # non-empty
        assert img["xref"] is not None

    def test_page_without_images_returns_empty(self, tmp_path: Path):
        pdf_path = _create_pdf_with_image(tmp_path)
        result = extract_page_images(pdf_path, page_numbers=[2])

        assert 2 in result
        assert result[2] == []

    def test_text_only_pdf_returns_empty(self, tmp_path: Path):
        pdf_path = _create_pdf_text_only(tmp_path)
        result = extract_page_images(pdf_path)

        assert 1 in result
        assert result[1] == []

    def test_selective_pages(self, tmp_path: Path):
        pdf_path = _create_pdf_with_image(tmp_path)
        result = extract_page_images(pdf_path, page_numbers=[1])

        assert 1 in result
        assert 2 not in result  # not requested

    def test_without_base64(self, tmp_path: Path):
        pdf_path = _create_pdf_with_image(tmp_path)
        result = extract_page_images(pdf_path, include_base64=False)

        if result.get(1):
            img = result[1][0]
            assert img.get("base64_data") is None

    def test_dedup_across_pages(self, tmp_path: Path):
        """If same image xref appears on multiple pages, it's only returned once."""
        pdf_path = _create_pdf_with_image(tmp_path)
        result = extract_page_images(pdf_path)

        all_xrefs = []
        for page_images in result.values():
            for img in page_images:
                all_xrefs.append(img["xref"])
        assert len(all_xrefs) == len(set(all_xrefs)), "Duplicate xrefs found"
