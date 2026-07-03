"""Pipeline error taxonomy for fatal failures vs recoverable warnings."""

from __future__ import annotations


class PipelineError(Exception):
    """Base exception for pipeline failures."""

    def __init__(self, message: str) -> None:
        """Initialize with a human-readable message."""
        super().__init__(message)
        self.message = message


class FatalPipelineError(PipelineError):
    """Unrecoverable error that must halt pipeline execution."""


class PipelineWarning(PipelineError):
    """Recoverable issue; pipeline may continue after logging."""
