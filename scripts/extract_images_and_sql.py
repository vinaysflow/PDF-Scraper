"""Extract PDF figures to disk + emit a Supabase-ready SQL file.

Runs in three phases:
  1. PyMuPDF extracts every embedded image from the PDF, saves as .png
     under <out_dir>/<stem>_images/pageN_figM.png.
  2. Reads the existing question-bank TSV (from build_question_tsv.py) and
     matches each question to figures on the same page (fills diagram_url).
  3. Writes a .sql file with CREATE TABLE + one INSERT per question row.

Usage:
  python scripts/extract_images_and_sql.py <pdf_path> <tsv_path> <out_prefix> \
      [--table questions_bank] [--url-prefix ./]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Allow running as `python scripts/foo.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.figure_extract import extract_figures  # noqa: E402

# Same 18-column schema as build_question_tsv.py
HEADER = [
    "board_id", "grade", "subject", "topic", "unit",
    "question_type", "question_from", "marks", "difficulty",
    "cognitive_level", "question_text_en", "options", "correct_answer",
    "easy_explanation", "memory_tip",
    "two_to_five_options", "two_to_five_correct_answer", "diagram_url",
]

# Postgres type per column (all TEXT except grade/marks which are integers).
COL_TYPES = {
    "grade": "INT",
    "marks": "INT",
}


def _pg_col(col: str) -> str:
    return f'"{col}" {COL_TYPES.get(col, "TEXT")}'


def _sql_literal(v: str, col: str) -> str:
    """Format a value as a Postgres SQL literal."""
    if v is None or v == "":
        return "NULL"
    if COL_TYPES.get(col) == "INT":
        try:
            return str(int(v))
        except ValueError:
            return "NULL"
    # Escape single quotes; keep everything else including newlines.
    escaped = v.replace("'", "''")
    return f"'{escaped}'"


DECORATIVE_MIN_BYTES = 5_000  # skip <5KB PNGs — decorative marks, not figures


def extract_and_save_images(pdf_path: Path, images_dir: Path) -> dict[int, list[str]]:
    """Extract every figure to <images_dir>/pageN_figM.png; return page→[paths].

    Skips very small images (< DECORATIVE_MIN_BYTES) which are typically
    decorative marks like footer separators or answer-key stamps rather than
    real illustrations.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    figures = extract_figures(pdf_path)

    counters: dict[int, int] = {}
    by_page: dict[int, list[str]] = {}

    for fig in figures:
        page = fig["page_number"]
        counters[page] = counters.get(page, 0) + 1
        name = f"page{page}_fig{counters[page]}.png"
        out = images_dir / name
        fig["image"].save(out, "PNG")
        if out.stat().st_size < DECORATIVE_MIN_BYTES:
            out.unlink()
            counters[page] -= 1
            continue
        by_page.setdefault(page, []).append(str(out))

    return by_page


def guess_page_for_row(row_idx: int, total_rows: int) -> int | None:
    """Fallback if we can't infer the page from the row.

    The TSV doesn't currently persist page_number per row, so we return None
    and the caller will leave diagram_url empty unless a mapping is supplied.
    """
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_path")
    ap.add_argument("tsv_path", help="Existing 18-col TSV from build_question_tsv.py")
    ap.add_argument("out_prefix", help="Prefix; writes <prefix>.filled.tsv and <prefix>.sql")
    ap.add_argument("--table", default="questions_bank")
    ap.add_argument(
        "--url-prefix", default="./",
        help="Prefix prepended to each image filename in diagram_url "
             "(e.g. https://xxx.supabase.co/storage/v1/object/public/question-images/)",
    )
    ap.add_argument(
        "--page-map",
        help="Optional JSON file: {question_number: page_number}. If omitted, "
             "we try to infer from the extraction JSON (see --extraction).",
    )
    ap.add_argument(
        "--extraction",
        help="Optional path to the extraction JSON (used to derive page_number "
             "per question by matching question numbers).",
    )
    args = ap.parse_args()

    pdf = Path(args.pdf_path)
    tsv = Path(args.tsv_path)
    out_prefix = args.out_prefix
    if not pdf.exists():
        print(f"pdf not found: {pdf}", file=sys.stderr)
        return 1
    if not tsv.exists():
        print(f"tsv not found: {tsv}", file=sys.stderr)
        return 1

    # 1. Extract images to disk
    images_dir = Path(f"{out_prefix}_images")
    by_page = extract_and_save_images(pdf, images_dir)
    total_imgs = sum(len(v) for v in by_page.values())
    print(f"extracted {total_imgs} images to {images_dir}/", file=sys.stderr)

    # 2. Load TSV
    with open(tsv) as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    header = rows[0]
    if header != HEADER:
        print(f"warning: TSV header does not exactly match 18-col schema", file=sys.stderr)

    # 3. Build question_number → page_number map using the same parser as
    #    build_question_tsv.py (handles tables + section boundaries correctly).
    q_to_page: dict[int, int] = {}
    if args.extraction:
        import json
        from scripts.build_question_tsv import (  # noqa: E402
            LANG_PACKS, parse_questions, _split_pages,
        )
        data = json.loads(Path(args.extraction).read_text())
        pack = LANG_PACKS["kannada"]
        # parse_questions returns only question-page questions; answer pages
        # are already excluded via _split_pages.
        for q in parse_questions(data["pages"], pack):
            q_to_page[q["question_number"]] = q["page_number"]

    # 4. Fill diagram_url on rows whose question sits on a page with figures.
    #    The 18-col TSV doesn't carry question_number, so we use row_index+1
    #    as the question_number (rows are already sorted by question_number
    #    by build_question_tsv.py).
    for i, r in enumerate(rows[1:], start=1):
        qn = i
        page = q_to_page.get(qn)
        if page and page in by_page:
            # Use the first figure on that page (multi-figure pages can be
            # split further later).
            fname = Path(by_page[page][0]).name
            r[HEADER.index("diagram_url")] = f"{args.url_prefix}{fname}"

    # 5. Write the enriched TSV
    filled_tsv = f"{out_prefix}.filled.tsv"
    with open(filled_tsv, "w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writerows(rows)
    print(f"wrote {filled_tsv}", file=sys.stderr)

    # 6. Emit SQL
    sql_path = f"{out_prefix}.sql"
    cols_sql = ",\n  ".join(_pg_col(c) for c in HEADER)
    create_stmt = (
        f"-- Auto-generated by extract_images_and_sql.py\n"
        f"CREATE TABLE IF NOT EXISTS {args.table} (\n"
        f"  id BIGSERIAL PRIMARY KEY,\n"
        f"  {cols_sql},\n"
        f"  created_at TIMESTAMPTZ DEFAULT NOW()\n"
        f");\n\n"
    )

    col_list_sql = ", ".join(f'"{c}"' for c in HEADER)
    insert_lines = []
    for r in rows[1:]:
        values = ", ".join(_sql_literal(v, c) for v, c in zip(r, HEADER))
        insert_lines.append(f"INSERT INTO {args.table} ({col_list_sql}) VALUES ({values});")

    with open(sql_path, "w") as fh:
        fh.write(create_stmt)
        fh.write("\n".join(insert_lines))
        fh.write("\n")

    print(
        f"wrote {sql_path}  ({len(rows)-1} INSERT rows, table={args.table})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
