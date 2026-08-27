"""Build a Question-Bank TSV/XLSX from a Sarvam extraction JSON.

Produces the 18-column schema matching the reference file
Mathematics_Maths-KM-part-8_Class5.xlsx:

  board_id | grade | subject | topic | unit | question_type | question_from |
  marks | difficulty | cognitive_level | question_text_en | options |
  correct_answer | easy_explanation | memory_tip | two_to_five_options |
  two_to_five_correct_answer | diagram_url

Design principles:
  * TIER 1 — universal scrubs: script-agnostic post-processing that fixes
    Sarvam figure captions, orphan page numbers, column markers, etc.
    Applied to every PDF regardless of language.
  * TIER 2 — swappable language pack: script-specific vocabulary (section
    keywords, answer-section header, difficulty words, marks word,
    column-marker chars) is loaded from a small dict. To add a new language
    add ~30 lines to LANG_PACKS below; no parser changes needed.

Usage:
  python scripts/build_question_tsv.py <extraction.json> <out_prefix> \
      [--lang-pack kannada|hindi|english] \
      [--board KARNATAKA_STATE] [--grade 10] [--subject Kannada] \
      [--topic "…"] [--unit "…"] [--question-from LBA]
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# --------------------------------------------------------------------------- #
# 18-column output schema
# --------------------------------------------------------------------------- #

HEADER = [
    "board_id", "grade", "subject", "topic", "unit",
    "question_type", "question_from", "marks", "difficulty",
    "cognitive_level", "question_text_en", "options", "correct_answer",
    "easy_explanation", "memory_tip",
    "two_to_five_options", "two_to_five_correct_answer", "diagram_url",
]


# --------------------------------------------------------------------------- #
# TIER 2 — Language packs (swappable vocabulary)
# --------------------------------------------------------------------------- #

@dataclass
class LangPack:
    name: str
    answer_header_re: re.Pattern           # marks start of answer section
    marks_word_re: re.Pattern              # e.g. "\[\s*N\s*-?\s*(ಅಂಕ|अंक|marks?)\s*\]"
    difficulty_map: dict[str, str]         # source label -> Easy/Medium/Hard
    section_keywords: list[tuple[str, tuple[str, int]]]  # ordered
    column_markers: str                    # e.g. "ಅಆಇಈaAbBcCdD" for stripping trailing "X) "
    noise_line_res: list[re.Pattern] = field(default_factory=list)


def _build_kannada_pack() -> LangPack:
    return LangPack(
        name="kannada",
        answer_header_re=re.compile(r"ಮಾದರಿ\s*ಉತ್ತರಗಳು"),
        marks_word_re=re.compile(r"\[\s*([0-9]+)\s*[-–]?\s*ಅಂಕ\s*\]"),
        difficulty_map={
            "ಸುಲಭ": "Easy",
            "ಸಾಧಾರಣ": "Medium",
            "ಕಠಿಣ": "Hard",
        },
        section_keywords=[
            ("ಹೊಂದಿಸಿ",                  ("Match the Following", 1)),
            ("ಪದಗಳಿಗೆ ಅರ್ಥ",             ("Short Answer",        1)),
            ("ಆವರಣದಲ್ಲಿ ಸೂಚಿಸಿದಂತೆ",     ("Short Answer",        1)),
            ("ಎರಡು ಮೂರು ವಾಕ್ಯ",          ("Short Answer",        2)),
            ("ಒಂದು ವಾಕ್ಯದಲ್ಲಿ",          ("Short Answer",        1)),
            ("ಈ ಕೆಳಗಿನ ಪ್ರಶ್ನೆಗಳಿಗೆ",     ("Long Answer",         3)),
            ("ಯಾರು ಯಾರಿಗೆ",             ("Short Answer",        2)),
            ("ಬಿಟ್ಟ ಸ್ಥಳ",               ("Fill in the Blank",   1)),
            ("ಸೂಕ್ತ ಪದ",                ("Fill in the Blank",   1)),
            ("ಗೆರೆ ಎಳೆದ",               ("Short Answer",        1)),
            ("ವೃತ್ತದ ಒಳಗೆ",              ("Short Answer",        1)),
            ("ದಿಕ್ಕುಗಳ ಹೆಸರ",            ("Short Answer",        1)),
            ("ಪಟ್ಟಿ ಮಾಡಿ",              ("Long Answer",         4)),
            ("ವಿಷದೀಕರಿಸಿ",              ("Long Answer",         5)),
        ],
        column_markers="ಅಆಇಈಉಊಎಏ",
    )


def _build_hindi_pack() -> LangPack:
    return LangPack(
        name="hindi",
        answer_header_re=re.compile(r"(?:आदर्श|मॉडल)\s*उत्तर"),
        marks_word_re=re.compile(r"\[\s*([0-9]+)\s*[-–]?\s*अंक\s*\]"),
        difficulty_map={
            "सरल": "Easy",
            "आसान": "Easy",
            "मध्यम": "Medium",
            "साधारण": "Medium",
            "कठिन": "Hard",
        },
        section_keywords=[
            ("मिलान",                    ("Match the Following", 1)),
            ("अर्थ लिख",                 ("Short Answer",        1)),
            ("एक वाक्य",                 ("Short Answer",        1)),
            ("दो-तीन वाक्य",             ("Short Answer",        2)),
            ("दीर्घ उत्तर",              ("Long Answer",         3)),
            ("रिक्त स्थान",              ("Fill in the Blank",   1)),
        ],
        column_markers="कखगघअआइईउऊ",
    )


def _build_english_pack() -> LangPack:
    return LangPack(
        name="english",
        answer_header_re=re.compile(r"(?:model|sample|answer)\s+(?:answers?|key)", re.I),
        marks_word_re=re.compile(r"\[\s*([0-9]+)\s*[-–]?\s*marks?\s*\]", re.I),
        difficulty_map={
            "easy": "Easy",
            "medium": "Medium",
            "moderate": "Medium",
            "hard": "Hard",
            "difficult": "Hard",
        },
        section_keywords=[
            ("match the following",     ("Match the Following", 1)),
            ("choose the correct",       ("MCQ",                 1)),
            ("multiple choice",          ("MCQ",                 1)),
            ("fill in the blank",        ("Fill in the Blank",   1)),
            ("answer in one sentence",   ("Short Answer",        1)),
            ("answer in brief",          ("Short Answer",        2)),
            ("answer in detail",         ("Long Answer",         5)),
            ("long answer",              ("Long Answer",         5)),
            ("short answer",             ("Short Answer",        2)),
            ("who said to whom",         ("Short Answer",        2)),
        ],
        column_markers="abcdABCD",
    )


LANG_PACKS: dict[str, LangPack] = {
    "kannada": _build_kannada_pack(),
    "hindi": _build_hindi_pack(),
    "english": _build_english_pack(),
}


# --------------------------------------------------------------------------- #
# Regexes (universal — script-agnostic)
# --------------------------------------------------------------------------- #

ROMAN_HEADER_RE = re.compile(
    r"^\s*(?:##\s+)?(I|II|III|IV|V|VI|VII|VIII|IX|X)\.\s*(.+?)\s*$"
)
QUESTION_START_RE = re.compile(r"^\s*([0-9]{1,3})\.\s+(.+?)\s*$", re.MULTILINE)
LO_RE = re.compile(r"\[\s*LO\s*[-\s]*\s*([0-9]+)\s*\]", re.I)
IMG_MD_RE = re.compile(r"!\[[^\]]*\]\(data:image[^)]*\)")


# --------------------------------------------------------------------------- #
# TIER 1 — Universal scrubs (safe for every Sarvam-processed PDF)
# --------------------------------------------------------------------------- #

# Sarvam emits figure captions as [IMAGE] followed by *…description…*
CAPTION_RE = re.compile(r"\[IMAGE\]\s*\*[^*]*\*", re.S)
IMAGE_TOKEN_RE = re.compile(r"\[IMAGE\]")
ASTERISK_WRAPPED_RE = re.compile(r"\*+([^*]+)\*+")
LEADING_DIGIT_DOTS_RE = re.compile(r"^\s*[0-9]{1,3}\.{2,}\s*")  # "8..ಔಷಧ" -> "ಔಷಧ"
TRAILING_DIVIDER_RE = re.compile(r"\s*\*{2,}[\s*]*$")
TRAILING_PAGENO_RE = re.compile(r"(?:\s+[0-9]{1,3}\s*)+$")


def _scrub_question(text: str, pack: LangPack) -> str:
    """Universal cleanup for question_text_en."""
    t = CAPTION_RE.sub(" ", text)                   # figure captions
    t = IMAGE_TOKEN_RE.sub(" ", t)                  # any remaining [IMAGE]
    t = ASTERISK_WRAPPED_RE.sub(r"\1", t)           # *bold* -> bold
    t = pack.marks_word_re.sub("", t)               # leaked "[N-ಅಂಕ]" etc.
    t = LO_RE.sub("", t)                            # leaked "[LO-14]"
    for diff in pack.difficulty_map:
        t = re.sub(rf"\(\s*{re.escape(diff)}\s*\)", "", t)
    t = TRAILING_DIVIDER_RE.sub("", t)
    t = TRAILING_PAGENO_RE.sub("", t)
    # Strip trailing column markers like "ಆ)", "क)", "a)", "b)".
    marker_class = re.escape(pack.column_markers)
    t = re.sub(rf"[\s.,]*[{marker_class}][.)]\s*$", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" .,-*")
    return t


def _scrub_answer(text: str) -> str:
    """Universal cleanup for correct_answer / easy_explanation."""
    t = CAPTION_RE.sub(" ", text)
    t = IMAGE_TOKEN_RE.sub(" ", t)
    t = LEADING_DIGIT_DOTS_RE.sub("", t)            # "8..ಔಷಧ" -> "ಔಷಧ"
    t = ASTERISK_WRAPPED_RE.sub(r"\1", t)
    t = TRAILING_DIVIDER_RE.sub("", t)
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    return t


# --------------------------------------------------------------------------- #
# Text prep
# --------------------------------------------------------------------------- #

def _flatten_tables(md_text: str) -> str:
    """Flatten <table>...</table> to plain lines of `cell  cell` per row."""

    def _flatten(match: re.Match) -> str:
        table = match.group(0)
        rows = re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", table, re.I)
        out_lines: list[str] = []
        for row in rows:
            cells = re.findall(r"<t[hd][^>]*>([\s\S]*?)</t[hd]>", row, re.I)
            cleaned = [
                html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in cells
            ]
            line = "  ".join(c for c in cleaned if c)
            if line:
                out_lines.append(line)
        return "\n".join(out_lines) + "\n"

    return re.sub(r"<table[\s\S]*?</table>", _flatten, md_text, flags=re.I)


def _prep_page_text(page: dict) -> str:
    text = page.get("text") or ""
    text = IMG_MD_RE.sub("[IMAGE]", text)
    return _flatten_tables(text)


def _classify_section(title: str, pack: LangPack) -> tuple[str, int]:
    for key, mapping in pack.section_keywords:
        if key.lower() in title.lower():
            return mapping
    return "Short Answer", 1


def _split_pages(pages: list[dict], pack: LangPack) -> tuple[list[dict], list[dict]]:
    for i, p in enumerate(pages):
        if pack.answer_header_re.search(p.get("text") or ""):
            return pages[:i], pages[i:]
    return pages, []


# --------------------------------------------------------------------------- #
# Question parser
# --------------------------------------------------------------------------- #

def parse_questions(pages: list[dict], pack: LangPack) -> list[dict]:
    q_pages, _ = _split_pages(pages, pack)
    questions: dict[int, dict] = {}

    current_section: str | None = None
    current_qtype = "Short Answer"
    current_marks = 1
    section_seen = False

    buffered: list[str] = []
    active_qnum: int | None = None
    active_page = 0
    active_qtype = current_qtype
    active_marks = current_marks
    active_section = current_section

    def flush() -> None:
        nonlocal buffered, active_qnum
        if active_qnum is None or not buffered:
            buffered = []
            active_qnum = None
            return
        raw = " ".join(s.strip() for s in buffered if s.strip())
        questions[active_qnum] = {
            "question_number": active_qnum,
            "page_number": active_page,
            "section": active_section,
            "question_type": active_qtype,
            "marks": active_marks,
            "raw": raw,
        }
        buffered = []
        active_qnum = None

    def start_question(qnum: int, first_text: str, page_num: int) -> None:
        nonlocal active_qnum, active_page, active_section, active_qtype, active_marks
        flush()
        active_qnum = qnum
        active_page = page_num
        active_section = current_section
        active_qtype = current_qtype
        active_marks = current_marks
        buffered.append(first_text)

    for page in q_pages:
        page_num = page["page_number"]
        flat = _prep_page_text(page)
        lines = flat.splitlines()

        for raw_line in lines:
            line = raw_line.rstrip()

            m = ROMAN_HEADER_RE.match(line)
            if m and len(m.group(2)) > 3:
                flush()
                current_section = m.group(1)
                section_seen = True
                title = m.group(2)
                current_qtype, current_marks = _classify_section(title, pack)
                mm = pack.marks_word_re.search(title) or pack.marks_word_re.search(line)
                if mm:
                    current_marks = int(mm.group(1))
                inline_q = re.search(r"([0-9]{1,3})\.\s+(.+)", title)
                if inline_q:
                    start_question(int(inline_q.group(1)), inline_q.group(2), page_num)
                continue

            if not section_seen:
                continue

            mm = pack.marks_word_re.search(line)
            if mm and not QUESTION_START_RE.match(line):
                current_marks = int(mm.group(1))
                # A marks header inside an active question overrides that
                # question's marks (e.g. sub-part with its own [5-ಅಂಕ]).
                if active_qnum is not None:
                    active_marks = current_marks

            qm = QUESTION_START_RE.match(line)
            if qm:
                start_question(int(qm.group(1)), qm.group(2), page_num)
                continue

            if active_qnum is not None:
                buffered.append(line)

    flush()
    return sorted(questions.values(), key=lambda q: q["question_number"])


# --------------------------------------------------------------------------- #
# Answer parser (range-aware)
# --------------------------------------------------------------------------- #

def parse_answers(pages: list[dict], pack: LangPack) -> dict[int, str]:
    _, answer_pages = _split_pages(pages, pack)

    answers: dict[int, list[str]] = {}
    current: int | None = None
    pending_range: tuple[int, int] | None = None
    range_buffer: list[str] = []

    NOISE = re.compile(r"^(?:##\s*)?(?:[0-9]{1,3}\s*$|\*{3,}.*)$")
    SKIP = re.compile(r"^\[IMAGE\]$")
    ANS_START_RE = re.compile(r"^\s*([0-9]{1,3})\.\s*(.*)$")

    def unwrap(s: str) -> str:
        return re.sub(r"^\*+\s*|\s*\*+$", "", s).strip()

    def flush_range() -> None:
        nonlocal pending_range, range_buffer
        if pending_range is None or not range_buffer:
            pending_range = None
            range_buffer = []
            return
        s, e = pending_range
        combined = " ".join(range_buffer)
        tokens = [
            t.strip(" ,.*") for t in re.split(r"[,،]", combined)
            if t.strip(" ,.*")
        ]
        if len(tokens) == (e - s + 1):
            for i, tok in enumerate(tokens):
                answers[s + i] = [tok]
        else:
            for i in range(s, e + 1):
                answers.setdefault(i, []).append(combined)
        pending_range = None
        range_buffer = []

    # Also match "ಆ." / "ಅ." / "क." / "a." / "A." prefixed range headers.
    marker_class = re.escape(pack.column_markers)
    ALT_RANGE_RE = re.compile(
        rf"^[{marker_class}]\.\s*([0-9]{{1,3}})\s*(?:ರಿಂದ|to|se|-)\s*([0-9]{{1,3}})\s*$",
        re.I,
    )
    INLINE_RANGE_RE = re.compile(
        r"^\s*(?:ರಿಂದ|to|se|-)\s*([0-9]{1,3})\s*$"
    )

    for page in answer_pages:
        flat = _prep_page_text(page)
        for line in flat.splitlines():
            line = line.rstrip()
            stripped = unwrap(line.strip())
            if not stripped:
                continue
            if SKIP.match(stripped):
                continue
            if NOISE.match(stripped) or pack.answer_header_re.match(stripped):
                flush_range()
                continue

            m = ANS_START_RE.match(stripped)
            if m:
                flush_range()
                start = int(m.group(1))
                rest = m.group(2).strip()

                m2 = INLINE_RANGE_RE.match(rest)
                if m2:
                    pending_range = (start, int(m2.group(1)))
                    current = None
                    continue

                current = start
                answers.setdefault(current, [])
                if rest:
                    answers[current].append(rest)
                continue

            m3 = ALT_RANGE_RE.match(stripped)
            if m3:
                flush_range()
                pending_range = (int(m3.group(1)), int(m3.group(2)))
                current = None
                continue

            if pending_range is not None:
                range_buffer.append(stripped)
                continue

            if current is not None:
                answers[current].append(stripped)

    flush_range()
    return {n: "\n".join(parts).strip() for n, parts in answers.items()}


# --------------------------------------------------------------------------- #
# Row assembly
# --------------------------------------------------------------------------- #

def _canonical_difficulty(raw_text: str, pack: LangPack) -> str | None:
    for src, canon in pack.difficulty_map.items():
        if re.search(rf"\({re.escape(src)}\)", raw_text) or re.search(
            rf"\b{re.escape(src)}\b", raw_text, re.I
        ):
            return canon
    return None


def build_rows(
    data: dict, pack: LangPack, meta: dict[str, str],
) -> list[list[str]]:
    pages = data["pages"]
    questions = parse_questions(pages, pack)
    answers = parse_answers(pages, pack)

    rows: list[list[str]] = [HEADER]
    for q in questions:
        n = q["question_number"]
        raw = q["raw"]
        difficulty = _canonical_difficulty(raw, pack) or ""
        clean_q = _scrub_question(raw, pack)
        raw_answer = answers.get(n, "")
        clean_a = _scrub_answer(raw_answer)

        rows.append([
            meta["board_id"],
            meta["grade"],
            meta["subject"],
            meta["topic"],
            meta["unit"],
            q["question_type"],
            meta["question_from"],
            str(q["marks"]),
            difficulty,
            "",                 # cognitive_level
            clean_q,
            "",                 # options
            clean_a,
            clean_a,            # easy_explanation
            "",                 # memory_tip
            "",                 # two_to_five_options
            "",                 # two_to_five_correct_answer
            "",                 # diagram_url
        ])
    return rows


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("out_prefix", help="Writes <prefix>.tsv and <prefix>.xlsx")
    ap.add_argument("--lang-pack", default="kannada", choices=list(LANG_PACKS))
    ap.add_argument("--board", default="KARNATAKA_STATE")
    ap.add_argument("--grade", default="10")
    ap.add_argument("--subject", default="Kannada")
    ap.add_argument("--topic", default="ಪುಟ್ಟಜ್ಜಿ ಪುಟ್ಟಜ್ಜಿ ಕಥೆ ಹೇಳು")
    ap.add_argument("--unit", default="Kannada KM part 1 - Section 1")
    ap.add_argument("--question-from", default="LBA")
    args = ap.parse_args()

    pack = LANG_PACKS[args.lang_pack]
    data = json.loads(Path(args.json_path).read_text())

    meta = {
        "board_id": args.board,
        "grade": args.grade,
        "subject": args.subject,
        "topic": args.topic,
        "unit": args.unit,
        "question_from": args.question_from,
    }

    rows = build_rows(data, pack, meta)

    tsv_path = f"{args.out_prefix}.tsv"
    with open(tsv_path, "w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writerows(rows)

    xlsx_path = None
    try:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Questions"
        for r in rows:
            ws.append(r)
        xlsx_path = f"{args.out_prefix}.xlsx"
        wb.save(xlsx_path)
    except Exception as exc:  # pragma: no cover
        print(f"xlsx write skipped: {exc}", file=sys.stderr)

    n_qs = len(rows) - 1
    n_ans = sum(1 for r in rows[1:] if r[12].strip())
    print(
        f"wrote {tsv_path}" + (f" + {xlsx_path}" if xlsx_path else "")
        + f"  (lang_pack={pack.name}, {n_qs} questions, {n_ans} with answers)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
