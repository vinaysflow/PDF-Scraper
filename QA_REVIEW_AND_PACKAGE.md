# PDF Scraper (pdf-ocr-mvp) — Code Review & QA Package

Generated for: `pdf-ocr-mvp`  
Scope: `app/` (extract, API, CLI, providers), `tests/`

---

## 1. Code Review Summary

### 1.1 Architecture Overview

| Layer | Components | Purpose |
|-------|------------|--------|
| **Orchestration** | `app/extract.py` | `extract_pdf()` — native text + OCR routing, quality gates, page assembly, enrichment |
| **Entry points** | `app/cli.py`, `app/api.py` | CLI (argparse) and FastAPI (sync + async extract, jobs, question bank, ingest) |
| **OCR providers** | `app/providers/ocr_sarvam.py`, `app/ocr.py` (Tesseract), `app/providers/ocr_paddle.py` | Sarvam (regional), Tesseract (default), PaddleOCR (optional) |
| **Support** | `app/utils.py`, `app/config.py`, `app/schema.py`, `app/ocr_router.py` | Validation, binaries, PDF utils, config, Pydantic models |
| **Enrichment** | `app/diagram_pipeline.py`, `app/question_bank.py`, `app/providers/image_extract.py`, etc. | Diagrams/VLM, question bank, images, layout, tables, math |

The codebase is **production-oriented**: clear separation of concerns, config-driven limits (SAFE_MODE, DPI, max pages), optional API key, and structured errors (ExtractionError, HTTP 4xx/5xx).

### 1.2 Strengths

- **Quality gates**: Configurable thresholds (strict vs 90% target), layout-specific overrides (table/noisy/text), language overrides (Kannada, Sarvam bypass). Decision logic (A/B) and retries are well defined.
- **OCR routing**: Automatic choice of Sarvam (regional) vs Tesseract vs PaddleOCR; fallback when Sarvam fails or is unavailable; DPI boost for regional Tesseract fallback.
- **Resilience**: Sarvam chunk retries with exponential backoff; progressive downsizing (chunk → half → single-page); output validation (script purity); quality retries per page.
- **API design**: Sync and async extract; job store; optional API key; safe limits (file size, DPI, max pages); path traversal guard on image serving.
- **CLI**: Rich options (quality-target, fail-on-needs-review, consolidated-output, question-bank), clear exit codes (0/1/2/3).
- **Tests**: `tests/test_ocr_sarvam.py` covers `is_available`, ZIP parsing, chunk retries, parallel orchestration, language router.

### 1.3 Risks & Recommendations

| Area | Risk | Recommendation |
|------|------|-----------------|
| **extract.py** | Large single function `extract_pdf()` (~450 lines); many branches and overrides | Extract helpers (e.g. `_run_ocr_for_required_pages`, `_run_quality_retries`) into named functions for testability and readability |
| **API** | `_unhandled_exception_handler` catches all `Exception`; can hide programming errors | Differentiate `HTTPException` vs `ExtractionError` vs unexpected; log traceback for 500s |
| **Secrets** | `SARVAM_API_KEY`, `OPENAI_API_KEY`, `API_KEY` from env | Document in README; ensure not logged (config startup already avoids printing keys) |
| **Temp files** | `_stream_upload_to_temp` and Sarvam chunk PDFs; cleanup on error paths | Ensure `os.unlink`/`finally` on all paths (currently looks correct; add integration test for cleanup on 413/500) |
| **Dependencies** | Optional imports (sarvamai, fitz, paddleocr, openai) | Keep `is_available()`-style guards and try/except; add optional dependency groups in pyproject.toml if not already |
| **version.py** | `subprocess.check_output(["git", ...])` can fail in Docker or read-only env | Already has GIT_COMMIT file fallback; document for deploy |

### 1.4 Security & Robustness

- **Path traversal**: `serve_image` uses ` Path.resolve().relative_to(IMAGE_STORE_DIR)` — correct.
- **File size**: Upload limited by `MAX_FILE_SIZE_BYTES` and chunked reading.
- **Input validation**: `validate_pdf_path`, `guard_max_pages`, `ensure_binaries` used before heavy work.
- **Text sanity**: `_text_looks_sane()` rejects garbage and (when `regional=True`) mixed scripts to avoid garbled native text.

