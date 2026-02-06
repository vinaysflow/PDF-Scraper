"""Tests for app.schema models."""

from __future__ import annotations

import unittest
from datetime import datetime

from app.schema import (
    BBox,
    ConsolidatedReport,
    DiagramReading,
    DiagramResult,
    DocumentDiagramsResult,
    ExtractionMetadata,
    ExtractionResult,
    FigureInfo,
    HighQualityImage,
    Page,
    PageImage,
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
        p = Page(page_number=1, source="native", text="x")
        self.assertEqual(p.tokens, [])

    def test_page_model_dump(self) -> None:
        p = Page(page_number=2, source="ocr", text="ab", tokens=[])
        d = p.model_dump()
        self.assertEqual(d["page_number"], 2)
        self.assertEqual(d["source"], "ocr")


class TestExtractionMetadata(unittest.TestCase):
    def test_metadata_dpi_optional(self) -> None:
        m = ExtractionMetadata(
            method="native",
            pages_total=1,
            dpi=None,
            engine="native",
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
            min_native_similarity=0.9,
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
                method="native",
                pages_total=1,
                dpi=None,
                engine="native",
            ),
            pages=[Page(page_number=1, source="native", text="x", tokens=[])],
            full_text="x",
            stats=Stats(total_tokens=0, avg_confidence=None),
            quality=None,
            diagrams=None,
        )
        self.assertIsNone(r.quality)
        self.assertIsNone(r.diagrams)


class TestPageImage(unittest.TestCase):
    def test_image_url_and_path_fields(self) -> None:
        img = PageImage(
            format="png",
            width=100,
            height=100,
            size_bytes=5000,
            image_url="/api/images/doc-1/page_1/img_0.png",
            image_path="/tmp/image_store/doc-1/page_1/img_0.png",
        )
        self.assertEqual(img.image_url, "/api/images/doc-1/page_1/img_0.png")
        self.assertEqual(img.image_path, "/tmp/image_store/doc-1/page_1/img_0.png")
        self.assertIsNone(img.base64_data)

    def test_image_with_base64_data(self) -> None:
        img = PageImage(
            format="jpeg",
            width=200,
            height=150,
            size_bytes=10000,
            base64_data="iVBORw0KGgo=",
            image_url="/api/images/doc-2/page_1/img_0.jpeg",
        )
        self.assertEqual(img.base64_data, "iVBORw0KGgo=")

    def test_image_defaults(self) -> None:
        img = PageImage(format="png", width=50, height=50)
        self.assertIsNone(img.base64_data)
        self.assertIsNone(img.image_url)
        self.assertIsNone(img.image_path)
        self.assertIsNone(img.xref)
        self.assertIsNone(img.bbox)
        self.assertIsNone(img.description)
        self.assertEqual(img.size_bytes, 0)


class TestHighQualityImage(unittest.TestCase):
    def test_high_quality_image_fields(self) -> None:
        hqi = HighQualityImage(
            page_number=1,
            index=0,
            format="png",
            width=100,
            height=100,
            bbox={"x": 10, "y": 20, "w": 100, "h": 100},
            image_url="/api/images/doc-1/page_1/img_0.png",
            image_path="/tmp/store/doc-1/page_1/img_0.png",
        )
        self.assertEqual(hqi.page_number, 1)
        self.assertEqual(hqi.index, 0)
        self.assertEqual(hqi.image_url, "/api/images/doc-1/page_1/img_0.png")


class TestConsolidatedReportWithImages(unittest.TestCase):
    def test_high_quality_images_default_empty(self) -> None:
        report = ConsolidatedReport(document={"filename": "a.pdf"})
        self.assertEqual(report.high_quality_images, [])

    def test_high_quality_images_included(self) -> None:
        hqi = HighQualityImage(
            page_number=1, index=0, format="png",
            width=100, height=100,
            image_url="/api/images/doc-1/page_1/img_0.png",
        )
        report = ConsolidatedReport(
            document={"filename": "a.pdf"},
            high_quality_images=[hqi],
        )
        self.assertEqual(len(report.high_quality_images), 1)
        self.assertEqual(report.high_quality_images[0].format, "png")


if __name__ == "__main__":
    unittest.main()
