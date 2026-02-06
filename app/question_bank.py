"""Orchestrator for building a QuestionBank from an ExtractionResult.

Chains: regex parser -> spatial image associator -> LLM enricher
to produce a database-ready QuestionBank JSON structure.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from .question_enricher import enrich_questions
from .question_parser import associate_images, parse_all_pages
from .schema import (
    ExtractionResult,
    Question,
    QuestionBank,
    QuestionImage,
    QuestionOption,
    QuestionPart,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exam metadata extraction (header page)
# ---------------------------------------------------------------------------

def _extract_exam_metadata(full_text: str) -> dict[str, Any]:
    """Parse exam title, subject, and total marks from the first page text."""
    metadata: dict[str, Any] = {}

    # Exam title: look for "MODEL QUESTION PAPER" or similar
    title_match = re.search(
        r"(S\.?S\.?L\.?C\.?\s+MODEL\s+QUESTION\s+PAPER[^\n]*)",
        full_text,
        re.IGNORECASE,
    )
    if title_match:
        metadata["exam_title"] = title_match.group(1).strip()

    # Subject (match up to end of line, not across newlines)
    subject_match = re.search(
        r"Subject\s*:\s*([A-Z][A-Za-z ]+)",
        full_text,
    )
    if subject_match:
        metadata["subject"] = subject_match.group(1).strip()

    # Total marks
    marks_match = re.search(
        r"Max\.?\s*Marks?\s*:\s*(\d+)",
        full_text,
        re.IGNORECASE,
    )
    if marks_match:
        metadata["total_marks"] = int(marks_match.group(1))

    return metadata


def _extract_sections(full_text: str) -> list[dict[str, Any]]:
    """Extract section information (marks per question, question count)."""
    sections: list[dict[str, Any]] = []

    # Pattern: "8 x 1 = 8", "8 × 2 = 16", or "8  1 = 8" (whitespace separator)
    section_marks_re = re.compile(
        r"(\d+)\s+[x×]?\s*(\d+)\s*=\s*(\d+)",
    )

    # Roman numeral section headers
    roman_re = re.compile(
        r"^\s*(I{1,3}|IV|VI{0,3}|IX|X)\s*[.)]\s+",
        re.MULTILINE,
    )

    roman_matches = list(roman_re.finditer(full_text))
    for i, rm in enumerate(roman_matches):
        section_label = rm.group(1)
        # Look for marks pattern in the first 3 lines after this section header
        end_pos = roman_matches[i + 1].start() if i + 1 < len(roman_matches) else len(full_text)
        section_text = full_text[rm.start():end_pos]

        marks_match = section_marks_re.search(section_text)
        if marks_match:
            count = int(marks_match.group(1))
            marks_per = int(marks_match.group(2))
            total = int(marks_match.group(3))
            # Validate: count * marks_per should equal total
            if count * marks_per == total:
                sections.append({
                    "section": section_label,
                    "marks_per_question": marks_per,
                    "count": count,
                })

    return sections


# ---------------------------------------------------------------------------
# Build QuestionBank
# ---------------------------------------------------------------------------

def build_question_bank(
    extraction_result: ExtractionResult,
    enrich_with_llm: bool = True,
) -> QuestionBank:
    """Build a QuestionBank from an ExtractionResult.

    Parameters
    ----------
    extraction_result:
        The full extraction result from the PDF pipeline.
    enrich_with_llm:
        Whether to call the LLM for enrichment (type, topic, difficulty).
        Set to False for faster processing or when no API key is available.

    Returns
    -------
    A QuestionBank model ready for JSON serialization or database ingestion.
    """
    result_dict = extraction_result.model_dump()
    pages = result_dict.get("pages", [])
    diagrams = result_dict.get("diagrams")
    full_text = result_dict.get("full_text", "")

    # Step 1: Parse questions from all pages
    logger.info("Parsing questions from %d pages", len(pages))
    raw_segments = parse_all_pages(pages)
    logger.info("Found %d question segments", len(raw_segments))

    # Step 2: Associate images with questions
    logger.info("Associating images with questions")
    associate_images(raw_segments, pages, diagrams)

    # Step 3: Prepare segment dicts for enrichment
    segment_dicts = []
    for seg in raw_segments:
        segment_dicts.append({
            "question_number": seg.question_number,
            "section": seg.section,
            "page_number": seg.page_number,
            "text": seg.text,
            "has_or_alternative": seg.has_or_alternative,
            "or_text": seg.or_text,
            "images": seg.images,
        })

    # Step 4: LLM enrichment
    exam_metadata = _extract_exam_metadata(full_text)
    exam_context = None
    if exam_metadata.get("exam_title") or exam_metadata.get("subject"):
        exam_context = f"{exam_metadata.get('exam_title', '')} - {exam_metadata.get('subject', '')}"

    enrichments: list[dict[str, Any]] = []
    if enrich_with_llm:
        logger.info("Enriching %d questions with LLM", len(segment_dicts))
        enrichments = enrich_questions(segment_dicts, exam_context=exam_context)
    else:
        from .question_enricher import _fallback_enrichment
        enrichments = _fallback_enrichment(segment_dicts)

    # Step 5: Merge parsed segments + enrichments into Question models
    # Build a lookup by question_number instead of relying on positional index
    enrichment_lookup: dict[int, dict[str, Any]] = {}
    for enr in enrichments:
        qn = enr.get("question_number")
        if qn is not None:
            enrichment_lookup[int(qn)] = enr

    questions: list[Question] = []
    for seg in raw_segments:
        enrichment = enrichment_lookup.get(seg.question_number or 0, {})
        if seg.question_number and seg.question_number not in enrichment_lookup:
            logger.warning(
                "No enrichment found for question %d; using defaults",
                seg.question_number,
            )

        # Build options
        options = [
            QuestionOption(label=opt["label"], text=opt["text"])
            for opt in enrichment.get("options", [])
        ]

        # Build sub-parts
        sub_parts = [
            QuestionPart(
                label=sp["label"],
                text=sp["text"],
                marks=sp.get("marks"),
            )
            for sp in enrichment.get("sub_parts", [])
        ]

        # Build images
        images = [
            QuestionImage(
                image_url=img.get("image_url"),
                image_path=img.get("image_path"),
                format=img.get("format", "png"),
                width=img.get("width", 0),
                height=img.get("height", 0),
                description=img.get("description"),
                bbox=img.get("bbox"),
            )
            for img in seg.images
        ]

        # Build the OR alternative question if present
        or_question = None
        if seg.has_or_alternative and seg.or_text:
            or_question = Question(
                question_number=seg.question_number or 0,
                section=seg.section,
                page_number=seg.page_number,
                text=seg.or_text,
                question_type=enrichment.get("question_type"),
                marks=enrichment.get("marks"),
                topic=enrichment.get("topic"),
                difficulty=enrichment.get("difficulty"),
            )

        question = Question(
            question_number=seg.question_number or 0,
            section=seg.section,
            page_number=seg.page_number,
            text=seg.text,
            question_type=enrichment.get("question_type"),
            marks=enrichment.get("marks"),
            topic=enrichment.get("topic"),
            difficulty=enrichment.get("difficulty"),
            options=options,
            sub_parts=sub_parts,
            images=images,
            has_or_alternative=seg.has_or_alternative,
            or_question=or_question,
        )
        questions.append(question)

    # Step 6: Build the QuestionBank
    sections = _extract_sections(full_text)
    qbank = QuestionBank(
        doc_id=extraction_result.doc_id,
        filename=extraction_result.filename,
        ingested_at=extraction_result.ingested_at,
        exam_title=exam_metadata.get("exam_title"),
        subject=exam_metadata.get("subject"),
        total_marks=exam_metadata.get("total_marks"),
        total_questions=len(questions),
        sections=sections,
        questions=questions,
    )

    logger.info(
        "Built question bank: %d questions, %d sections",
        qbank.total_questions,
        len(qbank.sections),
    )
    return qbank
