"""Command-line interface for PDF extraction."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .extract import extract_pdf
from .utils import ExtractionError


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""

    parser = argparse.ArgumentParser(description="Extract text and OCR from a PDF.")
    parser.add_argument("pdf_path", help="Path to the PDF file.")
    parser.add_argument("--dpi", type=int, default=600, help="OCR DPI (default: 600).")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum allowed pages before failing.",
    )
    parser.add_argument(
        "--force-ocr",
        action="store_true",
        help="Always run OCR (even if native extraction succeeds).",
    )
    parser.add_argument(
        "--strict-quality",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply strict quality gates and mark needs_review on failure.",
    )
    parser.add_argument(
        "--quality-retries",
        type=int,
        default=2,
        help="Number of per-page OCR retries for quality (default: 2).",
    )
    parser.add_argument(
        "--quality-target",
        type=int,
        default=None,
        metavar="PCT",
        help="Quality target percentage (e.g. 90). Uses relaxed gates for that target (default: strict).",
    )
    parser.add_argument(
        "--language",
        type=str,
        default=None,
        help="Document language for OCR (e.g. kannada, hindi). Overrides --ocr-lang when set.",
    )
    parser.add_argument(
        "--ocr-lang",
        type=str,
        default="eng",
        help="Tesseract language code (default: eng). Used when --language is not set.",
    )
    parser.add_argument(
        "--tessdata-path",
        type=str,
        default=None,
        help="Path to custom tessdata directory (optional).",
    )
    parser.add_argument(
        "--extract-diagrams",
        action="store_true",
        help="Extract figures and run VLM diagram reading (requires OPENAI_API_KEY for descriptions).",
    )
    parser.add_argument(
        "--include-base64",
        action="store_true",
        help="Embed base64-encoded image data in the JSON output (off by default).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="Directory for saving extracted images. "
             "If set, images go into DIR/<stem>_images/. "
             "Defaults to IMAGE_STORE_DIR env var.",
    )
    parser.add_argument(
        "--consolidated-output",
        type=str,
        default=None,
        metavar="FILE",
        help="Write a consolidated high-quality report (quality + approved pages + diagram descriptions) to FILE.",
    )
    parser.add_argument(
        "--question-bank",
        type=str,
        default=None,
        metavar="FILE",
        help="Generate a question bank JSON and write to FILE. "
             "Parses questions, associates images, and optionally enriches with LLM.",
    )
    parser.add_argument(
        "--no-llm-enrich",
        action="store_true",
        help="Skip LLM enrichment when generating question bank (uses rule-based fallback).",
    )
    return parser


def main() -> int:
    """Entry point for the CLI."""

    parser = build_parser()
    args = parser.parse_args()

    try:
        # Resolve image output directory for CLI usage
        image_output_dir = args.output_dir
        if image_output_dir:
            stem = Path(args.pdf_path).stem
            image_output_dir = os.path.join(image_output_dir, f"{stem}_images")

        result = extract_pdf(
            args.pdf_path,
            dpi=args.dpi,
            max_pages=args.max_pages,
            force_ocr=args.force_ocr,
            strict_quality=args.strict_quality,
            quality_retries=args.quality_retries,
            quality_target=args.quality_target,
            language=args.language,
            ocr_lang=args.ocr_lang,
            tessdata_path=args.tessdata_path,
            extract_diagrams=args.extract_diagrams,
            include_base64=args.include_base64,
            image_output_dir=image_output_dir,
        )
        if args.consolidated_output:
            from .consolidated import build_consolidated_report
            report = build_consolidated_report(result, full_output_path=None)
            with open(args.consolidated_output, "w") as f:
                f.write(report.model_dump_json(indent=2))
        if args.question_bank:
            from .question_bank import build_question_bank
            qbank = build_question_bank(
                result,
                enrich_with_llm=not args.no_llm_enrich,
            )
            with open(args.question_bank, "w") as f:
                f.write(qbank.model_dump_json(indent=2))
            print(f"Question bank written to {args.question_bank}", file=sys.stderr)
        print(result.model_dump_json(indent=2))
        return 0
    except ExtractionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - safety net
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
