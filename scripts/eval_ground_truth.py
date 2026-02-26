#!/usr/bin/env python3
"""Evaluate extraction accuracy against page-level ground truth.

Compares an extraction result JSON to a ground-truth JSON and reports
per-page WER similarity and CER, with aggregate statistics and
threshold-based pass/fail exit codes.

Ground-truth formats accepted:

  Format A (page-number -> text map):
    { "1": "reference text for page 1", "2": "..." }

  Format B (pages list, same shape as extraction output):
    { "pages": [ {"page_number": 1, "text": "..."}, ... ] }

Usage:

  python scripts/eval_ground_truth.py \\
      --extraction output.json \\
      --ground-truth gt.json \\
      --min-wer-sim 0.90 \\
      --max-cer 0.10 \\
      --out report.json

Exit codes:
  0  All thresholds passed.
  1  One or more thresholds failed.
  2  Invalid input (missing files, bad JSON, no overlapping pages).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Collapse whitespace and lowercase for comparison."""
    normalized = (
        text.replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .replace("\r\n", "\n")
        .replace("\n", " ")
    )
    return " ".join(normalized.split()).strip().lower()


def _levenshtein(a, b) -> int:
    if a == b:
        return 0
    if len(a) == 0:
        return len(b)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


def wer_similarity(reference: str, hypothesis: str) -> float | None:
    """Word-level similarity = 1 - WER. None if reference is empty."""
    ref_words = _normalize(reference).split()
    hyp_words = _normalize(hypothesis).split()
    if not ref_words:
        return None
    wer = _levenshtein(ref_words, hyp_words) / len(ref_words)
    return max(0.0, 1.0 - wer)


def character_error_rate(reference: str, hypothesis: str) -> float | None:
    """Character-level error rate. None if reference is empty."""
    ref_chars = list(_normalize(reference))
    hyp_chars = list(_normalize(hypothesis))
    if not ref_chars:
        return None
    return _levenshtein(ref_chars, hyp_chars) / len(ref_chars)


def char_similarity(reference: str, hypothesis: str) -> float | None:
    cer = character_error_rate(reference, hypothesis)
    if cer is None:
        return None
    return max(0.0, 1.0 - cer)


# ---------------------------------------------------------------------------
# Ground-truth loading
# ---------------------------------------------------------------------------

def load_extraction_pages(path: Path) -> dict[int, str]:
    """Load extraction JSON and return {page_number: text}."""
    with open(path) as f:
        data = json.load(f)
    pages = data.get("pages", [])
    return {int(p["page_number"]): p.get("text", "") for p in pages}


