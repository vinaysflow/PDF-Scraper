"""
QA tests for extraction pipeline: quality gates, consolidated report, output schema.
Run with: python -m unittest tests.qa_pipeline -v
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Import app modules (tests run from project root)
from app.consolidated import build_consolidated_report
from app.extract import (
    DIAGRAM_HEAVY_LOW_CONF_THRESHOLD,
    DIAGRAM_HEAVY_MAX_PASS_SIMILARITY,
    LAYOUT_QUALITY_OVERRIDES,
    _page_quality,
)
from app.schema import (
    ExtractionMetadata,
    ExtractionResult,
    Page,
    QualityResult,
    QualityGate,
    Stats,
)


class TestQualityGates(unittest.TestCase):
    """Quality gate logic: layout overrides and diagram-heavy relaxation."""

    def test_table_layout_gets_relaxed_min_pass(self) -> None:
        self.assertIn("table", LAYOUT_QUALITY_OVERRIDES)
        self.assertLess(
            LAYOUT_QUALITY_OVERRIDES["table"]["min_pass_similarity"],
            0.9,
            msg="Table layout should relax min_pass_similarity",
        )

    def test_noisy_layout_has_max_low_conf(self) -> None:
        self.assertIn("noisy", LAYOUT_QUALITY_OVERRIDES)
        self.assertGreaterEqual(
            LAYOUT_QUALITY_OVERRIDES["noisy"]["max_low_conf_ratio"],
            0.75,
            msg="Noisy layout should allow higher low_conf_ratio",
        )

    def test_diagram_heavy_thresholds_defined(self) -> None:
        self.assertLess(DIAGRAM_HEAVY_LOW_CONF_THRESHOLD, 1.0)
        self.assertGreater(DIAGRAM_HEAVY_MAX_PASS_SIMILARITY, 0.0)

    def test_page_quality_table_approves_with_relaxed_pass(self) -> None:
        """With quality_target 90, table page with pass_similarity 0.5 and low_conf 0.5 should approve."""
        overrides = {
            "max_low_conf_ratio": 0.6,
            "min_pass_similarity": 0.9,
            "min_avg_confidence": 90.0,
            "skip_native_similarity_gate_when_native_selected": True,
        }
        gate = _page_quality(
            page_number=1,
            native_text="",
            ocr_page={
                "text": "x",
                "tokens": [{"confidence": 95.0}, {"confidence": 92.0}],
                "pass_similarity": 0.5,
                "layout": "table",
            },
            retry_attempts=0,
            best_strategy=None,
            quality_overrides=overrides,
        )
        self.assertEqual(gate.layout, "table")
        self.assertEqual(gate.status, "approved", msg=f"failed_gates: {gate.failed_gates}")

    def test_page_quality_diagram_heavy_approves(self) -> None:
        """Diagram-heavy page (high low_conf > 0.85, low pass < 0.25) should approve with Phase 1b."""
        overrides = {
            "max_low_conf_ratio": 0.6,
            "min_pass_similarity": 0.9,
            "min_avg_confidence": 90.0,
            "skip_native_similarity_gate_when_native_selected": True,
        }
        # 9 low-conf + 1 high-conf so low_conf_ratio = 0.9 (> 0.85), avg_conf = 95 (>= 90)
        tokens = [{"confidence": 50.0} for _ in range(9)] + [{"confidence": 95.0}]
        gate = _page_quality(
            page_number=1,
            native_text="",
            ocr_page={
                "text": "x",
                "tokens": tokens,
                "pass_similarity": 0.16,
                "layout": "noisy",
            },
            retry_attempts=0,
            best_strategy=None,
            quality_overrides=overrides,
        )
        self.assertEqual(gate.status, "approved", msg=f"failed_gates: {gate.failed_gates}")


class TestConsolidatedReport(unittest.TestCase):
    """Consolidated report schema and content."""

    def test_build_consolidated_report_schema(self) -> None:
        """Report has required top-level keys and types."""
        result = ExtractionResult(
            doc_id="qa-doc",
            filename="test.pdf",
            ingested_at=datetime.now(timezone.utc),
            extraction=ExtractionMetadata(
                method="ocr",
                pages_total=2,
                dpi=300,
                engine="tesseract",
            ),
            pages=[
                Page(page_number=1, source="ocr", text="Page 1", tokens=[]),
                Page(page_number=2, source="ocr", text="Page 2", tokens=[]),
            ],
            full_text="Page 1\nPage 2",
            stats=Stats(total_tokens=0, avg_confidence=None),
            quality=QualityResult(
                status="approved",
                strict=True,
                min_avg_confidence=90.0,
                max_low_conf_ratio=0.6,
                min_dual_pass_similarity=0.9,
                min_native_similarity=0.9,
                pages=[
                    QualityGate(page_number=1, status="approved", failed_gates=[]),
                    QualityGate(page_number=2, status="approved", failed_gates=[]),
                ],
            ),
            diagrams=None,
        )
        report = build_consolidated_report(result)
        self.assertIn("document", report.model_dump())
        self.assertIn("quality_summary", report.model_dump())
        self.assertIn("high_quality_pages", report.model_dump())
        self.assertIn("high_quality_diagrams", report.model_dump())
        self.assertIn("stats", report.model_dump())
        self.assertEqual(report.quality_summary.status, "approved")
        self.assertEqual(report.quality_summary.approved_count, 2)
        self.assertEqual(len(report.high_quality_pages), 2)


class TestFullOutputSchema(unittest.TestCase):
    """Validate full extraction JSON output schema (run after a full pipeline run)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.out_dir = Path(__file__).resolve().parent.parent / "outputs"
        cls.full_path = cls.out_dir / "ENGLISH_10th_Maths_Model_paper_01_full.json"
        cls.consolidated_path = cls.out_dir / "ENGLISH_10th_Maths_01_consolidated.json"

    def test_full_output_exists_and_valid_json(self) -> None:
        if not self.full_path.exists():
            self.skipTest("Full output file not found; run pipeline first")
        with open(self.full_path) as f:
            data = json.load(f)
        self.assertIn("doc_id", data)
        self.assertIn("filename", data)
        self.assertIn("pages", data)
        self.assertIn("extraction", data)
        self.assertIn("quality", data)
        self.assertIsInstance(data["pages"], list)
        self.assertIsInstance(data["extraction"], dict)
        self.assertIn("pages_total", data["extraction"])
        if data["pages"]:
            page = data["pages"][0]
            self.assertIn("page_number", page)
            self.assertIn("source", page)
            self.assertIn("text", page)
            self.assertIn("tokens", page)

    def test_consolidated_output_exists_and_valid(self) -> None:
        if not self.consolidated_path.exists():
            self.skipTest("Consolidated output file not found; run pipeline first")
        with open(self.consolidated_path) as f:
            data = json.load(f)
        self.assertIn("document", data)
        self.assertIn("quality_summary", data)
        self.assertIn("high_quality_pages", data)
        self.assertIn("high_quality_diagrams", data)
        self.assertIn("stats", data)
        self.assertIn("approved_count", data["quality_summary"])
        self.assertIn("pages_total", data["quality_summary"])


