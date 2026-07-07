#!/usr/bin/env python3
"""Deprecated — use neuro_pipeline.release_gate instead."""

from __future__ import annotations

import sys
import warnings

from neuro_pipeline.release_gate import main as release_gate_main


def main(argv: list[str] | None = None) -> int:
    """Deprecated wrapper for the public-release gate."""
    warnings.warn(
        "publication_gate is deprecated; use neuro-release-gate or "
        "python -m neuro_pipeline.run_release_pipeline",
        DeprecationWarning,
        stacklevel=2,
    )
    return release_gate_main(argv)


if __name__ == "__main__":
    sys.exit(main())
