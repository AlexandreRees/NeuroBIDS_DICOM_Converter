"""Batch-conversion specific exceptions."""

from __future__ import annotations

from neuro_pipeline.utils.exceptions import NeuroPipelineError


class BatchError(NeuroPipelineError):
    """Base error for batch conversion operations."""


class BatchResumeError(BatchError):
    """Raised when a previous batch state cannot be resumed safely."""


class BatchJobNotFoundError(BatchError):
    """Raised when a requested batch job id is unknown."""


class BatchPausedError(BatchError):
    """Raised when a batch run is stopped because the user paused it."""
