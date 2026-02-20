# Discovery: What’s built, in prod, and relevant for Karnataka/Kannada

**Scope:** Grep/review of the repo. No plan, no code changes. For **Review → Plan → Execute on click**.

---

## Executive summary

| What | Summary |
|------|--------|
| **Prod stack** | Backend (FastAPI + Tesseract/Paddle) on Railway via Docker; upload UI on Vercel proxying to backend. OCR default is English. |
| **Karnataka/Kannada today** | No dedicated flow. CLI/API support `ocr_lang` and `tessdata_path`; **UI does not** — so browser uploads always use `eng`. |
| **Main gaps** | (1) UI never sends `ocr_lang` → Kannada needs API/CLI. (2) Paddle gets `ocr_lang[:2]` → `kan` becomes `ka` instead of `kn`. (3) No Kannada quality preset or sample run for `Kannada SL.pdf`. |
| **Sample file** | `Kannada SL.pdf` (your Downloads path) — no script or doc references it yet; “exception extraction” would need to be added. |
| **Next** | Implemented: language routing, UI selector, Kannada quality preset, Paddle lang fix. See [docs/PLAN_KANNADA_REGIONAL_REBUILD.md](PLAN_KANNADA_REGIONAL_REBUILD.md) and sample run below. |

---

## 1. What’s built and pushed to prod

### Deployment
- **Backend:** FastAPI app in Docker; intended for **Railway** (also Render, Fly.io). `railway.toml` + `Dockerfile`; `PORT` → safe mode (lower DPI, batched pages). `docs/PRODUCTION.md`, `DEPLOY_SIMPLE.md`, `DEPLOY_STEPS.md`, `DEPLOY_TROUBLESHOOTING.md`.
- **Frontend:** Static upload page + Vercel serverless proxy (`api/extract.js`). UI on **Vercel**; proxy forwards to `EXTRACT_API_URL` (backend). No OCR runs on Vercel.
- **Production behaviour:** `SKIP_NATIVE=1` on Railway (OCR-only, no Java); `SAFE_MODE` when `PORT` set; `SYNC_MAX_PAGES` (e.g. 5), `ASYNC_MAX_PAGES` (e.g. 100), `SAFE_DPI` (300), `SAFE_BATCH_PAGES` (3). See `app/config.py`, `docs/PRODUCTION.md`.

### Extraction pipeline (finalized)
- **Entrypoints:** CLI (`app/cli.py`), API (`app/api.py`: POST `/extract`, POST `/api/extract`, POST `/api/extract/async`, GET `/api/extract/async/{job_id}`).
- **Flow:** `extract_pdf()` in `app/extract.py`: validate PDF → native text (PyMuPDF) → decide pages needing OCR → OCR (Tesseract or Paddle) → build pages → quality gates + retries → optional diagrams/layout/tables/images → result JSON.
- **OCR:** Tesseract default (`app/ocr.py`: `OCR_LANG = "eng"`, layout presets, dual-pass, table cell OCR, retries). Optional PaddleOCR via `OCR_ENGINE=paddleocr` (`app/providers/ocr_paddle.py`).
- **Quality:** `_page_quality` in `extract.py`; layout overrides (table/noisy/text); quality target 90; native-sufficient / native-fallback / figure-page bypasses. Tests in `tests/test_quality_gate.py` use “KARNATAKA SCHOOL EXAMINATION AND ASSESSMENT BOARD” (English header use case only).
- **Output:** Canonical JSON: `doc_id`, `filename`, `pages` (text, tokens, source), `extraction` (method, engine, dpi), `quality`. Optional: consolidated report, question bank, diagrams.

