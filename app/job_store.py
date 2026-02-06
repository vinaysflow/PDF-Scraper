"""In-memory job store for async extraction jobs with optional disk persistence.

Thread-safe. Each job goes through: pending -> processing -> completed | failed.

When JOB_STORE_DIR is set, completed/failed jobs are persisted to disk as JSON
so results survive server restarts.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "processing", "completed", "failed"]

# In-memory TTL: evict entries older than 1 hour to prevent unbounded growth.
_IN_MEMORY_TTL_SECONDS = 3600


class _JobEntry:
    __slots__ = ("status", "result", "error", "created_at", "updated_at", "filename")

    def __init__(self) -> None:
        now = time.time()
        self.status: JobStatus = "pending"
        self.result: Any | None = None
        self.error: str | None = None
        self.created_at: float = now
        self.updated_at: float = now
        self.filename: str | None = None


class JobStore:
    """Thread-safe job store with optional disk persistence."""

    def __init__(self, persist_dir: str | None = None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, _JobEntry] = {}
        self._persist_dir: Path | None = Path(persist_dir) if persist_dir else None
        if self._persist_dir:
            self._persist_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create_job(self) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._evict_old()
            entry = _JobEntry()
            self._jobs[job_id] = entry
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is not None:
                return self._entry_to_dict(entry)

        # Try disk if not in memory
        if self._persist_dir:
            disk_path = self._persist_dir / f"{job_id}.json"
            if disk_path.exists():
                try:
                    data = json.loads(disk_path.read_text())
                    return data
                except Exception:
                    logger.warning("Failed to read persisted job %s", job_id)

        return None

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
                self._persist_to_disk(job_id, entry)

    def set_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is not None:
                entry.status = "failed"
                entry.error = error
                entry.updated_at = time.time()
                self._persist_to_disk(job_id, entry)

    def list_jobs(self, status_filter: str | None = None) -> list[dict]:
        """Return a list of job summaries (no result payloads)."""
        jobs: list[dict] = []
        with self._lock:
            for job_id, entry in self._jobs.items():
                if status_filter and entry.status != status_filter:
                    continue
                jobs.append({
                    "job_id": job_id,
                    "status": entry.status,
                    "created_at": entry.created_at,
                    "updated_at": entry.updated_at,
                    "filename": entry.filename,
                })

        # Also scan disk for completed jobs not in memory
        if self._persist_dir:
            in_memory_ids = {j["job_id"] for j in jobs}
            for path in self._persist_dir.glob("*.json"):
                jid = path.stem
                if jid in in_memory_ids:
                    continue
                try:
                    data = json.loads(path.read_text())
                    disk_status = data.get("status", "unknown")
                    if status_filter and disk_status != status_filter:
                        continue
                    jobs.append({
                        "job_id": jid,
                        "status": disk_status,
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "filename": data.get("filename"),
                    })
                except Exception:
                    pass

        return sorted(jobs, key=lambda j: j.get("created_at") or 0, reverse=True)

    def set_filename(self, job_id: str, filename: str) -> None:
        """Associate an original filename with a job."""
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is not None:
                entry.filename = filename

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    @staticmethod
    def _entry_to_dict(entry: _JobEntry) -> dict:
        return {
            "status": entry.status,
            "result": entry.result,
            "error": entry.error,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "filename": entry.filename,
        }

    def _persist_to_disk(self, job_id: str, entry: _JobEntry) -> None:
        """Write a completed/failed job to disk (called under lock)."""
        if not self._persist_dir:
            return
        try:
            data = self._entry_to_dict(entry)
            disk_path = self._persist_dir / f"{job_id}.json"
            disk_path.write_text(json.dumps(data, default=str))
        except Exception:
            logger.warning("Failed to persist job %s to disk", job_id)

    def _evict_old(self) -> None:
        """Remove in-memory entries older than TTL (called under lock)."""
        now = time.time()
        stale = [
            jid
            for jid, entry in self._jobs.items()
            if (now - entry.updated_at) > _IN_MEMORY_TTL_SECONDS
            and entry.status in ("completed", "failed")
        ]
        for jid in stale:
            del self._jobs[jid]


# Module-level singleton used by worker and API.
_persist_dir = os.environ.get("JOB_STORE_DIR", "")
store = JobStore(persist_dir=_persist_dir if _persist_dir else None)
