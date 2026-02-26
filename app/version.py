"""Build version info — populated at Docker build time or read from git at runtime."""

from __future__ import annotations

import subprocess
from pathlib import Path

_commit: str | None = None


def get_commit() -> str:
    """Return the short git commit hash, cached after first call."""
    global _commit
    if _commit is not None:
        return _commit

    # 1. Check GIT_COMMIT file written during Docker build
    commit_file = Path(__file__).resolve().parent.parent / "GIT_COMMIT"
    if commit_file.exists():
        _commit = commit_file.read_text().strip() or "unknown"
        return _commit

    # 2. Fall back to live git (works in local dev)
    try:
        _commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parent.parent,
        ).decode().strip()
    except Exception:
        _commit = "unknown"
    return _commit
