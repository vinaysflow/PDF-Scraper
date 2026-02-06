"""Tests for app.schema models."""

from __future__ import annotations

import unittest
from datetime import datetime

from app.schema import (
    BBox,
    DiagramReading,
    DiagramResult,
    DocumentDiagramsResult,
    ExtractionMetadata,
    ExtractionResult,
    FigureInfo,
    Page,
    QualityGate,
    QualityResult,
    Stats,
    Token,
)


class TestBBox(unittest.TestCase):
    def test_bbox_fields(self) -> None:
        b = BBox(x=0, y=1, w=10, h=20)
        self.assertEqual(b.x, 0)
        self.assertEqual(b.h, 20)


class TestToken(unittest.TestCase):
    def test_token_with_bbox(self) -> None:
        t = Token(
            text="hi",
            bbox=BBox(x=0, y=0, w=5, h=5),
            confidence=95.0,
        )
        self.assertEqual(t.text, "hi")
        self.assertEqual(t.confidence, 95.0)


class TestPage(unittest.TestCase):
    def test_page_default_tokens(self) -> None:
        p = Page(page_number=1, source="tika", text="x")
        self.assertEqual(p.tokens, [])

    def test_page_model_dump(self) -> None:
        p = Page(page_number=2, source="ocr", text="ab", tokens=[])
        d = p.model_dump()
        self.assertEqual(d["page_number"], 2)
        self.assertEqual(d["source"], "ocr")


class TestExtractionMetadata(unittest.TestCase):
    def test_metadata_dpi_optional(self) -> None:
        m = ExtractionMetadata(
            method="tika",
            pages_total=1,
            dpi=None,
            engine="tika",
        )
        self.assertIsNone(m.dpi)


class TestStats(unittest.TestCase):
    def test_avg_confidence_none(self) -> None:
        s = Stats(total_tokens=0, avg_confidence=None)
        self.assertIsNone(s.avg_confidence)


class TestQualityGate(unittest.TestCase):
    def test_failed_gates_default(self) -> None:
        g = QualityGate(page_number=1, status="approved")
        self.assertEqual(g.failed_gates, [])


class TestQualityResult(unittest.TestCase):
    def test_pages_list(self) -> None:
        q = QualityResult(
            status="approved",
            strict=True,
            min_avg_confidence=90.0,
            max_low_conf_ratio=0.6,
            min_dual_pass_similarity=0.9,
            min_tika_similarity=0.9,
            pages=[],
        )
        self.assertEqual(len(q.pages), 0)


class TestFigureInfo(unittest.TestCase):
    def test_bbox_dict(self) -> None:
        f = FigureInfo(
            page_number=1,
            bbox={"x": 0, "y": 0, "w": 100, "h": 50},
            area=5000.0,
            image_path=None,
        )
        self.assertEqual(f.bbox["w"], 100)


class TestDiagramReading(unittest.TestCase):
    def test_error_set(self) -> None:
        r = DiagramReading(description=None, error="VLM disabled")
        self.assertEqual(r.error, "VLM disabled")


class TestDiagramResult(unittest.TestCase):
    def test_figure_and_reading(self) -> None:
        fig = FigureInfo(page_number=1, bbox={}, area=100.0, image_path=None)
        read = DiagramReading(description="A chart", error=None)
        dr = DiagramResult(figure=fig, reading=read)
        self.assertEqual(dr.figure.page_number, 1)
        self.assertEqual(dr.reading.description, "A chart")


class TestDocumentDiagramsResult(unittest.TestCase):
    def test_figures_total_matches_diagrams_len(self) -> None:
        d = DocumentDiagramsResult(
            doc_id="id",
            filename="f.pdf",
            figures_total=0,
            diagrams=[],
            ingested_at=datetime.now(),
        )
        self.assertEqual(d.figures_total, 0)
        self.assertEqual(len(d.diagrams), 0)


class TestExtractionResult(unittest.TestCase):
    def test_quality_optional(self) -> None:
        from app.schema import ExtractionResult, ExtractionMetadata, Page, Stats
        r = ExtractionResult(
            doc_id="x",
            filename="x.pdf",
            ingested_at=datetime.now(),
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
        self.assertIsNone(r.quality)
        self.assertIsNone(r.diagrams)


if __name__ == "__main__":
    unittest.main()