### Language / OCR settings
- **CLI:** `--ocr-lang` (default `eng`), `--tessdata-path`. Passed through to `extract_pdf` and Tesseract.
- **API:** Query/body params `ocr_lang` (default `"eng"`), `tessdata_path`. Passed to `_do_extract` → `extract_pdf`.
- **Tesseract:** Uses `ocr_lang` as-is in `_build_config(..., lang=ocr_lang, ...)` in `app/ocr.py` (and in table cell OCR, retries).
- **Paddle:** In `app/extract.py` (Paddle path), language is passed as `ocr_lang[:2]` to `paddle_ocr_pages(..., lang=ocr_lang[:2], ...)`. So `eng` → `en`, `kan` → `ka`. Paddle typically uses ISO 639-1 (e.g. `kn` for Kannada), so `kan` → `ka` is wrong for Kannada; no explicit mapping exists.
- **UI (Vercel):** Upload form does **not** send `ocr_lang` or `tessdata_path`. Only: file, max_pages, force_ocr, quality_target, extract_diagrams. So in prod, backend always uses default `ocr_lang="eng"` for browser uploads.

### Exception handling
- **Worker:** `app/worker.py` catches `Exception` in `_run`, marks job failed, stores error message.
- **API:** Global `Exception` → 500 JSON; `ExtractionError` → 400; upload/empty file → 400; job not found → 404; etc. in `app/api.py`.
- **Extract:** Several `except Exception` in `extract.py` (e.g. image/layout/table extraction) that set a message and continue or re-raise. No dedicated “exception extraction” or “Kannada exception path” exists.

### Scripts and training
- **Scripts:** `scripts/quality_batch.py` (supports `--ocr-lang`), `scripts/run_training_set.py`. No script for a specific “Kannada SL” or Karnataka sample.
- **Training:** `training/README.md`, `training/train_tesseract.sh` — custom Tesseract model (e.g. `eng_custom`); docs mention `--ocr-lang` and `--tessdata-path` for use after training. No Karnataka/Kannada-specific instructions.

### Sample file you mentioned
- **Path:** `/Users/vinaytripathi/Downloads/Kannada SL.pdf` — not in repo; no script or doc currently references it. “Sample exception extraction” for this file would need to be added (e.g. script or documented CLI command).

---

## 2. Gaps for Karnataka / Kannada use case

| Area | Current state | Gap |
|------|----------------|----------------|
| **OCR language** | Default `eng`; CLI/API accept `ocr_lang` | UI never sends `ocr_lang`; Kannada users get English OCR in prod unless they call API/CLI with `ocr_lang=kan`. |
| **Tesseract** | Uses `ocr_lang` as-is | Tesseract code for Kannada is `kan`; need `kan.traineddata` on the system (not in repo). |
| **Paddle** | Uses `ocr_lang[:2]` | `kan` → `ka`; Paddle expects `kn` for Kannada. No Tesseract→Paddle language map. |
| **Quality gates** | Tuned for English (e.g. confidence, dual-pass) | No Kannada-specific relaxation or “Karnataka language” preset documented or implemented. |
| **Karnataka context** | Only in test string “KARNATAKA SCHOOL EXAMINATION…” | No dedicated flow or docs for Karnataka language or “exception extraction” for Kannada SL PDF. |
| **Sample extraction** | Generic CLI/API only | No one-click sample for `Kannada SL.pdf` or documented “exception extraction” run. |

---

## 3. Doc references (no changes made)

- Production: `docs/PRODUCTION.md`, `DEPLOY_SIMPLE.md`, `DEPLOY_STEPS.md`, `DEPLOY_TROUBLESHOOTING.md`, `VERCEL.md`, `DESIGN_PRODUCTION_OCR.md`
- OCR / quality: `app/ocr.py`, `app/extract.py`, `app/providers/ocr_paddle.py`, `docs/IMPROVEMENTS.md`, `PLAN_LAYOUT_SPECIFIC_HANDLING.md`
- Language: `app/cli.py` (--ocr-lang), `app/api.py` (ocr_lang), `training/README.md`

---

## Sample run (Kannada)

Use the UI and set **Document language** to **Kannada**, or run from CLI:

```bash
python -m app.cli "/path/to/Kannada SL.pdf" --language kannada --force-ocr --max-pages 10
```

For the full document, omit `--max-pages` or set it to the page count. Optional script: [scripts/kannada_sample_extract.py](../scripts/kannada_sample_extract.py) (run from repo root).