def load_ground_truth(path: Path) -> dict[int, str]:
    """Load ground-truth JSON (Format A or B) and return {page_number: text}."""
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict) and "pages" in data and isinstance(data["pages"], list):
        return {int(p["page_number"]): p.get("text", "") for p in data["pages"]}

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            try:
                result[int(key)] = str(value)
            except (ValueError, TypeError):
                continue
        return result

    raise ValueError("Ground-truth JSON must be a dict (page-number keys or {pages: [...]}).")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_pages(
    extracted: dict[int, str],
    ground_truth: dict[int, str],
) -> tuple[list[dict], dict]:
    """Compare extracted text to ground truth page-by-page.

    Returns (per_page_results, aggregate_stats).
    """
    matched_pages = sorted(set(extracted) & set(ground_truth))
    missing_in_extraction = sorted(set(ground_truth) - set(extracted))
    missing_in_gt = sorted(set(extracted) - set(ground_truth))

    per_page: list[dict] = []
    wer_sims: list[float] = []
    cers: list[float] = []
    char_sims: list[float] = []

    for pn in matched_pages:
        ref = ground_truth[pn]
        hyp = extracted[pn]
        ws = wer_similarity(ref, hyp)
        cer = character_error_rate(ref, hyp)
        cs = char_similarity(ref, hyp)

        entry = {
            "page_number": pn,
            "ref_chars": len(ref),
            "hyp_chars": len(hyp),
            "wer_similarity": round(ws, 4) if ws is not None else None,
            "cer": round(cer, 4) if cer is not None else None,
            "char_similarity": round(cs, 4) if cs is not None else None,
        }
        per_page.append(entry)
        if ws is not None:
            wer_sims.append(ws)
        if cer is not None:
            cers.append(cer)
        if cs is not None:
            char_sims.append(cs)

    def _stats(values: list[float]) -> dict:
        if not values:
            return {"mean": None, "median": None, "min": None, "max": None}
        return {
            "mean": round(statistics.mean(values), 4),
            "median": round(statistics.median(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }

    aggregate = {
        "matched_pages": len(matched_pages),
        "missing_in_extraction": missing_in_extraction,
        "missing_in_ground_truth": missing_in_gt,
        "wer_similarity": _stats(wer_sims),
        "cer": _stats(cers),
        "char_similarity": _stats(char_sims),
    }

    return per_page, aggregate


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Evaluate extraction accuracy against page-level ground truth.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--extraction", required=True, help="Path to extraction result JSON.")
    p.add_argument("--ground-truth", required=True, help="Path to ground-truth JSON.")
    p.add_argument(
        "--min-wer-sim", type=float, default=0.90,
        help="Minimum mean WER similarity to pass (default: 0.90).",
    )
    p.add_argument(
        "--max-cer", type=float, default=0.10,
        help="Maximum mean CER to pass (default: 0.10).",
    )
    p.add_argument(
        "--out", default=None,
        help="Write detailed JSON report to this path (optional).",
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    extraction_path = Path(args.extraction)
    gt_path = Path(args.ground_truth)

    if not extraction_path.exists():
        print(f"Error: extraction file not found: {extraction_path}", file=sys.stderr)
        return 2
    if not gt_path.exists():
        print(f"Error: ground-truth file not found: {gt_path}", file=sys.stderr)
        return 2

    try:
        extracted = load_extraction_pages(extraction_path)
    except Exception as e:
        print(f"Error loading extraction JSON: {e}", file=sys.stderr)
        return 2

    try:
        ground_truth = load_ground_truth(gt_path)
    except Exception as e:
        print(f"Error loading ground-truth JSON: {e}", file=sys.stderr)
        return 2

    if not ground_truth:
        print("Error: ground-truth has no pages.", file=sys.stderr)
        return 2

    per_page, aggregate = evaluate_pages(extracted, ground_truth)

    if aggregate["matched_pages"] == 0:
        print("Error: no overlapping pages between extraction and ground truth.", file=sys.stderr)
        return 2

    # --- Human-readable summary ---
    print(f"Evaluation: {extraction_path.name} vs {gt_path.name}")
    print(f"  Matched pages:          {aggregate['matched_pages']}")
    if aggregate["missing_in_extraction"]:
        print(f"  Missing in extraction:  {aggregate['missing_in_extraction']}")
    if aggregate["missing_in_ground_truth"]:
        print(f"  Missing in ground truth:{aggregate['missing_in_ground_truth']}")
    print()

    ws = aggregate["wer_similarity"]
    cs = aggregate["char_similarity"]
    cr = aggregate["cer"]
    print(f"  WER Similarity:  mean={ws['mean']}  median={ws['median']}  min={ws['min']}  max={ws['max']}")
    print(f"  Char Similarity: mean={cs['mean']}  median={cs['median']}  min={cs['min']}  max={cs['max']}")
    print(f"  CER:             mean={cr['mean']}  median={cr['median']}  min={cr['min']}  max={cr['max']}")
    print()

    below_wer = [p for p in per_page if p["wer_similarity"] is not None and p["wer_similarity"] < args.min_wer_sim]
    above_cer = [p for p in per_page if p["cer"] is not None and p["cer"] > args.max_cer]
    if below_wer:
        print(f"  Pages below --min-wer-sim {args.min_wer_sim}:")
        for p in below_wer:
            print(f"    Page {p['page_number']}: wer_sim={p['wer_similarity']}")
    if above_cer:
        print(f"  Pages above --max-cer {args.max_cer}:")
        for p in above_cer:
            print(f"    Page {p['page_number']}: cer={p['cer']}")

    # --- Threshold check ---
    passed = True
    if ws["mean"] is not None and ws["mean"] < args.min_wer_sim:
        print(f"\n  FAIL: mean WER similarity {ws['mean']} < {args.min_wer_sim}")
        passed = False
    if cr["mean"] is not None and cr["mean"] > args.max_cer:
        print(f"\n  FAIL: mean CER {cr['mean']} > {args.max_cer}")
        passed = False

    if passed:
        print("\n  PASS: all thresholds met.")

    # --- Optional JSON report ---
    if args.out:
        report = {
            "extraction_file": str(extraction_path),
            "ground_truth_file": str(gt_path),
            "thresholds": {
                "min_wer_similarity": args.min_wer_sim,
                "max_cer": args.max_cer,
            },
            "passed": passed,
            "aggregate": aggregate,
            "pages": per_page,
        }
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  Report written to {out_path}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
