"""Regex-based question segmenter and spatial image associator.

Splits page-level extracted text into individual question segments and
associates images with questions based on figure references and spatial
proximity.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for question detection
# ---------------------------------------------------------------------------

# Section headers like "I.", "II.", "III.", "IV.", "V.", "VI."
_ROMAN_SECTIONS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10,
}
_SECTION_RE = re.compile(
    r"^\s*(I{1,3}|IV|VI{0,3}|IX|X)\s*[.)]\s+",
    re.MULTILINE,
)

# Question number patterns: "1.", "1)", "(1)", "Q1.", "Q.1"
_QUESTION_NUM_RE = re.compile(
    r"^\s*(?:Q\.?\s*)?(\d{1,3})\s*[.)]\s",
    re.MULTILINE,
)

# OR alternative separator
_OR_RE = re.compile(r"^\s*OR\s*$", re.MULTILINE | re.IGNORECASE)

# Marks pattern: "8 x 1 = 8", "8 × 2 = 16", or "8  1 = 8" (whitespace separator)
_MARKS_HEADER_RE = re.compile(
    r"(\d+)\s+[x×]?\s*(\d+)\s*=\s*(\d+)",
)

# Figure reference in question text
_FIGURE_REF_RE = re.compile(
    r"(?:in\s+the\s+figure|as\s+shown|the\s+(?:given\s+)?(?:figure|diagram|graph))",
    re.IGNORECASE,
)

# Instructions page detection -- skip these pages entirely
_INSTRUCTIONS_RE = re.compile(
    r"(?:General\s+Instructions|Instructions\s+to\s+the\s+candidate)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes for raw parsed segments
# ---------------------------------------------------------------------------

@dataclass
class RawQuestionSegment:
    """A single question segment parsed from page text."""

    question_number: int | None = None
    section: str | None = None
    page_number: int = 0
    text: str = ""
    y_start: float | None = None  # approximate Y-position on page (fraction 0-1)
    y_end: float | None = None
    has_or_alternative: bool = False
    or_text: str | None = None
    images: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------

def _detect_current_section(line: str, current_section: str | None) -> str | None:
    """Check if a line is a section header (e.g. 'I.  Four alternatives...')."""
    m = _SECTION_RE.match(line)
    if m:
        roman = m.group(1)
        if roman in _ROMAN_SECTIONS:
            return roman
    return current_section


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def parse_page_questions(
    text: str,
    page_number: int,
    page_height: float | None = None,
    current_section: str | None = None,
) -> tuple[list[RawQuestionSegment], str | None]:
    """Split a single page's text into question segments.

    Parameters
    ----------
    text:
        Full text of the page.
    page_number:
        1-based page number.
    page_height:
        Page height in points (for Y-position estimation).
    current_section:
        Section label carried over from previous page.

    Returns
    -------
    Tuple of (list of segments, last_section_label).
    """
    if not text or not text.strip():
        return [], current_section

    # Skip instruction/header pages entirely
    if _INSTRUCTIONS_RE.search(text):
        logger.debug("Skipping instructions page %d", page_number)
        return [], current_section

    lines = text.split("\n")
    total_chars = max(len(text), 1)
    segments: list[RawQuestionSegment] = []
    current_segment: RawQuestionSegment | None = None
    char_offset = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        line_frac = char_offset / total_chars  # position as fraction of page

        # Check for section header
        new_section = _detect_current_section(line, None)
        if new_section:
            current_section = new_section

        # Check for question number
        m = _QUESTION_NUM_RE.match(line)
        if m:
            q_num = int(m.group(1))
            # Close previous segment
            if current_segment and current_segment.text.strip():
                current_segment.y_end = line_frac
                _split_or_alternative(current_segment)
                segments.append(current_segment)

            current_segment = RawQuestionSegment(
                question_number=q_num,
                section=current_section,
                page_number=page_number,
                text=line.strip() + "\n",
                y_start=line_frac,
            )
            char_offset += line_len
            continue

        # Check for OR separator within a question
        if current_segment and _OR_RE.match(line):
            current_segment.text += line + "\n"
            current_segment.has_or_alternative = True
            char_offset += line_len
            continue

        # Accumulate text to current segment (skip marks-only headers)
        if current_segment:
            # Skip lines that are just marks headers like "8 x 1 = 8"
            stripped = line.strip()
            if stripped and _MARKS_HEADER_RE.fullmatch(stripped):
                char_offset += line_len
                continue
            current_segment.text += line + "\n"
        char_offset += line_len

    # Close last segment
    if current_segment and current_segment.text.strip():
        current_segment.y_end = 1.0
        _split_or_alternative(current_segment)
        segments.append(current_segment)

    return segments, current_section


def _split_or_alternative(segment: RawQuestionSegment) -> None:
    """If the segment contains an OR block, split into main text + or_text."""
    if not segment.has_or_alternative:
        return

    parts = _OR_RE.split(segment.text, maxsplit=1)
    if len(parts) == 2:
        segment.text = parts[0].strip()
        segment.or_text = parts[1].strip()


def parse_all_pages(
    pages: list[dict[str, Any]],
) -> list[RawQuestionSegment]:
    """Parse questions from all pages of an extraction result.

    Parameters
    ----------
    pages:
        List of page dicts from ``ExtractionResult.model_dump()["pages"]``.

    Returns
    -------
    List of all question segments across all pages, sorted by question number.
    """
    all_segments: list[RawQuestionSegment] = []
    current_section: str | None = None

    for page in pages:
        page_num = page.get("page_number", 0)
        text = page.get("text", "")
        page_height = page.get("page_height")

        segments, current_section = parse_page_questions(
            text, page_num, page_height, current_section,
        )
        all_segments.extend(segments)

    # Sort by question number (None goes last)
    all_segments.sort(key=lambda s: (s.question_number or 9999))
    return all_segments


# ---------------------------------------------------------------------------
# Spatial image-to-question association
# ---------------------------------------------------------------------------

def associate_images(
    segments: list[RawQuestionSegment],
    pages: list[dict[str, Any]],
    diagrams: dict[str, Any] | None = None,
) -> None:
    """Associate page images with question segments.

    Uses a two-pass strategy:
      1. **Primary**: assign images to questions that reference "figure"/"diagram"
         on the same page.
      2. **Fallback**: assign remaining images by spatial proximity (Y-position).

    Modifies segments in place by populating their ``images`` list.

    Parameters
    ----------
    segments:
        Parsed question segments (from ``parse_all_pages``).
    pages:
        Page dicts from extraction result.
    diagrams:
        Optional diagrams dict from extraction result.
    """
    # Build page_number -> segments index
    page_segments: dict[int, list[RawQuestionSegment]] = {}
    for seg in segments:
        page_segments.setdefault(seg.page_number, []).append(seg)

    # Build diagram description lookup: page_number -> [{bbox, description}]
    diagram_desc: dict[int, list[dict]] = {}
    if diagrams and diagrams.get("diagrams"):
        for dr in diagrams["diagrams"]:
            fig = dr.get("figure", {})
            reading = dr.get("reading", {})
            pg = fig.get("page_number", 0)
            desc = reading.get("description")
            if desc:
                diagram_desc.setdefault(pg, []).append({
                    "bbox": fig.get("bbox"),
                    "description": desc,
                })

    for page in pages:
        page_num = page.get("page_number", 0)
        page_height = page.get("page_height") or 792.0  # default letter height
        images = page.get("images", [])
        segs = page_segments.get(page_num, [])

        if not segs or not images:
            continue

        # Partition segments into those that reference figures and those that don't
        fig_segs = [s for s in segs if _FIGURE_REF_RE.search(s.text)]

        for img in images:
            bbox = img.get("bbox")
            if not bbox:
                continue

            img_y = bbox.get("y", 0)
            img_frac = img_y / page_height

            best_seg = _pick_best_segment(
                img_frac, fig_segs, segs, page_height,
            )

            if best_seg is not None:
                # Try to find VLM description for this image
                description = _find_diagram_description(
                    img_y, bbox, page_num, diagram_desc,
                )
                best_seg.images.append({
                    "image_url": img.get("image_url"),
                    "image_path": img.get("image_path"),
                    "format": img.get("format", "png"),
                    "width": img.get("width", 0),
                    "height": img.get("height", 0),
                    "description": description,
                    "bbox": bbox,
                })


def _pick_best_segment(
    img_frac: float,
    fig_segs: list[RawQuestionSegment],
    all_segs: list[RawQuestionSegment],
    page_height: float,
) -> RawQuestionSegment | None:
    """Pick the best segment for an image.

    Strategy:
      1. If there are figure-referencing segments, pick the closest one by Y
         position -- but prefer segments whose Y-range contains or is just
         above the image (the figure usually appears right after the question).
      2. Otherwise, pick the closest segment by Y from all segments.
    """
    def _proximity(seg: RawQuestionSegment) -> float:
        """Score: lower is better.  Prefer segment whose start is at or just
        above the image (image appears after the question text).
        """
        seg_start = seg.y_start or 0.0
        seg_end = seg.y_end or 1.0
        # If image is within segment range, score by distance to start
        if seg_start <= img_frac <= seg_end:
            return img_frac - seg_start  # small = image near top of segment
        # If image is below segment, prefer closer segments
        if img_frac > seg_end:
            return (img_frac - seg_end) + 0.01
        # Image is above segment start -- less likely match
        return (seg_start - img_frac) + 0.5

    # Pass 1: prefer figure-referencing segments
    if fig_segs:
        return min(fig_segs, key=_proximity)

    # Pass 2: nearest segment by proximity
    if all_segs:
        return min(all_segs, key=_proximity)

    return None


def _find_diagram_description(
    img_y: float,
    bbox: dict,
    page_num: int,
    diagram_desc: dict[int, list[dict]],
) -> str | None:
    """Look up VLM description for an image by approximate bbox match."""
    page_diagrams = diagram_desc.get(page_num, [])
    for diag in page_diagrams:
        diag_bbox = diag.get("bbox", {})
        if (
            diag_bbox
            and abs(diag_bbox.get("y", 0) - img_y) < 20
            and abs(diag_bbox.get("x", 0) - bbox.get("x", 0)) < 20
        ):
            return diag.get("description")
    return None
