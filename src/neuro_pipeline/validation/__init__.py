"""Post-conversion validation package."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.validation.dwi_validator import DiffusionValidator
from neuro_pipeline.validation.metadata_validator import MetadataValidator
from neuro_pipeline.validation.models import (
    DWIValidationResult,
    MetadataValidationResult,
    ValidationResult,
    ValidationStatus,
    ValidationSummary,
)
from neuro_pipeline.validation.nifti_validator import NiftiValidator
from neuro_pipeline.validation.report_generator import ReportContext, ReportGenerator


def run_full_validation(output_directory: Path | str) -> ValidationSummary:
    """Run NIfTI + DWI + metadata validators on an output tree."""
    root = Path(output_directory)
    return ValidationSummary(
        nifti_results=NiftiValidator(root).validate_all(),
        dwi_results=DiffusionValidator(root).validate_all(),
        metadata_results=MetadataValidator(root).validate_all(),
    )


__all__ = [
    "DiffusionValidator",
    "DWIValidationResult",
    "MetadataValidationResult",
    "MetadataValidator",
    "NiftiValidator",
    "ReportContext",
    "ReportGenerator",
    "ValidationResult",
    "ValidationStatus",
    "ValidationSummary",
    "run_full_validation",
]
