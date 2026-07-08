"""Pipeline constants, extension hooks, and stage contracts."""

from neuro_pipeline.config.constants import (
    BIDS_SPEC_VERSION,
    BIDS_VALIDATOR_NPM_VERSION,
    COHORT_NAMES,
    NIFTI_SUFFIXES,
    PIPELINE_VERSION,
)
from neuro_pipeline.config.defaults import MIN_VOLUME_SIZE_MB
from neuro_pipeline.config.extensions import EXTENSION_HOOKS, build_manifest, write_manifest

__all__ = [
    "BIDS_SPEC_VERSION",
    "BIDS_VALIDATOR_NPM_VERSION",
    "COHORT_NAMES",
    "EXTENSION_HOOKS",
    "MIN_VOLUME_SIZE_MB",
    "NIFTI_SUFFIXES",
    "PIPELINE_VERSION",
    "build_manifest",
    "write_manifest",
]
