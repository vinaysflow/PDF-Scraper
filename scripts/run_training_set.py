#!/usr/bin/env python3
"""Run batch quality evaluation on the training/test PDF set."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Default: Sample PDF FOR TESTING folder (training PDFs for this model)
DEFAULT_TRAINING_PDF_DIR = Path.home() / "Downloads" / "Sample PDF FOR TESTING"


def main() -> int:
    training_dir = Path(
        os.environ.get("TRAINING_PDF_DIR", str(DEFAULT_TRAINING_PDF_DIR))
    )
    if not training_dir.is_dir():
        print(f"Error: training PDF dir not found: {training_dir}", file=sys.stderr)
        return 1

    pdfs = sorted(training_dir.glob("*.pdf"))
    if not pdfs:
        print(f"Error: no PDFs in {training_dir}", file=sys.stderr)
        return 1

    # Delegate to quality_batch with the resolved PDF paths; pass through CLI args
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.quality_batch import main as batch_main

    sys.argv = ["quality_batch"] + [str(p) for p in pdfs] + sys.argv[1:]
    return batch_main()


if __name__ == "__main__":
    raise SystemExit(main())
