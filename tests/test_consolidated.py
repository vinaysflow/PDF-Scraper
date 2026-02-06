"""Tests for app.consolidated."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.consolidated import build_consolidated_report
from app.schema import (
    ExtractionMetadata,
    ExtractionResult,
    Page,
    QualityGate,
    QualityResult,
    Stats,
)


class TestBuildConsolidatedReport(unittest.TestCase):
    def test_minimal_result_no_quality_no_diagrams(self) -> None:
        result = ExtractionResult(
            doc_id="min",
            filename="min.pdf",
            ingested_at=datetime.now(timezone.utc),
            extraction=ExtractionMetadata(
                method="tika",
                pages_total=1,
                dpi=None,
                engine="tika",
            ),
            pages=[Page(page_number=1, source="tika", text="x", tokens=[])],
            full_text="x",
            stats=Stats(total_tokens=0, avg_confidence=None),
            quality=None,
            diagrams=None,
        )
        report = build_consolidated_report(result)
        self.assertIsNone(report.quality_summary)
        self.assertEqual(len(report.high_quality_pages), 0)
        self.assertEqual(len(report.high_quality_diagrams), 0)
        self.assertEqual(report.document["filename"], "min.pdf")

    def test_with_quality_some_approved(self) -> None:
        result = ExtractionResult(
            doc_id="q",
            filename="q.pdf",
            ingested_at=datetime.now(timezone.utc),
            extraction=ExtractionMetadata(
                method="ocr",
                pages_total=2,
                dpi=300,
                engine="tesseract",
            ),
            pages=[
                Page(page_number=1, source="ocr", text="Page one", tokens=[]),
                Page(page_number=2, source="ocr", text="Page two", tokens=[]),
            ],
            full_text="Page one\nPage two",
            stats=Stats(total_tokens=0, avg_confidence=None),
            quality=QualityResult(
                status="needs_review",
                strict=True,
                min_avg_confidence=90.0,
                max_low_conf_ratio=0.6,
                min_dual_pass_similarity=0.9,
                min_tika_similarity=0.9,
                pages=[
                    QualityGate(page_number=1, status="approved", failed_gates=[]),
                    QualityGate(page_number=2, status="needs_review", failed_gates=["dual_pass_similarity"]),
                ],
            ),
            diagrams=None,
        )
        report = build_consolidated_report(result)
        self.assertIsNotNone(report.quality_summary)
        self.assertEqual(report.quality_summary.status, "needs_review")
        self.assertEqual(report.quality_summary.approved_count, 1)
        self.assertEqual(report.quality_summary.needs_review_count, 1)
        self.assertEqual(len(report.high_quality_pages), 1)
        self.assertEqual(report.high_quality_pages[0].page_number, 1)
        self.assertEqual(report.high_quality_pages[0].quality_status, "approved")

    def test_text_preview_truncated(self) -> None:
        long_text = "a" * 1000
        result = ExtractionResult(
            doc_id="t",
            filename="t.pdf",
            ingested_at=datetime.now(timezone.utc),
            extraction=ExtractionMetadata(
                method="ocr",
                pages_total=1,
                dpi=300,
                engine="tesseract",
            ),
            pages=[Page(page_number=1, source="ocr", text=long_text, tokens=[])],
            full_text=long_text,
            stats=Stats(total_tokens=0, avg_confidence=None),
            quality=QualityResult(
                status="approved",
                strict=True,
                min_avg_confidence=90.0,
                max_low_conf_ratio=0.6,
                min_dual_pass_similarity=0.9,
                min_tika_similarity=0.9,
                pages=[QualityGate(page_number=1, status="approved", failed_gates=[])],
            ),
            diagrams=None,
        )
        report = build_consolidated_report(result, text_preview_chars=100)
        self.assertEqual(len(report.high_quality_pages), 1)
        self.assertLessEqual(len(report.high_quality_pages[0].text_preview), 103)


if __name__ == "__main__":
    unittest.main()
