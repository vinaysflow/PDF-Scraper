"""Background worker for async extraction jobs.

Uses a small ThreadPoolExecutor (1–2 workers) so the ASGI event loop is not blocked.
"""

from __future__ import annotations

import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .extract import extract_pdf
from .job_store import store

# Max concurrent background jobs. Keep low in constrained envs.
_MAX_WORKERS = int(os.environ.get("ASYNC_WORKERS", "1"))
_pool = ThreadPoolExecutor(max_workers=max(1, _MAX_WORKERS))


def _run(job_id: str, pdf_path: str, extract_kwargs: dict[str, Any]) -> None:
    """Execute ``extract_pdf`` and update job store. Runs in a thread."""
    store.set_processing(job_id)
    try:
        result = extract_pdf(pdf_path, **extract_kwargs)
        store.set_completed(job_id, result.model_dump())
    except Exception as exc:
        store.set_failed(job_id, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        # Clean up temp file (created by _stream_upload_to_temp in api.py).
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except OSError:
            pass


def enqueue(job_id: str, pdf_path: str, **extract_kwargs: Any) -> None:
    """Submit an extraction job to the background thread pool."""
    _pool.submit(_run, job_id, pdf_path, extract_kwargs)
