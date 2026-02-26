"""Tests for app.providers.ocr_sarvam module."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_real_import = __import__


class TestIsAvailable:
    """Test is_available() with various SDK / API key combinations."""

    def test_available_when_sdk_and_key_present(self):
        import app.providers.ocr_sarvam as mod
        mod._AVAILABLE = None

        mock_sarvamai = MagicMock()
        with patch.dict("sys.modules", {"sarvamai": mock_sarvamai}):
            with patch("app.config.SARVAM_API_KEY", "test-key-123"):
                result = mod.is_available()
                assert result is True

        mod._AVAILABLE = None

    def test_unavailable_when_no_key(self):
        import app.providers.ocr_sarvam as mod
        mod._AVAILABLE = None

        mock_sarvamai = MagicMock()
        with patch.dict("sys.modules", {"sarvamai": mock_sarvamai}):
            with patch("app.config.SARVAM_API_KEY", ""):
                result = mod.is_available()
                assert result is False

        mod._AVAILABLE = None

    def test_unavailable_when_sdk_not_installed(self):
        import sys
        import app.providers.ocr_sarvam as mod
        mod._AVAILABLE = None

        saved = sys.modules.pop("sarvamai", None)
        try:
            def _import_fail(name, *a, **k):
                if name == "sarvamai":
                    raise ImportError("No module named 'sarvamai'")
                return _real_import(name, *a, **k)

            with patch("builtins.__import__", side_effect=_import_fail):
                result = mod.is_available()
                assert result is False
        finally:
            if saved is not None:
                sys.modules["sarvamai"] = saved
            mod._AVAILABLE = None


class TestParseMarkdownPages:
    """Test _parse_markdown_pages ZIP parsing."""

    def _make_zip(self, files: dict[str, str]) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        with zipfile.ZipFile(tmp.name, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return Path(tmp.name)

    def test_multi_file_zip(self):
        from app.providers.ocr_sarvam import _parse_markdown_pages

        zip_path = self._make_zip({
            "page_1.md": "# Page One\nContent of page one.",
            "page_2.md": "# Page Two\nContent of page two.",
            "page_3.md": "# Page Three\nContent of page three.",
        })
        result = _parse_markdown_pages(zip_path, [5, 6, 7])

        assert len(result) == 3
        assert result[5] == "# Page One\nContent of page one."
        assert result[6] == "# Page Two\nContent of page two."
        assert result[7] == "# Page Three\nContent of page three."

    def test_single_file_with_separators(self):
        from app.providers.ocr_sarvam import _parse_markdown_pages

        content = "Page 1 content\n---\nPage 2 content\n---\nPage 3 content"
        zip_path = self._make_zip({"output.md": content})
        result = _parse_markdown_pages(zip_path, [1, 2, 3])

        assert len(result) == 3
        assert result[1] == "Page 1 content"
        assert result[2] == "Page 2 content"
        assert result[3] == "Page 3 content"

    def test_single_file_no_separators(self):
        from app.providers.ocr_sarvam import _parse_markdown_pages

        content = "All content in one file"
        zip_path = self._make_zip({"output.md": content})
        result = _parse_markdown_pages(zip_path, [1, 2])

        assert len(result) == 2
        assert result[1] == content
        assert result[2] == content

    def test_empty_zip(self):
        from app.providers.ocr_sarvam import _parse_markdown_pages

        zip_path = self._make_zip({})
        result = _parse_markdown_pages(zip_path, [1])
        assert result == {}

    def test_ignores_macosx_metadata(self):
        from app.providers.ocr_sarvam import _parse_markdown_pages

        zip_path = self._make_zip({
            "__MACOSX/._page_1.md": "metadata",
            "page_1.md": "Real content",
        })
        result = _parse_markdown_pages(zip_path, [1])
        assert len(result) == 1
        assert result[1] == "Real content"

    def test_natural_sort_order(self):
        """page_2.md should come before page_10.md."""
        from app.providers.ocr_sarvam import _parse_markdown_pages

        zip_path = self._make_zip({
            "page_1.md": "First",
            "page_10.md": "Tenth",
            "page_2.md": "Second",
        })
        result = _parse_markdown_pages(zip_path, [1, 2, 3])

        assert result[1] == "First"
        assert result[2] == "Second"
        assert result[3] == "Tenth"


class TestOcrPdfChunk:
    """Test ocr_pdf_chunk with mocked Sarvam SDK."""

    @patch("app.providers.ocr_sarvam._extract_pages_pdf")
    @patch("app.providers.ocr_sarvam._parse_markdown_pages")
    def test_successful_chunk(self, mock_parse, mock_extract):
        from app.providers.ocr_sarvam import ocr_pdf_chunk

        mock_extract.return_value = Path("/tmp/fake_chunk.pdf")

        mock_parse.return_value = {
            1: "ಕನ್ನಡ ಪಠ್ಯ",
            2: "ಇನ್ನಷ್ಟು ಪಠ್ಯ",
        }

        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_client.document_intelligence.create_job.return_value = mock_job
        mock_status = MagicMock()
        mock_status.job_state = "Completed"
        mock_job.wait_until_complete.return_value = mock_status

        mock_sarvamai = MagicMock()
        mock_sarvamai.SarvamAI.return_value = mock_client
        with patch.dict("sys.modules", {"sarvamai": mock_sarvamai}):
            with patch("app.config.SARVAM_API_KEY", "test-key"):
                result = ocr_pdf_chunk(Path("/tmp/test.pdf"), [1, 2], "kn-IN")

        assert len(result) == 2
        assert result[1]["text"] == "ಕನ್ನಡ ಪಠ್ಯ"
        assert result[1]["tokens"] == []
        assert result[1]["pass_similarity"] == 1.0
        assert result[2]["text"] == "ಇನ್ನಷ್ಟು ಪಠ್ಯ"

    @patch("app.providers.ocr_sarvam.time.sleep")
    @patch("app.providers.ocr_sarvam._extract_pages_pdf")
    def test_api_failure_retries_then_returns_empty(self, mock_extract, mock_sleep):
        from app.providers.ocr_sarvam import ocr_pdf_chunk

        mock_extract.return_value = Path("/tmp/fake_chunk.pdf")

        mock_sarvamai = MagicMock()
        mock_sarvamai.SarvamAI.side_effect = Exception("API down")
        with patch.dict("sys.modules", {"sarvamai": mock_sarvamai}):
            with patch("app.config.SARVAM_API_KEY", "test-key"):
                result = ocr_pdf_chunk(Path("/tmp/test.pdf"), [1, 2, 3], "kn-IN")

        assert len(result) == 3
        for pn in [1, 2, 3]:
            assert result[pn]["text"] == ""
        assert mock_sleep.call_count == 2

    @patch("app.providers.ocr_sarvam.time.sleep")
    @patch("app.providers.ocr_sarvam._extract_pages_pdf")
    @patch("app.providers.ocr_sarvam._parse_markdown_pages")
    def test_retry_succeeds_on_second_attempt(self, mock_parse, mock_extract, mock_sleep):
        from app.providers.ocr_sarvam import ocr_pdf_chunk

        mock_extract.return_value = Path("/tmp/fake_chunk.pdf")
        mock_parse.return_value = {1: "ಕನ್ನಡ"}

        call_count = {"n": 0}

        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_client.document_intelligence.create_job.return_value = mock_job
        mock_status = MagicMock()
        mock_status.job_state = "Completed"
        mock_job.wait_until_complete.return_value = mock_status

        mock_sarvamai = MagicMock()

        def _client_factory(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("Transient failure")
            return mock_client

        mock_sarvamai.SarvamAI.side_effect = _client_factory
        with patch.dict("sys.modules", {"sarvamai": mock_sarvamai}):
            with patch("app.config.SARVAM_API_KEY", "test-key"):
                result = ocr_pdf_chunk(Path("/tmp/test.pdf"), [1], "kn-IN")

        assert result[1]["text"] == "ಕನ್ನಡ"
        assert mock_sleep.call_count == 1


class TestOcrPagesParallel:
    """Test parallel orchestration."""

    @patch("app.providers.ocr_sarvam.ocr_pdf_chunk")
    def test_splits_into_chunks(self, mock_chunk):
        from app.providers.ocr_sarvam import ocr_pages_parallel

        def _fake_chunk(pdf_path, page_numbers, lang):
            return {
                pn: {"page_number": pn, "text": f"Page {pn}", "tokens": [], "pass_similarity": 1.0, "layout": "text"}
                for pn in page_numbers
            }
        mock_chunk.side_effect = _fake_chunk

        result = ocr_pages_parallel(
            Path("/tmp/test.pdf"),
            pages=[1, 2, 3, 4, 5, 6, 7],
            sarvam_lang="kn-IN",
            chunk_size=3,
        )

        assert len(result) == 7
        for pn in range(1, 8):
            assert result[pn]["text"] == f"Page {pn}"

        assert mock_chunk.call_count == 3

    @patch("app.providers.ocr_sarvam.ocr_pdf_chunk")
    def test_empty_pages_returns_empty(self, mock_chunk):
        from app.providers.ocr_sarvam import ocr_pages_parallel

        result = ocr_pages_parallel(
            Path("/tmp/test.pdf"),
            pages=[],
            sarvam_lang="kn-IN",
        )
        assert result == {}
        mock_chunk.assert_not_called()

    @patch("app.providers.ocr_sarvam.ocr_pdf_chunk")
    def test_chunk_failure_returns_empty_for_those_pages(self, mock_chunk):
        from app.providers.ocr_sarvam import ocr_pages_parallel

        def _fail_second(pdf_path, page_numbers, lang):
            if 4 in page_numbers:
                raise RuntimeError("Chunk failed")
            return {
                pn: {"page_number": pn, "text": f"Page {pn}", "tokens": [], "pass_similarity": 1.0, "layout": "text"}
                for pn in page_numbers
            }
        mock_chunk.side_effect = _fail_second

        result = ocr_pages_parallel(
            Path("/tmp/test.pdf"),
            pages=[1, 2, 3, 4, 5, 6],
            sarvam_lang="kn-IN",
            chunk_size=3,
        )

        assert result[1]["text"] == "Page 1"
        assert result[4]["text"] == ""
        assert result[5]["text"] == ""
        assert result[6]["text"] == ""

    @patch("app.providers.ocr_sarvam.ocr_pdf_chunk")
    def test_non_contiguous_pages_no_extra(self, mock_chunk):
        """Non-contiguous pages should NOT include unrequested pages."""
        from app.providers.ocr_sarvam import ocr_pages_parallel

        def _track_chunk(pdf_path, page_numbers, lang):
            return {
                pn: {"page_number": pn, "text": f"Page {pn}", "tokens": [], "pass_similarity": 1.0, "layout": "text"}
                for pn in page_numbers
            }
        mock_chunk.side_effect = _track_chunk

        result = ocr_pages_parallel(
            Path("/tmp/test.pdf"),
            pages=[1, 3, 7, 12],
            sarvam_lang="kn-IN",
            chunk_size=2,
        )

        assert set(result.keys()) == {1, 3, 7, 12}
        assert 2 not in result
        assert 8 not in result


class TestLanguageRouterSarvam:
    """Verify Sarvam lang is set correctly in OCR router."""

    def test_english_has_no_sarvam_lang(self):
        from app.ocr_router import resolve_ocr_config

        config = resolve_ocr_config(language="english")
        assert config.sarvam_lang is None

    def test_kannada_has_sarvam_lang(self):
        from app.ocr_router import resolve_ocr_config

        config = resolve_ocr_config(language="kannada")
        assert config.sarvam_lang == "kn-IN"

    def test_hindi_has_sarvam_lang(self):
        from app.ocr_router import resolve_ocr_config

        config = resolve_ocr_config(language="hindi")
        assert config.sarvam_lang == "hi-IN"

    def test_tamil_has_sarvam_lang(self):
        from app.ocr_router import resolve_ocr_config

        config = resolve_ocr_config(language="tamil")
        assert config.sarvam_lang == "ta-IN"

    def test_telugu_has_sarvam_lang(self):
        from app.ocr_router import resolve_ocr_config

        config = resolve_ocr_config(language="telugu")
        assert config.sarvam_lang == "te-IN"
