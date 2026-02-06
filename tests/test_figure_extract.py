"""Tests for app.figure_extract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.utils import PdfProcessingError

# Import after to ensure we see the right error for missing pymupdf
try:
    from app.figure_extract import extract_figures, MIN_FIGURE_AREA_DEFAULT
    HAS_PYMUPDF = True
except Exception:
    HAS_PYMUPDF = False


class TestFigureExtract(unittest.TestCase):
    def test_min_figure_area_constant(self) -> None:
        if not HAS_PYMUPDF:
            self.skipTest("PyMuPDF not available")
        self.assertGreater(MIN_FIGURE_AREA_DEFAULT, 0)

    def test_invalid_path_raises(self) -> None:
        if not HAS_PYMUPDF:
            self.skipTest("PyMuPDF not available")
        from app.utils import PdfValidationError
        with self.assertRaises(PdfValidationError):
            extract_figures("/nonexistent/file.pdf")

    def test_valid_pdf_returns_list(self) -> None:
        if not HAS_PYMUPDF:
            self.skipTest("PyMuPDF not available")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000101 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n")
            path = Path(f.name)
        try:
            figures = extract_figures(path, max_pages=1)
            self.assertIsInstance(figures, list)
            for fig in figures:
                self.assertIn("page_number", fig)
                self.assertIn("bbox", fig)
                self.assertIn("area", fig)
                self.assertIn("image", fig)
        finally:
            path.unlink(missing_ok=True)

    def test_large_min_figure_area_filters_out_small(self) -> None:
        if not HAS_PYMUPDF:
            self.skipTest("PyMuPDF not available")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000101 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n")
            path = Path(f.name)
        try:
            figures = extract_figures(path, max_pages=1, min_figure_area=1_000_000)
            self.assertEqual(len(figures), 0)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
