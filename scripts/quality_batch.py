#!/usr/bin/env python3
"""Batch quality evaluation for a set of PDFs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extract import extract_pdf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch evaluate OCR quality.")
    parser.add_argument("pdfs", nargs="+", help="PDF file paths to evaluate.")
    parser.add_argument("--force-ocr", action="store_true", help="Force OCR for all pages.")
    parser.add_argument("--strict-quality", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--quality-retries", type=int, default=2)
    parser.add_argument("--quality-target", type=int, default=None, metavar="PCT", help="e.g. 90 for 90%% accuracy gates")
    parser.add_argument("--ocr-lang", type=str, default="eng")
    parser.add_argument("--tessdata-path", type=str, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = []
    total_pages = 0
    failed_pages = 0

    for pdf_path in args.pdfs:
        result = extract_pdf(
            pdf_path,
            force_ocr=args.force_ocr,
            strict_quality=args.strict_quality,
            quality_retries=args.quality_retries,
            quality_target=args.quality_target,
            ocr_lang=args.ocr_lang,
            tessdata_path=args.tessdata_path,
        )
        quality = result.quality
        page_failures = [
            page for page in (quality.pages if quality else []) if page.status != "approved"
        ]
        total_pages += result.extraction.pages_total
        failed_pages += len(page_failures)
        results.append(
            {
                "pdf": Path(pdf_path).name,
                "pages_total": result.extraction.pages_total,
                "failed_pages": len(page_failures),
                "status": quality.status if quality else "unknown",
            }
        )

    summary = {
        "total_pages": total_pages,
        "failed_pages": failed_pages,
        "failed_ratio": round(failed_pages / total_pages, 4) if total_pages else 0,
        "files": results,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
