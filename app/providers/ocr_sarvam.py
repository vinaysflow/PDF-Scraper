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


def _extract_page_range_pdf(pdf_path: Path, first_page: int, last_page: int) -> Path:
    """Extract a page range from a PDF into a temporary file using PyMuPDF."""
    import fitz  # PyMuPDF

    src = fitz.open(str(pdf_path))
    dst = fitz.open()
    dst.insert_pdf(src, from_page=first_page - 1, to_page=last_page - 1)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    dst.save(tmp.name)
    dst.close()
    src.close()
    return Path(tmp.name)


def _parse_markdown_pages(zip_path: Path, first_page: int, page_count: int) -> dict[int, str]:
    """Parse the Sarvam output ZIP and map content back to page numbers.

    Sarvam returns a ZIP containing Markdown (or HTML) files. The files may
    be named by page index (e.g. page_1.md, page_2.md) or there may be a
    single file for the whole chunk. This function handles both cases.
    """
    page_texts: dict[int, str] = {}

    with zipfile.ZipFile(str(zip_path), "r") as zf:
        md_files = sorted(
            [n for n in zf.namelist() if n.endswith((".md", ".html")) and not n.startswith("__")],
        )

        if not md_files:
            logger.warning("Sarvam output ZIP contains no .md/.html files")
            return page_texts

        if len(md_files) == 1:
            content = zf.read(md_files[0]).decode("utf-8", errors="replace")
            sections = re.split(r"(?m)^---\s*$", content)
            sections = [s.strip() for s in sections if s.strip()]

            if len(sections) >= page_count:
                for i in range(page_count):
                    page_texts[first_page + i] = sections[i]
            else:
                for i in range(page_count):
                    page_texts[first_page + i] = content
        else:
            for i, fname in enumerate(md_files[:page_count]):
                content = zf.read(fname).decode("utf-8", errors="replace")
                page_texts[first_page + i] = content.strip()

    return page_texts


def ocr_pdf_chunk(
    pdf_path: Path,
    first_page: int,
    last_page: int,
    sarvam_lang: str,
    output_format: str = "md",
) -> dict[int, dict[str, Any]]:
    """Process a chunk of pages through the Sarvam Document Intelligence API.

    Returns a dict mapping page_number -> result dict compatible with the
    Tesseract/Paddle output format.
    """
    import sarvamai as _sarvamai_sdk
    from ..config import SARVAM_API_KEY

    page_count = last_page - first_page + 1
    chunk_pdf = _extract_page_range_pdf(pdf_path, first_page, last_page)

    try:
        client = _sarvamai_sdk.SarvamAI(api_subscription_key=SARVAM_API_KEY)

        job = client.document_intelligence.create_job(
            language=sarvam_lang,
            output_format=output_format,
        )
        logger.info(
            "Sarvam job created for pages %d-%d (%s): %s",
            first_page, last_page, sarvam_lang, getattr(job, "job_id", "?"),
        )

        job.upload_file(str(chunk_pdf))
        job.start()
        status = job.wait_until_complete()

        job_state = getattr(status, "job_state", None) or getattr(status, "state", "unknown")
        if job_state not in ("Completed", "PartiallyCompleted"):
            logger.warning("Sarvam job ended with state=%s for pages %d-%d", job_state, first_page, last_page)
            return _empty_results(first_page, last_page)

        output_zip = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        job.download_output(output_zip.name)

        page_texts = _parse_markdown_pages(Path(output_zip.name), first_page, page_count)

        results: dict[int, dict[str, Any]] = {}
        for pn in range(first_page, last_page + 1):
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
        logger.warning("Sarvam API failed for pages %d-%d: %s", first_page, last_page, exc)
        return _empty_results(first_page, last_page)
    finally:
        chunk_pdf.unlink(missing_ok=True)


def _empty_results(first_page: int, last_page: int) -> dict[int, dict[str, Any]]:
    """Return empty result dicts for a page range (used on failure)."""
    return {
        pn: {
            "page_number": pn,
            "text": "",
            "tokens": [],
            "pass_similarity": None,
            "layout": None,
        }
        for pn in range(first_page, last_page + 1)
    }


def ocr_pages_parallel(
    pdf_path: str | Path,
    pages: list[int],
    sarvam_lang: str,
    chunk_size: int = 5,
    max_workers: int = 4,
) -> dict[int, dict[str, Any]]:
    """Process pages through Sarvam Vision in parallel chunks.

    Splits the page list into chunks of ``chunk_size``, submits each to
    Sarvam in parallel, and merges results.
    """
    pdf_path = Path(pdf_path)
    if not pages:
        return {}

    sorted_pages = sorted(pages)
    chunks: list[tuple[int, int]] = []
    i = 0
    while i < len(sorted_pages):
        chunk_start = sorted_pages[i]
        chunk_end = sorted_pages[min(i + chunk_size - 1, len(sorted_pages) - 1)]
        chunks.append((chunk_start, chunk_end))
        i += chunk_size

    logger.info(
        "Sarvam: processing %d pages in %d chunk(s) of up to %d pages (%s)",
        len(pages), len(chunks), chunk_size, sarvam_lang,
    )

    all_results: dict[int, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(chunks))) as pool:
        futures = {
            pool.submit(ocr_pdf_chunk, pdf_path, start, end, sarvam_lang): (start, end)
            for start, end in chunks
        }
        for future in as_completed(futures):
            start, end = futures[future]
            try:
                chunk_results = future.result()
                all_results.update(chunk_results)
            except Exception as exc:
                logger.warning("Sarvam chunk %d-%d raised: %s", start, end, exc)
                all_results.update(_empty_results(start, end))

    return all_results
