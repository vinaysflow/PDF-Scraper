"""Tests for source-aware quality gate bypass logic."""

from __future__ import annotations

import unittest

from app.extract import _page_quality, MIN_TIKA_CHARS


class TestTikaSufficientBypass(unittest.TestCase):
    """When selected_source=tika and tika text is substantial, auto-approve."""

    def test_tika_sufficient_approves_despite_bad_ocr(self) -> None:
        """Page 1 scenario: good tika text, garbage OCR. Should approve."""
        tika_text = "KARNATAKA SCHOOL EXAMINATION AND ASSESSMENT BOARD " * 5  # > 50 chars
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
            tika_text=tika_text,
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        self.assertEqual(gate.page_type, "tika_sufficient")
        self.assertEqual(gate.selected_source, "tika")
        self.assertEqual(gate.failed_gates, [])

    def test_tika_insufficient_falls_through_to_normal_gate(self) -> None:
        """If tika text is too short, normal quality gate applies."""
        tika_text = "short"
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
            tika_text=tika_text,
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        # With bad OCR and short tika, should NOT auto-approve via tika_sufficient
        self.assertNotEqual(gate.page_type, "tika_sufficient")


class TestTikaFallbackBypass(unittest.TestCase):
    """When OCR is unreliable but tika text is good, fall back to tika."""

    def test_ocr_total_failure_with_good_tika_falls_back(self) -> None:
        """avg_confidence=None (zero usable tokens) + good tika → tika_fallback."""
        tika_text = "This is substantial tika text with more than fifty characters of content."
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
            tika_text=tika_text,
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        # Could be tika_sufficient or tika_fallback depending on selected_source
        self.assertIn(gate.page_type, ("tika_sufficient", "tika_fallback"))
        self.assertEqual(gate.selected_source, "tika")

    def test_ocr_unreliable_with_good_tika_falls_back(self) -> None:
        """high low_conf + low dual_pass + good tika → tika_fallback."""
        tika_text = "Substantial text " * 10
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
            tika_text=tika_text,
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        self.assertIn(gate.page_type, ("tika_sufficient", "tika_fallback"))


class TestFigurePageBypass(unittest.TestCase):
    """When OCR fails and no tika text, detect as figure page."""

    def test_ocr_total_failure_no_tika_marks_figure(self) -> None:
        """No usable OCR tokens, no tika text → figure page, approved."""
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
            tika_text="",
            ocr_page=ocr_page,
            retry_attempts=2,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        self.assertEqual(gate.page_type, "figure")

    def test_diagram_page_unreliable_ocr_no_tika(self) -> None:
        """Page 11 scenario: high low_conf, very low dual_pass, no tika."""
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
            tika_text="",
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
            tika_text="hello world",
            ocr_page=ocr_page,
            retry_attempts=0,
            best_strategy=None,
        )
        self.assertEqual(gate.status, "approved")
        self.assertEqual(gate.page_type, "text")

    def test_bad_ocr_bad_tika_still_fails(self) -> None:
        """Mediocre OCR (not total failure) + short tika → normal gate, needs_review."""
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
            tika_text="short",
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
