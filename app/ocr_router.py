"""OCR language routing: resolve language / ocr_lang to engine-specific codes and quality preset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Canonical profile id -> profile dict (tesseract_lang, paddleocr_lang, quality_preset, preprocess)
LANGUAGE_PROFILES: dict[str, dict[str, Any]] = {
    "english": {
        "id": "english",
        "tesseract_lang": "eng",
        "paddleocr_lang": "en",
        "primary_engine": "tesseract",
        "quality_preset": "default",
        "preprocess": "standard",
    },
    "kannada": {
        "id": "kannada",
        "tesseract_lang": "kan",
        "paddleocr_lang": "kn",
        "primary_engine": "tesseract",
        "quality_preset": "kannada",
        "preprocess": "standard",
    },
    "hindi": {
        "id": "hindi",
        "tesseract_lang": "hin",
        "paddleocr_lang": "hi",
        "primary_engine": "tesseract",
        "quality_preset": "default",
        "preprocess": "standard",
    },
    "tamil": {
        "id": "tamil",
        "tesseract_lang": "tam",
        "paddleocr_lang": "ta",
        "primary_engine": "tesseract",
        "quality_preset": "default",
        "preprocess": "standard",
    },
    "telugu": {
        "id": "telugu",
        "tesseract_lang": "tel",
        "paddleocr_lang": "te",
        "primary_engine": "tesseract",
        "quality_preset": "default",
        "preprocess": "standard",
    },
}

# Alias (e.g. "kan", "kn") -> canonical profile id
LANGUAGE_ALIASES: dict[str, str] = {
    "eng": "english",
    "en": "english",
    "kan": "kannada",
    "kn": "kannada",
    "hin": "hindi",
    "hi": "hindi",
    "tam": "tamil",
    "ta": "tamil",
    "tel": "telugu",
    "te": "telugu",
}


@dataclass(frozen=True)
class ResolvedOCRConfig:
    """Resolved OCR config: engine-specific lang codes and quality preset."""

    tesseract_lang: str
    paddleocr_lang: str | None
    quality_preset: str
    preprocess: str
    language_id: str  # canonical id for response (e.g. "kannada")


def resolve_ocr_config(
    language: str | None = None,
    ocr_lang: str = "eng",
) -> ResolvedOCRConfig:
    """Resolve language or legacy ocr_lang to a full OCR config.

    If language is provided (e.g. "kannada", "kn"), it is normalized and used.
    Otherwise ocr_lang is used to look up a profile via LANGUAGE_ALIASES.
    Unknown values fall back to the English profile.
    """
    profile_id: str | None = None
    if language is not None and language.strip():
        normalized = language.strip().lower()
        profile_id = LANGUAGE_PROFILES.get(normalized) and normalized or LANGUAGE_ALIASES.get(
            normalized
        )
    if profile_id is None:
        profile_id = LANGUAGE_ALIASES.get(ocr_lang.strip().lower()) or "english"
    profile = LANGUAGE_PROFILES.get(profile_id, LANGUAGE_PROFILES["english"])
    return ResolvedOCRConfig(
        tesseract_lang=profile["tesseract_lang"],
        paddleocr_lang=profile.get("paddleocr_lang"),
        quality_preset=profile.get("quality_preset", "default"),
        preprocess=profile.get("preprocess", "standard"),
        language_id=profile["id"],
    )
