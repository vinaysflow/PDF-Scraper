"""Tests for app.providers.ocr_paddle module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from app.providers.ocr_paddle import is_available, ocr_page, ocr_pages


class TestIsAvailable:
    def test_returns_bool(self):
        result = is_available()
        assert isinstance(result, bool)


class TestOcrPage:
    """Test ocr_page with mocked PaddleOCR engine."""

    @patch("app.providers.ocr_paddle._get_engine")
    def test_returns_text_and_tokens(self, mock_get_engine):
        """Mocked PaddleOCR returns text with bounding boxes."""
        mock_engine = MagicMock()
        # PaddleOCR returns: [[ [box_points, (text, confidence)], ... ]]
        mock_engine.ocr.return_value = [[
            [
                [[10, 20], [200, 20], [200, 50], [10, 50]],
                ("Hello World", 0.95)
            ],
            [
                [[10, 60], [150, 60], [150, 90], [10, 90]],
                ("Test line", 0.88)
            ],
        ]]
        mock_get_engine.return_value = mock_engine

        img = Image.new("RGB", (400, 200), color="white")
        result = ocr_page(img)

        assert result["text"] == "Hello World\nTest line"
        assert len(result["tokens"]) == 2
        assert result["tokens"][0]["text"] == "Hello World"
        assert result["tokens"][0]["confidence"] == 95.0  # 0.95 * 100
        assert result["tokens"][0]["bbox"]["x"] == 10
        assert result["tokens"][0]["bbox"]["y"] == 20
        assert result["pass_similarity"] == 1.0

    @patch("app.providers.ocr_paddle._get_engine")
    def test_handles_empty_results(self, mock_get_engine):
        mock_engine = MagicMock()
        mock_engine.ocr.return_value = [[]]
        mock_get_engine.return_value = mock_engine

        img = Image.new("RGB", (400, 200), color="white")
        result = ocr_page(img)

        assert result["text"] == ""
        assert result["tokens"] == []

    @patch("app.providers.ocr_paddle._get_engine")
    def test_handles_none_results(self, mock_get_engine):
        mock_engine = MagicMock()
        mock_engine.ocr.return_value = [None]
        mock_get_engine.return_value = mock_engine

        img = Image.new("RGB", (400, 200), color="white")
        result = ocr_page(img)

        assert result["text"] == ""
        assert result["tokens"] == []


class TestOcrPages:
    """Test batch page processing."""

    @patch("app.providers.ocr_paddle.ocr_page")
    def test_processes_multiple_pages(self, mock_ocr_page):
        # Return a fresh dict on each call to avoid mutation issues
        def _fresh_result(*args, **kwargs):
            return {
                "text": "Page text",
                "tokens": [{"text": "Page", "bbox": {"x": 0, "y": 0, "w": 50, "h": 20}, "confidence": 96.0}],
                "pass_similarity": 1.0,
                "layout": "text",
            }
        mock_ocr_page.side_effect = _fresh_result

        images = [Image.new("RGB", (400, 200)) for _ in range(3)]
        result = ocr_pages(images, start_page=5)

        assert len(result) == 3
        assert 5 in result
        assert 6 in result
        assert 7 in result
        # Each page should have correct page_number set
        for expected_pn in [5, 6, 7]:
            assert result[expected_pn]["page_number"] == expected_pn
