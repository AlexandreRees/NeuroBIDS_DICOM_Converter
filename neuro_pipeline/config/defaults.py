"""Default parameters and pipeline configuration values."""

from __future__ import annotations

from neuro_pipeline.config.constants import BIDS_SPEC_VERSION, BIDS_VALIDATOR_NPM_VERSION
from neuro_pipeline.workflows.steps import (
    RELEASE_PIPELINE_STEPS,
    RELEASE_STEP_NAMES,
    RESEARCH_PIPELINE_STEPS,
    RESEARCH_STEP_NAMES,
)

# --- Quality control ---
MIN_VOLUME_SIZE_MB: float = 0.1

# --- Conversion geometry validation ---
GEOMETRY_TOLERANCE_MM: float = 0.05
GEOMETRY_AFFINE_TOLERANCE: float = 1e-3
GEOMETRY_ORIENTATION_TOLERANCE: float = 0.15

# --- Conversion audit ---
CONVERSION_AUDIT_TOLERANCE_MM: float = 0.05
CONVERSION_AUDIT_TOLERANCE_SEC: float = 0.001

# --- dcm2niix invocation defaults (see conversion/convert_to_bids.py) ---
DCM2NIIX_DEFAULT_ARGS: tuple[str, ...] = (
    "-b",
    "y",
    "-ba",
    "n",
    "-z",
    "y",
)

__all__ = [
    "BIDS_SPEC_VERSION",
    "BIDS_VALIDATOR_NPM_VERSION",
    "CONVERSION_AUDIT_TOLERANCE_MM",
    "CONVERSION_AUDIT_TOLERANCE_SEC",
    "DCM2NIIX_DEFAULT_ARGS",
    "GEOMETRY_AFFINE_TOLERANCE",
    "GEOMETRY_ORIENTATION_TOLERANCE",
    "GEOMETRY_TOLERANCE_MM",
    "MIN_VOLUME_SIZE_MB",
    "RELEASE_PIPELINE_STEPS",
    "RELEASE_STEP_NAMES",
    "RESEARCH_PIPELINE_STEPS",
    "RESEARCH_STEP_NAMES",
]
