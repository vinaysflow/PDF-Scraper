"""Sarvam Vision Document Intelligence — regional Indian language OCR.

Sarvam Vision is a 3B-parameter VLM purpose-built for Indian scripts.
It supports 22 Indian languages + English with 87%+ accuracy on Indic
documents, outperforming Tesseract and PaddleOCR for regional scripts.

This provider splits a PDF into configurable-size chunks, processes them
in parallel via the Sarvam Document Intelligence API, and returns results
in the same format as the Tesseract/Paddle providers.

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
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AVAILABLE: bool | None = None


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


def ocr_pdf_chunk(
    pdf_path: Path,
    page_numbers: list[int],
    sarvam_lang: str,
    output_format: str = "md",
) -> dict[int, dict[str, Any]]:
    """Process a chunk of specific pages through the Sarvam Document Intelligence API.

    ``page_numbers`` is a list of 1-based page numbers to process.
    Returns a dict mapping page_number -> result dict compatible with the
    Tesseract/Paddle output format.
    """
    import sarvamai as _sarvamai_sdk
    from ..config import SARVAM_API_KEY

    chunk_pdf = _extract_pages_pdf(pdf_path, page_numbers)
    output_zip_path: Path | None = None

    try:
        client = _sarvamai_sdk.SarvamAI(api_subscription_key=SARVAM_API_KEY)

        job = client.document_intelligence.create_job(
            language=sarvam_lang,
            output_format=output_format,
        )
        logger.info(
            "Sarvam job created for %d pages (%s): %s",
            len(page_numbers), sarvam_lang, getattr(job, "job_id", "?"),
        )

        job.upload_file(str(chunk_pdf))
        job.start()
        status = job.wait_until_complete()

        job_state = getattr(status, "job_state", None) or getattr(status, "state", "unknown")
        if job_state not in ("Completed", "PartiallyCompleted"):
            logger.warning("Sarvam job ended with state=%s for pages %s", job_state, page_numbers)
            return _empty_results_for_pages(page_numbers)

        fd, zip_name = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        output_zip_path = Path(zip_name)
        job.download_output(str(output_zip_path))

        page_texts = _parse_markdown_pages(output_zip_path, page_numbers)

        results: dict[int, dict[str, Any]] = {}
        for pn in page_numbers:
            text = page_texts.get(pn, "")
            results[pn] = {
                "page_number": pn,
                "text": text,
                "tokens": [],
                "pass_similarity": 1.0,
                "layout": "text",
            }
        return results

    except Exception as exc:
        logger.warning("Sarvam API failed for pages %s: %s", page_numbers, exc)
        return _empty_results_for_pages(page_numbers)
    finally:
        chunk_pdf.unlink(missing_ok=True)
        if output_zip_path is not None:
            output_zip_path.unlink(missing_ok=True)


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


def ocr_pages_parallel(
    pdf_path: str | Path,
    pages: list[int],
    sarvam_lang: str,
    chunk_size: int = 5,
    max_workers: int = 4,
) -> dict[int, dict[str, Any]]:
    """Process pages through Sarvam Vision in parallel chunks.

    Splits the page list into chunks of ``chunk_size`` pages, submits each
    to Sarvam in parallel, and merges results. Only the requested pages are
    sent to the API — no extra pages are included.
    """
    pdf_path = Path(pdf_path)
    if not pages:
        return {}

    sorted_pages = sorted(pages)
    chunks: list[list[int]] = [
        sorted_pages[i : i + chunk_size]
        for i in range(0, len(sorted_pages), chunk_size)
    ]

    logger.info(
        "Sarvam: processing %d pages in %d chunk(s) of up to %d pages (%s)",
        len(pages), len(chunks), chunk_size, sarvam_lang,
    )

    all_results: dict[int, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(chunks))) as pool:
        futures = {
            pool.submit(ocr_pdf_chunk, pdf_path, chunk, sarvam_lang): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                chunk_results = future.result()
                all_results.update(chunk_results)
            except Exception as exc:
                logger.warning("Sarvam chunk %s raised: %s", chunk, exc)
                all_results.update(_empty_results_for_pages(chunk))

    return all_results
