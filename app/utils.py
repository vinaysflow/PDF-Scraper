"""Utility helpers for PDF extraction."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

from pdf2image import pdfinfo_from_path


class ExtractionError(Exception):
    """Base exception for extraction errors."""


class MissingDependencyError(ExtractionError):
    """Raised when required system dependencies are missing."""


class PdfValidationError(ExtractionError):
    """Raised when a PDF file is missing or unreadable."""


class PdfProcessingError(ExtractionError):
    """Raised when PDF processing fails."""


class MaxPagesExceededError(ExtractionError):
    """Raised when a PDF exceeds the maximum page limit."""


class EmptyContentError(ExtractionError):
    """Raised when extracted content is empty."""


class QualityGateError(ExtractionError):
    """Raised when strict quality gates are not satisfied."""


def normalize_text(text: str) -> str:
    """Normalize text for similarity comparison."""

    normalized = (
        text.replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .replace("\r\n", "\n")
        .replace("\n", " ")
    )
    normalized = " ".join(normalized.split())
    return normalized.strip().lower()


def levenshtein(a: list[str] | str, b: list[str] | str) -> int:
    """Compute Levenshtein distance between sequences."""

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
            insert = curr[j - 1] + 1
            delete = prev[j] + 1
            replace = prev[j - 1] + (0 if ca == cb else 1)
            curr.append(min(insert, delete, replace))
        prev = curr
    return prev[-1]


def word_error_rate(reference: str, hypothesis: str) -> float | None:
    """Return word error rate (WER) between reference and hypothesis."""

    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    ref_words = ref.split()
    hyp_words = hyp.split()
    if not ref_words:
        return None
    return levenshtein(ref_words, hyp_words) / max(len(ref_words), 1)


def similarity_ratio(reference: str, hypothesis: str) -> float | None:
    """Return similarity ratio (1 - WER) between reference and hypothesis."""

    wer = word_error_rate(reference, hypothesis)
    if wer is None:
        return None
    return 1.0 - wer


def check_binary_exists(binary_name: str) -> bool:
    """Return True if a binary is available on PATH."""

    return shutil.which(binary_name) is not None


def ensure_binaries(binaries: Iterable[str]) -> None:
    """Ensure all required binaries exist on PATH."""

    missing = [binary for binary in binaries if not check_binary_exists(binary)]
    if missing:
        raise MissingDependencyError(
            f"Missing required system binaries: {', '.join(missing)}"
        )


def validate_pdf_path(path: str | Path) -> Path:
    """Validate that the PDF exists and is readable."""

    pdf_path = Path(path).expanduser().resolve()
    if not pdf_path.exists():
        raise PdfValidationError(f"PDF not found: {pdf_path}")
    if not pdf_path.is_file():
        raise PdfValidationError(f"PDF path is not a file: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise PdfValidationError("Input file must be a PDF.")
    if not os.access(pdf_path, os.R_OK):
        raise PdfValidationError(f"PDF is not readable: {pdf_path}")
    return pdf_path


def get_pdf_page_count(pdf_path: Path) -> int:
    """Return the number of pages in a PDF."""

    try:
        info = pdfinfo_from_path(str(pdf_path))
        return int(info.get("Pages", 0))
    except Exception as exc:  # pragma: no cover - error detail is surfaced to caller
        raise PdfProcessingError(f"Failed to read PDF metadata: {exc}") from exc


def guard_max_pages(page_count: int, max_pages: int | None) -> None:
    """Raise if page_count exceeds max_pages."""

    if max_pages is None:
        return
    if page_count > max_pages:
        raise MaxPagesExceededError(
            f"PDF has {page_count} pages, exceeds limit of {max_pages}."
        )
