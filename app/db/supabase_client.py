"""Supabase connection helper.

Provides a lazily-initialized Supabase client using ``SUPABASE_URL`` and
``SUPABASE_KEY`` environment variables (exposed through ``app.config``).
"""

from __future__ import annotations

import logging

from ..config import SUPABASE_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)

_client = None


def is_configured() -> bool:
    """Return True if Supabase credentials are present."""
    return bool(SUPABASE_URL and SUPABASE_KEY)


def get_client():
    """Return a cached Supabase client instance.

    Raises
    ------
    RuntimeError
        If ``SUPABASE_URL`` or ``SUPABASE_KEY`` are not set.
    ImportError
        If the ``supabase`` package is not installed.
    """
    global _client
    if _client is not None:
        return _client

    if not is_configured():
        raise RuntimeError(
            "Supabase credentials not configured. "
            "Set SUPABASE_URL and SUPABASE_KEY environment variables."
        )

    try:
        from supabase import create_client
    except ImportError as e:
        raise ImportError(
            "supabase package is not installed. "
            "Install it with: pip install supabase"
        ) from e

    _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Supabase client initialized for %s", SUPABASE_URL)
    return _client


def reset_client() -> None:
    """Reset the cached client (useful for testing)."""
    global _client
    _client = None
