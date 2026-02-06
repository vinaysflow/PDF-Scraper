# Performance and production tuning

## Time-to-output optimizations

1. **Parallel page OCR** (`app/ocr.py`)
   - Pages are processed in a thread pool so multiple Tesseract runs can execute concurrently.
   - Default workers: **4** (override with env `OCR_WORKERS`, e.g. `OCR_WORKERS=8`).
   - Tesseract is invoked as a subprocess per run, so threads can run several pages at once without blocking on the GIL for long.

2. **Parallel VLM calls** (`app/diagram_pipeline.py`)
   - When `--extract-diagrams` is used, each figure’s describe/structure/chart calls run in a thread pool.
   - Default workers: **5** (override with env `VLM_WORKERS`, e.g. `VLM_WORKERS=10`).
   - Keep `VLM_WORKERS` within your OpenAI rate limits (RPM/TPM) to avoid throttling.

3. **Tika + PDF render in parallel** (`app/extract.py`)
   - With `--force-ocr`, Tika extraction and PDF→image rendering run concurrently.
   - OCR then uses the pre-rendered images and does not render again, so wall time is reduced by the overlap.

## Environment variables

| Variable       | Default | Description                                      |
|----------------|---------|--------------------------------------------------|
| `OCR_WORKERS`  | `4`     | Max concurrent pages for OCR (1–32).             |
| `VLM_WORKERS`  | `5`     | Max concurrent figures for VLM (1–20).           |

## Expected impact

- **OCR:** With 4 workers, a 31-page run can be ~3–4× faster than sequential (depending on CPU and layout).
- **Diagrams:** With 5 workers, 15 figures can complete in roughly 3 batches instead of 15 sequential calls.
- **Tika + render:** Saves roughly `min(tika_time, render_time)` when `--force-ocr` is used.

## Tuning tips

- Increase `OCR_WORKERS` on multi-core machines; avoid setting it higher than core count if CPU-bound.
- Increase `VLM_WORKERS` only if your OpenAI tier allows higher concurrency without 429s.
- For very large PDFs, consider splitting by page range or running multiple documents in parallel at the job level.
