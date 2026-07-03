"""Shared dataclasses for anonymization state and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from mri_anonymization.dicom_validation import DicomValidationResult

if TYPE_CHECKING:
    from mri_anonymization.paths import AnonymizationPaths

__all__ = [
    "AnonymizationState",
    "DateShift",
    "DicomValidationResult",
    "FileResult",
    "PipelineStats",
    "SubjectMapping",
    "ValidationResult",
]


@dataclass(frozen=True)
class SubjectMapping:
    """Mapping from original BIDS subject ID to anonymized ID."""

    original_subject_id: str
    anonymized_subject_id: str


@dataclass(frozen=True)
class DateShift:
    """Per-subject date shift in days."""

    subject: str
    shift_days: int


@dataclass
class FileResult:
    """Outcome of processing a single file."""

    source_path: str
    output_path: str
    subject_id: str
    file_type: str
    status: str
    message: str = ""


@dataclass
class PipelineStats:
    """Aggregate statistics for documentation and validation."""

    n_subjects: int = 0
    n_sessions: int = 0
    n_files_processed: int = 0
    n_files_skipped: int = 0
    n_files_failed: int = 0
    n_dicom_files: int = 0
    n_metadata_files: int = 0
    n_nifti_files: int = 0
    n_defaced: int = 0
    n_defacing_skipped: int = 0
    n_defacing_failed: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def n_files(self) -> int:
        """Total files touched by the pipeline."""
        return self.n_files_processed + self.n_files_skipped + self.n_files_failed


@dataclass
class ValidationResult:
    """Structured validation outcome."""

    passed: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        """Record one validation check."""
        self.checks.append((name, passed, detail))
        if not passed:
            self.passed = False


@dataclass
class AnonymizationState:
    """Shared state passed through pipeline stages."""

    subject_mappings: dict[str, str]
    date_shifts: dict[str, int]
    input_dir: Path
    paths: "AnonymizationPaths"
    preserve_patient_sex: bool
    file_results: list[FileResult] = field(default_factory=list)
    stats: PipelineStats = field(default_factory=PipelineStats)