class TestOCRWorkersConfig(unittest.TestCase):
    """OCR and VLM worker defaults and env parsing."""

    def test_ocr_workers_env_parsed(self) -> None:
        from app.ocr import _default_ocr_workers
        # Default without env
        os.environ.pop("OCR_WORKERS", None)
        w = _default_ocr_workers()
        self.assertGreaterEqual(w, 1)
        self.assertLessEqual(w, 32)
        # With env
        os.environ["OCR_WORKERS"] = "8"
        try:
            self.assertEqual(_default_ocr_workers(), 8)
        finally:
            os.environ.pop("OCR_WORKERS", None)

    def test_vlm_workers_default(self) -> None:
        from app.diagram_pipeline import _default_vlm_workers
        os.environ.pop("VLM_WORKERS", None)
        w = _default_vlm_workers()
        self.assertGreaterEqual(w, 1)
        self.assertLessEqual(w, 20)


class TestOCRParallelParity(unittest.TestCase):
    """Integration: OCR with workers=1 vs workers=2 yields same structure and page count."""

    @classmethod
    def setUpClass(cls) -> None:
        sample = os.environ.get(
            "SAMPLE_PDF",
            str(Path.home() / "Downloads/Sample PDF FOR TESTING/english maths question paper 01.pdf"),
        )
        cls.sample_pdf = Path(sample)

    def test_ocr_workers_parity(self) -> None:
        if not self.sample_pdf.exists():
            self.skipTest(f"Sample PDF not found: {self.sample_pdf}")
        from pdf2image import convert_from_path
        from app.ocr import extract_with_ocr

        pdf_path = self.sample_pdf
        images = convert_from_path(str(pdf_path), dpi=150, first_page=1, last_page=2)
        if len(images) < 2:
            self.skipTest("Need at least 2 pages for parity test")

        _, pages1 = extract_with_ocr(pdf_path, dpi=150, max_pages=2, workers=1, images=images)
        _, pages2 = extract_with_ocr(pdf_path, dpi=150, max_pages=2, workers=2, images=images)

        self.assertEqual(len(pages1), len(pages2), "Page count must match")
        for i, (p1, p2) in enumerate(zip(pages1, pages2)):
            self.assertEqual(p1["page_number"], p2["page_number"], f"Page number mismatch at {i}")
            for key in ("text", "tokens", "layout", "pass_similarity", "strategy"):
                self.assertIn(key, p1, f"workers=1 page missing key {key}")
                self.assertIn(key, p2, f"workers=2 page missing key {key}")
        # Text may differ slightly due to non-determinism; structure must be present
        self.assertIsInstance(pages1[0]["tokens"], list)
        self.assertIsInstance(pages2[0]["tokens"], list)


if __name__ == "__main__":
    unittest.main()
