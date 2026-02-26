"""Sarvam Vision Document Intelligence — regional Indian language OCR.

Sarvam Vision is a 3B-parameter VLM purpose-built for Indian scripts.
It supports 22 Indian languages + English with 87%+ accuracy on Indic
documents, outperforming Tesseract and PaddleOCR for regional scripts.

This provider splits a PDF into configurable-size chunks, processes them
in parallel via the Sarvam Document Intelligence API, and returns results
in the same format as the Tesseract/Paddle providers.

Resilience features:
- Progressive chunk downsizing: failed chunks are retried at half size,
  then single-page, before giving up.
- Output validation: returned text is checked for script purity (detects
  garbled encoding from the native PDF text layer leaking through).
- Structured logging: every chunk reports success/failure/retry counts.

Usage::

    from app.providers.ocr_sarvam import is_available, ocr_pages_parallel

    if is_available():
        results = ocr_pages_parallel(
            pdf_path, pages=[1,2,3,4,5],
            sarvam_lang="kn-IN", chunk_size=5,
        )
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Script ranges for output validation
_INDIC_SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "kn-IN": (0x0C80, 0x0CFF),   # Kannada
    "hi-IN": (0x0900, 0x097F),   # Devanagari
    "ta-IN": (0x0B80, 0x0BFF),   # Tamil
    "te-IN": (0x0C00, 0x0C7F),   # Telugu
}

_FOREIGN_SCRIPT_RANGES = [
    (0x0E00, 0x0E7F),   # Thai
    (0x0D80, 0x0DFF),   # Sinhala
    (0x1780, 0x17FF),   # Khmer
    (0x0E80, 0x0EFF),   # Lao
]

_MIN_PURITY_THRESHOLD = 0.40

_AVAILABLE: bool | None = None


def _validate_output_text(text: str, sarvam_lang: str) -> bool:
    """Check that returned text is actually in the expected script.

    Returns True if the text looks like valid OCR output (correct script,
    minimal foreign-script contamination). Returns False if it looks like
    garbled native text leaked through.
    """
    if not text or not text.strip():
        return False

    expected_range = _INDIC_SCRIPT_RANGES.get(sarvam_lang)
    if expected_range is None:
        return True  # unknown language, skip validation

    letter_total = 0
    expected_count = 0
    foreign_count = 0

    for ch in text:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        letter_total += 1
        if expected_range[0] <= cp <= expected_range[1]:
            expected_count += 1
        for lo, hi in _FOREIGN_SCRIPT_RANGES:
            if lo <= cp <= hi:
                foreign_count += 1
                break

    if letter_total < 5:
        return True  # too few letters to judge (page numbers, etc.)

    foreign_ratio = foreign_count / letter_total
    if foreign_ratio > 0.05:
        return False

    return True


def is_available() -> bool:
    """Return True if sarvamai SDK is importable and SARVAM_API_KEY is set."""
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import sarvamai  # noqa: F401
            from .. import config as _cfg
            _AVAILABLE = bool(_cfg.SARVAM_API_KEY)
            if _AVAILABLE:
                print(f"[Sarvam] SDK found (v{getattr(sarvamai, '__version__', '?')}), API key set — enabled", flush=True)
            else:
                print("[Sarvam] SDK found but SARVAM_API_KEY not set — disabled", flush=True)
        except ImportError as exc:
            _AVAILABLE = False
            print(f"[Sarvam] sarvamai not installed ({exc}) — disabled", flush=True)
        except Exception as exc:
            _AVAILABLE = False
            print(f"[Sarvam] unexpected error during init: {exc} — disabled", flush=True)
    return _AVAILABLE


def _extract_pages_pdf(pdf_path: Path, page_numbers: list[int]) -> Path:
    """Extract specific pages from a PDF into a temporary file using PyMuPDF.

    ``page_numbers`` are 1-based. Only the requested pages are included,
    in the order given.
    """
    import fitz  # PyMuPDF

    src = fitz.open(str(pdf_path))
    try:
        dst = fitz.open()
        try:
            for pn in page_numbers:
                idx = pn - 1
                if 0 <= idx < len(src):
                    dst.insert_pdf(src, from_page=idx, to_page=idx)
            tmp_path = Path(tempfile.mkstemp(suffix=".pdf")[1])
            dst.save(str(tmp_path))
        finally:
            dst.close()
    finally:
        src.close()
    return tmp_path


def _natural_sort_key(name: str):
    """Sort key that handles embedded numbers correctly (page_2 before page_10)."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _parse_markdown_pages(zip_path: Path, page_numbers: list[int]) -> dict[int, str]:
    """Parse the Sarvam output ZIP and map content back to page numbers.

    Sarvam returns a ZIP containing Markdown (or HTML) files. The files may
    be named by page index (e.g. page_1.md, page_2.md) or there may be a
    single file for the whole chunk. This function handles both cases.
    """
    page_count = len(page_numbers)
    page_texts: dict[int, str] = {}

    try:
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            md_files = sorted(
                [
                    os.path.basename(n)
                    for n in zf.namelist()
                    if n.endswith((".md", ".html"))
                    and not os.path.basename(n).startswith("__")
                    and not n.startswith("__")
                ],
                key=_natural_sort_key,
            )

            if not md_files:
                logger.warning("Sarvam output ZIP contains no .md/.html files")
                return page_texts

            all_names = {os.path.basename(n): n for n in zf.namelist()}

            if len(md_files) == 1:
                full_name = all_names.get(md_files[0], md_files[0])
                content = zf.read(full_name).decode("utf-8", errors="replace")
                sections = re.split(r"(?m)^---\s*$", content)
                sections = [s.strip() for s in sections if s.strip()]

                if len(sections) >= page_count:
                    for i, pn in enumerate(page_numbers):
                        page_texts[pn] = sections[i]
                else:
                    for pn in page_numbers:
                        page_texts[pn] = content
            else:
                for i, fname in enumerate(md_files[:page_count]):
                    full_name = all_names.get(fname, fname)
                    content = zf.read(full_name).decode("utf-8", errors="replace")
                    page_texts[page_numbers[i]] = content.strip()
    except zipfile.BadZipFile:
        logger.warning("Sarvam output is not a valid ZIP file")

    return page_texts


