"""Canonical pipeline step names for research and public-release workflows."""

from __future__ import annotations

# Internal research pipeline: DICOM discovery → BIDS dataset for analysis.
RESEARCH_PIPELINE_STEPS: tuple[tuple[str, str], ...] = (
    ("inventory", "neuro_pipeline.acquisition.inventory"),
    ("generate_mapping", "neuro_pipeline.anonymization.mapping"),
    ("convert_to_bids", "neuro_pipeline.conversion.convert_to_bids"),
    ("validate_dataset", "neuro_pipeline.validation.validate_dataset"),
    ("quality_control", "neuro_pipeline.qc.quality_control"),
    ("derivatives_build", "neuro_pipeline.derivatives.build"),
)

RESEARCH_STEP_NAMES: tuple[str, ...] = tuple(name for name, _ in RESEARCH_PIPELINE_STEPS)

# Public release pipeline: anonymize raw_bids for external sharing (run separately).
RELEASE_PIPELINE_STEPS: tuple[tuple[str, str], ...] = (
    ("anonymize", "neuro_pipeline.publication.release"),
    ("validate_public_dataset", "neuro_pipeline.validation.validate_public_dataset"),
    ("release_gate", "neuro_pipeline.publication.release_gate"),
)

RELEASE_STEP_NAMES: tuple[str, ...] = tuple(name for name, _ in RELEASE_PIPELINE_STEPS)
