"""In-memory job store for async extraction jobs.

Thread-safe. Each job goes through: pending → processing → completed | failed.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Literal

JobStatus = Literal["pending", "processing", "completed", "failed"]


class _JobEntry:
    __slots__ = ("status", "result", "error", "created_at", "updated_at")

    def __init__(self) -> None:
        now = time.time()
        self.status: JobStatus = "pending"
        self.result: Any | None = None
        self.error: str | None = None
        self.created_at: float = now
        self.updated_at: float = now


class JobStore:
    """Simple thread-safe in-memory job store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, _JobEntry] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create_job(self) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            entry = _JobEntry()
            self._jobs[job_id] = entry
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                return None
            return {
                "status": entry.status,
                "result": entry.result,
                "error": entry.error,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
            }

    def set_processing(self, job_id: str) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is not None:
                entry.status = "processing"
                entry.updated_at = time.time()

    def set_completed(self, job_id: str, result: Any) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is not None:
                entry.status = "completed"
                entry.result = result
                entry.updated_at = time.time()

    def set_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is not None:
                entry.status = "failed"
                entry.error = error
                entry.updated_at = time.time()

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)


# Module-level singleton used by worker and API.
store = JobStore()