---

## 2. QA Package — Test Scenarios & Coverage

### 2.1 Target Modules & Main Functions

| Module | Main functions / behavior | Priority |
|--------|---------------------------|----------|
| `app/extract` | `extract_pdf`, `_text_looks_sane`, `_page_quality`, `_build_pages`, `_calculate_stats`, `_quality_summary` | P0 |
| `app/providers/ocr_sarvam` | `is_available`, `ocr_pages_parallel`, `ocr_pdf_chunk`, `_parse_markdown_pages`, `_validate_output_text` | P0 |
| `app/api` | `extract_endpoint`, `async_extract_endpoint`, `_stream_upload_to_temp`, `_apply_safe_limits`, `serve_image`, `question_bank_endpoint`, `ingest_endpoint` | P0 |
| `app/cli` | `build_parser`, `main` (exit codes, consolidated-output, question-bank, fail-on-needs-review) | P1 |
| `app/ocr_router` | `resolve_ocr_config` (language → sarvam_lang, tesseract_lang, quality_preset) | P1 |
| `app/utils` | `validate_pdf_path`, `guard_max_pages`, `ensure_binaries`, `similarity_ratio` | P1 |
| `app/version` | `get_commit` (GIT_COMMIT file vs git) | P2 |

### 2.2 Unit Test Scenarios

**`app/extract`**

- `_text_looks_sane`:
  - Returns `False` for &lt; 3 words, avg word length &lt; 1.5 or &gt; 25, alnum_ratio &lt; 0.4.
  - With `regional=True`: returns `False` when >5% of letters are in Thai/Sinhala/Malayalam/Khmer/Lao ranges (e.g. garbled native).
- `_page_quality`:
  - Sarvam engine: non-empty text → status `approved`, no confidence gates.
  - Tesseract: with `quality_overrides` (e.g. 90% target), check `min_avg_confidence`, `max_low_conf_ratio`, `min_pass_similarity`, `min_native_similarity`, `skip_native_similarity_gate_when_native_selected`.
  - Layout overrides: `table`, `noisy`, `text` apply correct overrides.
  - Diagram-heavy branch: when `low_conf_ratio > 0.85` and `pass_similarity < 0.25`, apply `DIAGRAM_HEAVY_OVERRIDES`.
  - `never_native` (regional/force_ocr): never select native; on ocr_total_failure or ocr_unreliable → page_type `figure` and no failed gates.
  - `native_sufficient` + ocr failure → `native_fallback`, selected_source `native`, decision `A`.
- `_build_pages`:
  - With `selected_sources`: page uses native or OCR per key.
  - With `force_regional=True`: always OCR text (never native).
- `_calculate_stats`: `total_tokens`, `avg_confidence` (filtered ≥92), `confidence_pages` (raw_avg, filtered_avg, low_conf_ratio).

**`app/providers/ocr_sarvam`** (existing tests are strong; add)

- `_validate_output_text`: empty → False; unknown `sarvam_lang` → True; &gt;5% foreign script → False; &lt;5 letters → True.

**`app/api`**

- `_apply_safe_limits`: when `SAFE_MODE=False`, return (dpi, max_pages) unchanged; when `SAFE_MODE=True`, cap dpi to `SAFE_DPI`, max_pages to `SYNC_MAX_PAGES`/`ASYNC_MAX_PAGES`.
- `_stream_upload_to_temp`: no filename → 400; file over `MAX_FILE_SIZE_BYTES` → 413 and temp file deleted; empty file → 400 and temp file deleted; success → return path, caller cleans up.
- `serve_image`: missing file → 404; path traversal (e.g. `..`) → 403.

**`app/cli`**

- `main`: ExtractionError → exit 1; generic Exception → exit 2; `fail_on_needs_review` and quality not approved → exit 3; success with consolidated-output/question-bank files written.

**`app/ocr_router`**

- `resolve_ocr_config`: english → sarvam_lang None; kannada → kn-IN; hindi → hi-IN; tamil → ta-IN; telugu → te-IN; quality_preset for overrides.

### 2.3 Integration / API Test Scenarios

