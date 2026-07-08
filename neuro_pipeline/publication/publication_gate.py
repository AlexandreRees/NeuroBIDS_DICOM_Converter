"""Deprecated — use neuro_pipeline.publication.release_gate instead."""

from __future__ import annotations

import warnings

from neuro_pipeline.publication.release_gate import main as release_gate_main


def main(argv: list[str] | None = None) -> int:
    """Deprecated wrapper for the public-release gate."""
    warnings.warn(
        "publication_gate is deprecated; use neuro-release-gate or "
        "python -m neuro_pipeline.workflows.run_release_pipeline",
        DeprecationWarning,
        stacklevel=2,
    )
    return release_gate_main(argv)
