"""Domain models for DICOM series and conversion jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SeriesStatus(str, Enum):
    """Lifecycle status of a detected DICOM series."""

    PENDING = "Pending"
    CONVERTING = "Converting"
    DONE = "Done"
    FAILED = "Failed"
    SKIPPED = "Skipped"


@dataclass(slots=True)
class DicomSeries:
    """Metadata for one DICOM series discovered during folder scan."""

    patient_id: str
    study_description: str
    series_description: str
    protocol_name: str
    series_number: int | None
    acquisition_number: int | None
    modality: str
    num_images: int
    source_dir: Path
    sample_file: Path
    status: SeriesStatus = SeriesStatus.PENDING
    smart_name: str = ""
    message: str = ""
    sequence_type: str = "unknown"
    series_instance_uid: str = ""
    study_instance_uid: str = ""
    fine_sequence_type: str = ""
    sequence_confidence: float = 0.0
    bids_suffix: str = ""
    detection_confidence: float = 0.0
    detection_label: str = ""
    detection_plugin: str = ""
    requires_manual_mapping: bool = False
    # Original DICOM PatientID when patient_id was remapped for multi-folder routing.
    dicom_patient_id: str = ""
    source_subject_folder: str = ""
    subject_detection_method: str = ""
    # Format / convertibility metadata (populated at scan; never from pixels)
    sop_class_uid: str = ""
    transfer_syntax_uid: str = ""
    number_of_frames: int | None = None
    dicom_object_class: str = ""
    convertibility: str = ""
    convertible_to_nifti: bool = True

    @property
    def display_name(self) -> str:
        """Human-readable series label for tables and logs."""
        desc = self.series_description or self.protocol_name or "Unknown"
        if self.series_number is not None:
            return f"{self.series_number:03d}_{desc}"
        return desc

    def to_row(self) -> tuple[str, str, str, str, str]:
        """Return columns used by the GUI series table."""
        return (
            self.display_name,
            self.modality or "—",
            self.sequence_type or "unknown",
            str(self.num_images),
            self.status.value,
        )


@dataclass(slots=True)
class ConversionOptions:
    """User-selected conversion options mirrored from the GUI."""

    compress: bool = True
    one_folder_per_patient: bool = True
    preserve_json: bool = True
    smart_naming: bool = True
    validate_output: bool = True
    output_layout: str = "nifti"  # "nifti" | "bids"
    subject_id: str = ""  # REQUIRED for BIDS — never inferred from folder
    session_id: str = ""  # bare label or ses-* ; empty → no session folder
    study_mode: str = "single"  # "single" | "longitudinal"
    session_queue: list[str] = field(default_factory=list)
    export_profile: str = ""  # "" | "bids" | "clinical" | "archive"
    threads: int = 4
    dcm2niix_path: str = "auto"


@dataclass(slots=True)
class ConversionJob:
    """One series conversion unit of work."""

    series: DicomSeries
    output_dir: Path
    options: ConversionOptions


@dataclass(slots=True)
class ConversionResult:
    """Outcome of converting a single series."""

    series: DicomSeries
    success: bool
    command: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    output_files: list[Path] = field(default_factory=list)
    error: str = ""

    def as_log_extra(self) -> dict[str, Any]:
        """Structured fields for the conversion logger."""
        return {
            "patient": self.series.patient_id,
            "series": self.series.display_name,
            "command": " ".join(self.command),
            "duration": f"{self.duration_seconds:.2f}s",
            "error": self.error,
        }


@dataclass(slots=True)
class ProgressInfo:
    """Aggregated progress reported to the GUI during conversion."""

    current_series: str = ""
    converted: int = 0
    remaining: int = 0
    total: int = 0
    percent: float = 0.0
    estimated_seconds_remaining: float | None = None
    message: str = ""

    @property
    def eta_text(self) -> str:
        if self.estimated_seconds_remaining is None:
            return "Estimating…"
        seconds = max(0, int(self.estimated_seconds_remaining))
        minutes, secs = divmod(seconds, 60)
        if minutes:
            return f"~{minutes}m {secs}s remaining"
        return f"~{secs}s remaining"
