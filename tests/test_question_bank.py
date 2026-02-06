"""Tests for app.question_bank orchestrator and app.question_enricher."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.question_bank import (
    _extract_exam_metadata,
    _extract_sections,
    build_question_bank,
)
from app.question_enricher import (
    _extract_options_regex,
    _fallback_enrichment,
    _guess_difficulty,
    _guess_marks_from_text,
    _has_figure_reference,
)
from app.schema import (
    ExtractionMetadata,
    ExtractionResult,
    Page,
    PageImage,
    Question,
    QuestionBank,
    QuestionImage,
    QuestionOption,
    QuestionPart,
    Stats,
)


# ---------------------------------------------------------------------------
# Enricher unit tests
# ---------------------------------------------------------------------------


class TestExtractOptionsRegex(unittest.TestCase):
    def test_standard_mcq(self) -> None:
        text = "(A) 1  (B) 3  (C) 5  (D) 15"
        opts = _extract_options_regex(text)
        self.assertEqual(len(opts), 4)
        self.assertEqual(opts[0]["label"], "A")
        self.assertEqual(opts[0]["text"], "1")
        self.assertEqual(opts[3]["label"], "D")

    def test_no_options(self) -> None:
        text = "Find the common difference."
        opts = _extract_options_regex(text)
        self.assertEqual(opts, [])

    def test_lowercase_options(self) -> None:
        text = "(a) yes  (b) no"
        opts = _extract_options_regex(text)
        self.assertEqual(len(opts), 2)
        self.assertEqual(opts[0]["label"], "A")


class TestGuessDifficulty(unittest.TestCase):
    def test_easy(self) -> None:
        self.assertEqual(_guess_difficulty(1), "easy")

    def test_medium(self) -> None:
        self.assertEqual(_guess_difficulty(2), "medium")
        self.assertEqual(_guess_difficulty(3), "medium")

    def test_hard(self) -> None:
        self.assertEqual(_guess_difficulty(5), "hard")

    def test_none(self) -> None:
        self.assertIsNone(_guess_difficulty(None))


class TestGuessMarks(unittest.TestCase):
    def test_trailing_number(self) -> None:
        self.assertEqual(_guess_marks_from_text("Find the HCF  2"), 2)

    def test_no_marks(self) -> None:
        self.assertIsNone(_guess_marks_from_text("Prove that √5 is irrational"))


class TestHasFigureReference(unittest.TestCase):
    def test_with_figure(self) -> None:
        self.assertTrue(_has_figure_reference("In the figure, find the value"))

    def test_with_diagram(self) -> None:
        self.assertTrue(_has_figure_reference("The given diagram shows"))

    def test_without_figure(self) -> None:
        self.assertFalse(_has_figure_reference("Find the HCF of 3 and 5"))


class TestFallbackEnrichment(unittest.TestCase):
    def test_mcq_detected(self) -> None:
        segments = [{
            "question_number": 1,
            "text": "The HCF is (A) 1 (B) 3 (C) 5 (D) 15",
        }]
        result = _fallback_enrichment(segments)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["question_type"], "mcq")
        self.assertEqual(len(result[0]["options"]), 4)

    def test_non_mcq(self) -> None:
        segments = [{
            "question_number": 17,
            "text": "Find the first term of the AP.",
        }]
        result = _fallback_enrichment(segments)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["question_type"])
        self.assertEqual(result[0]["options"], [])


# ---------------------------------------------------------------------------
# Exam metadata extraction tests
# ---------------------------------------------------------------------------


class TestExtractExamMetadata(unittest.TestCase):
    def test_title_and_subject(self) -> None:
        text = (
            "S.S.L.C. MODEL QUESTION PAPER – 01 – 2025-26\n"
            "Subject: MATHEMATICS\n"
            "Max. Marks: 80\n"
        )
        meta = _extract_exam_metadata(text)
        self.assertIn("exam_title", meta)
        self.assertEqual(meta["subject"], "MATHEMATICS")
        self.assertEqual(meta["total_marks"], 80)

    def test_no_metadata(self) -> None:
        meta = _extract_exam_metadata("Some random text without metadata")
        self.assertEqual(meta, {})


class TestExtractSections(unittest.TestCase):
    def test_sections_detected(self) -> None:
        text = (
            "I. Four alternatives are given 8 x 1 = 8\n"
            "1. Question\n"
            "II. Answer the following 8 x 1 = 8\n"
            "9. Question\n"
        )
        sections = _extract_sections(text)
        self.assertGreaterEqual(len(sections), 1)
        self.assertEqual(sections[0]["section"], "I")


# ---------------------------------------------------------------------------
# Schema model tests
# ---------------------------------------------------------------------------


class TestQuestionModels(unittest.TestCase):
    def test_question_option(self) -> None:
        opt = QuestionOption(label="A", text="1")
        self.assertEqual(opt.label, "A")
        self.assertEqual(opt.text, "1")

    def test_question_image(self) -> None:
        img = QuestionImage(
            image_url="/api/images/doc/page_1/img_0.png",
            description="A graph",
            width=200,
            height=150,
        )
        self.assertEqual(img.width, 200)
        self.assertEqual(img.description, "A graph")

    def test_question_part(self) -> None:
        part = QuestionPart(label="a", text="Find x", marks=2)
        self.assertEqual(part.marks, 2)

    def test_question_full(self) -> None:
        q = Question(
            question_number=1,
            section="I",
            page_number=2,
            text="HCF of 3 and 5",
            question_type="mcq",
            marks=1,
            topic="Real Numbers",
            difficulty="easy",
            options=[
                QuestionOption(label="A", text="1"),
                QuestionOption(label="B", text="3"),
            ],
            images=[
                QuestionImage(image_url="/img.png"),
            ],
        )
        self.assertEqual(q.question_number, 1)
        self.assertEqual(len(q.options), 2)
        self.assertEqual(len(q.images), 1)

    def test_question_or_alternative(self) -> None:
        or_q = Question(
            question_number=17,
            page_number=5,
            text="Alternative question",
        )
        q = Question(
            question_number=17,
            page_number=5,
            text="Main question",
            has_or_alternative=True,
            or_question=or_q,
        )
        self.assertTrue(q.has_or_alternative)
        self.assertIsNotNone(q.or_question)
        self.assertEqual(q.or_question.text, "Alternative question")

    def test_question_bank(self) -> None:
        qbank = QuestionBank(
            doc_id="abc-123",
            filename="paper.pdf",
            ingested_at=datetime.now(timezone.utc),
            exam_title="SSLC Math Paper",
            subject="MATHEMATICS",
            total_marks=80,
            total_questions=2,
            sections=[{"section": "I", "marks_per_question": 1, "count": 8}],
            questions=[
                Question(question_number=1, page_number=1, text="Q1"),
                Question(question_number=2, page_number=1, text="Q2"),
            ],
        )
        self.assertEqual(qbank.total_questions, 2)
        self.assertEqual(len(qbank.questions), 2)
        d = qbank.model_dump()
        self.assertEqual(d["doc_id"], "abc-123")


# ---------------------------------------------------------------------------
# Orchestrator integration test
# ---------------------------------------------------------------------------


class TestBuildQuestionBank(unittest.TestCase):
    """Test the full orchestration pipeline (without LLM)."""

    def _make_extraction_result(self) -> ExtractionResult:
        page1 = Page(
            page_number=1,
            source="native",
            text=(
                "S.S.L.C. MODEL QUESTION PAPER – 01 – 2025-26\n"
                "Subject: MATHEMATICS\n"
                "Max. Marks: 80\n"
                "General Instructions to the candidate:\n"
                "1. This question paper consists of 38 questions.\n"
                "2. Follow the instructions given against the questions.\n"
            ),
        )
        page2 = Page(
            page_number=2,
            source="native",
            text=(
                "I. Four alternatives are given 8 x 1 = 8\n\n"
                "1. The H.C.F of 3 and 5 is,\n"
                "(A) 1  (B) 3  (C) 5  (D) 15\n\n"
                "2. In the figure, the number of zeroes of the polynomial is,\n"
                "(A) 3  (B) 5  (C) 4  (D) 1\n"
            ),
            images=[
                PageImage(
                    format="png", width=229, height=214,
                    bbox={"x": 208, "y": 550, "w": 120, "h": 109},
                    image_url="/api/images/doc/page_2/img_0.png",
                    image_path="/tmp/img.png",
                ),
            ],
            page_height=792,
        )
        return ExtractionResult(
            doc_id="test-doc-id",
            filename="math_paper.pdf",
            ingested_at=datetime.now(timezone.utc),
            extraction=ExtractionMetadata(
                method="ocr", pages_total=2, dpi=600, engine="tesseract",
            ),
            pages=[page1, page2],
            full_text=page1.text + page2.text,
            stats=Stats(total_tokens=0),
        )

    def test_build_without_llm(self) -> None:
        result = self._make_extraction_result()
        qbank = build_question_bank(result, enrich_with_llm=False)

        self.assertIsInstance(qbank, QuestionBank)
        self.assertEqual(qbank.doc_id, "test-doc-id")
        self.assertEqual(qbank.subject, "MATHEMATICS")
        self.assertEqual(qbank.total_marks, 80)
        # Exactly 2 questions (page 1 instructions are skipped)
        self.assertEqual(qbank.total_questions, 2)

        # Check question numbers
        q_nums = [q.question_number for q in qbank.questions]
        self.assertEqual(q_nums, [1, 2])

        # All from page 2 with section I
        for q in qbank.questions:
            self.assertEqual(q.page_number, 2)
            self.assertEqual(q.section, "I")

    def test_images_associated(self) -> None:
        result = self._make_extraction_result()
        qbank = build_question_bank(result, enrich_with_llm=False)

        # Question 2 references "In the figure" and has an image nearby
        q2 = next(
            (q for q in qbank.questions if q.question_number == 2),
            None,
        )
        self.assertIsNotNone(q2)
        self.assertGreaterEqual(len(q2.images), 1)
        self.assertEqual(q2.images[0].image_url, "/api/images/doc/page_2/img_0.png")

    def test_json_serializable(self) -> None:
        result = self._make_extraction_result()
        qbank = build_question_bank(result, enrich_with_llm=False)
        json_str = qbank.model_dump_json(indent=2)
        self.assertIn("test-doc-id", json_str)
        self.assertIn("MATHEMATICS", json_str)


if __name__ == "__main__":
    unittest.main()
