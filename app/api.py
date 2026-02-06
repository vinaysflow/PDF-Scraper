"""FastAPI app for PDF extraction."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .extract import extract_pdf
from .utils import ExtractionError

app = FastAPI(title="PDF OCR MVP")


@app.on_event("startup")
def _log_safe_mode():
    import sys
    skip = os.environ.get("SKIP_TIKA", "")
    port = os.environ.get("PORT", "")
    msg = f"PDF OCR: SKIP_TIKA={skip!r} PORT={port!r} -> safe_limits={'on' if (skip.lower() in ('1', 'true', 'yes') or port) else 'off'}"
    print(msg, flush=True)
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# On Railway (PORT set) or when SKIP_TIKA is set: cap DPI and pages to avoid OOM.
SKIP_TIKA = os.environ.get("SKIP_TIKA", "").strip().lower() in ("1", "true", "yes")
ON_RAILWAY = "PORT" in os.environ
SAFE_DPI = 300
SAFE_MAX_PAGES = 25


def _apply_safe_limits(dpi: int, max_pages: int | None) -> tuple[int, int | None]:
    if not (SKIP_TIKA or ON_RAILWAY):
        return dpi, max_pages
    return min(dpi, SAFE_DPI), max_pages if max_pages is not None else SAFE_MAX_PAGES


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """Return JSON with error detail so the upload page can show it."""
    from fastapi.responses import JSONResponse
    if isinstance(exc, HTTPException):
        raise exc
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) or "Internal server error"},
    )


@app.get("/")
async def index():
    """Serve the upload page."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Upload page not found.")
    return FileResponse(index_path)


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
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            temp_path = tmp.name
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail="Uploaded file is empty.")
            tmp.write(content)
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
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


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
    """Extract text and OCR from an uploaded PDF."""
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
    """Same as /extract; allows frontend to use /api/extract for Vercel compatibility."""
    dpi, max_pages = _apply_safe_limits(dpi, max_pages)
    try:
        return await _do_extract(
            file, dpi, max_pages, force_ocr, strict_quality, quality_retries,
            quality_target, ocr_lang, tessdata_path, extract_diagrams,
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
