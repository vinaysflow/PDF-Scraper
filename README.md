# PDF OCR MVP

Production-ready MVP that extracts text and token-level OCR from PDFs and returns a canonical JSON payload. It supports:

- Born-digital PDFs via Apache Tika
- Scanned PDFs via Tesseract OCR
- Mixed PDFs with hybrid extraction (Tika first, OCR fallback)

## Requirements

- macOS with Homebrew
- Python 3.11+
- System binaries: Tesseract and Poppler

Install system dependencies:

```
brew install tesseract poppler
```

Apache Tika runs via Java under the hood. Ensure a JRE is available:

```
brew install openjdk
```

## Setup

```
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## CLI Usage

```
python -m app.cli /path/to/file.pdf --dpi 600 --max-pages 10
```

Force OCR even when Tika succeeds (to produce confidence/tokens):

```
python -m app.cli /path/to/file.pdf --dpi 600 --max-pages 10 --force-ocr
```

Strict quality gates (default on):

```
python -m app.cli /path/to/file.pdf --strict-quality
```

To bypass strict gating entirely:

```
python -m app.cli /path/to/file.pdf --no-strict-quality
```

Quality retries (per-page re-OCR, default 2):

```
python -m app.cli /path/to/file.pdf --quality-retries 2
```

## OCR Quality Tuning

- Default OCR DPI is 600 for accuracy.
- For even lower-quality scans, try higher DPI (600–800) at the cost of speed:
  ```
  python -m app.cli /path/to/file.pdf --dpi 800
  ```
- Default OCR settings are defined in `app/ocr.py` (`OCR_OEM`, `OCR_PSM`, `OCR_LANG`, `OCR_THRESHOLD`).
- The OCR pipeline uses multi-pass PSM selection (`OCR_PSM_CANDIDATES`) for better accuracy.
- If the PDF is table-heavy, keep `4` in `OCR_PSM_CANDIDATES`.
- Otsu thresholding and OSD rotation are enabled by default for accuracy.
- Strict quality gates require:
  - avg confidence >= 93 (computed on tokens with confidence >= 92)
  - low-confidence ratio <= 50%
  - dual-pass similarity >= 0.85
  - Tika vs OCR similarity >= 0.85 (when Tika text is present)
- In strict mode, output is still returned with `quality.status=needs_review` when any page fails after retries.
- Decision rule: if `accuracy_score >= 0.8` then choose **B** (OCR text/tokens), else choose **A** (Tika text when available).
- OCR uses layered preprocessing strategies (standard + aggressive) and multiple PSM passes, then selects the best consensus output.
- You can override OCR language and tessdata path:
  ```
  python -m app.cli /path/to/file.pdf --ocr-lang eng_custom --tessdata-path /path/to/tessdata
  ```
 - Table pages use OpenCV line removal + cell OCR, with relaxed gates for table layouts.

## Targeting 90% accuracy and quality

To aim for **~90% accuracy** and have pages pass quality as “approved”:

1. **Use the 90% quality target** so gates match that goal:
   ```
   python -m app.cli /path/to/file.pdf --quality-target 90 --force-ocr
   ```
   With `--quality-target 90`, gates are: avg confidence ≥ 90%, low-conf ratio ≤ 60%, dual-pass and Tika similarity ≥ 0.90, and OCR is chosen when accuracy ≥ 0.90.

2. **Improve OCR input and retries**
   - **DPI:** Use 600–800 for scans (e.g. `--dpi 800` for poor scans).
   - **Retries:** Use `--quality-retries 3` so failed pages get more OCR attempts at higher DPI/thresholds.
   - **Strict mode:** Keep `--strict-quality` (default) so quality is measured; use `--no-strict-quality` only to bypass gates.

3. **Source quality**
   - Prefer 300+ DPI scans; avoid blurry or heavily compressed images.
   - For born-digital PDFs with little or bad embedded text, use `--force-ocr` so Tesseract runs and confidence/similarity are computed.

4. **Custom models**
   - For domain-specific text (e.g. maths, symbols), train a Tesseract model (see `training/README.md`) and pass `--ocr-lang` and `--tessdata-path`.

5. **Check the output**
   - `quality.status`: `"approved"` means all pages passed the (possibly relaxed) gates.
   - `quality.pages[].accuracy_score`: Tika vs OCR similarity or confidence-derived score; aim for ≥ 0.90 when using `--quality-target 90`.
   - `quality.pages[].failed_gates`: lists which gates failed so you can tune DPI, retries, or source PDFs.

## Performance and parallelism (production)

The pipeline is tuned for faster time-to-output:

- **Parallel OCR:** Page-level OCR runs in a thread pool (default 4 workers). Set `OCR_WORKERS` to tune (e.g. `OCR_WORKERS=8`).
- **Parallel VLM:** When using `--extract-diagrams`, figure descriptions are requested in parallel (default 5 workers). Set `VLM_WORKERS` to tune (e.g. `VLM_WORKERS=10`); stay within your OpenAI rate limits.
- **Tika + render overlap:** With `--force-ocr`, Tika extraction and PDF→image rendering run in parallel so OCR can start as soon as both are ready.

Example for a 31-page PDF with diagrams:

```bash
OCR_WORKERS=6 VLM_WORKERS=8 python -m app.cli /path/to/file.pdf --force-ocr --max-pages 31 --extract-diagrams --quality-target 90
```

See `docs/PERFORMANCE.md` for more detail.

## Test / training PDFs

The set of PDFs used to evaluate and tune this model is:

- **Path:** `~/Downloads/Sample PDF FOR TESTING` (or set `TRAINING_PDF_DIR` to override)

Contents: English 10th Science and Maths model papers (01–04) and question papers (01–04). Use this folder when comparing quality across runs or regressions.

Run batch quality on all training PDFs:

```bash
python scripts/run_training_set.py --force-ocr --strict-quality
```

Optional: pass a different directory or save the summary to a file:

```bash
TRAINING_PDF_DIR=/path/to/other python scripts/run_training_set.py --force-ocr > outputs/batch_training_summary.json
```

## Training a custom model

See `training/README.md` for the full workflow. Summary:

- Place images + ground-truth text in `training/data/`
- Run:
  ```
  bash training/train_tesseract.sh --lang eng_custom --images training/data/images --ground-truth training/data/gt
  ```
- Use the trained model via `--ocr-lang` and `--tessdata-path`

## API and web upload

Start the server:

```bash
uvicorn app.api:app --reload
```

**Web UI:** Open [http://127.0.0.1:8000](http://127.0.0.1:8000) to use the upload page. You can select a PDF, set max pages, force OCR, quality target 90%, and optional diagram extraction, then download the full JSON result. To deploy: **simple steps** → [docs/DEPLOY_SIMPLE.md](docs/DEPLOY_SIMPLE.md) (Railway + Vercel). More options → [docs/VERCEL.md](docs/VERCEL.md).

**API:** Extract a PDF via POST:

```bash
curl -X POST "http://127.0.0.1:8000/extract?dpi=600&max_pages=10&force_ocr=false" \
  -F "file=@/path/to/file.pdf"
