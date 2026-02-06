"""Tests for app.api endpoints (sync + async)."""

from __future__ import annotations

import io
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class TestHealthAndConfig(unittest.TestCase):
    def setUp(self) -> None:
        from app.api import app
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_health(self) -> None:
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})

    def test_api_config(self) -> None:
        r = self.client.get("/api/config")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("sync_max_pages", data)
        self.assertIn("async_max_pages", data)
        self.assertIsInstance(data["sync_max_pages"], int)


class TestStreamUploadSizeLimit(unittest.TestCase):
    """Verify that oversized uploads are rejected with 413."""

    def setUp(self) -> None:
        from app.api import app
        self.client = TestClient(app, raise_server_exceptions=False)

    @patch("app.api.MAX_FILE_SIZE_BYTES", 100)
    def test_oversized_upload_returns_413(self) -> None:
        big = b"x" * 200
        r = self.client.post(
            "/api/extract",
            files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")},
        )
        self.assertEqual(r.status_code, 413)
        self.assertIn("too large", r.json()["detail"].lower())

    def test_empty_upload_returns_400(self) -> None:
        r = self.client.post(
            "/api/extract",
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("empty", r.json()["detail"].lower())


class TestAsyncSizeLimit(unittest.TestCase):
    """Verify 413 on async endpoint too."""

    def setUp(self) -> None:
        from app.api import app
        self.client = TestClient(app, raise_server_exceptions=False)

    @patch("app.api.MAX_FILE_SIZE_BYTES", 100)
    def test_async_oversized_returns_413(self) -> None:
        big = b"x" * 200
        r = self.client.post(
            "/api/extract/async",
            files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")},
        )
        self.assertEqual(r.status_code, 413)


class TestAsyncEndpoints(unittest.TestCase):
    """Test the async submit + poll flow with mocked extract_pdf."""

    def setUp(self) -> None:
        from app.api import app
        self.client = TestClient(app, raise_server_exceptions=False)

    @patch("app.worker.extract_pdf")
    def test_async_submit_and_poll(self, mock_extract: MagicMock) -> None:
        fake_result = MagicMock()
        fake_result.model_dump.return_value = {
            "doc_id": "test",
            "pages": [],
            "full_text": "hello",
        }
        mock_extract.return_value = fake_result

        pdf_bytes = b"%PDF-1.4 test content"
        r = self.client.post(
            "/api/extract/async",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        self.assertEqual(r.status_code, 202)
        data = r.json()
        self.assertIn("job_id", data)
        self.assertEqual(data["status"], "accepted")

        job_id = data["job_id"]

        # Poll until completed (should be fast with mock)
        for _ in range(20):
            time.sleep(0.2)
            poll = self.client.get(f"/api/extract/async/{job_id}")
            self.assertEqual(poll.status_code, 200)
            job = poll.json()
            if job["status"] == "completed":
                self.assertIsNotNone(job["result"])
                self.assertEqual(job["result"]["doc_id"], "test")
                break
            if job["status"] == "failed":
                self.fail(f"Job failed: {job['error']}")
        else:
            self.fail("Job did not complete within polling window")

    def test_poll_nonexistent_job_returns_404(self) -> None:
        r = self.client.get("/api/extract/async/nonexistent_id")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
