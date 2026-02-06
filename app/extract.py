"""Main extraction orchestrator."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from uuid import uuid4

from pdf2image import convert_from_path

from .config import EXTRACT_IMAGES, EXTRACT_LAYOUT, EXTRACT_MATH, EXTRACT_TABLES, OCR_ENGINE, SAFE_BATCH_PAGES, SAFE_MODE
from .ocr import extract_with_ocr, rerun_page_ocr
from .pdf_text import (
    extract_layout_blocks,
    extract_native_text,
    extract_page_dimensions,
    page_has_text,
)
from .schema import (
    ExtractionMetadata,
    ExtractionResult,
    LayoutBlock,
    Page,
    PageEquation,
    PageImage,
    PageTable,
    QualityGate,
    QualityResult,
    Stats,
)
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

# Thresholds for detecting OCR failure / figure-heavy pages.
# When both conditions are true simultaneously, OCR is unreliable for this page.
OCR_UNRELIABLE_LOW_CONF = 0.75   # 75%+ tokens below confidence threshold
OCR_UNRELIABLE_DUAL_PASS = 0.25  # two OCR passes agree < 25%

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
LAYOUT_QUALITY_OVERRIDES: dict[str, dict] = {
    "table": {
        "max_low_conf_ratio": 0.8,
        "min_pass_similarity": 0.36,
        "min_tika_similarity": 0.0,
        "min_avg_confidence": 90.0,
    },
    "noisy": {
        "max_low_conf_ratio": 0.85,
        "min_pass_similarity": 0.35,
        "min_tika_similarity": 0.0,
        "min_avg_confidence": 90.0,
    },
    "text": {
        "min_pass_similarity": 0.88,
    },
}

DIAGRAM_HEAVY_LOW_CONF_THRESHOLD = 0.85
DIAGRAM_HEAVY_MAX_PASS_SIMILARITY = 0.25
DIAGRAM_HEAVY_OVERRIDES = {
    "max_low_conf_ratio": 0.95,
    "min_pass_similarity": 0.15,
}


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
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

    if quality_overrides:
        max_low_conf_ratio = quality_overrides.get("max_low_conf_ratio", QUALITY_MAX_LOW_CONF_RATIO)
        min_pass_similarity = quality_overrides.get("min_pass_similarity", QUALITY_MIN_PASS_SIMILARITY)
        min_tika_similarity = quality_overrides.get("min_tika_similarity", QUALITY_MIN_TIKA_SIMILARITY)
        min_avg_confidence = quality_overrides.get("min_avg_confidence", QUALITY_MIN_AVG_CONFIDENCE)
    else:
        max_low_conf_ratio = QUALITY_MAX_LOW_CONF_RATIO
        min_pass_similarity = QUALITY_MIN_PASS_SIMILARITY
        min_tika_similarity = QUALITY_MIN_TIKA_SIMILARITY
        min_avg_confidence = QUALITY_MIN_AVG_CONFIDENCE

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

    skip_tika_gate_when_tika = bool(
        quality_overrides and quality_overrides.get("skip_tika_similarity_gate_when_tika_selected")
    )

    # ------------------------------------------------------------------
    # Source-aware quality bypass (Tier 1 intelligence)
    # ------------------------------------------------------------------
    tika_sufficient = len(tika_text.strip()) >= MIN_TIKA_CHARS
    ocr_total_failure = avg_conf is None  # zero tokens above confidence threshold
    ocr_unreliable = (
        low_conf_ratio is not None and low_conf_ratio > OCR_UNRELIABLE_LOW_CONF
        and pass_similarity is not None and pass_similarity < OCR_UNRELIABLE_DUAL_PASS
    )
    page_type = "text"

    if selected_source == "tika" and tika_sufficient:
        # Tika extracted good text and was selected. OCR metrics are irrelevant
        # to the final output — auto-approve.
        page_type = "tika_sufficient"
        failed: list[str] = []
    elif (ocr_total_failure or ocr_unreliable) and tika_sufficient:
        # OCR failed or is unreliable, but Tika has good text. Fall back to Tika.
        page_type = "tika_fallback"
        selected_source = "tika"
        decision = "A"
        failed: list[str] = []
    elif ocr_total_failure or ocr_unreliable:
        # OCR failed and no substantial Tika text — page is likely figure/diagram.
        # This is expected; approve with a "figure" flag.
        page_type = "figure"
        failed: list[str] = []
    else:
        # Normal quality gate evaluation.
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
        page_type=page_type,
        avg_confidence=round(avg_conf, 4) if avg_conf is not None else None,
        low_conf_ratio=round(low_conf_ratio, 4) if low_conf_ratio is not None else None,
        dual_pass_similarity=round(pass_similarity, 4) if pass_similarity is not None else None,
        tika_similarity=round(tika_similarity, 4) if tika_similarity is not None else None,
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


# ---------------------------------------------------------------------------
# Batched OCR (safe mode): render + OCR in small page batches to bound memory
# ---------------------------------------------------------------------------
def _ocr_batched(
    validated_path: Path,
    page_count: int,
    dpi: int,
    max_pages: int | None,
    ocr_lang: str,
    tessdata_path: str | None,
    batch_size: int = SAFE_BATCH_PAGES,
) -> Dict[int, dict]:
    """Render and OCR pages in batches of *batch_size*. Returns ocr_pages dict."""
    last_page = min(max_pages, page_count) if max_pages else page_count
    ocr_pages: Dict[int, dict] = {}
    for start in range(1, last_page + 1, batch_size):
        end = min(start + batch_size - 1, last_page)
        batch_images = convert_from_path(
            str(validated_path), dpi=dpi, first_page=start, last_page=end,
        )
        _, page_list = extract_with_ocr(
            validated_path, dpi=dpi, max_pages=None,
            ocr_lang=ocr_lang, tessdata_path=tessdata_path,
            images=batch_images, workers=1,
        )
        for p in page_list:
            real_page = start + (p["page_number"] - 1)
            p["page_number"] = real_page
            ocr_pages[real_page] = p
        del batch_images  # free images before next batch
    return ocr_pages


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
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

    # -------------------------------------------------------------------
    # Step 1: Native text extraction (PyMuPDF — fast, no JVM)
    # -------------------------------------------------------------------
    native_text, native_pages = extract_native_text(validated_path)
    native_page_map: Dict[int, str] = {
        p["page_number"]: p["text"] for p in native_pages
    }

    # -------------------------------------------------------------------
    # Step 2: Determine which pages need OCR
    # -------------------------------------------------------------------
    ocr_required: set[int] = set()
    if force_ocr:
        ocr_required = set(range(1, page_count + 1))
    else:
        for pg in native_pages:
            if not page_has_text(pg, min_chars=MIN_TIKA_CHARS):
                ocr_required.add(pg["page_number"])

    # -------------------------------------------------------------------
    # Step 3: OCR only the pages that need it
    # -------------------------------------------------------------------
    pre_rendered_images = None
    ocr_pages: Dict[int, dict] = {}
    use_paddle = OCR_ENGINE == "paddleocr"

    if ocr_required and use_paddle:
        # ----- PaddleOCR path -----
        try:
            from .providers.ocr_paddle import is_available as paddle_available, ocr_pages as paddle_ocr_pages

            if paddle_available():
                ensure_binaries(["pdftoppm"])
                for pn in sorted(ocr_required):
                    batch_images = convert_from_path(
                        str(validated_path), dpi=dpi, first_page=pn, last_page=pn,
                    )
                    paddle_results = paddle_ocr_pages(batch_images, lang=ocr_lang[:2], start_page=pn)
                    ocr_pages.update(paddle_results)
                    del batch_images
            else:
                use_paddle = False  # fall back to Tesseract
        except Exception:
            use_paddle = False  # fall back to Tesseract

    if ocr_required and not use_paddle:
        # ----- Tesseract path (default) -----
        ensure_binaries(["tesseract", "pdftoppm"])

        if force_ocr:
            # Render all pages for OCR when force_ocr is on.
            pre_rendered_images = convert_from_path(
                str(validated_path), dpi=dpi, first_page=1, last_page=max_pages,
            )
            _, ocr_page_list = extract_with_ocr(
                validated_path, dpi=dpi, max_pages=max_pages,
                ocr_lang=ocr_lang, tessdata_path=tessdata_path,
                images=pre_rendered_images,
            )
            ocr_pages = {
                page["page_number"]: page for page in ocr_page_list if page is not None
            }
        elif SAFE_MODE:
            # Batched OCR for constrained environments (Railway).
            ocr_pages = _ocr_batched(
                validated_path, page_count, dpi, max_pages,
                ocr_lang, tessdata_path,
            )
        else:
            # Render + OCR only the pages that need it (not ALL pages).
            for pn in sorted(ocr_required):
                batch_images = convert_from_path(
                    str(validated_path), dpi=dpi, first_page=pn, last_page=pn,
                )
                _, page_list = extract_with_ocr(
                    validated_path, dpi=dpi, max_pages=None,
                    ocr_lang=ocr_lang, tessdata_path=tessdata_path,
                    images=batch_images, workers=1,
                )
                for p in page_list:
                    p["page_number"] = pn
                    ocr_pages[pn] = p
                del batch_images

    if not ocr_required and not native_text.strip():
        raise PdfProcessingError("No text could be extracted from PDF.")
    if ocr_required and not ocr_pages:
        raise PdfProcessingError("OCR did not return any pages.")

    # -------------------------------------------------------------------
    # Step 4: Initial page assembly
    # -------------------------------------------------------------------
    ocr_engine_name = "paddleocr" if use_paddle else "tesseract"
    if ocr_required:
        prefer_native_text = force_ocr  # when force_ocr, prefer native text over OCR
        pages = _build_pages(page_count, native_page_map, ocr_pages, ocr_required,
                             prefer_tika_text=prefer_native_text, selected_sources=None)
        method = "hybrid" if not force_ocr else "ocr"
        engine = f"pymupdf+{ocr_engine_name}" if not force_ocr else ocr_engine_name
        full_text = "\n".join(page.text for page in pages if page.text).strip()
    else:
        pages = _build_pages(page_count, native_page_map, {}, set(),
                             prefer_tika_text=False, selected_sources=None)
        method = "native"
        engine = "pymupdf"
        full_text = native_text.strip()

    if not full_text:
        raise EmptyContentError("Extracted content is empty.")

    # -------------------------------------------------------------------
    # Quality retries
    # -------------------------------------------------------------------
    retry_meta: dict[int, dict] = {}
    if ocr_required:
        for attempt in range(quality_retries):
            quality_pages: list[QualityGate] = []
            failures = []
            for page_number in range(1, page_count + 1):
                quality_gate = _page_quality(
                    page_number,
                    native_page_map.get(page_number, ""),
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
                    validated_path, page_number, attempt,
                    ocr_lang=ocr_lang, tessdata_path=tessdata_path,
                )
                current_page = ocr_pages.get(page_number, {})
                current_tokens = current_page.get("tokens", [])
                current_conf = [token.get("confidence", 0.0) for token in current_tokens]
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

    # -------------------------------------------------------------------
    # Final quality assessment + page assembly
    # -------------------------------------------------------------------
    quality_pages_final: list[QualityGate] = []
    for page_number in range(1, page_count + 1):
        quality_pages_final.append(
            _page_quality(
                page_number,
                native_page_map.get(page_number, ""),
                ocr_pages.get(page_number),
                retry_meta.get(page_number, {}).get("attempts", 0),
                ocr_pages.get(page_number, {}).get("strategy"),
                quality_overrides,
            )
        )
    quality = _quality_summary(quality_pages_final, strict_quality, quality_overrides)
    selected_sources = {
        page.page_number: page.selected_source for page in quality_pages_final
    }

    if ocr_required:
        prefer_native_text = force_ocr
        pages = _build_pages(page_count, native_page_map, ocr_pages, ocr_required,
                             prefer_tika_text=prefer_native_text, selected_sources=selected_sources)
        full_text = "\n".join(page.text for page in pages if page.text).strip()
    else:
        pages = _build_pages(page_count, native_page_map, {}, set(),
                             prefer_tika_text=False, selected_sources=selected_sources)
        full_text = native_text.strip()

    stats = _calculate_stats(pages)

    # -------------------------------------------------------------------
    # Enrichment: page dimensions, images, layout blocks (provider-based)
    # -------------------------------------------------------------------
    try:
        page_dims = extract_page_dimensions(validated_path)
        for page in pages:
            w, h = page_dims.get(page.page_number, (None, None))
            page.page_width = w
            page.page_height = h
    except Exception:
        pass  # non-critical — leave dimensions as None

    if EXTRACT_IMAGES:
        try:
            from .providers.image_extract import extract_page_images

            all_images = extract_page_images(
                validated_path, page_numbers=None, include_base64=True,
            )
            for page in pages:
                raw_imgs = all_images.get(page.page_number, [])
                page.images = [PageImage(**img) for img in raw_imgs]
        except Exception:
            pass  # non-critical — images remain empty lists

    if EXTRACT_LAYOUT:
        try:
            all_blocks = extract_layout_blocks(validated_path, page_numbers=None)
            for page in pages:
                raw_blocks = all_blocks.get(page.page_number, [])
                page.layout_blocks = [LayoutBlock(**b) for b in raw_blocks]
        except Exception:
            pass  # non-critical — layout_blocks remain empty lists

    if EXTRACT_TABLES:
        try:
            from .providers.table_extract import extract_tables, is_available as tables_available

            if tables_available():
                all_tables = extract_tables(validated_path, page_numbers=None)
                for page in pages:
                    raw_tables = all_tables.get(page.page_number, [])
                    page.tables = [PageTable(**t) for t in raw_tables]
        except Exception:
            pass  # non-critical — tables remain empty lists

    if EXTRACT_MATH and EXTRACT_IMAGES:
        # Math OCR requires images to be extracted first (needs base64 data)
        try:
            from .providers.math_ocr import is_available as math_available, recognize_equations_from_page_images

            if math_available():
                for page in pages:
                    if page.images:
                        img_dicts = [img.model_dump() for img in page.images]
                        eqs = recognize_equations_from_page_images(img_dicts)
                        page.equations = [PageEquation(**eq) for eq in eqs]
        except Exception:
            pass  # non-critical — equations remain empty lists

    diagrams_result = None
    if extract_diagrams:
        try:
            from .diagram_pipeline import run_diagram_pipeline
            diagrams_result = run_diagram_pipeline(
                validated_path, max_pages=max_pages, use_vlm=True,
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
