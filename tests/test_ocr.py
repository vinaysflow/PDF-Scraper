"""Tests for app.ocr."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from PIL import Image

from app.ocr import (
    _default_ocr_workers,
    _process_one_ocr_page,
    extract_with_ocr,
)


class TestDefaultOCRWorkers(unittest.TestCase):
    def test_default_without_env(self) -> None:
        os.environ.pop("OCR_WORKERS", None)
        w = _default_ocr_workers()
        self.assertGreaterEqual(w, 1)
        self.assertLessEqual(w, 32)

    def test_env_parsed(self) -> None:
        os.environ["OCR_WORKERS"] = "8"
        try:
            self.assertEqual(_default_ocr_workers(), 8)
        finally:
            os.environ.pop("OCR_WORKERS", None)

    def test_invalid_env_falls_back(self) -> None:
        os.environ["OCR_WORKERS"] = "not_a_number"
        try:
            w = _default_ocr_workers()
            self.assertIn(w, range(1, 33))
        finally:
            os.environ.pop("OCR_WORKERS", None)


class TestExtractWithOCR(unittest.TestCase):
    def test_empty_images_returns_empty(self) -> None:
        text, pages = extract_with_ocr(
            Path("/nonexistent.pdf"),
            images=[],
            workers=1,
        )
        self.assertEqual(text, "")
        self.assertEqual(pages, [])


class TestProcessOneOCRPage(unittest.TestCase):
    """_process_one_ocr_page returns correct structure (keys and types)."""

    def test_returns_required_keys(self) -> None:
        img = Image.new("RGB", (200, 200), color="white")
        out = _process_one_ocr_page(1, img, "eng", None)
        self.assertIsInstance(out, dict)
        self.assertEqual(out["page_number"], 1)
        for key in ("text", "tokens", "layout", "pass_similarity", "strategy"):
            self.assertIn(key, out, msg=f"Missing key: {key}")
        self.assertIsInstance(out["tokens"], list)
        self.assertIsInstance(out["strategy"], dict)
        self.assertIn(out["layout"], ("text", "table", "noisy"))

    def test_small_image_still_returns_structure(self) -> None:
        # Use RGB; layout classification uses OpenCV which expects 3-channel for RGB2GRAY
        img = Image.new("RGB", (50, 50), color=(255, 255, 255))
        out = _process_one_ocr_page(2, img, "eng", None)
        self.assertEqual(out["page_number"], 2)
        self.assertIn("layout", out)
        self.assertIn("pass_similarity", out)


if __name__ == "__main__":
    unittest.main()