- **POST /extract** (sync):
  - Valid PDF, small page count → 200, JSON with `doc_id`, `pages`, `full_text`, `quality.status`.
  - Missing file / invalid form → 400.
  - File too large → 413.
  - Invalid PDF or extraction error → 400 (ExtractionError).
  - Optional `X-API-Key` when `API_KEY` set: wrong key → 403.
- **POST /api/extract/async**:
  - Valid PDF → 202 + `job_id`; GET `/api/extract/async/{job_id}` → eventually `status: completed` and `result`.
  - Invalid job_id → 404.
- **GET /api/images/{doc_id}/{page}/{filename}**:
  - Valid path under `IMAGE_STORE_DIR` → 200.
  - Path traversal → 403.
  - Not found → 404.
- **GET /api/question-bank/{job_id}**:
  - Completed job → 200, question bank JSON.
  - Pending/failed job → 409.
  - No result data → 404.
- **POST /api/ingest/{job_id}**:
  - Supabase not configured → 503.
  - Otherwise same as question-bank then ingest.

### 2.4 Edge Cases & Negative Tests

- **PDF**: Corrupt file, zero pages, password-protected, non-PDF MIME type.
- **OCR**: Sarvam SDK missing or `SARVAM_API_KEY` unset → fallback to Tesseract; Sarvam job state not Completed/PartiallyCompleted → empty results after retries.
- **Quality**: All pages need_review → `quality.status` needs_review; `fail_on_needs_review` → exit 3.
- **Limits**: `max_pages` exceeded → guard_max_pages error; `SAFE_MODE` + large max_pages → capped.
- **Concurrency**: Multiple async jobs; same job_id polled concurrently (expect 200 with same status/result).

### 2.5 Suggested New Tests (Pytest)

```python
# tests/test_extract_quality.py (examples)
def test_text_looks_sane_rejects_few_words():
    from app.extract import _text_looks_sane
    assert _text_looks_sane("a b") is False

def test_text_looks_sane_accepts_normal_english():
    from app.extract import _text_looks_sane
    assert _text_looks_sane("The quick brown fox jumps.") is True

def test_page_quality_sarvam_non_empty_approved():
    from app.extract import _page_quality
    gate = _page_quality(1, "", {"text": "ಕನ್ನಡ", "tokens": []}, 0, None, None, engine="sarvam")
    assert gate.status == "approved"
```

```python
# tests/test_api_safe_limits.py
def test_apply_safe_limits_when_safe_mode_false():
    with patch("app.api.SAFE_MODE", False):
        from app.api import _apply_safe_limits
        assert _apply_safe_limits(800, 20) == (800, 20)

def test_apply_safe_limits_caps_when_safe_mode_true():
    with patch("app.api.SAFE_MODE", True):
        with patch("app.api.SAFE_DPI", 300):
            with patch("app.api.SYNC_MAX_PAGES", 10):
                from app.api import _apply_safe_limits
                assert _apply_safe_limits(800, None) == (300, 10)
```

```python
# tests/test_ocr_router.py (extend existing)
def test_resolve_ocr_config_english_no_sarvam():
    from app.ocr_router import resolve_ocr_config
    c = resolve_ocr_config(language="english")
    assert c.sarvam_lang is None
```

### 2.6 Regression & Performance

- **Ground truth**: Use `scripts/eval_ground_truth.py` with fixed reference JSON; assert WER/CER thresholds in CI.
- **Training set**: Run `scripts/run_training_set.py` (or equivalent) and assert no regression in approved rate.
- **Performance**: Optional benchmark for a 30-page PDF (sync extract with force_ocr) to catch large slowdowns.

---

## 3. Summary Checklist

| Item | Status |
|------|--------|
| Code review (architecture, strengths, risks) | Done |
| Security (path traversal, file size, validation) | Reviewed |
| Unit test scenarios for extract, api, cli, ocr_router | Documented |
| Integration/API scenarios | Documented |
| Edge cases & negative tests | Documented |
| Example pytest snippets | Provided |
| Existing tests (test_ocr_sarvam) | Referenced |

Use this document to add tests under `tests/` and to drive manual/exploratory QA (API, CLI, different PDFs and languages). For automated test generation from this package, you can feed sections 2.1–2.5 into a test generator or QA Monster once Python plugin support is available.
