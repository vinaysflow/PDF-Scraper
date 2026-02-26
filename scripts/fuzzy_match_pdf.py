#!/usr/bin/env python3
"""Fuzzy-match OCR extraction against native PDF text layer.

Extracts the native text from each PDF page (via PyMuPDF) and compares
it against the OCR extraction JSON.  Reports per-page and aggregate
similarity metrics, plus a Unicode-script analysis to flag garbled output.

Usage:
    python scripts/fuzzy_match_pdf.py \
        --pdf "/path/to/original.pdf" \
        --extraction "/path/to/extraction.json" \
        [--out report.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF


# ── Metrics ──────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return " ".join(
        text.replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .replace("\r\n", "\n")
        .replace("\n", " ")
        .split()
    ).strip()


def _levenshtein(a, b) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


def char_similarity(ref: str, hyp: str) -> float | None:
    ref_n = list(_normalize(ref))
    hyp_n = list(_normalize(hyp))
    if not ref_n:
        return None
    cer = _levenshtein(ref_n, hyp_n) / len(ref_n)
    return max(0.0, round(1.0 - cer, 4))


def word_similarity(ref: str, hyp: str) -> float | None:
    ref_w = _normalize(ref).split()
    hyp_w = _normalize(hyp).split()
    if not ref_w:
        return None
    wer = _levenshtein(ref_w, hyp_w) / len(ref_w)
    return max(0.0, round(1.0 - wer, 4))


# ── Unicode script analysis ─────────────────────────────────────────

KANNADA_RANGE = range(0x0C80, 0x0CFF + 1)
DEVANAGARI_RANGE = range(0x0900, 0x09FF + 1)

SCRIPT_BUCKETS = {
    "Kannada":    lambda cp: cp in KANNADA_RANGE,
    "Devanagari": lambda cp: cp in DEVANAGARI_RANGE,
    "Latin":      lambda cp: unicodedata.category(chr(cp)).startswith("L") and cp < 0x0250,
    "Digit":      lambda cp: unicodedata.category(chr(cp)).startswith("N"),
    "Punctuation": lambda cp: unicodedata.category(chr(cp)).startswith("P"),
    "Space":      lambda cp: unicodedata.category(chr(cp)) in ("Zs", "Zl", "Zp") or chr(cp) in " \t\n",
}


def classify_char(ch: str) -> str:
    cp = ord(ch)
    for name, test in SCRIPT_BUCKETS.items():
        if test(cp):
            return name
    cat = unicodedata.category(ch)
    try:
        script = unicodedata.name(ch, "").split()[0]
    except Exception:
        script = f"U+{cp:04X}"
    return script if script else f"Other({cat})"


def script_distribution(text: str) -> dict[str, int]:
    counts: Counter = Counter()
    for ch in text:
        counts[classify_char(ch)] += 1
    return dict(counts.most_common())


def kannada_purity(text: str) -> float:
    """Fraction of non-space, non-digit, non-punctuation chars that are Kannada."""
    total = 0
    kan = 0
    for ch in text:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if cat.startswith(("Z", "N", "P")) or ch in " \t\n\r":
            continue
        total += 1
        if cp in KANNADA_RANGE:
            kan += 1
    return round(kan / total, 4) if total else 0.0


# ── PDF native text extraction ──────────────────────────────────────

def extract_native_text(pdf_path: str) -> dict[int, str]:
    doc = fitz.open(pdf_path)
    pages = {}
    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text("text")
        pages[i + 1] = text
    doc.close()
    return pages


# ── Load extraction JSON ────────────────────────────────────────────

def load_extraction(path: str) -> dict[int, str]:
    with open(path) as f:
        data = json.load(f)
    return {int(p["page_number"]): p.get("text", "") for p in data.get("pages", [])}


# ── Evaluation ──────────────────────────────────────────────────────

def evaluate(
    pdf_path: str,
    extraction_path: str,
) -> dict:
    native = extract_native_text(pdf_path)
    ocr = load_extraction(extraction_path)

    per_page = []
    char_sims = []
    word_sims = []
    purity_scores = []
    native_purity_scores = []

    common_pages = sorted(set(native) & set(ocr))

    for pn in common_pages:
        native_text = native[pn]
        ocr_text = ocr[pn]

        cs = char_similarity(native_text, ocr_text)
        ws = word_similarity(native_text, ocr_text)
        kp_ocr = kannada_purity(ocr_text)
        kp_native = kannada_purity(native_text)
        ocr_scripts = script_distribution(ocr_text)

        entry = {
            "page": pn,
            "native_chars": len(native_text),
            "ocr_chars": len(ocr_text),
            "char_similarity": cs,
            "word_similarity": ws,
            "kannada_purity_ocr": kp_ocr,
            "kannada_purity_native": kp_native,
            "ocr_script_distribution": ocr_scripts,
        }
        per_page.append(entry)

        if cs is not None:
            char_sims.append(cs)
        if ws is not None:
            word_sims.append(ws)
        purity_scores.append(kp_ocr)
        native_purity_scores.append(kp_native)

    def _stats(vals):
        if not vals:
            return {}
        return {
            "mean": round(statistics.mean(vals), 4),
            "median": round(statistics.median(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "stdev": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
        }

    # Identify degradation: pages where purity drops below 50%
    degraded = [p for p in per_page if p["kannada_purity_ocr"] < 0.50]
    clean = [p for p in per_page if p["kannada_purity_ocr"] >= 0.80]

    aggregate = {
        "total_pages": len(common_pages),
        "char_similarity": _stats(char_sims),
        "word_similarity": _stats(word_sims),
        "kannada_purity_ocr": _stats(purity_scores),
        "kannada_purity_native": _stats(native_purity_scores),
        "clean_pages_count": len(clean),
        "degraded_pages_count": len(degraded),
        "degraded_pages": [p["page"] for p in degraded],
    }

    return {
        "aggregate": aggregate,
        "per_page": per_page,
    }


# ── CLI / main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", required=True, help="Path to original PDF")
    parser.add_argument("--extraction", required=True, help="Path to extraction JSON")
    parser.add_argument("--out", default=None, help="Write JSON report to this path")
    args = parser.parse_args()

    if not Path(args.pdf).exists():
        print(f"Error: PDF not found: {args.pdf}", file=sys.stderr)
        return 1
    if not Path(args.extraction).exists():
        print(f"Error: extraction JSON not found: {args.extraction}", file=sys.stderr)
        return 1

    print(f"Comparing OCR extraction vs native PDF text...\n")
    result = evaluate(args.pdf, args.extraction)

    agg = result["aggregate"]
    pages = result["per_page"]

    # ── Summary ──
    print(f"Total pages compared: {agg['total_pages']}")
    print(f"Clean pages (Kannada purity >= 80%): {agg['clean_pages_count']}")
    print(f"Degraded pages (Kannada purity < 50%): {agg['degraded_pages_count']}")
    print()

    cs = agg["char_similarity"]
    ws = agg["word_similarity"]
    kp = agg["kannada_purity_ocr"]
    kpn = agg["kannada_purity_native"]

    print("── Aggregate Metrics ──")
    if cs:
        print(f"  Char Similarity (OCR vs Native):  mean={cs['mean']}  median={cs['median']}  min={cs['min']}  max={cs['max']}")
    if ws:
        print(f"  Word Similarity (OCR vs Native):  mean={ws['mean']}  median={ws['median']}  min={ws['min']}  max={ws['max']}")
    if kp:
        print(f"  Kannada Purity (OCR output):      mean={kp['mean']}  median={kp['median']}  min={kp['min']}  max={kp['max']}")
    if kpn:
        print(f"  Kannada Purity (native PDF text):  mean={kpn['mean']}  median={kpn['median']}  min={kpn['min']}  max={kpn['max']}")
    print()

    # ── Per-page detail (first 5, worst 5) ──
    print("── First 5 Pages ──")
    for p in pages[:5]:
        print(f"  Page {p['page']:3d}: char_sim={p['char_similarity']}  word_sim={p['word_similarity']}  "
              f"kan_purity={p['kannada_purity_ocr']}  native_purity={p['kannada_purity_native']}  "
              f"ocr_len={p['ocr_chars']}  native_len={p['native_chars']}")
    print()

    sorted_by_purity = sorted(pages, key=lambda x: x["kannada_purity_ocr"])
    print("── 5 Worst Pages (by Kannada Purity) ──")
    for p in sorted_by_purity[:5]:
        top_scripts = list(p["ocr_script_distribution"].items())[:5]
        scripts_str = ", ".join(f"{s}:{c}" for s, c in top_scripts)
        print(f"  Page {p['page']:3d}: kan_purity={p['kannada_purity_ocr']}  char_sim={p['char_similarity']}  "
              f"scripts=[{scripts_str}]")
    print()

    # ── Degradation trend ──
    print("── Degradation Trend (every 10th page) ──")
    for p in pages:
        if p["page"] % 10 == 1 or p["page"] == pages[-1]["page"]:
            print(f"  Page {p['page']:3d}: kan_purity={p['kannada_purity_ocr']}  char_sim={p['char_similarity']}  word_sim={p['word_similarity']}")
    print()

    if agg["degraded_pages"]:
        print(f"Degraded page numbers: {agg['degraded_pages']}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nFull report written to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
