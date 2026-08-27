"""Produce a 17-column Tesseract-style TSV for a PDF.

Columns (in order):
  doc_id, filename, dpi, engine, language,
  level, page_num, block_num, par_num, line_num, word_num,
  left, top, width, height, conf, text

Usage:
  python scripts/make_tesseract_tsv.py <pdf_path> <out_tsv> [--dpi 600] [--lang kan] [--doc-id UUID]
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import fitz  # PyMuPDF

TESS_COLS = [
    "level", "page_num", "block_num", "par_num", "line_num", "word_num",
    "left", "top", "width", "height", "conf", "text",
]
DOC_COLS = ["doc_id", "filename", "dpi", "engine", "language"]
HEADER = DOC_COLS + TESS_COLS  # 17 columns


def run_tesseract_tsv(image_path: Path, lang: str) -> list[list[str]]:
    """Return parsed TSV rows (excluding Tesseract's header row)."""
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", lang, "tsv"],
        capture_output=True, text=True, check=True,
    )
    lines = result.stdout.splitlines()
    if not lines:
        return []
    rows = [ln.split("\t") for ln in lines[1:] if ln]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_path")
    ap.add_argument("out_tsv")
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--lang", default="kan")
    ap.add_argument("--doc-id", default=None,
                    help="Reuse a specific doc_id (else generate a new UUID).")
    args = ap.parse_args()

    pdf = Path(args.pdf_path)
    if not pdf.exists():
        print(f"pdf not found: {pdf}", file=sys.stderr)
        return 1

    doc_id = args.doc_id or str(uuid.uuid4())
    doc = fitz.open(pdf)

    total_tokens = 0
    with open(args.out_tsv, "w", newline="") as fh, tempfile.TemporaryDirectory() as td:
        writer = csv.writer(fh, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(HEADER)

        for i, page in enumerate(doc):
            page_num = i + 1
            img = Path(td) / f"page_{page_num}.png"
            page.get_pixmap(dpi=args.dpi).save(img)

            rows = run_tesseract_tsv(img, args.lang)
            for r in rows:
                if len(r) < len(TESS_COLS):
                    continue
                # Force the page_num column to the real PDF page number
                # (Tesseract emits 1 per single-image invocation).
                r[1] = str(page_num)
                # Some rows have blank text (structural rows); keep them but
                # normalize the text field (last col) which may be missing.
                if len(r) == len(TESS_COLS) - 1:
                    r.append("")
                writer.writerow([
                    doc_id, pdf.name, str(args.dpi), "tesseract", args.lang,
                    *r[:len(TESS_COLS)],
                ])
                total_tokens += 1

            print(f"page {page_num}: {len(rows)} rows", file=sys.stderr)

    print(f"wrote {args.out_tsv} ({total_tokens} rows, doc_id={doc_id})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
