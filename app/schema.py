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


class PageImage(BaseModel):
    """Embedded image extracted from a PDF page."""

    xref: int | None = None
    format: str  # e.g. "png", "jpeg"
    width: int
    height: int
    bbox: dict | None = None  # {x, y, w, h} in points
    size_bytes: int = 0
    base64_data: str | None = None  # base64-encoded image bytes (opt-in)
    image_url: str | None = None  # API-served URL for the image
    image_path: str | None = None  # local file path on disk
    description: str | None = None  # optional VLM caption


class LayoutBlock(BaseModel):
    """Positional block from native PDF layout (text, image, or drawing)."""

    type: str  # "text" | "image" | "drawing"
    bbox: dict  # {x, y, w, h} in points
    text: str | None = None
    font: str | None = None
    size: float | None = None
    color: int | None = None  # sRGB integer


class PageEquation(BaseModel):
    """Math equation recognized from an image region."""

    bbox: dict | None = None  # {x, y, w, h} in points
    latex: str | None = None
    rendered_text: str | None = None
    error: str | None = None


class PageTable(BaseModel):
    """Structured table extracted from a PDF page."""

    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    csv_text: str = ""
    accuracy: float | None = None
    bbox: dict | None = None  # {x, y, w, h} in points
    num_rows: int = 0
    num_cols: int = 0


class Page(BaseModel):
    """Page-level extraction data."""

    page_number: int
    source: str
    text: str
    tokens: List[Token] = Field(default_factory=list)
    images: List[PageImage] = Field(default_factory=list)
    tables: List[PageTable] = Field(default_factory=list)
    equations: List[PageEquation] = Field(default_factory=list)
    layout_blocks: List[LayoutBlock] = Field(default_factory=list)
    page_width: float | None = None
    page_height: float | None = None


class ExtractionMetadata(BaseModel):
    """Extraction metadata for the document."""

    method: str
    pages_total: int
    dpi: int | None = None
    engine: str


class PageConfidenceSummary(BaseModel):
    """Per-page confidence breakdown (raw and filtered)."""

    page_number: int
    total_tokens: int
    raw_avg_confidence: float | None = None  # all tokens, unfiltered
    filtered_avg_confidence: float | None = None  # tokens >= MIN_CONFIDENCE threshold
    low_conf_token_count: int = 0
    low_conf_ratio: float | None = None


class Stats(BaseModel):
    """Aggregate stats for the extraction."""

    total_tokens: int
    avg_confidence: float | None = None
    confidence_pages: List[PageConfidenceSummary] = Field(default_factory=list)


class QualityGate(BaseModel):
    """Per-page quality gate result."""

    page_number: int
    status: str
    layout: str | None = None
    page_type: str | None = None  # "text" | "native_sufficient" | "native_fallback" | "figure"
    avg_confidence: float | None = None
    low_conf_ratio: float | None = None
    dual_pass_similarity: float | None = None
    native_similarity: float | None = None
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
    min_native_similarity: float
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
    enrichment_warnings: List[str] = Field(default_factory=list)


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


class HighQualityImage(BaseModel):
    """Image metadata for an approved page (no base64 data)."""

    page_number: int
    index: int
    format: str
    width: int
    height: int
    bbox: dict | None = None
    image_url: str | None = None
    image_path: str | None = None


# ---------------------------------------------------------------------------
# Question Bank models
# ---------------------------------------------------------------------------


class QuestionOption(BaseModel):
    """One MCQ option (e.g. A, B, C, D)."""

    label: str  # "A", "B", "C", "D"
    text: str  # the option text


class QuestionImage(BaseModel):
    """Image associated with a specific question."""

    image_url: str | None = None
    image_path: str | None = None
    format: str = "png"
    width: int = 0
    height: int = 0
    description: str | None = None  # VLM description if available
    bbox: dict | None = None


class QuestionPart(BaseModel):
    """Sub-part of a question (e.g. (a), (b), (i), (ii))."""

    label: str  # "a", "b", "i", "ii"
    text: str
    marks: int | None = None


class Question(BaseModel):
    """A single question extracted from an exam paper."""

    question_number: int
    section: str | None = None  # "I", "II", etc.
    page_number: int
    text: str  # full question text
    question_type: str | None = None  # mcq, short_answer, long_answer, proof, construction
    marks: int | None = None
    topic: str | None = None
    difficulty: str | None = None  # easy, medium, hard
    options: List[QuestionOption] = Field(default_factory=list)
    sub_parts: List[QuestionPart] = Field(default_factory=list)
    images: List[QuestionImage] = Field(default_factory=list)
    has_or_alternative: bool = False
    or_question: Question | None = None  # the OR alternative


class QuestionBank(BaseModel):
    """Database-ready question bank extracted from an exam paper."""

    model_config = ConfigDict(json_encoders={datetime: lambda dt: dt.isoformat()})

    doc_id: str
    filename: str
    ingested_at: datetime
    exam_title: str | None = None
    subject: str | None = None
    total_marks: int | None = None
    total_questions: int
    sections: List[dict] = Field(default_factory=list)
    questions: List[Question]


class ConsolidatedReport(BaseModel):
    """Single consolidated output from all checks; high-quality items only for pages/diagrams."""

    model_config = ConfigDict(json_encoders={datetime: lambda dt: dt.isoformat()})

    document: dict  # filename, doc_id, pages_total, ingested_at
    quality_summary: QualitySummary | None = None
    high_quality_pages: List[HighQualityPage] = Field(default_factory=list)
    high_quality_images: List[HighQualityImage] = Field(default_factory=list)
    high_quality_diagrams: List[HighQualityDiagram] = Field(default_factory=list)
    full_text_preview: str | None = None  # first 5000 chars
    stats: dict | None = None
    full_output_path: str | None = None  # optional path to full JSON
