"""Discovery models — file records and subject candidates (DICOM never modified)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class DiscoveryMode(str, Enum):
    """How subjects are reconstructed from a recursive DICOM tree."""

    AUTOMATIC = "automatic"
    PATIENT_ID = "patient_id"
    FOLDER_RECURSIVE = "folder_recursive"


class DetectionMethod(str, Enum):
    PATIENT_ID = "patient_id"
    FOLDER_BASED = "folder_based"
    DEEP_FOLDER = "deep_folder"
    SINGLE = "single"


@dataclass(slots=True)
class DicomFileRecord:
    """One DICOM file discovered during recursive scan (metadata only)."""

    filepath: Path
    parent_folder: Path
    series_instance_uid: str = ""
    study_instance_uid: str = ""
    patient_id: str = ""
    patient_name: str = ""
    study_date: str = ""
    series_description: str = ""
    protocol_name: str = ""
    series_number: int | None = None
    acquisition_number: int | None = None
    modality: str = ""
    study_description: str = ""

    def parent_chain(self, root: Path) -> list[str]:
        """Folder names from parent of file up to (not including) root."""
        names: list[str] = []
        try:
            current = self.parent_folder.resolve()
            root_r = root.resolve()
            while current != root_r and root_r in current.parents:
                names.append(current.name)
                parent = current.parent
                if parent == current:
                    break
                current = parent
        except (OSError, ValueError):
            return [self.parent_folder.name]
        return names  # [DICOM, MR, raw, visit1, SUB02] innermost first

    def relative_parts(self, root: Path) -> tuple[str, ...]:
        try:
            rel = self.filepath.resolve().relative_to(root.resolve())
            return rel.parts[:-1]  # folders only
        except (OSError, ValueError):
            return ()


@dataclass(slots=True)
class SubjectRecord:
    """One reconstructed subject (routing key), independent of raw DICOM edits."""

    bids_subject: str
    source_folder: str
    source_folder_path: str
    dicom_patient_id: str
    detection_method: str
    reason: str = ""
    dicom_files: int = 0
    series_uids: list[str] = field(default_factory=list)
    study_uids: list[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bids_subject": self.bids_subject,
            "source_folder": self.source_folder,
            "source_folder_path": self.source_folder_path,
            "dicom_patient_id": self.dicom_patient_id,
            "detection_method": self.detection_method,
            "reason": self.reason,
            "dicom_files": self.dicom_files,
            "series_count": len(self.series_uids),
            "study_count": len(self.study_uids),
            "score": self.score,
        }


@dataclass(slots=True)
class DiscoveryResult:
    """Full recursive discovery outcome for one input root."""

    input_root: str
    mode: str
    detection_method: str
    reason: str
    records: list[DicomFileRecord] = field(default_factory=list)
    subjects: list[SubjectRecord] = field(default_factory=list)
    # filepath → bids subject label (routing)
    file_to_subject: dict[str, str] = field(default_factory=dict)
    n_dicom_files: int = 0
    n_series: int = 0
    message: str = ""

    @property
    def has_dicom(self) -> bool:
        return self.n_dicom_files > 0 and bool(self.subjects)
