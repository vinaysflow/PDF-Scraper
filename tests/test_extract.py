"""Unit tests for extraction postprocessing."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.extract import (
    _build_pages,
    _calculate_stats,
    _quality_summary,
)
from app.schema import (
    BBox,
    ExtractionMetadata,
    ExtractionResult,
    Page,
    QualityGate,
    QualityResult,
    Stats,
    Token,
)


class TestBuildPages(unittest.TestCase):
    def test_ocr_used_pages_get_ocr_text(self) -> None:
        tika_map = {1: "tika1", 2: "tika2"}
        # Tokens must match Token schema (bbox, confidence) when building Page
        tok = {"text": "a", "bbox": {"x": 0, "y": 0, "w": 5, "h": 5}, "confidence": 95.0}
        ocr_pages = {
            1: {"text": "ocr1", "tokens": [tok]},
            2: {"text": "ocr2", "tokens": []},
        }
        pages = _build_pages(
            page_count=2,
            tika_pages=tika_map,
            ocr_pages=ocr_pages,
            ocr_used={1, 2},
            prefer_tika_text=False,
            selected_sources=None,
        )
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].source, "ocr")
        self.assertEqual(pages[0].text, "ocr1")
        self.assertEqual(len(pages[0].tokens), 1)
        self.assertEqual(pages[1].text, "ocr2")

    def test_selected_source_tika_uses_tika_text(self) -> None:
        tika_map = {1: "tika text"}
        ocr_pages = {1: {"text": "ocr text", "tokens": []}}
        pages = _build_pages(
            page_count=1,
            tika_pages=tika_map,
            ocr_pages=ocr_pages,
            ocr_used={1},
            prefer_tika_text=False,
            selected_sources={1: "tika"},
        )
        self.assertEqual(pages[0].source, "tika")
        self.assertEqual(pages[0].text, "tika text")
        self.assertEqual(pages[0].tokens, [])

    def test_not_ocr_used_gets_tika_only(self) -> None:
        tika_map = {1: "only tika"}
        pages = _build_pages(
            page_count=1,
            tika_pages=tika_map,
            ocr_pages={},
            ocr_used=set(),
            prefer_tika_text=False,
            selected_sources=None,
        )
        self.assertEqual(pages[0].source, "tika")
        self.assertEqual(pages[0].text, "only tika")
        self.assertEqual(pages[0].tokens, [])

    def test_prefer_tika_text_with_tika_content_uses_tika(self) -> None:
        # When prefer_tika_text=True and tika has content, we use tika even if selected_source was ocr.
        tika_map = {1: "tika"}
        ocr_pages = {1: {"text": "ocr", "tokens": []}}
        pages = _build_pages(
            page_count=1,
            tika_pages=tika_map,
            ocr_pages=ocr_pages,
            ocr_used={1},
            prefer_tika_text=True,
            selected_sources={1: "ocr"},
        )
        self.assertEqual(pages[0].source, "tika")
        self.assertEqual(pages[0].text, "tika")


class TestQualitySummary(unittest.TestCase):
    def test_all_approved_yields_approved(self) -> None:
        gates = [
            QualityGate(page_number=1, status="approved", failed_gates=[]),
            QualityGate(page_number=2, status="approved", failed_gates=[]),
        ]
        q = _quality_summary(gates, strict=True, quality_overrides=None)
        self.assertEqual(q.status, "approved")
        self.assertEqual(len(q.pages), 2)

    def test_any_needs_review_yields_needs_review(self) -> None:
        gates = [
            QualityGate(page_number=1, status="approved", failed_gates=[]),
            QualityGate(page_number=2, status="needs_review", failed_gates=["dual_pass_similarity"]),
        ]
        q = _quality_summary(gates, strict=True, quality_overrides=None)
        self.assertEqual(q.status, "needs_review")

    def test_quality_overrides_applied(self) -> None:
        gates = [QualityGate(page_number=1, status="approved", failed_gates=[])]
        overrides = {
            "min_avg_confidence": 90.0,
            "max_low_conf_ratio": 0.6,
            "min_pass_similarity": 0.9,
            "min_tika_similarity": 0.9,
        }
        q = _quality_summary(gates, strict=True, quality_overrides=overrides)
        self.assertEqual(q.min_avg_confidence, 90.0)
        self.assertEqual(q.max_low_conf_ratio, 0.6)


class TestExtractionSchema(unittest.TestCase):
    def test_schema_validation_and_stats(self) -> None:
        pages = [
            Page(
                page_number=1,
                source="ocr",
                text="Hello world",
                tokens=[
                    Token(
                        text="Hello",
                        bbox=BBox(x=0, y=0, w=10, h=10),
                        confidence=95.0,
                    ),
                    Token(
                        text="world",
                        bbox=BBox(x=12, y=0, w=12, h=10),
                        confidence=90.0,
                    ),
                ],
            )
        ]
        stats = _calculate_stats(pages)
        result = ExtractionResult(
            doc_id="doc-123",
            filename="sample.pdf",
            ingested_at=datetime(2026, 1, 28, tzinfo=timezone.utc),
            extraction=ExtractionMetadata(
                method="ocr",
                pages_total=1,
                dpi=300,
                engine="tesseract",
            ),
            pages=pages,
            full_text="Hello world",
            stats=stats,
            quality=None,
            diagrams=None,
        )

        payload = result.model_dump()
        self.assertEqual(payload["stats"]["total_tokens"], 2)
        # avg_confidence uses only tokens with confidence >= MIN_CONFIDENCE_FOR_AVG (92); 90 is excluded
        self.assertAlmostEqual(payload["stats"]["avg_confidence"], 95.0)

    def test_stats_with_no_tokens(self) -> None:
        pages = [Page(page_number=1, source="tika", text="Text", tokens=[])]
        stats = _calculate_stats(pages)
        self.assertEqual(stats.total_tokens, 0)
        self.assertIsNone(stats.avg_confidence)


if __name__ == "__main__":
    unittest.main()
