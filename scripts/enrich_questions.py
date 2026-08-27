"""Enrich the 18-column question-bank TSV with LLM-generated fields.

Reads outputs/<stem>.filled.tsv (built by build_question_tsv.py), then uses the
Sarvam chat completions API (`sarvam-105b`) to populate:

- `easy_explanation` — a simpler rephrasing of the model answer
- `memory_tip` — a short mnemonic / hint
- `options` — only if the question is genuinely multiple-choice (skipped otherwise)

The script is idempotent: rows that already have real (non-duplicate) values
are left untouched. It checkpoints after each batch so a crash never loses
completed work. When done, it re-emits the sibling .xlsx and .sql outputs so
Supabase ingestion picks up the new columns.

Usage:
    scripts/enrich_questions.py outputs/ilovepdf_merged.filled.tsv \
        --language kannada --workers 3 --batch-size 5

Requires SARVAM_API_KEY in the environment (loaded from .env via the caller).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("enrich")

TARGET_COLUMNS = ("easy_explanation", "memory_tip", "options")
# sarvam-105b is a reasoning model that emits into `reasoning_content` and
# usually truncates before it ever fills `content`. The `-conversations` variant
# is the chat-tuned sibling: streams directly into `content`, ~5x faster,
# comparable Kannada quality for short-form enrichment.
SARVAM_MODEL = "sarvam-105b-conversations"

# ---------------------------------------------------------------------------
# Language-specific prompts. Mirrors the LangPack pattern in build_question_tsv.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptPack:
    system: str
    user_template: str  # {question} {answer} placeholders


PROMPT_PACKS: dict[str, PromptPack] = {
    "kannada": PromptPack(
        system=(
            "You are a Karnataka state-board Kannada language teacher building a "
            "question bank for 10th-standard students. You always respond with a "
            "single valid JSON object and never wrap it in markdown fences."
        ),
        user_template=(
            "Below is a Kannada exam question and its model answer. Produce three fields:\n"
            "1. \"easy_explanation\" — 1-2 sentences in KANNADA that a grade-5 student could\n"
            "   understand. Do NOT just repeat the answer; explain WHY it is correct or what\n"
            "   the concept means.\n"
            "2. \"memory_tip\" — one short KANNADA mnemonic, rhyme, or hook (max ~15 words)\n"
            "   that helps a student recall the answer.\n"
            "3. \"options\" — ONLY populate if the original question is clearly multiple-choice\n"
            "   (has \"ಆಯ್ಕೆಗಳು\" or lettered choices in the stem). Otherwise return an empty\n"
            "   array []. Never invent distractors for subjective questions.\n\n"
            "Return ONLY a JSON object with those three keys.\n\n"
            "Question: {question}\n"
            "Model answer: {answer}\n"
        ),
    ),
    "hindi": PromptPack(
        system=(
            "You are a CBSE Hindi teacher enriching a 10th-grade question bank. "
            "Respond with a single valid JSON object, no markdown fences."
        ),
        user_template=(
            "Below is a Hindi exam question and its model answer. Return JSON with:\n"
            "- \"easy_explanation\": 1-2 sentences in HINDI explaining the concept simply.\n"
            "- \"memory_tip\": one short HINDI mnemonic (max ~15 words).\n"
            "- \"options\": populate only for MCQs, else return [].\n\n"
            "Question: {question}\nModel answer: {answer}\n"
        ),
    ),
    "english": PromptPack(
        system=(
            "You are an ICSE/CBSE teacher enriching a 10th-grade question bank. "
            "Respond with a single valid JSON object, no markdown fences."
        ),
        user_template=(
            "Below is an English exam question and its model answer. Return JSON with:\n"
            "- \"easy_explanation\": 1-2 sentences of plain-English explanation.\n"
            "- \"memory_tip\": one short mnemonic (max ~15 words).\n"
            "- \"options\": populate only for MCQs, else return [].\n\n"
            "Question: {question}\nModel answer: {answer}\n"
        ),
    ),
}


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _needs_enrichment(row: dict[str, str]) -> bool:
    """A row needs enrichment when memory_tip is empty OR easy_explanation is a
    verbatim duplicate of correct_answer (the placeholder we wrote in build_question_tsv)."""
    memory_tip = (row.get("memory_tip") or "").strip()
    easy = (row.get("easy_explanation") or "").strip()
    answer = (row.get("correct_answer") or "").strip()
    if not memory_tip:
        return True
    if not easy or easy == answer:
        return True
    return False


def _looks_like_mcq(text: str) -> bool:
    """Very light heuristic: does the stem carry MCQ markers?"""
    if not text:
        return False
    if re.search(r"\bಆಯ್ಕೆಗಳು\b|\bवि\s*कल्प\b|\bchoose the correct\b", text, re.IGNORECASE):
        return True
    if re.search(r"\([ಅಆaAiI][\.\)]\s+", text):
        return True
    return False


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _extract_json(text: str) -> dict | None:
    text = _strip_json_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


# ---------------------------------------------------------------------------
# Sarvam call
# ---------------------------------------------------------------------------


def _enrich_one(client, pack: PromptPack, row: dict[str, str]) -> dict:
    """Return {easy_explanation, memory_tip, options} for one row.

    Falls back to safe defaults on API/parse failure."""
    question = (row.get("question_text_en") or "").strip()
    answer = (row.get("correct_answer") or "").strip()
    if not question:
        return {}

    user_msg = pack.user_template.format(question=question, answer=answer or "(none)")

    for attempt in range(3):
        try:
            resp = client.chat.completions(
                model=SARVAM_MODEL,
                messages=[
                    {"role": "system", "content": pack.system},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=400,
            )
            raw = resp.choices[0].message.content or ""
            payload = _extract_json(raw)
            if not payload:
                logger.warning("row %s: unparseable JSON on attempt %d", row.get("id") or "?", attempt + 1)
                continue

            easy = str(payload.get("easy_explanation", "")).strip()
            tip = str(payload.get("memory_tip", "")).strip()
            options_field = payload.get("options", [])
            options_str = ""
            if _looks_like_mcq(question) and isinstance(options_field, list) and options_field:
                pieces = []
                for opt in options_field:
                    if isinstance(opt, dict):
                        label = str(opt.get("label", "")).strip()
                        text = str(opt.get("text", "")).strip()
                        pieces.append(f"{label}) {text}" if label else text)
                    elif isinstance(opt, str):
                        pieces.append(opt.strip())
                options_str = " | ".join(p for p in pieces if p)
            return {
                "easy_explanation": easy,
                "memory_tip": tip,
                "options": options_str,
            }
        except Exception as exc:  # noqa: BLE001 — network layer is broad
            logger.warning("row %s: API error on attempt %d: %s", row.get("id") or "?", attempt + 1, exc)
            time.sleep(1.5 * (attempt + 1))

    logger.error("row %s: giving up after retries", row.get("id") or "?")
    return {}


def _write_tsv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in header})


def _write_xlsx(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    try:
        from openpyxl import Workbook
    except ImportError:
        logger.warning("openpyxl not installed; skipping .xlsx regen")
        return
    wb = Workbook()
    ws = wb.active
    ws.title = "questions"
    ws.append(header)
    for row in rows:
        ws.append([row.get(col, "") for col in header])
    wb.save(path)


def _write_sql(sql_path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    """Rewrite the Supabase INSERT statements (schema unchanged, just fresh data)."""
    lines = [
        "-- Auto-generated by scripts/enrich_questions.py",
        "-- Assumes CREATE TABLE from the initial extract_images_and_sql.py run.",
        "",
    ]
    for row in rows:
        cols = ", ".join(f'"{c}"' for c in header)
        values = []
        for col in header:
            val = row.get(col, "")
            if val == "" or val is None:
                values.append("NULL")
            else:
                escaped = str(val).replace("'", "''")
                values.append(f"'{escaped}'")
        lines.append(f"INSERT INTO question_bank ({cols}) VALUES ({', '.join(values)});")
    sql_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tsv", type=Path, help="Path to *.filled.tsv from build_question_tsv.py")
    parser.add_argument("--language", choices=sorted(PROMPT_PACKS), default="kannada")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent Sarvam requests")
    parser.add_argument("--limit", type=int, default=None, help="Only enrich first N rows (debug)")
    parser.add_argument("--force", action="store_true", help="Re-enrich rows even if already filled")
    args = parser.parse_args()

    if not args.tsv.exists():
        logger.error("TSV not found: %s", args.tsv)
        return 1

    from sarvamai import SarvamAI  # imported lazily so --help works without SDK

    client = SarvamAI()  # reads SARVAM_API_KEY from env
    pack = PROMPT_PACKS[args.language]

    with args.tsv.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        header = list(reader.fieldnames or [])
        rows = list(reader)

    for col in TARGET_COLUMNS:
        if col not in header:
            header.append(col)

    todo = [
        (idx, row) for idx, row in enumerate(rows)
        if args.force or _needs_enrichment(row)
    ]
    if args.limit is not None:
        todo = todo[: args.limit]

    logger.info(
        "loaded %d rows; %d need enrichment (language=%s, workers=%d)",
        len(rows), len(todo), args.language, args.workers,
    )
    if not todo:
        logger.info("nothing to do")
        return 0

    completed = 0

    def _work(idx_row):
        idx, row = idx_row
        return idx, _enrich_one(client, pack, row)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_work, item): item for item in todo}
        for fut in as_completed(futures):
            idx, patch = fut.result()
            if patch:
                for k in TARGET_COLUMNS:
                    if k in patch:
                        rows[idx][k] = patch[k]
            completed += 1
            if completed % 5 == 0 or completed == len(todo):
                logger.info("progress: %d / %d", completed, len(todo))
                _write_tsv(args.tsv, header, rows)  # checkpoint

    _write_tsv(args.tsv, header, rows)
    logger.info("wrote enriched TSV: %s", args.tsv)

    xlsx_path = args.tsv.with_suffix(".xlsx")
    if xlsx_path.exists():
        _write_xlsx(xlsx_path, header, rows)
        logger.info("wrote enriched XLSX: %s", xlsx_path)

    sql_path = args.tsv.with_suffix(".sql")
    if sql_path.exists():
        _write_sql(sql_path, header, rows)
        logger.info("wrote enriched SQL: %s", sql_path)

    filled = {col: sum(1 for r in rows if (r.get(col) or "").strip()) for col in TARGET_COLUMNS}
    logger.info("final fill: %s (out of %d rows)", filled, len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
