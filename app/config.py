"""Centralized configuration for production limits and runtime flags.

All env-driven settings live here so there is a single source of truth.
Import from ``app.config`` in api.py, extract.py, etc.
"""

from __future__ import annotations

import os
import sys


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _env_int(name: str, default: int, lo: int = 1, hi: int = 10_000) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name, str(default)))))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Runtime flags
# ---------------------------------------------------------------------------
ON_RAILWAY: bool = "PORT" in os.environ
SAFE_MODE: bool = ON_RAILWAY

# ---------------------------------------------------------------------------
# Limits (conservative on Railway ~512 MB RAM, generous locally)
# ---------------------------------------------------------------------------
_SYNC_DEFAULT = 5 if ON_RAILWAY else 50
_ASYNC_DEFAULT = 100 if ON_RAILWAY else 500
SYNC_MAX_PAGES: int = _env_int("SYNC_MAX_PAGES", default=_SYNC_DEFAULT, hi=500)
ASYNC_MAX_PAGES: int = _env_int("ASYNC_MAX_PAGES", default=_ASYNC_DEFAULT, hi=1000)
SAFE_DPI: int = _env_int("SAFE_DPI", default=300, hi=1200)
SAFE_BATCH_PAGES: int = _env_int("SAFE_BATCH_PAGES", default=3, hi=20)
MAX_FILE_SIZE_BYTES: int = _env_int(
    "MAX_FILE_SIZE_BYTES", default=20 * 1024 * 1024, lo=1, hi=500 * 1024 * 1024,
)
UPLOAD_CHUNK_SIZE: int = 64 * 1024  # 64 KiB streaming chunks

# ---------------------------------------------------------------------------
# Provider feature flags (opt-in, all default off)
# ---------------------------------------------------------------------------
EXTRACT_IMAGES: bool = _env_bool("EXTRACT_IMAGES")
EXTRACT_LAYOUT: bool = _env_bool("EXTRACT_LAYOUT")
EXTRACT_TABLES: bool = _env_bool("EXTRACT_TABLES")
EXTRACT_MATH: bool = _env_bool("EXTRACT_MATH")
OCR_ENGINE: str = os.environ.get("OCR_ENGINE", "tesseract").strip().lower()


def log_startup_config() -> None:
    """Print one startup line summarising active configuration."""
    msg = (
        f"PDF OCR config: SAFE_MODE={SAFE_MODE} "
        f"SYNC_MAX_PAGES={SYNC_MAX_PAGES} ASYNC_MAX_PAGES={ASYNC_MAX_PAGES} "
        f"SAFE_DPI={SAFE_DPI} SAFE_BATCH_PAGES={SAFE_BATCH_PAGES} "
        f"MAX_FILE_SIZE_BYTES={MAX_FILE_SIZE_BYTES} "
        f"OCR_ENGINE={OCR_ENGINE} "
        f"EXTRACT_IMAGES={EXTRACT_IMAGES} EXTRACT_LAYOUT={EXTRACT_LAYOUT} "
        f"EXTRACT_TABLES={EXTRACT_TABLES} EXTRACT_MATH={EXTRACT_MATH}"
    )
    print(msg, flush=True)
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
