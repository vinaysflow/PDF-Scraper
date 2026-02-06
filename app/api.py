"""FastAPI app for PDF extraction."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Security, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader

from .config import (
    API_KEY,
    ASYNC_MAX_PAGES,
    IMAGE_STORE_DIR,
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
# API key authentication (optional — disabled when API_KEY env var is empty)
# ---------------------------------------------------------------------------
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(key: str | None = Security(_api_key_header)):
    """Validate the X-API-Key header when API_KEY is configured."""
    if not API_KEY:
        return  # auth disabled — no key configured
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


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
def _apply_safe_limits(
    dpi: int, max_pages: int | None, *, is_async: bool = False,
) -> tuple[int, int | None]:
    """Cap DPI and max_pages based on environment.

    When SAFE_MODE is active (Railway), apply conservative defaults.
    The async path uses ASYNC_MAX_PAGES; the sync path uses SYNC_MAX_PAGES.
    When running locally (SAFE_MODE=False), no limits are enforced.
    """
    if not SAFE_MODE:
        return dpi, max_pages
    default_cap = ASYNC_MAX_PAGES if is_async else SYNC_MAX_PAGES
    capped_pages = max_pages if max_pages is not None else default_cap
    return min(dpi, SAFE_DPI), capped_pages


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
    include_base64: bool = False,
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
            include_base64=include_base64,
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
# Job listing endpoint
# ---------------------------------------------------------------------------
@app.get("/api/jobs", dependencies=[Depends(verify_api_key)])
async def list_jobs(status: str | None = None):
    """List recent jobs. Optional ?status=completed filter."""
    return job_store.list_jobs(status_filter=status)


# ---------------------------------------------------------------------------
# Sync extraction endpoints
# ---------------------------------------------------------------------------
@app.post("/extract", dependencies=[Depends(verify_api_key)])
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
    include_base64: bool = False,
):
    """Extract text and OCR from an uploaded PDF (sync, small docs)."""
    dpi, max_pages = _apply_safe_limits(dpi, max_pages)
    try:
        return await _do_extract(
            file, dpi, max_pages, force_ocr, strict_quality, quality_retries,
            quality_target, ocr_lang, tessdata_path, extract_diagrams,
            include_base64=include_base64,
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/extract", dependencies=[Depends(verify_api_key)])
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
    include_base64: bool = False,
):
    """Same as /extract; allows frontend to use /api/extract for Vercel compat."""
    dpi, max_pages = _apply_safe_limits(dpi, max_pages)
    try:
        return await _do_extract(
            file, dpi, max_pages, force_ocr, strict_quality, quality_retries,
            quality_target, ocr_lang, tessdata_path, extract_diagrams,
            include_base64=include_base64,
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Async extraction endpoints (Phase 2)
# ---------------------------------------------------------------------------
@app.post("/api/extract/async", status_code=202, dependencies=[Depends(verify_api_key)])
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
    include_base64: bool = False,
):
    """Accept a PDF and return 202 + job_id. Poll /api/extract/async/{job_id} for result."""
    dpi, max_pages = _apply_safe_limits(dpi, max_pages, is_async=True)
    temp_path = await _stream_upload_to_temp(file)
    job_id = job_store.create_job()
    job_store.set_filename(job_id, file.filename or "unknown.pdf")
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
        include_base64=include_base64,
    )
    return {"job_id": job_id, "status": "accepted"}


@app.get("/api/extract/async/{job_id}", dependencies=[Depends(verify_api_key)])
async def async_extract_status(job_id: str):
    """Poll job status. Returns result when completed, error when failed."""
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


# ---------------------------------------------------------------------------
# Image serving endpoint
# ---------------------------------------------------------------------------
@app.get("/api/images/{doc_id}/{page}/{filename}", dependencies=[Depends(verify_api_key)])
async def serve_image(doc_id: str, page: str, filename: str):
    """Serve an extracted image file from the image store."""
    image_path = Path(IMAGE_STORE_DIR) / doc_id / page / filename
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found.")
    # Prevent path traversal
    try:
        image_path.resolve().relative_to(Path(IMAGE_STORE_DIR).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied.")
    return FileResponse(str(image_path))


# ---------------------------------------------------------------------------
# Question bank endpoint
# ---------------------------------------------------------------------------
@app.get("/api/question-bank/{job_id}", dependencies=[Depends(verify_api_key)])
async def question_bank_endpoint(
    job_id: str,
    enrich_with_llm: bool = True,
):
    """Generate a question bank from a completed async extraction job."""
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Job is '{job.get('status')}', not completed.",
        )
    result_data = job.get("result")
    if not result_data:
        raise HTTPException(status_code=404, detail="No result data for this job.")

    from .question_bank import build_question_bank
    from .schema import ExtractionResult

    extraction_result = ExtractionResult(**result_data)
    qbank = build_question_bank(extraction_result, enrich_with_llm=enrich_with_llm)
    return qbank.model_dump()


# ---------------------------------------------------------------------------
# Supabase ingestion endpoint
# ---------------------------------------------------------------------------
@app.post("/api/ingest/{job_id}", dependencies=[Depends(verify_api_key)])
async def ingest_endpoint(
    job_id: str,
    enrich_with_llm: bool = True,
):
    """Generate a question bank from a completed job and ingest into Supabase."""
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Job is '{job.get('status')}', not completed.",
        )
    result_data = job.get("result")
    if not result_data:
        raise HTTPException(status_code=404, detail="No result data for this job.")

    from .db.supabase_client import is_configured as supabase_configured

    if not supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY.",
        )

    from .db.ingest import ingest_question_bank
    from .question_bank import build_question_bank
    from .schema import ExtractionResult

    extraction_result = ExtractionResult(**result_data)
    qbank = build_question_bank(extraction_result, enrich_with_llm=enrich_with_llm)
    summary = ingest_question_bank(qbank)
    return summary


# ---------------------------------------------------------------------------
# Reconstruction endpoint
# ---------------------------------------------------------------------------
@app.get("/api/reconstruct/{job_id}", response_class=HTMLResponse, dependencies=[Depends(verify_api_key)])
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
