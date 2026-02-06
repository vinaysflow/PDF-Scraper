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

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


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
    suffix = ".pdf" if not file.filename.lower().endswith(".pdf") else ""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
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
    try:
        return await _do_extract(
            file, dpi, max_pages, force_ocr, strict_quality, quality_retries,
            quality_target, ocr_lang, tessdata_path, extract_diagrams,
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
