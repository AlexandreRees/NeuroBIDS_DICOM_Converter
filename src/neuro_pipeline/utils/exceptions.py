"""Custom application exceptions."""

from __future__ import annotations


class NeuroPipelineError(Exception):
    """Base class for expected, user-facing application errors."""


class Dcm2niixNotFoundError(NeuroPipelineError):
    """Raised when the dcm2niix binary cannot be located."""


class MissingDcm2niixError(Dcm2niixNotFoundError):
    """Alias preferred by the public API / GUI messages."""


class EmptyFolderError(NeuroPipelineError):
    """Raised when the selected input folder is empty."""


class NonDicomFolderError(NeuroPipelineError):
    """Raised when no readable DICOM series are found."""


class InvalidDicomFolderError(NonDicomFolderError):
    """Alias for non-DICOM / invalid DICOM folder errors."""


class PermissionDeniedError(NeuroPipelineError):
    """Raised when filesystem permissions prevent read/write."""


class OutputFolderError(NeuroPipelineError):
    """Raised for existing or unusable output folders."""


class ConversionFailedError(NeuroPipelineError):
    """Raised when dcm2niix exits with a non-zero status."""


class CorruptedDicomError(NeuroPipelineError):
    """Raised when a DICOM file cannot be parsed."""


class ValidationError(NeuroPipelineError):
    """Raised when post-conversion validation cannot complete."""
