"""LLM enrichment for question segments using GPT-4o.

Sends batched question segments to the LLM and returns structured metadata:
question type, marks, topic, difficulty, options (MCQ), and sub-parts.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENRICHMENT_MODEL = os.environ.get("ENRICHMENT_MODEL", "gpt-4o-mini")
ENRICHMENT_TIMEOUT = 60
ENRICHMENT_MAX_RETRIES = 2
ENRICHMENT_BATCH_SIZE = 15  # questions per API call


def _is_configured() -> bool:
    """Check if OpenAI API key is available."""
    return bool(os.environ.get("OPENAI_API_KEY"))


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert exam paper analyzer. Given a list of questions extracted from \
an exam paper, return a JSON array where each element contains structured metadata \
for the corresponding question.

For each question, return:
{
  "question_number": <int>,
  "question_type": "<mcq|short_answer|long_answer|proof|construction>",
  "marks": <int or null>,
  "topic": "<subject topic, e.g. Real Numbers, Polynomials, Triangles, Trigonometry>",
  "difficulty": "<easy|medium|hard>",
  "options": [{"label": "A", "text": "..."}, ...] (only for MCQs, empty list otherwise),
  "sub_parts": [{"label": "a", "text": "...", "marks": <int or null>}, ...] (if multi-part),
  "requires_figure": <true|false>
}

Rules:
- For MCQs, extract all options (A, B, C, D) from the question text.
- If the question mentions "figure", "diagram", "graph", set requires_figure to true.
- Estimate difficulty based on marks and complexity: 1 mark = easy, 2-3 = medium, 4-5 = hard.
- Topic should be specific to the math domain (e.g., "Arithmetic Progressions" not just "Math").
- Return ONLY the JSON array, no markdown fences or extra text.
"""


def _build_user_prompt(
    segments: list[dict[str, Any]],
    exam_context: str | None = None,
) -> str:
    """Build the user prompt with question segments."""
    parts: list[str] = []
    if exam_context:
        parts.append(f"Exam context: {exam_context}\n")
    parts.append("Questions to analyze:\n")
    for seg in segments:
        q_num = seg.get("question_number", "?")
        section = seg.get("section", "")
        text = seg.get("text", "")
        has_or = seg.get("has_or_alternative", False)
        or_text = seg.get("or_text", "")
        img_desc = ""
        for img in seg.get("images", []):
            desc = img.get("description")
            if desc:
                img_desc += f"\n  [Associated figure: {desc}]"

        entry = f"Q{q_num} (Section {section}):\n{text}"
        if has_or and or_text:
            entry += f"\nOR\n{or_text}"
        if img_desc:
            entry += img_desc
        parts.append(entry)
        parts.append("---")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# LLM enrichment
# ---------------------------------------------------------------------------

def enrich_questions(
    segments: list[dict[str, Any]],
    exam_context: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Enrich question segments with LLM-derived metadata.

    Parameters
    ----------
    segments:
        List of raw question segment dicts (from RawQuestionSegment).
    exam_context:
        Optional exam context string (e.g. "SSLC Mathematics 2025-26").
    model:
        Override the LLM model to use.

    Returns
    -------
    List of enrichment dicts (one per question), in the same order as input.
    If LLM is not configured or fails, returns enrichment with None values.
    """
    if not segments:
        return []

    if not _is_configured():
        logger.warning("OpenAI API key not configured; skipping LLM enrichment")
        return _fallback_enrichment(segments)

    try:
        import openai
    except ImportError:
        logger.warning("openai package not installed; skipping LLM enrichment")
        return _fallback_enrichment(segments)

    use_model = model or ENRICHMENT_MODEL
    client = openai.OpenAI()
    all_enrichments: list[dict[str, Any]] = []

    # Process in batches
    for i in range(0, len(segments), ENRICHMENT_BATCH_SIZE):
        batch = segments[i : i + ENRICHMENT_BATCH_SIZE]
        user_prompt = _build_user_prompt(batch, exam_context)

        enrichments = _call_llm(client, use_model, user_prompt, len(batch))
        if enrichments:
            all_enrichments.extend(enrichments)
        else:
            all_enrichments.extend(_fallback_enrichment(batch))

    return all_enrichments


def _call_llm(
    client: Any,
    model: str,
    user_prompt: str,
    expected_count: int,
) -> list[dict[str, Any]] | None:
    """Make the actual API call with retries."""
    last_err = None
    for attempt in range(ENRICHMENT_MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                timeout=ENRICHMENT_TIMEOUT,
            )
            content = resp.choices[0].message.content.strip() if resp.choices else ""
            if not content:
                return None

            # Strip markdown code fences if present
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)

            result = json.loads(content)
            if isinstance(result, list):
                return result
            return None

        except json.JSONDecodeError as e:
            logger.warning("LLM returned invalid JSON (attempt %d): %s", attempt + 1, e)
            last_err = e
        except Exception as e:
            logger.warning("LLM enrichment failed (attempt %d): %s", attempt + 1, e)
            last_err = e

        if attempt < ENRICHMENT_MAX_RETRIES:
            time.sleep(1.0 * (attempt + 1))

    logger.error("LLM enrichment failed after %d attempts: %s", ENRICHMENT_MAX_RETRIES + 1, last_err)
    return None


# ---------------------------------------------------------------------------
# Fallback (rule-based) enrichment
# ---------------------------------------------------------------------------

def _fallback_enrichment(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Provide basic enrichment without LLM using heuristics."""
    results = []
    for seg in segments:
        text = seg.get("text", "")
        q_num = seg.get("question_number")

        # Detect MCQ by option pattern
        has_options = bool(
            _extract_options_regex(text)
        )
        q_type = "mcq" if has_options else None

        # Extract marks from text context
        marks = _guess_marks_from_text(text)

        results.append({
            "question_number": q_num,
            "question_type": q_type,
            "marks": marks,
            "topic": None,
            "difficulty": _guess_difficulty(marks),
            "options": _extract_options_regex(text) if has_options else [],
            "sub_parts": [],
            "requires_figure": bool(
                _has_figure_reference(text)
            ),
        })
    return results


def _extract_options_regex(text: str) -> list[dict[str, str]]:
    """Extract MCQ options from text using regex."""
    import re
    # Pattern matches (A) text, (B) text, etc.
    pattern = re.compile(
        r"\(([A-Da-d])\)\s*(.+?)(?=\s*\([A-Da-d]\)|\s*$)",
        re.DOTALL,
    )
    matches = pattern.findall(text)
    if not matches:
        return []
    return [
        {"label": label.upper(), "text": t.strip()}
        for label, t in matches
    ]


def _guess_marks_from_text(text: str) -> int | None:
    """Try to extract marks from trailing numbers or context."""
    import re
    # Look for standalone trailing number that could be marks
    m = re.search(r"\b(\d{1,2})\s*$", text.strip())
    if m:
        val = int(m.group(1))
        if 1 <= val <= 10:
            return val
    return None


def _guess_difficulty(marks: int | None) -> str | None:
    """Estimate difficulty from marks."""
    if marks is None:
        return None
    if marks <= 1:
        return "easy"
    if marks <= 3:
        return "medium"
    return "hard"


def _has_figure_reference(text: str) -> bool:
    """Check if text references a figure or diagram."""
    import re
    return bool(re.search(
        r"(?:in\s+the\s+figure|as\s+shown|the\s+(?:given\s+)?(?:figure|diagram|graph))",
        text,
        re.IGNORECASE,
    ))
