"""Tests for app.config."""

from __future__ import annotations

import os
import unittest


class TestConfig(unittest.TestCase):
    """Test that config values are read from env and have sensible defaults."""

    def test_defaults_when_env_clean(self) -> None:
        """With no env overrides, defaults should be used."""
        # Config is read at import time — we just check the values make sense.
        from app.config import (
            ASYNC_MAX_PAGES,
            MAX_FILE_SIZE_BYTES,
            SAFE_BATCH_PAGES,
            SAFE_DPI,
            SYNC_MAX_PAGES,
        )
        self.assertGreater(SYNC_MAX_PAGES, 0)
        self.assertGreater(ASYNC_MAX_PAGES, SYNC_MAX_PAGES)
        self.assertGreater(SAFE_DPI, 0)
        self.assertGreater(SAFE_BATCH_PAGES, 0)
        self.assertGreater(MAX_FILE_SIZE_BYTES, 0)

    def test_log_startup_config_runs(self) -> None:
        from app.config import log_startup_config
        # Should not raise.
        log_startup_config()


if __name__ == "__main__":
    unittest.main()
