"""Build consolidated report from extraction result (high-quality summary)."""

from __future__ import annotations

from .schema import (
    ConsolidatedReport,
    ExtractionResult,
    HighQualityDiagram,
    HighQualityPage,
    QualitySummary,
)

TEXT_PREVIEW_CHARS = 500
FULL_TEXT_PREVIEW_CHARS = 5000


def build_consolidated_report(
    result: ExtractionResult,
    full_output_path: str | None = None,
    text_preview_chars: int = TEXT_PREVIEW_CHARS,
    full_text_preview_chars: int = FULL_TEXT_PREVIEW_CHARS,
) -> ConsolidatedReport:
    """
    Build a single consolidated report from an ExtractionResult.
    - quality_summary: overall and per-page quality (all pages summarized).
    - high_quality_pages: only pages with quality status "approved".
    - high_quality_diagrams: only figures with reading.error None and description present.
    """
    doc = {
        "filename": result.filename,
        "doc_id": result.doc_id,
        "pages_total": result.extraction.pages_total,
        "ingested_at": result.ingested_at.isoformat(),
    }

    quality_summary: QualitySummary | None = None
    high_quality_pages: list[HighQualityPage] = []

    if result.quality:
        q = result.quality
        approved = [p.page_number for p in q.pages if p.status == "approved"]
        needs_review = [
            {
                "page_number": p.page_number,
                "failed_gates": p.failed_gates,
                "layout": p.layout,
                "status": p.status,
            }
            for p in q.pages
            if p.status != "approved"
        ]
        quality_summary = QualitySummary(
            status=q.status,
            strict=q.strict,
            pages_total=len(q.pages),
            approved_count=len(approved),
            needs_review_count=len(needs_review),
            approved_page_numbers=approved,
            needs_review_pages=needs_review,
        )
        approved_set = set(approved)
        for page in result.pages:
            if page.page_number in approved_set:
                preview = (page.text or "")[:text_preview_chars]
                if len(page.text or "") > text_preview_chars:
                    preview += "..."
                high_quality_pages.append(
                    HighQualityPage(
                        page_number=page.page_number,
                        source=page.source,
                        text_preview=preview,
                        quality_status="approved",
                    )
                )

    high_quality_diagrams: list[HighQualityDiagram] = []
    if result.diagrams:
        for dr in result.diagrams.diagrams:
            read = dr.reading
            if read.error is None and read.description:
                high_quality_diagrams.append(
                    HighQualityDiagram(
                        page_number=dr.figure.page_number,
                        bbox=dr.figure.bbox,
                        area=dr.figure.area,
                        description=read.description,
                        kind=read.kind,
                    )
                )

    full_text_preview = None
    if result.full_text:
        full_text_preview = result.full_text[:full_text_preview_chars]
        if len(result.full_text) > full_text_preview_chars:
            full_text_preview += "..."

    stats = None
    if result.stats:
        stats = result.stats.model_dump()

    return ConsolidatedReport(
        document=doc,
        quality_summary=quality_summary,
        high_quality_pages=high_quality_pages,
        high_quality_diagrams=high_quality_diagrams,
        full_text_preview=full_text_preview,
        stats=stats,
        full_output_path=full_output_path,
    )
