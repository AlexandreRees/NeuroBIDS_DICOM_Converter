"""Shared utilities for the neuroimaging BIDS pipeline."""

from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError, PipelineWarning
from neuro_pipeline.config.extensions import PIPELINE_VERSION, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import COHORT_NAMES, ProjectPaths, resolve_project_root

__all__ = [
    "COHORT_NAMES",
    "FatalPipelineError",
    "PIPELINE_VERSION",
    "PipelineWarning",
    "ProjectPaths",
    "build_base_parser",
    "configure_logging",
    "resolve_project_root",
    "write_manifest",
]