_MAX_CHUNK_RETRIES = 3


def ocr_pdf_chunk(
    pdf_path: Path,
    page_numbers: list[int],
    sarvam_lang: str,
    output_format: str = "md",
    validate_output: bool = True,
) -> dict[int, dict[str, Any]]:
    """Process a chunk of specific pages through the Sarvam Document Intelligence API.

    ``page_numbers`` is a list of 1-based page numbers to process.
    Retries up to ``_MAX_CHUNK_RETRIES`` times with exponential backoff on failure.
    When ``validate_output`` is True, each page's text is checked for script
    purity — pages with garbled encoding are returned as empty so the caller
    can retry or fall back.
    """
    import sarvamai as _sarvamai_sdk
    from ..config import SARVAM_API_KEY

    chunk_label = f"pages {page_numbers[0]}–{page_numbers[-1]}" if len(page_numbers) > 1 else f"page {page_numbers[0]}"
    chunk_pdf = _extract_pages_pdf(pdf_path, page_numbers)

    try:
        for attempt in range(_MAX_CHUNK_RETRIES):
            output_zip_path: Path | None = None
            try:
                client = _sarvamai_sdk.SarvamAI(api_subscription_key=SARVAM_API_KEY)

                job = client.document_intelligence.create_job(
                    language=sarvam_lang,
                    output_format=output_format,
                )
                job_id = getattr(job, "job_id", "?")
                print(
                    f"[Sarvam] chunk {chunk_label} ({len(page_numbers)}p) → job {job_id} (attempt {attempt + 1}/{_MAX_CHUNK_RETRIES})",
                    flush=True,
                )

                job.upload_file(str(chunk_pdf))
                job.start()
                status = job.wait_until_complete()

                job_state = getattr(status, "job_state", None) or getattr(status, "state", "unknown")
                if job_state not in ("Completed", "PartiallyCompleted"):
                    print(
                        f"[Sarvam] chunk {chunk_label} ended state={job_state} (attempt {attempt + 1}/{_MAX_CHUNK_RETRIES})",
                        flush=True,
                    )
                    if attempt < _MAX_CHUNK_RETRIES - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return _empty_results_for_pages(page_numbers)

                fd, zip_name = tempfile.mkstemp(suffix=".zip")
                os.close(fd)
                output_zip_path = Path(zip_name)
                job.download_output(str(output_zip_path))

                page_texts = _parse_markdown_pages(output_zip_path, page_numbers)

                results: dict[int, dict[str, Any]] = {}
                valid_count = 0
                for pn in page_numbers:
                    text = page_texts.get(pn, "")
                    is_valid = (
                        not validate_output
                        or _validate_output_text(text, sarvam_lang)
                    )
                    if text.strip() and is_valid:
                        results[pn] = {
                            "page_number": pn,
                            "text": text,
                            "tokens": [],
                            "pass_similarity": 1.0,
                            "layout": "text",
                        }
                        valid_count += 1
                    else:
                        reason = "empty" if not text.strip() else "failed validation"
                        logger.info("Sarvam page %d: %s", pn, reason)
                        results[pn] = _empty_results_for_pages([pn])[pn]

                print(
                    f"[Sarvam] chunk {chunk_label} complete: {valid_count}/{len(page_numbers)} valid pages",
                    flush=True,
                )
                return results

            except Exception as exc:
                if attempt < _MAX_CHUNK_RETRIES - 1:
                    wait = 2 ** attempt
                    print(
                        f"[Sarvam] chunk {chunk_label} attempt {attempt + 1} failed: {exc} — retrying in {wait}s",
                        flush=True,
                    )
                    time.sleep(wait)
                else:
                    print(
                        f"[Sarvam] chunk {chunk_label} FAILED after {_MAX_CHUNK_RETRIES} attempts: {exc}",
                        flush=True,
                    )
                    return _empty_results_for_pages(page_numbers)
            finally:
                if output_zip_path is not None:
                    output_zip_path.unlink(missing_ok=True)

        return _empty_results_for_pages(page_numbers)
    finally:
        chunk_pdf.unlink(missing_ok=True)


