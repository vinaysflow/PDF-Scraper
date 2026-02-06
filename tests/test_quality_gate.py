"""Tests for source-aware quality gate bypass logic."""

from __future__ import annotations

import unittest

from app.extract import _page_quality, MIN_NATIVE_CHARS


class TestNativeSufficientBypass(unittest.TestCase):
    """When selected_source=native and native text is substantial, auto-approve."""

    def test_native_sufficient_approves_despite_bad_ocr(self) -> None:
        """Page 1 scenario: good native text, garbage OCR. Should approve."""
        native_text = "KARNATAKA SCHOOL EXAMINATION AND ASSESSMENT BOARD " * 5  # > 50 chars
        # OCR produced garbage: all tokens below confidence threshold
        ocr_page = {
            "tokens": [
                {"text": "x", "confidence": 50.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
                {"text": "y", "confidence": 40.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
            ],
            "text": "x y",
            "pass_similarity": None,
            "layout": "table",
        }
        gate = _page_quality(
            page_number=1,
            native_text=native_text,
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        self.assertEqual(gate.page_type, "native_sufficient")
        self.assertEqual(gate.selected_source, "native")
        self.assertEqual(gate.failed_gates, [])

    def test_native_insufficient_falls_through_to_normal_gate(self) -> None:
        """If native text is too short, normal quality gate applies."""
        native_text = "short"
        ocr_page = {
            "tokens": [
                {"text": "a", "confidence": 50.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
            ],
            "text": "a",
            "pass_similarity": None,
            "layout": "text",
        }
        gate = _page_quality(
            page_number=1,
            native_text=native_text,
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        # With bad OCR and short native, should NOT auto-approve via native_sufficient
        self.assertNotEqual(gate.page_type, "native_sufficient")


class TestNativeFallbackBypass(unittest.TestCase):
    """When OCR is unreliable but native text is good, fall back to native."""

    def test_ocr_total_failure_with_good_native_falls_back(self) -> None:
        """avg_confidence=None (zero usable tokens) + good native → native_fallback."""
        native_text = "This is substantial native text with more than fifty characters of content."
        # OCR tokens all below 92% threshold → avg_conf = None
        ocr_page = {
            "tokens": [
                {"text": "x", "confidence": 50.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
            ],
            "text": "x",
            "pass_similarity": 0.5,
            "layout": "text",
        }
        gate = _page_quality(
            page_number=1,
            native_text=native_text,
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        # Could be native_sufficient or native_fallback depending on selected_source
        self.assertIn(gate.page_type, ("native_sufficient", "native_fallback"))
        self.assertEqual(gate.selected_source, "native")

    def test_ocr_unreliable_with_good_native_falls_back(self) -> None:
        """high low_conf + low dual_pass + good native → native_fallback."""
        native_text = "Substantial text " * 10
        ocr_page = {
            "tokens": [
                {"text": "a", "confidence": 96.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
                {"text": "b", "confidence": 50.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
                {"text": "c", "confidence": 50.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
                {"text": "d", "confidence": 50.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
                {"text": "e", "confidence": 50.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
            ],
            "text": "a b c d e",
            "pass_similarity": 0.10,  # < 0.25 → unreliable
            "layout": "table",
        }
        gate = _page_quality(
            page_number=5,
            native_text=native_text,
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        self.assertIn(gate.page_type, ("native_sufficient", "native_fallback"))


class TestFigurePageBypass(unittest.TestCase):
    """When OCR fails and no native text, detect as figure page."""

    def test_ocr_total_failure_no_native_marks_figure(self) -> None:
        """No usable OCR tokens, no native text → figure page, approved."""
        ocr_page = {
            "tokens": [
                {"text": "=", "confidence": 30.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
            ],
            "text": "=",
            "pass_similarity": None,
            "layout": "noisy",
        }
        gate = _page_quality(
            page_number=11,
            native_text="",
            ocr_page=ocr_page,
            retry_attempts=2,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        self.assertEqual(gate.page_type, "figure")

    def test_diagram_page_unreliable_ocr_no_native(self) -> None:
        """Page 11 scenario: high low_conf, very low dual_pass, no native."""
        ocr_page = {
            "tokens": [
                {"text": "a", "confidence": 96.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
            ] + [
                {"text": "x", "confidence": 50.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}}
                for _ in range(9)
            ],  # 1 good + 9 bad → low_conf_ratio = 0.9
            "text": "a " + "x " * 9,
            "pass_similarity": 0.16,  # very low
            "layout": "table",
        }
        gate = _page_quality(
            page_number=11,
            native_text="",
            ocr_page=ocr_page,
            retry_attempts=2,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        self.assertEqual(gate.page_type, "figure")


class TestNormalGateStillWorks(unittest.TestCase):
    """Normal quality gate (no bypass) still works for text pages."""

    def test_good_ocr_approves_as_text(self) -> None:
        """Good OCR metrics → approved with page_type=text."""
        ocr_page = {
            "tokens": [
                {"text": "hello", "confidence": 96.0, "bbox": {"x": 0, "y": 0, "w": 20, "h": 10}},
                {"text": "world", "confidence": 97.0, "bbox": {"x": 22, "y": 0, "w": 20, "h": 10}},
            ],
            "text": "hello world",
            "pass_similarity": 0.95,
            "layout": "text",
        }
        gate = _page_quality(
            page_number=1,
            native_text="hello world",
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        self.assertEqual(gate.page_type, "text")

    def test_bad_ocr_bad_native_still_fails(self) -> None:
        """Mediocre OCR (not total failure) + short native → normal gate, needs_review."""
        ocr_page = {
            "tokens": [
                {"text": "a", "confidence": 93.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
                {"text": "b", "confidence": 50.0, "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}},
            ],
            "text": "a b",
            "pass_similarity": 0.50,  # above OCR_UNRELIABLE_DUAL_PASS (0.25) → not unreliable
            "layout": "text",
        }
        gate = _page_quality(
            page_number=1,
            native_text="short",
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        self.assertEqual(gate.page_type, "text")
        # low_conf_ratio = 0.5, which hits gate for default thresholds
        self.assertEqual(gate.status, "needs_review")
        self.assertTrue(len(gate.failed_gates) > 0)


if __name__ == "__main__":
    unittest.main()
