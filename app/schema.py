"""Pydantic models for extraction results."""

from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class BBox(BaseModel):
    """Bounding box for a token."""

    x: int
    y: int
    w: int
    h: int


class Token(BaseModel):
    """Token-level OCR data."""

    text: str
    bbox: BBox
    confidence: float


class Page(BaseModel):
    """Page-level extraction data."""

    page_number: int
    source: str
    text: str
    tokens: List[Token] = Field(default_factory=list)


class ExtractionMetadata(BaseModel):
    """Extraction metadata for the document."""

    method: str
    pages_total: int
    dpi: int | None = None
    engine: str


class Stats(BaseModel):
    """Aggregate stats for the extraction."""

    total_tokens: int
    avg_confidence: float | None = None


class QualityGate(BaseModel):
    """Per-page quality gate result."""

    page_number: int
    status: str
    layout: str | None = None
    avg_confidence: float | None = None
    low_conf_ratio: float | None = None
    dual_pass_similarity: float | None = None
    tika_similarity: float | None = None
    failed_gates: List[str] = Field(default_factory=list)
    retry_attempts: int = 0
    best_strategy: dict | None = None
    accuracy_score: float | None = None
    decision: str | None = None
    selected_source: str | None = None


class QualityResult(BaseModel):
    """Document-level quality gates."""

    status: str
    strict: bool
    min_avg_confidence: float
    max_low_conf_ratio: float
    min_dual_pass_similarity: float
    min_tika_similarity: float
    pages: List[QualityGate]


class FigureInfo(BaseModel):
    """Extracted figure metadata (no image bytes in schema)."""

    page_number: int
    bbox: dict  # x, y, w, h (points)
    area: float
    image_path: str | None = None


class DiagramReading(BaseModel):
    """VLM output for one figure: description and optional structure/chart_data."""

    description: str | None = None
    structure: dict | None = None
    chart_data: dict | None = None
    kind: str | None = None  # flowchart|chart|photo|other
    error: str | None = None


class DiagramResult(BaseModel):
    """One figure plus its reading."""

    figure: FigureInfo
    reading: DiagramReading


class DocumentDiagramsResult(BaseModel):
    """Document-level diagram extraction result."""

    model_config = ConfigDict(json_encoders={datetime: lambda dt: dt.isoformat()})

    doc_id: str
    filename: str
    figures_total: int
    diagrams: List[DiagramResult]
    ingested_at: datetime


class ExtractionResult(BaseModel):
    """Canonical extraction output payload."""

    model_config = ConfigDict(json_encoders={datetime: lambda dt: dt.isoformat()})

    doc_id: str
    filename: str
    ingested_at: datetime
    extraction: ExtractionMetadata
    pages: List[Page]
    full_text: str
    stats: Stats
    quality: QualityResult | None = None
    diagrams: DocumentDiagramsResult | None = None


class QualitySummary(BaseModel):
    """Consolidated quality summary."""

    status: str
    strict: bool
    pages_total: int
    approved_count: int
    needs_review_count: int
    approved_page_numbers: List[int]
    needs_review_pages: List[dict]  # page_number, failed_gates, layout, etc.


class HighQualityPage(BaseModel):
    """One page that passed quality gates (approved)."""

    page_number: int
    source: str
    text_preview: str  # first N chars
    quality_status: str = "approved"


class HighQualityDiagram(BaseModel):
    """One figure with a valid VLM reading (no error, has description)."""

    page_number: int
    bbox: dict
    area: float
    description: str
    kind: str | None = None


class ConsolidatedReport(BaseModel):
    """Single consolidated output from all checks; high-quality items only for pages/diagrams."""

    model_config = ConfigDict(json_encoders={datetime: lambda dt: dt.isoformat()})

    document: dict  # filename, doc_id, pages_total, ingested_at
    quality_summary: QualitySummary | None = None
    high_quality_pages: List[HighQualityPage] = Field(default_factory=list)
    high_quality_diagrams: List[HighQualityDiagram] = Field(default_factory=list)
    full_text_preview: str | None = None  # first 5000 chars
    stats: dict | None = None
    full_output_path: str | None = None  # optional path to full JSON
