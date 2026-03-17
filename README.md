# PDF OCR Engine

**Production-Grade PDF Text Extraction with Quality Assurance**

Native + OCR hybrid extraction · Token-level confidence · Multi-pass quality gates · VLM diagram understanding

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 90%](https://img.shields.io/badge/python-90%25-blue)](https://github.com/vinaysflow/PDF-Scraper)

-----

## The Problem

PDF text extraction sounds solved. It isn’t.

Born-digital PDFs (generated from Word, LaTeX) have extractable text layers. Scanned PDFs (photographed documents, government forms, exam papers) don’t. Most real-world PDFs are a mix of both — some pages have text, some are images, some have embedded figures with no alt-text.

Existing tools force a choice: use native extraction (fast, no confidence scores, fails on scans) or use OCR (slow, inaccurate on clean text, no quality signal). Neither tells you *how accurate the output actually is*. When you’re processing hundreds of documents — exam papers, legal filings, financial reports — you need to know which pages you can trust and which need human review.

**The core gap:** No open-source PDF extraction tool combines native + OCR hybrid extraction, per-page quality scoring, automatic quality gates, and a canonical output schema that downstream systems can consume without parsing heuristics.

## The Hypothesis

A hybrid extraction pipeline with built-in quality assurance can achieve 90%+ accuracy on mixed PDFs while clearly flagging pages that need human review — eliminating the “silent failure” problem where bad OCR gets treated as good data.

**The key insight:** Quality isn’t binary. A page with 95% average confidence and 10% low-confidence tokens is usable. A page with 60% average confidence is not. But without per-token confidence scores and dual-pass similarity checking, you can’t tell the difference. The quality gates make this distinction automatic.

## What This Does

A complete PDF extraction pipeline: CLI, API, and web interface.

```
PDF Input
    │
    ├── Born-digital? ──▶ Native extraction (fast, exact)
    │                         │
    ├── Scanned? ──────▶ Tesseract OCR (multi-pass, quality-scored)
    │                         │
    └── Mixed? ────────▶ Hybrid (native first, OCR fallback per page)
                              │
                    ┌─────────▼─────────┐
                    │  Quality Gates     │
                    │  • avg confidence  │
                    │  • low-conf ratio  │
                    │  • dual-pass sim   │
                    │  • native vs OCR   │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Canonical JSON    │
                    │  per-page text     │
                    │  token-level bbox  │
                    │  confidence scores │
                    │  quality verdicts  │
                    └───────────────────┘
```

### Key Capabilities

- **Hybrid extraction** — Native text extraction for born-digital pages, Tesseract OCR for scanned pages, automatic per-page detection
- **Multi-pass OCR** — Layered preprocessing (standard + aggressive), multiple PSM candidates, Otsu thresholding, OSD rotation. Selects best consensus output per page
- **Token-level output** — Every word comes with bounding box (`x,y,w,h`) and confidence score. Not just “here’s the text” — “here’s every word, where it is, and how sure we are”
- **Quality gates with auto-retry** — Pages that fail confidence thresholds get re-OCR’d at higher DPI/thresholds. Pages that still fail are flagged `needs_review`, not silently passed through
- **VLM diagram extraction** — Detects embedded figures via PyMuPDF, sends to OpenAI Vision for description and structure extraction. Graceful degradation when VLM is unavailable
- **Ground-truth evaluation** — Compare extraction output against human-verified reference text. Per-page WER similarity and CER with pass/fail thresholds
- **Custom Tesseract model training** — Full workflow for domain-specific text (math symbols, non-Latin scripts). Training data prep, model generation, evaluation
- **Parallel processing** — Page-level OCR in thread pool (configurable workers), parallel VLM requests, native + render overlap
- **Three interfaces** — CLI for scripting/CI, FastAPI endpoint for integration, web UI for manual use

## Architecture Decisions (and Why)

|Decision              |Choice                                  |Why                                                                                                                                                                          |
|----------------------|----------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|OCR engine            |Tesseract over cloud APIs               |Runs locally, no per-page API cost, trainable for domain-specific scripts. Cloud APIs are faster but create vendor lock-in and cost problems at scale                        |
|Quality scoring       |Dual-pass similarity + confidence gating|Single-pass OCR has no self-check. Running two passes and comparing detects OCR instability that confidence scores alone miss                                                |
|Native vs OCR decision|Accuracy score threshold (0.8)          |When both native text and OCR exist, compare them. If they agree (score >= 0.8), use OCR (has token-level data). If they diverge, use native (more reliable for born-digital)|
|Output format         |Canonical JSON with token-level bbox    |Downstream consumers (search indexing, NLP pipelines, LLM context stuffing) need structured output, not raw text dumps. Token bounding boxes enable spatial reasoning        |
|Retry strategy        |Per-page re-OCR with escalating DPI     |Failing the entire document because one page is bad is wasteful. Per-page retry with higher DPI/thresholds recovers most borderline pages                                    |
|Diagram handling      |PyMuPDF extraction + optional VLM       |Figure extraction works without any API. VLM description is additive, not required. Partial failures don’t break the pipeline                                                |

## What I’d Measure

|Metric                                      |Why It Matters                                                                                                                         |
|--------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
|**Pages approved vs needs_review ratio**    |The primary quality metric. High approval rate = pipeline is working; rising review rate = input quality degrading or gates need tuning|
|**Mean WER similarity against ground truth**|The real accuracy metric. Quality gates are internal consistency checks; ground truth comparison is external validation                |
|**OCR latency per page (p50/p99)**          |Direct impact on throughput. Multi-pass OCR is accurate but slow; this metric reveals when parallelization or DPI reduction is needed  |
|**Quality gate failure distribution**       |Which gates fail most? If dual-pass similarity fails often, OCR is unstable. If confidence fails, input quality is poor. Guides tuning |
|**VLM description accuracy**                |When diagrams are extracted, are the descriptions actually useful for downstream tasks? Requires human eval sampling                   |
|**Retry recovery rate**                     |What % of initially-failed pages pass after retry? Low recovery = retries are wasted compute; high = gates are correctly set           |

## What I Learned

**1. Quality gates are the product, not the OCR.** Tesseract is open-source and well-understood. The differentiator is knowing *when to trust the output*. The dual-pass similarity check was the single biggest accuracy improvement — it catches cases where OCR confidently produces wrong text (high confidence, low accuracy).

**2. The 90% accuracy target changed everything.** Starting with “maximize accuracy” led to over-engineering. Setting a concrete target (90% WER similarity) made every decision clearer: which DPI to default, how many retries justify the compute cost, when to flag for human review instead of burning more GPU time.

**3. Graceful degradation beats hard failure.** The VLM diagram extraction works without an API key (figures are still extracted, just not described). Quality gates return `needs_review` instead of crashing. Every failure mode produces structured output, not stack traces. This matters more in production than the happy path.

**4. Domain-specific models are underrated.** The Kannada exam paper use case showed that generic Tesseract models fail badly on non-Latin scripts with mathematical notation. The custom training pipeline (images + ground truth + `train_tesseract.sh`) turned a 40% accuracy job into a 90% one. Most teams skip this because training seems hard — it’s actually a weekend of labeling.

## Project Status

|Component              |Status |Detail                                                    |
|-----------------------|-------|----------------------------------------------------------|
|Native text extraction |Shipped|Born-digital PDF text layer extraction                    |
|Tesseract OCR pipeline |Shipped|Multi-pass, multi-PSM, preprocessing strategies           |
|Hybrid detection       |Shipped|Per-page native/OCR/mixed routing                         |
|Quality gates          |Shipped|Confidence, dual-pass similarity, native-OCR comparison   |
|Auto-retry on failure  |Shipped|Per-page re-OCR with escalating parameters                |
|Token-level output     |Shipped|Bounding boxes + confidence per word                      |
|VLM diagram extraction |Shipped|PyMuPDF figures + OpenAI Vision descriptions              |
|Ground-truth evaluation|Shipped|WER/CER with thresholds and per-page reporting            |
|Custom model training  |Shipped|Full Tesseract training workflow                          |
|Parallel processing    |Shipped|Thread pool OCR + parallel VLM                            |
|Web UI                 |Shipped|Upload, configure, download JSON                          |
|FastAPI endpoint       |Shipped|REST API with file upload                                 |
|CLI with exit codes    |Shipped|CI-friendly with quality-aware exit codes                 |
|Consolidated reporting |Shipped|Single JSON with quality summary + high-quality items only|

**Codebase:** Python 90% · 29 commits · CLI + API + Web UI · Deployable via Railway + Vercel

-----

## Quick Start

### Install

```bash
# macOS
brew install tesseract poppler openjdk

# Clone and setup
git clone https://github.com/vinaysflow/PDF-Scraper.git
cd PDF-Scraper
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### CLI

```bash
# Basic extraction
python -m app.cli /path/to/file.pdf --dpi 600 --max-pages 10

# Force OCR with 90% quality target
python -m app.cli /path/to/file.pdf --force-ocr --quality-target 90

# Full pipeline with diagrams
python -m app.cli /path/to/file.pdf --force-ocr --quality-target 90 --extract-diagrams

# CI mode: fail on quality issues
python -m app.cli /path/to/file.pdf --fail-on-needs-review
```

### API

```bash
uvicorn app.api:app --reload
# Web UI: http://127.0.0.1:8000
# API:
curl -X POST "http://127.0.0.1:8000/extract?dpi=600&force_ocr=true" \
  -F "file=@/path/to/file.pdf"
```

### Ground-Truth Evaluation

```bash
python scripts/eval_ground_truth.py \
    --extraction output.json \
    --ground-truth gt.json \
    --min-wer-sim 0.90 --max-cer 0.10
```

### Custom Model Training

```bash
bash training/train_tesseract.sh \
    --lang eng_custom \
    --images training/data/images \
    --ground-truth training/data/gt
# Then use: --ocr-lang eng_custom --tessdata-path /path/to/tessdata
```

-----

## Output Schema

```json
{
  "doc_id": "uuid",
  "filename": "original.pdf",
  "ingested_at": "2026-03-16T...",
  "extraction": { "method": "hybrid", "pages_total": 10, "dpi": 600 },
  "pages": [
    {
      "page_number": 1,
      "source": "ocr",
      "text": "extracted text...",
      "tokens": [{ "text": "word", "bbox": [x,y,w,h], "confidence": 96.2 }]
    }
  ],
  "quality": {
    "status": "approved",
    "pages": [{ "page_number": 1, "accuracy_score": 0.94, "failed_gates": [] }]
  },
  "diagrams": {
    "figures_total": 3,
    "diagrams": [{ "figure": {...}, "reading": { "description": "...", "kind": "bar_chart" }}]
  },
  "full_text": "concatenated text...",
  "stats": { "total_tokens": 4521, "avg_confidence": 94.7 }
}
```

## Performance

Parallel OCR + VLM processing for production throughput:

```bash
OCR_WORKERS=6 VLM_WORKERS=8 python -m app.cli /path/to/file.pdf \
    --force-ocr --max-pages 31 --extract-diagrams --quality-target 90
```

See [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) for benchmarks.

## Repository Structure

```
PDF-Scraper/
├── app/              # Core extraction engine
│   ├── cli.py        # CLI interface with exit codes
│   ├── api.py        # FastAPI endpoint
│   └── ocr.py        # Multi-pass OCR with quality gates
├── api/              # API deployment config
├── training/         # Custom Tesseract model training
├── scripts/          # Batch processing, evaluation, quality tools
├── tests/            # Unit tests
├── docs/             # Deployment guides, performance docs
├── static/           # Web UI assets
├── public/           # Vercel frontend
├── Dockerfile        # Container deployment
├── railway.toml      # Railway deployment
└── vercel.json       # Vercel deployment
```

## Deployment

- **Simple:** <docs/DEPLOY_SIMPLE.md> (Railway + Vercel)
- **Advanced:** <docs/VERCEL.md>

## License

[Apache 2.0](LICENSE)

-----

Built by [Vinay Tripathi](https://github.com/vinaysflow) · vinay@aurviaglobal.com