"""Tests for app.worker (mocked extract_pdf)."""

from __future__ import annotations

import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from app.job_store import JobStore


class TestWorker(unittest.TestCase):
    @patch("app.worker.store")
    @patch("app.worker.extract_pdf")
    def test_successful_job(self, mock_extract: MagicMock, mock_store_mod: MagicMock) -> None:
        """Worker calls extract_pdf, then sets job to completed."""
        from app.worker import _run

        fake_result = MagicMock()
        fake_result.model_dump.return_value = {"pages": []}
        mock_extract.return_value = fake_result

        # Create a temp file so the cleanup doesn't error
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4")
            tmp = f.name

        _run("job1", tmp, {"dpi": 300})

        mock_store_mod.set_processing.assert_called_once_with("job1")
        mock_store_mod.set_completed.assert_called_once_with("job1", {"pages": []})
        mock_store_mod.set_failed.assert_not_called()

    @patch("app.worker.store")
    @patch("app.worker.extract_pdf", side_effect=RuntimeError("boom"))
    def test_failed_job(self, mock_extract: MagicMock, mock_store_mod: MagicMock) -> None:
        """Worker sets job to failed on exception."""
        from app.worker import _run

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4")
            tmp = f.name

        _run("job2", tmp, {"dpi": 300})

        mock_store_mod.set_processing.assert_called_once_with("job2")
        mock_store_mod.set_failed.assert_called_once()
        self.assertIn("boom", mock_store_mod.set_failed.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
