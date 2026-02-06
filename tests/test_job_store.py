"""Tests for app.job_store."""

from __future__ import annotations

import unittest

from app.job_store import JobStore


class TestJobStore(unittest.TestCase):
    def setUp(self) -> None:
        self.store = JobStore()

    def test_create_returns_id(self) -> None:
        jid = self.store.create_job()
        self.assertIsInstance(jid, str)
        self.assertTrue(len(jid) > 0)

    def test_get_nonexistent_returns_none(self) -> None:
        self.assertIsNone(self.store.get_job("does_not_exist"))

    def test_lifecycle_pending_to_completed(self) -> None:
        jid = self.store.create_job()
        job = self.store.get_job(jid)
        self.assertEqual(job["status"], "pending")
        self.assertIsNone(job["result"])

        self.store.set_processing(jid)
        job = self.store.get_job(jid)
        self.assertEqual(job["status"], "processing")

        self.store.set_completed(jid, {"pages": []})
        job = self.store.get_job(jid)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"], {"pages": []})
        self.assertIsNone(job["error"])

    def test_lifecycle_pending_to_failed(self) -> None:
        jid = self.store.create_job()
        self.store.set_processing(jid)
        self.store.set_failed(jid, "OOM")
        job = self.store.get_job(jid)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], "OOM")
        self.assertIsNone(job["result"])

    def test_len(self) -> None:
        self.assertEqual(len(self.store), 0)
        self.store.create_job()
        self.store.create_job()
        self.assertEqual(len(self.store), 2)

    def test_multiple_jobs_independent(self) -> None:
        j1 = self.store.create_job()
        j2 = self.store.create_job()
        self.store.set_completed(j1, "result1")
        self.store.set_failed(j2, "err2")
        self.assertEqual(self.store.get_job(j1)["status"], "completed")
        self.assertEqual(self.store.get_job(j2)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
