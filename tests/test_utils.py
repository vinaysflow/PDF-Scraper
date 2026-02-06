"""Tests for app.utils."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.utils import (
    EmptyContentError,
    MaxPagesExceededError,
    PdfValidationError,
    check_binary_exists,
    guard_max_pages,
    levenshtein,
    normalize_text,
    similarity_ratio,
    validate_pdf_path,
    word_error_rate,
)


class TestNormalizeText(unittest.TestCase):
    def test_lowercase_and_collapse_whitespace(self) -> None:
        self.assertEqual(normalize_text("  Hello   World  "), "hello world")

    def test_fi_fl_ligatures(self) -> None:
        self.assertIn("fi", normalize_text("\ufb01"))  # ﬁ -> fi
        self.assertIn("fl", normalize_text("\ufb02"))  # ﬂ -> fl

    def test_crlf_to_space(self) -> None:
        self.assertEqual(normalize_text("a\r\nb"), "a b")

    def test_empty(self) -> None:
        self.assertEqual(normalize_text(""), "")


class TestLevenshtein(unittest.TestCase):
    def test_identical(self) -> None:
        self.assertEqual(levenshtein("abc", "abc"), 0)
        self.assertEqual(levenshtein([], []), 0)

    def test_one_empty(self) -> None:
        self.assertEqual(levenshtein("", "abc"), 3)
        self.assertEqual(levenshtein("ab", ""), 2)

    def test_substitution(self) -> None:
        self.assertEqual(levenshtein("cat", "bat"), 1)
        self.assertEqual(levenshtein("kitten", "sitting"), 3)

    def test_word_sequence(self) -> None:
        self.assertEqual(levenshtein("hello world".split(), "hello there".split()), 1)


class TestWordErrorRate(unittest.TestCase):
    def test_identical(self) -> None:
        self.assertEqual(word_error_rate("hello world", "hello world"), 0.0)

    def test_one_word_ref(self) -> None:
        self.assertEqual(word_error_rate("x", "y"), 1.0)
        self.assertEqual(word_error_rate("x", "x"), 0.0)

    def test_empty_reference(self) -> None:
        self.assertIsNone(word_error_rate("", "something"))

    def test_wer_ratio(self) -> None:
        # 2 of 4 words wrong
        wer = word_error_rate("a b c d", "a x c y")
        self.assertAlmostEqual(wer, 0.5)


class TestSimilarityRatio(unittest.TestCase):
    def test_identical(self) -> None:
        self.assertEqual(similarity_ratio("hello", "hello"), 1.0)

    def test_empty_ref(self) -> None:
        self.assertIsNone(similarity_ratio("", "hypothesis"))

    def test_complement_of_wer(self) -> None:
        ref, hyp = "one two three", "one two four"
        wer = word_error_rate(ref, hyp)
        sim = similarity_ratio(ref, hyp)
        self.assertIsNotNone(wer)
        self.assertIsNotNone(sim)
        self.assertAlmostEqual(sim, 1.0 - wer)


class TestValidatePdfPath(unittest.TestCase):
    def test_nonexistent_raises(self) -> None:
        with self.assertRaises(PdfValidationError):
            validate_pdf_path("/nonexistent/file.pdf")

    def test_wrong_extension_raises(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"x")
            path = f.name
        try:
            with self.assertRaises(PdfValidationError):
                validate_pdf_path(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_valid_pdf_exists(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 dummy")
            path = f.name
        try:
            result = validate_pdf_path(path)
            self.assertEqual(result.suffix.lower(), ".pdf")
            self.assertTrue(result.exists())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_accepts_path_object(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4")
            path = Path(f.name)
        try:
            result = validate_pdf_path(path)
            self.assertTrue(result.exists())
        finally:
            path.unlink(missing_ok=True)


class TestGuardMaxPages(unittest.TestCase):
    def test_none_allows_any(self) -> None:
        guard_max_pages(100, None)

    def test_under_limit_ok(self) -> None:
        guard_max_pages(10, 10)
        guard_max_pages(5, 10)

    def test_over_raises(self) -> None:
        with self.assertRaises(MaxPagesExceededError):
            guard_max_pages(31, 10)
        with self.assertRaises(MaxPagesExceededError):
            guard_max_pages(11, 10)


class TestCheckBinary(unittest.TestCase):
    def test_common_binary_exists(self) -> None:
        # At least one of these should exist on a dev machine
        self.assertTrue(check_binary_exists("python3") or check_binary_exists("python"))

    def test_nonexistent_binary(self) -> None:
        self.assertFalse(check_binary_exists("_nonexistent_binary_xyz_12345"))


if __name__ == "__main__":
    unittest.main()