```

## Output Schema

The JSON output includes:

- `doc_id`: UUID for the request
- `filename`: Original filename
- `ingested_at`: ISO timestamp
- `extraction`: `{method,pages_total,dpi,engine}`
- `pages`: list of `{page_number,source,text,tokens}`
- `full_text`: concatenated text across pages
- `stats`: `{total_tokens,avg_confidence}` (avg uses tokens with confidence >= 92)

Token entries include `text`, `bbox` (`x,y,w,h`), and `confidence`. Pages extracted with Tika have an empty `tokens` array.

## Diagram extraction

With `--extract-diagrams`, the pipeline also extracts embedded figures from the PDF (via PyMuPDF) and runs an optional VLM (OpenAI Vision) to describe each figure and optionally extract structure/chart data.

**Requirements:** `pymupdf` (required). For VLM descriptions, install the OpenAI client and set `OPENAI_API_KEY`:

```bash
# From the project root (pdf-ocr-mvp). Use any one of these:
pip install ".[diagrams]"
# If the above fails (e.g. quoting on your shell), install directly:
pip install openai
```

```bash
python -m app.cli /path/to/file.pdf --extract-diagrams
```

The JSON output includes a top-level `diagrams` object when `--extract-diagrams` is used:

- `diagrams.figures_total`: number of figures found
- `diagrams.diagrams[]`: each with `figure` (page_number, bbox, area) and `reading` (description, structure, chart_data, kind, error). If the VLM is not configured or fails, `reading.error` is set and description may be null.

**Robustness:** If `OPENAI_API_KEY` is not set, figure extraction still runs and each reading has `error: "VLM not configured"`. Partial failures (e.g. one figure fails VLM) do not break the run; that figure’s `reading.error` is set.

## Consolidated output (all checks, high quality only)

To get a **single JSON file** that summarizes all checks and lists only **high-quality** items (approved pages + diagram descriptions with no error):

```bash
python -m app.cli /path/to/file.pdf --force-ocr --quality-target 90 --extract-diagrams --consolidated-output outputs/report.json
```

- **stdout:** full extraction JSON (unchanged).
- **File at `--consolidated-output`:** consolidated report with: **document**, **quality_summary** (approved_count, needs_review_pages), **high_quality_pages** (approved only, with text_preview), **high_quality_diagrams** (figures with valid description), **full_text_preview**, **stats**.

## Error Handling

Common error cases:

- Missing system binaries (`tesseract`, `pdftoppm`)
- Corrupt or unreadable PDFs
- Empty extracted content
- Max pages guard exceeded

These return clear error messages in the CLI and HTTP 400 responses in the API.

## Tests

Run unit tests (no external PDFs required):

```
python -m unittest
```

Batch evaluate quality across multiple PDFs:

```
python scripts/quality_batch.py /path/to/a.pdf /path/to/b.pdf --force-ocr --strict-quality
```
