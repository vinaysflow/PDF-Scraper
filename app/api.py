"""FastAPI app for PDF extraction."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .config import (
    ASYNC_MAX_PAGES,
    MAX_FILE_SIZE_BYTES,
    SAFE_DPI,
    SAFE_MODE,
    SYNC_MAX_PAGES,
    UPLOAD_CHUNK_SIZE,
    log_startup_config,
)
from .extract import extract_pdf
from .job_store import store as job_store
from .utils import ExtractionError
from .worker import enqueue as enqueue_job

app = FastAPI(title="PDF OCR MVP")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _startup() -> None:
    log_startup_config()


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc: Exception):  # noqa: ARG001
    if isinstance(exc, HTTPException):
        raise exc
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) or "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _apply_safe_limits(dpi: int, max_pages: int | None) -> tuple[int, int | None]:
    if not SAFE_MODE:
        return dpi, max_pages
    return min(dpi, SAFE_DPI), max_pages if max_pages is not None else SYNC_MAX_PAGES


async def _stream_upload_to_temp(file: UploadFile) -> str:
    """Stream *file* to a temp file in chunks; enforce size limit. Returns path."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")
    total = 0
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        while True:
            chunk = await file.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large (limit {MAX_FILE_SIZE_BYTES // (1024*1024)} MB).",
                )
            tmp.write(chunk)
        tmp.flush()
    except HTTPException:
        tmp.close()
        os.unlink(tmp.name)
        raise
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise
    finally:
        tmp.close()
    if total == 0:
        os.unlink(tmp.name)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    return tmp.name


async def _do_extract(
    file: UploadFile,
    dpi: int,
    max_pages: int | None,
    force_ocr: bool,
    strict_quality: bool,
    quality_retries: int,
    quality_target: int | None,
    ocr_lang: str,
    tessdata_path: str | None,
    extract_diagrams: bool,
):
    temp_path = await _stream_upload_to_temp(file)
    try:
        result = extract_pdf(
            temp_path,
            dpi=dpi,
            max_pages=max_pages,
            force_ocr=force_ocr,
            strict_quality=strict_quality,
            quality_retries=quality_retries,
            quality_target=quality_target,
            ocr_lang=ocr_lang,
            tessdata_path=tessdata_path,
            extract_diagrams=extract_diagrams,
        )
        return result.model_dump()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ---------------------------------------------------------------------------
# Pages / health
# ---------------------------------------------------------------------------
@app.get("/")
async def index():
    """Serve the upload page."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Upload page not found.")
    return FileResponse(index_path)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def api_config():
    """Expose runtime limits so the frontend can decide sync vs async."""
    return {"sync_max_pages": SYNC_MAX_PAGES, "async_max_pages": ASYNC_MAX_PAGES}


# ---------------------------------------------------------------------------
# Sync extraction endpoints
# ---------------------------------------------------------------------------
@app.post("/extract")
async def extract_endpoint(
    file: UploadFile = File(...),
    dpi: int = 600,
    max_pages: int | None = None,
    force_ocr: bool = False,
    strict_quality: bool = True,
    quality_retries: int = 2,
    quality_target: int | None = None,
    ocr_lang: str = "eng",
    tessdata_path: str | None = None,
    extract_diagrams: bool = False,
):
    """Extract text and OCR from an uploaded PDF (sync, small docs)."""
    dpi, max_pages = _apply_safe_limits(dpi, max_pages)
    try:
        return await _do_extract(
            file, dpi, max_pages, force_ocr, strict_quality, quality_retries,
            quality_target, ocr_lang, tessdata_path, extract_diagrams,
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/extract")
async def api_extract_endpoint(
    file: UploadFile = File(...),
    dpi: int = 600,
    max_pages: int | None = None,
    force_ocr: bool = False,
    strict_quality: bool = True,
    quality_retries: int = 2,
    quality_target: int | None = None,
    ocr_lang: str = "eng",
    tessdata_path: str | None = None,
    extract_diagrams: bool = False,
):
    """Same as /extract; allows frontend to use /api/extract for Vercel compat."""
    dpi, max_pages = _apply_safe_limits(dpi, max_pages)
    try:
        return await _do_extract(
            file, dpi, max_pages, force_ocr, strict_quality, quality_retries,
            quality_target, ocr_lang, tessdata_path, extract_diagrams,
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Async extraction endpoints (Phase 2)
# ---------------------------------------------------------------------------
@app.post("/api/extract/async", status_code=202)
async def async_extract_endpoint(
    file: UploadFile = File(...),
    dpi: int = 600,
    max_pages: int | None = None,
    force_ocr: bool = False,
    strict_quality: bool = True,
    quality_retries: int = 2,
    quality_target: int | None = None,
    ocr_lang: str = "eng",
    tessdata_path: str | None = None,
    extract_diagrams: bool = False,
):
    """Accept a PDF and return 202 + job_id. Poll /api/extract/async/{job_id} for result."""
    dpi, max_pages = _apply_safe_limits(dpi, max_pages)
    temp_path = await _stream_upload_to_temp(file)
    job_id = job_store.create_job()
    enqueue_job(
        job_id,
        temp_path,
        dpi=dpi,
        max_pages=max_pages,
        force_ocr=force_ocr,
        strict_quality=strict_quality,
        quality_retries=quality_retries,
        quality_target=quality_target,
        ocr_lang=ocr_lang,
        tessdata_path=tessdata_path,
        extract_diagrams=extract_diagrams,
    )
    return {"job_id": job_id, "status": "accepted"}


@app.get("/api/extract/async/{job_id}")
async def async_extract_status(job_id: str):
    """Poll job status. Returns result when completed, error when failed."""
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


# ---------------------------------------------------------------------------
# Reconstruction endpoint
# ---------------------------------------------------------------------------
@app.get("/api/reconstruct/{job_id}", response_class=HTMLResponse)
async def reconstruct_page(job_id: str):
    """Render a visual HTML reconstruction of a completed extraction job."""
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Job is '{job.get('status')}', not completed.",
        )
    result = job.get("result")
    if not result:
        raise HTTPException(status_code=404, detail="No result data for this job.")

    from .providers.reconstruct import reconstruct_html

    html = reconstruct_html(result)
    return HTMLResponse(content=html)
