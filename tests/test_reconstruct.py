"""Tests for app.providers.reconstruct module."""

from __future__ import annotations

import pytest

from app.providers.reconstruct import reconstruct_html


def _make_result(**overrides) -> dict:
    """Build a minimal ExtractionResult dict for testing."""
    base = {
        "doc_id": "test-doc-123",
        "filename": "test.pdf",
        "ingested_at": "2025-01-01T00:00:00Z",
        "extraction": {"method": "native", "pages_total": 1, "engine": "pymupdf"},
        "pages": [
            {
                "page_number": 1,
                "source": "native",
                "text": "Hello World",
                "tokens": [],
                "images": [],
                "layout_blocks": [],
                "page_width": 612.0,
                "page_height": 792.0,
            }
        ],
        "full_text": "Hello World",
        "stats": {"total_tokens": 0},
    }
    base.update(overrides)
    return base


class TestReconstructHtml:
    def test_returns_valid_html(self):
        result = _make_result()
        html = reconstruct_html(result)
        assert "<!DOCTYPE html>" in html
        assert "Page 1" in html
        assert "test.pdf" in html

    def test_includes_fallback_text_when_no_layout(self):
        result = _make_result()
        html = reconstruct_html(result)
        assert "Hello World" in html

    def test_includes_layout_blocks(self):
        result = _make_result(
            pages=[
                {
                    "page_number": 1,
                    "source": "native",
                    "text": "Test heading",
                    "tokens": [],
                    "images": [],
                    "layout_blocks": [
                        {
                            "type": "text",
                            "bbox": {"x": 72, "y": 100, "w": 200, "h": 20},
                            "text": "Test heading",
                            "font": "Helvetica",
                            "size": 16.0,
                            "color": 0,
                        }
                    ],
                    "page_width": 612.0,
                    "page_height": 792.0,
                }
            ]
        )
        html = reconstruct_html(result)
        assert "Test heading" in html
        assert "Helvetica" in html
        assert 'class="blk txt"' in html

    def test_includes_embedded_images(self):
        result = _make_result(
            pages=[
                {
                    "page_number": 1,
                    "source": "native",
                    "text": "",
                    "tokens": [],
                    "images": [
                        {
                            "xref": 1,
                            "format": "png",
                            "width": 100,
                            "height": 100,
                            "bbox": {"x": 50, "y": 50, "w": 200, "h": 200},
                            "size_bytes": 500,
                            "base64_data": "iVBORw0KGgo=",
                        }
                    ],
                    "layout_blocks": [],
                    "page_width": 612.0,
                    "page_height": 792.0,
                }
            ]
        )
        html = reconstruct_html(result)
        assert "data:image/png;base64," in html
        assert "embedded-img" in html

    def test_handles_missing_page_dimensions(self):
        result = _make_result(
            pages=[
                {
                    "page_number": 1,
                    "source": "native",
                    "text": "No dims",
                    "tokens": [],
                    "images": [],
                    "layout_blocks": [],
                    "page_width": None,
                    "page_height": None,
                }
            ]
        )
        html = reconstruct_html(result)
        assert "No dims" in html

    def test_multi_page(self):
        result = _make_result(
            pages=[
                {
                    "page_number": i,
                    "source": "native",
                    "text": f"Page {i} content",
                    "tokens": [],
                    "images": [],
                    "layout_blocks": [],
                    "page_width": 612.0,
                    "page_height": 792.0,
                }
                for i in range(1, 4)
            ]
        )
        html = reconstruct_html(result)
        assert "Page 1" in html
        assert "Page 2" in html
        assert "Page 3" in html

    def test_escapes_html_in_text(self):
        result = _make_result(
            pages=[
                {
                    "page_number": 1,
                    "source": "native",
                    "text": '<script>alert("xss")</script>',
                    "tokens": [],
                    "images": [],
                    "layout_blocks": [],
                    "page_width": 612.0,
                    "page_height": 792.0,
                }
            ]
        )
        html = reconstruct_html(result)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_empty_pages_list(self):
        result = _make_result(pages=[])
        html = reconstruct_html(result)
        assert "<!DOCTYPE html>" in html
        assert "0 pages" in html
