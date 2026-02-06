"""Orchestrate figure extraction and VLM-based diagram reading."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .figure_extract import extract_figures
from .schema import (
    DiagramReading,
    DiagramResult,
    DocumentDiagramsResult,
    FigureInfo,
)
from .utils import validate_pdf_path

try:
    from . import diagram_vlm
except ImportError:
    diagram_vlm = None


def _default_vlm_workers() -> int:
    """Default number of parallel VLM workers (env VLM_WORKERS, or 5)."""
    try:
        return max(1, min(20, int(os.environ.get("VLM_WORKERS", "5"))))
    except (TypeError, ValueError):
        return 5


def _process_one_figure(
    fig: dict,
    use_vlm: bool,
    vlm_model: str,
) -> DiagramResult:
    """Run VLM (describe, structure, chart_data) for one figure. Used for parallel diagram pipeline."""
    page_number = fig["page_number"]
    bbox = fig["bbox"]
    area = fig["area"]
    image = fig.get("image")

    figure_info = FigureInfo(
        page_number=page_number,
        bbox=bbox,
        area=area,
        image_path=None,
    )

    description: str | None = None
    structure: dict | None = None
    chart_data: dict | None = None
    kind: str | None = None
    error: str | None = None

    if use_vlm and diagram_vlm and image is not None:
        if not diagram_vlm._is_configured():
            error = "VLM not configured (set OPENAI_API_KEY)"
        else:
            description = diagram_vlm.describe_figure(image, "describe", model=vlm_model)
            if description is None:
                error = "VLM describe failed"
            else:
                struct_text = diagram_vlm.describe_figure(image, "structure", model=vlm_model)
                if struct_text:
                    try:
                        if struct_text.strip().startswith("{"):
                            structure = json.loads(struct_text)
                            if isinstance(structure, dict):
                                kind = structure.get("type")
                    except Exception:
                        pass
                chart_data = diagram_vlm.extract_chart_data(image, model=vlm_model)
    else:
        if not use_vlm:
            error = "VLM disabled"
        elif image is None:
            error = "No image"

    reading = DiagramReading(
        description=description,
        structure=structure,
        chart_data=chart_data,
        kind=kind,
        error=error,
    )
    return DiagramResult(figure=figure_info, reading=reading)


def run_diagram_pipeline(
    pdf_path: str | Path,
    max_pages: int | None = None,
    min_figure_area: float | None = None,
    use_vlm: bool = True,
    vlm_model: str = "gpt-4o-mini",
    vlm_workers: int | None = None,
) -> DocumentDiagramsResult:
    """
    Extract figures from PDF and run VLM on each (in parallel). Returns DocumentDiagramsResult.
    If OPENAI_API_KEY is not set, use_vlm is ignored and readings have error set.
    """
    validated = validate_pdf_path(pdf_path)
    filename = validated.name
    doc_id = str(uuid4())
    ingested_at = datetime.now(timezone.utc)

    figures = extract_figures(
        validated,
        max_pages=max_pages,
        min_figure_area=min_figure_area or 1000,
    )

    if not figures:
        return DocumentDiagramsResult(
            doc_id=doc_id,
            filename=filename,
            figures_total=0,
            diagrams=[],
            ingested_at=ingested_at,
        )

    n_workers = vlm_workers if vlm_workers is not None else _default_vlm_workers()
    n_workers = min(n_workers, len(figures))

    if n_workers <= 1:
        diagrams = [
            _process_one_figure(fig, use_vlm, vlm_model) for fig in figures
        ]
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            diagrams = list(
                executor.map(
                    lambda fig: _process_one_figure(fig, use_vlm, vlm_model),
                    figures,
                )
            )

    return DocumentDiagramsResult(
        doc_id=doc_id,
        filename=filename,
        figures_total=len(diagrams),
        diagrams=diagrams,
        ingested_at=ingested_at,
    )
