"""Tests for app.ocr_router."""

from __future__ import annotations

import unittest

from app.ocr_router import ResolvedOCRConfig, resolve_ocr_config


class TestResolveWithLanguage(unittest.TestCase):
    def test_resolve_with_language_kannada(self) -> None:
        r = resolve_ocr_config(language="kannada", ocr_lang="eng")
        self.assertIsInstance(r, ResolvedOCRConfig)
        self.assertEqual(r.tesseract_lang, "kan")
        self.assertEqual(r.paddleocr_lang, "kn")
        self.assertEqual(r.quality_preset, "kannada")
        self.assertEqual(r.language_id, "kannada")

    def test_resolve_with_language_english(self) -> None:
        r = resolve_ocr_config(language="english", ocr_lang="eng")
        self.assertEqual(r.tesseract_lang, "eng")
        self.assertEqual(r.paddleocr_lang, "en")
        self.assertEqual(r.quality_preset, "default")
        self.assertEqual(r.language_id, "english")


class TestResolveWithoutLanguageUsesOcrLang(unittest.TestCase):
    def test_resolve_without_language_uses_ocr_lang_kan(self) -> None:
        r = resolve_ocr_config(language=None, ocr_lang="kan")
        self.assertEqual(r.tesseract_lang, "kan")
        self.assertEqual(r.paddleocr_lang, "kn")
        self.assertEqual(r.language_id, "kannada")

    def test_resolve_without_language_uses_ocr_lang_eng(self) -> None:
        r = resolve_ocr_config(language=None, ocr_lang="eng")
        self.assertEqual(r.tesseract_lang, "eng")
        self.assertEqual(r.language_id, "english")


class TestResolveUnknownFallsBackToEnglish(unittest.TestCase):
    def test_resolve_unknown_language_falls_back(self) -> None:
        r = resolve_ocr_config(language="unknown", ocr_lang="eng")
        self.assertEqual(r.tesseract_lang, "eng")
        self.assertEqual(r.language_id, "english")

    def test_resolve_unknown_ocr_lang_falls_back(self) -> None:
        r = resolve_ocr_config(language=None, ocr_lang="xx")
        self.assertEqual(r.tesseract_lang, "eng")
        self.assertEqual(r.language_id, "english")


class TestResolveAliases(unittest.TestCase):
    def test_resolve_alias_kn_to_kannada(self) -> None:
        r = resolve_ocr_config(language="kn", ocr_lang="eng")
        self.assertEqual(r.tesseract_lang, "kan")
        self.assertEqual(r.language_id, "kannada")

    def test_resolve_alias_hi_to_hindi(self) -> None:
        r = resolve_ocr_config(language="hi", ocr_lang="eng")
        self.assertEqual(r.tesseract_lang, "hin")
        self.assertEqual(r.paddleocr_lang, "hi")
        self.assertEqual(r.language_id, "hindi")
