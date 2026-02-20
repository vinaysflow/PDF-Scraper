#!/usr/bin/env python3
"""Run extraction on a Kannada PDF (e.g. Kannada SL.pdf) and write JSON to outputs/."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add repo root so app is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PDF = os.environ.get(
    "KANNADA_SAMPLE_PDF",
    str(Path.home() / "Downloads" / "Kannada SL.pdf"),
)
OUTPUT_DIR = REPO_ROOT / "outputs"
OUTPUT_FILE = OUTPUT_DIR / "kannada_sl_extraction.json"


def main() -> int:
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PDF
    if not os.path.isfile(pdf_path):
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        print("Usage: python scripts/kannada_sample_extract.py [path/to/kannada.pdf]", file=sys.stderr)
        return 1

    from app.extract import extract_pdf

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Extracting: {pdf_path} (language=kannada, force_ocr=True)", file=sys.stderr)
    result = extract_pdf(
        pdf_path,
        language="kannada",
        force_ocr=True,
        quality_target=90,
    )
    out = OUTPUT_FILE
    with open(out, "w") as f:
        f.write(result.model_dump_json(indent=2))
    print(f"Wrote: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
