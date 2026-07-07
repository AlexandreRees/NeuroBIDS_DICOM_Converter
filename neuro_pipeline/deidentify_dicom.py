#!/usr/bin/env python3
"""Deprecated — use neuro_pipeline.release_dataset or neuro-release instead."""

from __future__ import annotations

import sys
import warnings

from neuro_pipeline.release_dataset import main as release_main


def main(argv: list[str] | None = None) -> int:
    """Deprecated wrapper for public-release anonymization."""
    warnings.warn(
        "neuro-deidentify is deprecated; use neuro-release or "
        "python -m neuro_pipeline.run_release_pipeline",
        DeprecationWarning,
        stacklevel=2,
    )
    return release_main(argv)


if __name__ == "__main__":
    sys.exit(main())
