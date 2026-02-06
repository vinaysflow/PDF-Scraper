# QA and testing

## Running tests

From the project root with the venv activated:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -p "*.py" -v
```

Or run specific modules:

```bash
python -m unittest tests.test_extract tests.test_utils tests.test_ocr tests.qa_pipeline -v
```

**Full suite:** 75+ tests across 8 modules (~10 s including one integration test).

## QA coverage

### Unit tests

| Area | What’s tested |
|------|----------------|
| **Stats** | `_calculate_stats`: total_tokens, avg_confidence (only tokens ≥ 92). |
| **Quality gates** | Table/noisy layout overrides (relaxed min_pass, max_low_conf). Diagram-heavy thresholds and Phase 1b approval. |
| **Quality gate logic** | `_page_quality`: table page with relaxed pass approves; diagram-heavy page (high low_conf, low dual_pass) approves. |
| **Consolidated report** | `build_consolidated_report`: required keys (document, quality_summary, high_quality_pages, high_quality_diagrams, stats), approved count. |
| **Config** | `OCR_WORKERS` / `VLM_WORKERS` env parsing and bounds. |

### Output schema (after a full run)

If `outputs/ENGLISH_10th_Maths_Model_paper_01_full.json` and `outputs/ENGLISH_10th_Maths_01_consolidated.json` exist:

- Full output: `doc_id`, `filename`, `pages`, `extraction`, `quality`; each page has `page_number`, `source`, `text`, `tokens`.
- Consolidated: `document`, `quality_summary` (approved_count, pages_total), `high_quality_pages`, `high_quality_diagrams`, `stats`.

These tests are skipped when the files are not present.

### Integration (optional)

- **OCR workers parity**: Same PDF (2 pages, low DPI) run with `workers=1` and `workers=2`; same page count and same per-page keys (`text`, `tokens`, `layout`, `pass_similarity`, `strategy`). Skips if `SAMPLE_PDF` or default sample path is missing.

Set a sample PDF explicitly:

```bash
SAMPLE_PDF="/path/to/sample.pdf" python -m unittest tests.qa_pipeline.TestOCRParallelParity -v
```

## What’s not automated (manual QA)

- **End-to-end with diagrams**: Full pipeline with `--extract-diagrams` and VLM (requires `OPENAI_API_KEY`); spot-check consolidated report and diagram descriptions.
- **Quality retries**: Pages that fail gates and get retried with different DPI/strategy; confirm retry count and final status in output.
- **Native + render parallel**: With `--force-ocr`, native extraction and PDF render run in parallel; no dedicated test; rely on full run timing and success.
- **Large PDFs**: 31-page run and beyond; performance and stability checked manually.

## Adding tests

- New unit tests: add to the appropriate `tests/test_*.py` or `tests/qa_pipeline.py`.
- New integration tests: use `self.skipTest(...)` when external resources (PDF, API) are missing so CI can run without them.
