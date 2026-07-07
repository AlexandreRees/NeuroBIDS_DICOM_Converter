"""Canonical pipeline step names for research and public-release workflows."""

from __future__ import annotations

# Internal research pipeline: DICOM discovery → BIDS dataset for analysis.
RESEARCH_PIPELINE_STEPS: tuple[tuple[str, str], ...] = (
    ("inventory", "neuro_pipeline.inventory"),
    ("generate_mapping", "neuro_pipeline.generate_mapping"),
    ("convert_to_bids", "neuro_pipeline.convert_to_bids"),
    ("validate_dataset", "neuro_pipeline.validate_dataset"),
    ("quality_control", "neuro_pipeline.quality_control"),
    ("derivatives_build", "neuro_pipeline.derivatives_build"),
)

RESEARCH_STEP_NAMES: tuple[str, ...] = tuple(name for name, _ in RESEARCH_PIPELINE_STEPS)

# Public release pipeline: anonymize raw_bids for external sharing (run separately).
RELEASE_PIPELINE_STEPS: tuple[tuple[str, str], ...] = (
    ("anonymize", "neuro_pipeline.release_dataset"),
    ("validate_public_dataset", "neuro_pipeline.validate_public_dataset"),
    ("release_gate", "neuro_pipeline.release_gate"),
)

RELEASE_STEP_NAMES: tuple[str, ...] = tuple(name for name, _ in RELEASE_PIPELINE_STEPS)
