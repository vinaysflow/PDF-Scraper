"""Tests for app.question_parser – regex segmenter and spatial image associator."""

from __future__ import annotations

import unittest

from app.question_parser import (
    RawQuestionSegment,
    associate_images,
    parse_all_pages,
    parse_page_questions,
)


class TestParsePageQuestions(unittest.TestCase):
    """Tests for single-page question parsing."""

    def test_single_question(self) -> None:
        text = "1. The H.C.F of 3 and 5 is,\n(A) 1\n(B) 3\n(C) 5\n(D) 15\n"
        segments, section = parse_page_questions(text, page_number=1)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].question_number, 1)
        self.assertIn("H.C.F", segments[0].text)

    def test_multiple_questions(self) -> None:
        text = (
            "1. What is 2+2?\n(A) 3\n(B) 4\n(C) 5\n(D) 6\n\n"
            "2. What is 3+3?\n(A) 5\n(B) 6\n(C) 7\n(D) 8\n\n"
            "3. What is 4+4?\n"
        )
        segments, _ = parse_page_questions(text, page_number=1)
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0].question_number, 1)
        self.assertEqual(segments[1].question_number, 2)
        self.assertEqual(segments[2].question_number, 3)

    def test_section_detection(self) -> None:
        text = (
            "I. Four alternatives are given for each question.\n\n"
            "1. Question one\n\n"
            "2. Question two\n"
        )
        segments, section = parse_page_questions(text, page_number=1)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].section, "I")
        self.assertEqual(segments[1].section, "I")
        self.assertEqual(section, "I")

    def test_section_carries_over(self) -> None:
        text = "5. Question five\n6. Question six\n"
        segments, section = parse_page_questions(
            text, page_number=2, current_section="II",
        )
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].section, "II")
        self.assertEqual(segments[1].section, "II")

    def test_or_alternative(self) -> None:
        text = (
            "17. Find the first term.\n"
            "OR\n"
            "How many numbers between 201 and 401 are divisible by 6?\n"
        )
        segments, _ = parse_page_questions(text, page_number=1)
        self.assertEqual(len(segments), 1)
        self.assertTrue(segments[0].has_or_alternative)
        self.assertIsNotNone(segments[0].or_text)
        self.assertIn("divisible by 6", segments[0].or_text)

    def test_empty_text(self) -> None:
        segments, section = parse_page_questions("", page_number=1)
        self.assertEqual(segments, [])
        self.assertIsNone(section)

    def test_whitespace_only(self) -> None:
        segments, _ = parse_page_questions("   \n\n\n  ", page_number=1)
        self.assertEqual(segments, [])

    def test_y_positions_set(self) -> None:
        text = "1. First question\n\n2. Second question\n"
        segments, _ = parse_page_questions(text, page_number=1, page_height=792)
        for seg in segments:
            self.assertIsNotNone(seg.y_start)
            self.assertIsNotNone(seg.y_end)

    def test_marks_header_skipped(self) -> None:
        """Marks-only lines like '8 x 1 = 8' should not appear in question text."""
        text = "1. What is 2+2?\n8 x 1 = 8\n(A) 3\n(B) 4\n"
        segments, _ = parse_page_questions(text, page_number=1)
        self.assertEqual(len(segments), 1)
        self.assertNotIn("8 x 1 = 8", segments[0].text)

    def test_marks_header_whitespace_only_skipped(self) -> None:
        """Marks lines like '8  1 = 8' (no x) should also be skipped."""
        text = "1. What is 2+2?\n8  1 = 8\n(A) 3\n(B) 4\n"
        segments, _ = parse_page_questions(text, page_number=1)
        self.assertEqual(len(segments), 1)
        self.assertNotIn("8  1 = 8", segments[0].text)

    def test_instructions_page_skipped(self) -> None:
        """Pages containing 'General Instructions' should be skipped entirely."""
        text = (
            "General Instructions to the candidate:\n"
            "1. This question paper consists of 38 questions.\n"
            "2. Follow the instructions.\n"
            "3. Figures indicate marks.\n"
            "4. Maximum time is given.\n"
        )
        segments, section = parse_page_questions(text, page_number=1)
        self.assertEqual(segments, [])

    def test_instructions_to_candidate_skipped(self) -> None:
        """Variant instruction header also skipped."""
        text = (
            "Instructions to the candidate:\n"
            "1. Answer all questions.\n"
            "2. Write clearly.\n"
        )
        segments, _ = parse_page_questions(text, page_number=1)
        self.assertEqual(segments, [])


