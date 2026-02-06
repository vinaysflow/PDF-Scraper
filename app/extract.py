"""Main extraction orchestrator."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from uuid import uuid4

from pdf2image import convert_from_path

from .ocr import extract_with_ocr, rerun_page_ocr
from .schema import (
    ExtractionMetadata,
    ExtractionResult,
    Page,
    QualityGate,
    QualityResult,
    Stats,
)
from .tika_extract import extract_with_tika
from .utils import (
    EmptyContentError,
    MaxPagesExceededError,
    PdfProcessingError,
    ensure_binaries,
    get_pdf_page_count,
    guard_max_pages,
    similarity_ratio,
    validate_pdf_path,
)

MIN_TIKA_CHARS = 50
MIN_CONFIDENCE_FOR_AVG = 92.0
QUALITY_MIN_AVG_CONFIDENCE = 93.0
QUALITY_MAX_LOW_CONF_RATIO = 0.5
QUALITY_MIN_PASS_SIMILARITY = 0.85
QUALITY_MIN_TIKA_SIMILARITY = 0.85
QUALITY_RETRIES_DEFAULT = 2
DECISION_ACCURACY_THRESHOLD = 0.8

# Optional quality target (e.g. 90) overrides: min_avg_confidence, max_low_conf_ratio,
# min_pass_similarity, min_tika_similarity, decision_accuracy_threshold
QUALITY_TARGET_OVERRIDES: dict[int, dict] = {
    90: {
        "min_avg_confidence": 90.0,
        "max_low_conf_ratio": 0.6,
        "min_pass_similarity": 0.90,
        "min_tika_similarity": 0.90,
        "decision_accuracy_threshold": 0.9,
        "skip_tika_similarity_gate_when_tika_selected": True,
    },
}

# Layout-specific quality overrides. Only specify keys that relax relative to base.
# Merge rule: layout can only relax (lower min_*, raise max_low_conf_ratio).
# Tuned so 31-page maths model paper: table pages 18,19,23,29 and noisy 28,31 can approve.
LAYOUT_QUALITY_OVERRIDES: dict[str, dict] = {
    "table": {
        "max_low_conf_ratio": 0.8,
        "min_pass_similarity": 0.36,  # 0.36 allows dual_pass ~0.36+ (e.g. page 29); was 0.60
        "min_tika_similarity": 0.0,
        "min_avg_confidence": 90.0,
    },
    "noisy": {
        "max_low_conf_ratio": 0.85,   # allow more low-conf tokens on diagram-heavy noisy pages
        "min_pass_similarity": 0.35,  # 0.35 allows dual_pass ~0.37 (page 31), 0.53 (page 28); was 0.75
        "min_tika_similarity": 0.0,
        "min_avg_confidence": 90.0,   # align with table so diagram pages can approve
    },
    "text": {
        "min_pass_similarity": 0.88,
    },
}

# When both low_conf_ratio and dual_pass are very bad, treat as "diagram-heavy" and apply
# one more relaxation so a single very bad page (e.g. 93% low-conf, 16% dual_pass) can still approve.
# Only applied when layout is noisy and metrics cross these thresholds.
DIAGRAM_HEAVY_LOW_CONF_THRESHOLD = 0.85
DIAGRAM_HEAVY_MAX_PASS_SIMILARITY = 0.25
DIAGRAM_HEAVY_OVERRIDES = {
    "max_low_conf_ratio": 0.95,
    "min_pass_similarity": 0.15,
}


def _build_pages(
    page_count: int,
    tika_pages: Dict[int, str],
    ocr_pages: Dict[int, dict],
    ocr_used: set[int],
    prefer_tika_text: bool,
    selected_sources: dict[int, str] | None,
) -> list[Page]:
    pages: list[Page] = []
    for page_number in range(1, page_count + 1):
        tika_text = tika_pages.get(page_number, "")
        selected_source = (
            selected_sources.get(page_number) if selected_sources else None
        )
        if page_number in ocr_used:
            ocr_page = ocr_pages.get(page_number, {})
            use_tika_text = (
                selected_source == "tika"
                or (prefer_tika_text and bool(tika_text.strip()))
            )
            pages.append(
                Page(
                    page_number=page_number,
                    source="tika" if use_tika_text else "ocr",
                    text=tika_text if use_tika_text else ocr_page.get("text", ""),
                    tokens=[] if use_tika_text else ocr_page.get("tokens", []),
                )
            )
        else:
            pages.append(
                Page(
                    page_number=page_number,
                    source="tika",
                    text=tika_text,
                    tokens=[],
                )
            )
    return pages


def _calculate_stats(pages: list[Page]) -> Stats:
    total_tokens = sum(len(page.tokens) for page in pages)
    confidences: list[float] = []
    for page in pages:
        for token in page.tokens:
            if token.confidence >= MIN_CONFIDENCE_FOR_AVG:
                confidences.append(token.confidence)
    avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else None
    return Stats(total_tokens=total_tokens, avg_confidence=avg_conf)


def _page_quality(
    page_number: int,
    tika_text: str,
    ocr_page: dict | None,
    retry_attempts: int,
    best_strategy: dict | None,
    quality_overrides: dict | None = None,
) -> QualityGate:
    tokens = ocr_page.get("tokens", []) if ocr_page else []
    confidences = [token.get("confidence", 0.0) for token in tokens]
    high_conf = [c for c in confidences if c >= MIN_CONFIDENCE_FOR_AVG]
    avg_conf = sum(high_conf) / len(high_conf) if high_conf else None
    low_conf_ratio = (
        (len(confidences) - len(high_conf)) / len(confidences)
        if confidences
        else None
    )
    pass_similarity = ocr_page.get("pass_similarity") if ocr_page else None
    ocr_text = ocr_page.get("text", "") if ocr_page else ""
    layout = ocr_page.get("layout") if ocr_page else None
    tika_similarity = (
        similarity_ratio(tika_text, ocr_text) if tika_text and ocr_text else None
    )
    if tika_similarity is not None:
        accuracy_score = tika_similarity
    elif avg_conf is not None:
        accuracy_score = avg_conf / 100
    else:
        accuracy_score = None

    decision_threshold = (
        quality_overrides.get("decision_accuracy_threshold", DECISION_ACCURACY_THRESHOLD)
        if quality_overrides
        else DECISION_ACCURACY_THRESHOLD
    )
    if accuracy_score is not None and accuracy_score >= decision_threshold:
        decision = "B"
        selected_source = "ocr"
    else:
        decision = "A"
        selected_source = "tika" if tika_text.strip() else "ocr"

    # Base gates from quality_target (or defaults)
    if quality_overrides:
        max_low_conf_ratio = quality_overrides.get(
            "max_low_conf_ratio", QUALITY_MAX_LOW_CONF_RATIO
        )
        min_pass_similarity = quality_overrides.get(
            "min_pass_similarity", QUALITY_MIN_PASS_SIMILARITY
        )
        min_tika_similarity = quality_overrides.get(
            "min_tika_similarity", QUALITY_MIN_TIKA_SIMILARITY
        )
        min_avg_confidence = quality_overrides.get(
            "min_avg_confidence", QUALITY_MIN_AVG_CONFIDENCE
        )
    else:
        max_low_conf_ratio = QUALITY_MAX_LOW_CONF_RATIO
        min_pass_similarity = QUALITY_MIN_PASS_SIMILARITY
        min_tika_similarity = QUALITY_MIN_TIKA_SIMILARITY
        min_avg_confidence = QUALITY_MIN_AVG_CONFIDENCE

    # Phase 1: merge layout overrides (layout can only relax). Treat None as "text" so we get text relaxation when layout is missing (e.g. after retries).
    layout_for_gates = layout or "text"
    layout_overrides = LAYOUT_QUALITY_OVERRIDES.get(layout_for_gates, {})
    for key, value in layout_overrides.items():
        if key == "max_low_conf_ratio":
            max_low_conf_ratio = max(max_low_conf_ratio, value)
        elif key == "min_pass_similarity":
            min_pass_similarity = min(min_pass_similarity, value)
        elif key == "min_tika_similarity":
            min_tika_similarity = min(min_tika_similarity, value)
        elif key == "min_avg_confidence":
            min_avg_confidence = min(min_avg_confidence, value)

    # Phase 1b: diagram-heavy pages (very high low_conf, very low dual_pass) get one more relaxation so they can still approve.
    if (
        layout_for_gates in ("noisy", "table")
        and low_conf_ratio is not None
        and pass_similarity is not None
        and low_conf_ratio > DIAGRAM_HEAVY_LOW_CONF_THRESHOLD
        and pass_similarity < DIAGRAM_HEAVY_MAX_PASS_SIMILARITY
    ):
        for key, value in DIAGRAM_HEAVY_OVERRIDES.items():
            if key == "max_low_conf_ratio":
                max_low_conf_ratio = max(max_low_conf_ratio, value)
            elif key == "min_pass_similarity":
                min_pass_similarity = min(min_pass_similarity, value)

    # Phase 2: when we chose Tika, optionally skip tika_similarity gate
    skip_tika_gate_when_tika = bool(
        quality_overrides and quality_overrides.get("skip_tika_similarity_gate_when_tika_selected")
    )

    failed: list[str] = []
    if avg_conf is None or avg_conf < min_avg_confidence:
        failed.append("avg_confidence")
    if low_conf_ratio is None or low_conf_ratio > max_low_conf_ratio:
        failed.append("low_conf_ratio")
    if pass_similarity is None or pass_similarity < min_pass_similarity:
        failed.append("dual_pass_similarity")
    if (
        not (skip_tika_gate_when_tika and selected_source == "tika")
        and tika_similarity is not None
        and min_tika_similarity > 0
        and tika_similarity < min_tika_similarity
    ):
        failed.append("tika_similarity")

    return QualityGate(
        page_number=page_number,
        status="approved" if not failed else "needs_review",
        layout=layout,
        avg_confidence=round(avg_conf, 4) if avg_conf is not None else None,
        low_conf_ratio=round(low_conf_ratio, 4)
        if low_conf_ratio is not None
        else None,
        dual_pass_similarity=round(pass_similarity, 4)
        if pass_similarity is not None
        else None,
        tika_similarity=round(tika_similarity, 4)
        if tika_similarity is not None
        else None,
        failed_gates=failed,
        retry_attempts=retry_attempts,
        best_strategy=best_strategy,
        accuracy_score=round(accuracy_score, 4) if accuracy_score is not None else None,
        decision=decision,
        selected_source=selected_source,
    )


def _quality_summary(
    pages: list[QualityGate], strict: bool, quality_overrides: dict | None = None
) -> QualityResult:
    status = "approved" if all(page.status == "approved" for page in pages) else "needs_review"
    if quality_overrides:
        min_avg = quality_overrides.get("min_avg_confidence", QUALITY_MIN_AVG_CONFIDENCE)
        max_low = quality_overrides.get("max_low_conf_ratio", QUALITY_MAX_LOW_CONF_RATIO)
        min_pass = quality_overrides.get("min_pass_similarity", QUALITY_MIN_PASS_SIMILARITY)
        min_tika = quality_overrides.get("min_tika_similarity", QUALITY_MIN_TIKA_SIMILARITY)
    else:
        min_avg, max_low = QUALITY_MIN_AVG_CONFIDENCE, QUALITY_MAX_LOW_CONF_RATIO
        min_pass, min_tika = QUALITY_MIN_PASS_SIMILARITY, QUALITY_MIN_TIKA_SIMILARITY
    return QualityResult(
        status=status,
        strict=strict,
        min_avg_confidence=min_avg,
        max_low_conf_ratio=max_low,
        min_dual_pass_similarity=min_pass,
        min_tika_similarity=min_tika,
        pages=pages,
    )


def extract_pdf(
    pdf_path: str | Path,
    dpi: int = 600,
    max_pages: int | None = None,
    force_ocr: bool = False,
    strict_quality: bool = True,
    quality_retries: int = QUALITY_RETRIES_DEFAULT,
    quality_target: int | None = None,
    ocr_lang: str = "eng",
    tessdata_path: str | None = None,
    extract_diagrams: bool = False,
) -> ExtractionResult:
    """Extract text and token-level OCR from a PDF. Optionally run diagram extraction + VLM."""

    quality_overrides = QUALITY_TARGET_OVERRIDES.get(quality_target) if quality_target else None
    validated_path = validate_pdf_path(pdf_path)
    ensure_binaries(["pdftoppm"])
    page_count = get_pdf_page_count(validated_path)
    guard_max_pages(page_count, max_pages)

    tika_text = ""
    tika_pages: list[dict] = []
    tika_failed = False
    pre_rendered_images = None

    if force_ocr:
        # Run Tika and PDF rendering in parallel to save time before OCR.
        ensure_binaries(["tesseract", "pdftoppm"])
        with ThreadPoolExecutor(max_workers=2) as executor:
            f_tika = executor.submit(extract_with_tika, validated_path)
            f_render = executor.submit(
                convert_from_path,
                str(validated_path),
                dpi=dpi,
                first_page=1,
                last_page=max_pages,
            )
            try:
                tika_text, tika_pages = f_tika.result()
            except PdfProcessingError:
                tika_failed = True
            pre_rendered_images = f_render.result()
    else:
        try:
            tika_text, tika_pages = extract_with_tika(validated_path)
        except PdfProcessingError:
            tika_failed = True

    tika_page_map = {page["page_number"]: page.get("text", "") for page in tika_pages}
    ocr_required = set()
    if not tika_failed:
        for page_number in range(1, page_count + 1):
            page_text = tika_page_map.get(page_number, "")
            if len(page_text.strip()) < MIN_TIKA_CHARS:
                ocr_required.add(page_number)
    else:
        ocr_required = set(range(1, page_count + 1))
    if force_ocr:
        ocr_required = set(range(1, page_count + 1))

    ocr_pages: Dict[int, dict] = {}
    ocr_text = ""
    if ocr_required:
        ensure_binaries(["tesseract", "pdftoppm"])
        ocr_text, ocr_page_list = extract_with_ocr(
            validated_path,
            dpi=dpi,
            max_pages=max_pages,
            ocr_lang=ocr_lang,
            tessdata_path=tessdata_path,
            images=pre_rendered_images,
        )
        ocr_pages = {
            page["page_number"]: page for page in ocr_page_list if page is not None
        }

    if not ocr_required and tika_failed:
        raise PdfProcessingError("Failed to extract PDF with Tika and OCR.")

    if ocr_required and not ocr_pages:
        raise PdfProcessingError("OCR did not return any pages.")

    if ocr_required:
        prefer_tika_text = force_ocr and not tika_failed
        pages = _build_pages(
            page_count,
            tika_page_map,
            ocr_pages,
            ocr_required,
            prefer_tika_text=prefer_tika_text,
            selected_sources=None,
        )
        method = "hybrid" if not tika_failed else "ocr"
        engine = "tika+tesseract" if not tika_failed else "tesseract"
        full_text = "\n".join(page.text for page in pages if page.text).strip()
    else:
        pages = _build_pages(
            page_count,
            tika_page_map,
            {},
            set(),
            prefer_tika_text=False,
            selected_sources=None,
        )
        method = "tika"
        engine = "tika"
        full_text = tika_text.strip()

    if not full_text:
        raise EmptyContentError("Extracted content is empty.")

    retry_meta: dict[int, dict] = {}
    if ocr_required:
        for attempt in range(quality_retries):
            quality_pages: list[QualityGate] = []
            failures = []
            for page_number in range(1, page_count + 1):
                quality_gate = _page_quality(
                    page_number,
                    tika_page_map.get(page_number, ""),
                    ocr_pages.get(page_number),
                    retry_meta.get(page_number, {}).get("attempts", 0),
                    ocr_pages.get(page_number, {}).get("strategy"),
                    quality_overrides,
                )
                quality_pages.append(quality_gate)
                if quality_gate.status != "approved" and page_number in ocr_required:
                    failures.append(page_number)

            if not failures:
                break

            for page_number in failures:
                retry_result = rerun_page_ocr(
                    validated_path,
                    page_number,
                    attempt,
                    ocr_lang=ocr_lang,
                    tessdata_path=tessdata_path,
                )
                current_page = ocr_pages.get(page_number, {})
                current_tokens = current_page.get("tokens", [])
                current_conf = [
                    token.get("confidence", 0.0) for token in current_tokens
                ]
                current_high = [c for c in current_conf if c >= MIN_CONFIDENCE_FOR_AVG]
                current_score = sum(current_high) / len(current_high) if current_high else 0.0
                retry_tokens = retry_result.get("tokens", [])
                retry_conf = [token.get("confidence", 0.0) for token in retry_tokens]
                retry_high = [c for c in retry_conf if c >= MIN_CONFIDENCE_FOR_AVG]
                retry_score = sum(retry_high) / len(retry_high) if retry_high else 0.0

                if retry_score >= current_score:
                    ocr_pages[page_number] = {
                        "page_number": page_number,
                        "text": retry_result.get("text", ""),
                        "tokens": retry_result.get("tokens", []),
                        "pass_similarity": retry_result.get("pass_similarity"),
                        "strategy": retry_result.get("strategy"),
                        "layout": retry_result.get("layout"),
                    }
                retry_meta.setdefault(page_number, {"attempts": 0})
                retry_meta[page_number]["attempts"] += 1

    quality_pages: list[QualityGate] = []
    for page_number in range(1, page_count + 1):
        quality_pages.append(
            _page_quality(
                page_number,
                tika_page_map.get(page_number, ""),
                ocr_pages.get(page_number),
                retry_meta.get(page_number, {}).get("attempts", 0),
                ocr_pages.get(page_number, {}).get("strategy"),
                quality_overrides,
            )
        )
    quality = _quality_summary(quality_pages, strict_quality, quality_overrides)
    selected_sources = {
        page.page_number: page.selected_source for page in quality_pages
    }

    if ocr_required:
        prefer_tika_text = force_ocr and not tika_failed
        pages = _build_pages(
            page_count,
            tika_page_map,
            ocr_pages,
            ocr_required,
            prefer_tika_text=prefer_tika_text,
            selected_sources=selected_sources,
        )
        full_text = "\n".join(page.text for page in pages if page.text).strip()
    else:
        pages = _build_pages(
            page_count,
            tika_page_map,
            {},
            set(),
            prefer_tika_text=False,
            selected_sources=selected_sources,
        )
        full_text = tika_text.strip()

    stats = _calculate_stats(pages)
    diagrams_result = None
    if extract_diagrams:
        try:
            from .diagram_pipeline import run_diagram_pipeline
            diagrams_result = run_diagram_pipeline(
                validated_path,
                max_pages=max_pages,
                use_vlm=True,
            )
        except Exception:
            diagrams_result = None
    return ExtractionResult(
        doc_id=str(uuid4()),
        filename=validated_path.name,
        ingested_at=datetime.now(timezone.utc),
        extraction=ExtractionMetadata(
            method=method,
            pages_total=page_count,
            dpi=dpi if method in {"ocr", "hybrid"} else None,
            engine=engine,
        ),
        pages=pages,
        full_text=full_text,
        stats=stats,
        quality=quality,
        diagrams=diagrams_result,
    )