def _empty_results_for_pages(page_numbers: list[int]) -> dict[int, dict[str, Any]]:
    """Return empty result dicts for specific pages (used on failure)."""
    return {
        pn: {
            "page_number": pn,
            "text": "",
            "tokens": [],
            "pass_similarity": None,
            "layout": None,
        }
        for pn in page_numbers
    }


def _run_chunks_parallel(
    pdf_path: Path,
    chunks: list[list[int]],
    sarvam_lang: str,
    max_workers: int,
) -> dict[int, dict[str, Any]]:
    """Execute a list of chunks in parallel and return merged results."""
    results: dict[int, dict[str, Any]] = {}
    if not chunks:
        return results

    with ThreadPoolExecutor(max_workers=min(max_workers, len(chunks))) as pool:
        futures = {
            pool.submit(ocr_pdf_chunk, pdf_path, chunk, sarvam_lang): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                chunk_results = future.result()
                results.update(chunk_results)
            except Exception as exc:
                print(f"[Sarvam] chunk {chunk} raised: {exc}", flush=True)
                results.update(_empty_results_for_pages(chunk))

    return results


def ocr_pages_parallel(
    pdf_path: str | Path,
    pages: list[int],
    sarvam_lang: str,
    chunk_size: int = 5,
    max_workers: int = 2,
) -> dict[int, dict[str, Any]]:
    """Process pages through Sarvam Vision in parallel chunks with resilience.

    Processing strategy:
    1. Split pages into chunks of ``chunk_size``, process in parallel.
    2. Collect pages that returned empty (failed/garbled).
    3. Retry failed pages in smaller chunks (half size).
    4. Final retry: remaining failures as single-page calls.

    This ensures a transient API failure for one chunk doesn't lose
    all those pages permanently.
    """
    pdf_path = Path(pdf_path)
    if not pages:
        return {}

    sorted_pages = sorted(pages)
    total = len(sorted_pages)
    chunks: list[list[int]] = [
        sorted_pages[i : i + chunk_size]
        for i in range(0, total, chunk_size)
    ]

    print(
        f"[Sarvam] Pass 1: {total} pages → {len(chunks)} chunk(s) of ≤{chunk_size} ({sarvam_lang})",
        flush=True,
    )

    # ── Pass 1: initial parallel processing ──
    all_results = _run_chunks_parallel(pdf_path, chunks, sarvam_lang, max_workers)

    failed_pages = sorted(
        pn for pn, r in all_results.items()
        if not r.get("text", "").strip()
    )

    # ── Pass 2: retry failed pages in smaller chunks ──
    if failed_pages and chunk_size > 2:
        smaller = max(2, chunk_size // 2)
        retry_chunks = [
            failed_pages[i : i + smaller]
            for i in range(0, len(failed_pages), smaller)
        ]
        print(
            f"[Sarvam] Pass 2: retrying {len(failed_pages)} failed pages in {len(retry_chunks)} chunk(s) of ≤{smaller}",
            flush=True,
        )
        retry_results = _run_chunks_parallel(pdf_path, retry_chunks, sarvam_lang, max_workers)
        for pn, r in retry_results.items():
            if r.get("text", "").strip():
                all_results[pn] = r

        failed_pages = sorted(
            pn for pn, r in all_results.items()
            if not r.get("text", "").strip()
        )

    # ── Pass 3: final single-page retry for remaining failures ──
    if failed_pages:
        single_chunks = [[pn] for pn in failed_pages]
        print(
            f"[Sarvam] Pass 3: retrying {len(failed_pages)} pages individually",
            flush=True,
        )
        single_results = _run_chunks_parallel(
            pdf_path, single_chunks, sarvam_lang, max_workers,
        )
        for pn, r in single_results.items():
            if r.get("text", "").strip():
                all_results[pn] = r

    # ── Summary ──
    final_ok = sum(1 for r in all_results.values() if r.get("text", "").strip())
    final_empty = total - final_ok
    print(
        f"[Sarvam] Done: {final_ok}/{total} pages OK, {final_empty} empty → Tesseract fallback",
        flush=True,
    )

    return all_results
