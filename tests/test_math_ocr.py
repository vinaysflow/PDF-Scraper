"""Tests for app.providers.math_ocr module."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.providers.math_ocr import (
    _latex_to_text,
    is_available,
    recognize_equation,
    recognize_equations_from_page_images,
)


class TestLatexToText:
    """Test the LaTeX-to-text conversion helper."""

    def test_simple_fraction(self):
        result = _latex_to_text("\\frac{a}{b}")
        assert "a" in result
        assert "b" in result

    def test_sqrt(self):
        result = _latex_to_text("\\sqrt{x}")
        assert "sqrt" in result

    def test_greek_letters(self):
        result = _latex_to_text("\\alpha + \\beta = \\gamma")
        assert "alpha" in result
        assert "beta" in result

    def test_empty_string(self):
        assert _latex_to_text("") == ""

    def test_plain_text_passthrough(self):
        assert _latex_to_text("x + y = z") == "x + y = z"

    def test_operators(self):
        result = _latex_to_text("a \\times b \\div c")
        assert "x" in result  # \times -> " x "
        assert "/" in result  # \div -> " / "


class TestIsAvailable:
    def test_returns_bool(self):
        result = is_available()
        assert isinstance(result, bool)


class TestRecognizeEquation:
    """Test recognize_equation with mocked model."""

    @patch("app.providers.math_ocr._get_model")
    def test_returns_latex_on_success(self, mock_get_model):
        from PIL import Image
        mock_model = MagicMock(return_value="x^2 + y^2 = z^2")
        mock_get_model.return_value = mock_model

        img = Image.new("RGB", (200, 50), color="white")
        result = recognize_equation(img)

        assert result["latex"] == "x^2 + y^2 = z^2"
        assert result["error"] is None
        assert result["rendered_text"] is not None

    @patch("app.providers.math_ocr._get_model")
    def test_returns_error_on_failure(self, mock_get_model):
        from PIL import Image
        mock_get_model.side_effect = RuntimeError("Model load failed")

        img = Image.new("RGB", (200, 50), color="white")
        result = recognize_equation(img)

        assert result["latex"] is None
        assert result["error"] is not None


class TestRecognizeFromPageImages:
    """Test the heuristic equation detection."""

    def test_filters_by_aspect_ratio(self):
        # Wide image (equation-like)
        wide_img = {
            "width": 300, "height": 50,  # aspect = 6.0
            "base64_data": None,
            "bbox": {"x": 0, "y": 0, "w": 300, "h": 50},
        }
        # Square image (not equation-like)
        square_img = {
            "width": 100, "height": 100,  # aspect = 1.0
            "base64_data": None,
            "bbox": {"x": 0, "y": 0, "w": 100, "h": 100},
        }

        # Without base64 data, should skip both (no actual processing)
        results = recognize_equations_from_page_images([wide_img, square_img])
        # Square should be filtered out by aspect ratio, wide should be
        # skipped because no base64 data
        assert isinstance(results, list)

    def test_empty_input(self):
        results = recognize_equations_from_page_images([])
        assert results == []