class TestParseAllPages(unittest.TestCase):
    """Tests for multi-page parsing."""

    def test_cross_page_questions(self) -> None:
        pages = [
            {"page_number": 1, "text": "I. Choose the correct answer.\n1. Q1\n2. Q2\n"},
            {"page_number": 2, "text": "3. Q3\n4. Q4\n"},
        ]
        segments = parse_all_pages(pages)
        self.assertEqual(len(segments), 4)
        self.assertEqual(segments[0].question_number, 1)
        self.assertEqual(segments[3].question_number, 4)

    def test_sorted_by_question_number(self) -> None:
        pages = [
            {"page_number": 2, "text": "10. Q10\n11. Q11\n"},
            {"page_number": 1, "text": "1. Q1\n2. Q2\n"},
        ]
        segments = parse_all_pages(pages)
        numbers = [s.question_number for s in segments]
        self.assertEqual(numbers, [1, 2, 10, 11])

    def test_section_carries_across_pages(self) -> None:
        pages = [
            {"page_number": 1, "text": "II. Answer the following:\n9. Q9\n"},
            {"page_number": 2, "text": "10. Q10\n"},
        ]
        segments = parse_all_pages(pages)
        self.assertEqual(segments[0].section, "II")
        self.assertEqual(segments[1].section, "II")

    def test_empty_pages(self) -> None:
        pages = [
            {"page_number": 1, "text": ""},
            {"page_number": 2, "text": "   "},
        ]
        segments = parse_all_pages(pages)
        self.assertEqual(segments, [])

    def test_instructions_page_skipped_in_multi_page(self) -> None:
        pages = [
            {
                "page_number": 1,
                "text": (
                    "General Instructions to the candidate:\n"
                    "1. This paper has 38 questions.\n"
                    "2. Follow the instructions.\n"
                ),
            },
            {
                "page_number": 2,
                "text": "I. Choose the correct answer.\n1. Q1\n2. Q2\n",
            },
        ]
        segments = parse_all_pages(pages)
        # Only questions from page 2, not the instruction items from page 1
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].page_number, 2)
        self.assertEqual(segments[1].page_number, 2)


class TestAssociateImages(unittest.TestCase):
    """Tests for spatial image-to-question association."""

    def test_image_associated_to_nearest_question(self) -> None:
        seg1 = RawQuestionSegment(
            question_number=1, page_number=1, text="Q1",
            y_start=0.0, y_end=0.4,
        )
        seg2 = RawQuestionSegment(
            question_number=2, page_number=1, text="In the figure, Q2",
            y_start=0.4, y_end=0.9,
        )
        pages = [{
            "page_number": 1,
            "page_height": 792,
            "images": [{
                "bbox": {"x": 100, "y": 500, "w": 50, "h": 50},
                "image_url": "/img/1.png",
                "format": "png",
                "width": 50,
                "height": 50,
            }],
        }]
        associate_images([seg1, seg2], pages)
        # Image Y=500 out of 792 ≈ 0.63, should match seg2 (0.4-0.9)
        self.assertEqual(len(seg2.images), 1)
        self.assertEqual(seg2.images[0]["image_url"], "/img/1.png")
        self.assertEqual(len(seg1.images), 0)

    def test_figure_reference_preferred(self) -> None:
        """Segments mentioning 'figure' should be preferred for image association."""
        seg1 = RawQuestionSegment(
            question_number=1, page_number=1,
            text="In the figure, find the value",
            y_start=0.0, y_end=0.5,
        )
        seg2 = RawQuestionSegment(
            question_number=2, page_number=1,
            text="Find the HCF",
            y_start=0.3, y_end=0.7,
        )
        pages = [{
            "page_number": 1,
            "page_height": 792,
            "images": [{
                "bbox": {"x": 100, "y": 300, "w": 50, "h": 50},
                "format": "png", "width": 50, "height": 50,
            }],
        }]
        associate_images([seg1, seg2], pages)
        # Both segments overlap at y≈0.38, but seg1 mentions "figure"
        self.assertGreaterEqual(len(seg1.images), 1)

    def test_no_images_no_crash(self) -> None:
        seg = RawQuestionSegment(
            question_number=1, page_number=1, text="Q1",
            y_start=0.0, y_end=1.0,
        )
        pages = [{"page_number": 1, "page_height": 792, "images": []}]
        associate_images([seg], pages)
        self.assertEqual(seg.images, [])

    def test_diagram_description_attached(self) -> None:
        seg = RawQuestionSegment(
            question_number=2, page_number=2, text="In the figure, Q2",
            y_start=0.0, y_end=1.0,
        )
        pages = [{
            "page_number": 2,
            "page_height": 792,
            "images": [{
                "bbox": {"x": 200, "y": 300, "w": 100, "h": 100},
                "format": "png", "width": 100, "height": 100,
            }],
        }]
        diagrams = {
            "diagrams": [{
                "figure": {
                    "page_number": 2,
                    "bbox": {"x": 200, "y": 300, "w": 100, "h": 100},
                },
                "reading": {
                    "description": "A polynomial graph crossing x-axis",
                },
            }],
        }
        associate_images([seg], pages, diagrams)
        self.assertEqual(len(seg.images), 1)
        self.assertEqual(
            seg.images[0]["description"],
            "A polynomial graph crossing x-axis",
        )


if __name__ == "__main__":
    unittest.main()
