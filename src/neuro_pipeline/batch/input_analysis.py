"""Input-folder analysis driven by recursive discovery + series list."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from neuro_pipeline.discovery.models import DiscoveryMode, DiscoveryResult
from neuro_pipeline.models import DicomSeries

LOGGER = logging.getLogger(__name__)

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


@dataclass(slots=True)
class SubjectSummary:
    """One reconstructed subject group under the input folder."""

    patient_id: str
    subject_label: str
    series_count: int
    study_count: int
    dicom_files: int
    study_uids: list[str] = field(default_factory=list)
    series_uids: list[str] = field(default_factory=list)
    source_folder: str = ""
    source_folder_path: str = ""
    detection_method: str = ""
    original_patient_id: str = ""
    reason: str = ""


@dataclass(slots=True)
class InputAnalysis:
    """Result of recursively analysing a DICOM folder tree."""

    folder: str
    number_of_subjects: int = 0
    number_of_studies: int = 0
    number_of_series: int = 0
    number_of_dicom_files: int = 0
    subjects: list[SubjectSummary] = field(default_factory=list)
    series: list[DicomSeries] = field(default_factory=list)
    message: str = ""
    subject_grouping: str = "patient_id"
    detection_method: str = ""
    detection_reason: str = ""
    discovery_mode: str = DiscoveryMode.AUTOMATIC.value

    @property
    def has_dicom(self) -> bool:
        if self.number_of_dicom_files > 0 or self.number_of_series > 0:
            return True
        return any((s.dicom_files > 0 or s.series_count > 0) for s in self.subjects)

    def summary_text(self) -> str:
        """Human-readable text for the GUI Input analysis panel."""
        if self.message and not self.has_dicom:
            return self.message
        if not self.has_dicom:
            return "No DICOM files detected."

        lines = [
            f"Detected subjects: {self.number_of_subjects}",
            "",
        ]
        method = self.detection_method or self.subject_grouping
        if method:
            lines.append(f"Detection method: {_pretty_method(method)}")
        if self.detection_reason:
            lines.append(f"Reason: {self.detection_reason}")
        lines.append("")

        if self.number_of_subjects == 1:
            subj = self.subjects[0]
            lines.append(f"{subj.subject_label or subj.patient_id}")
            if subj.source_folder_path:
                lines.append(f"Source: {subj.source_folder_path}")
            elif subj.source_folder:
                lines.append(f"Source: {subj.source_folder}")
            lines.append(f"DICOM files: {subj.dicom_files}")
            lines.append(f"Series: {subj.series_count}")
            if subj.study_count:
                lines.append(f"Studies: {subj.study_count}")
        else:
            for subj in self.subjects:
                label = subj.subject_label or subj.patient_id
                lines.append(label)
                if subj.source_folder_path:
                    lines.append(f"  Source: {subj.source_folder_path}")
                elif subj.source_folder:
                    lines.append(f"  Source: {subj.source_folder}")
                if subj.original_patient_id:
                    lines.append(f"  Original PatientID: {subj.original_patient_id}")
                lines.append(f"  DICOM files: {subj.dicom_files}")
                lines.append(f"  Series: {subj.series_count}")
                lines.append("")
        lines.extend(["Output:", "BIDS dataset"])
        return "\n".join(lines)

    @classmethod
    def from_discovery(
        cls,
        series: list[DicomSeries],
        discovery: DiscoveryResult,
        *,
        folder: Path | str | None = None,
    ) -> InputAnalysis:
        """Build analysis from DatasetDiscovery + routed series."""
        root = str(folder or discovery.input_root)
        by_label: dict[str, list[DicomSeries]] = defaultdict(list)
        for item in series:
            by_label[(item.patient_id or "unknown").strip() or "unknown"].append(item)

        subjects: list[SubjectSummary] = []
        total_studies: set[str] = set()
        total_files = 0

        # Prefer discovery subject order
        seen: set[str] = set()
        ordered_labels: list[str] = [s.bids_subject for s in discovery.subjects]
        for label in list(by_label.keys()):
            if label not in ordered_labels:
                ordered_labels.append(label)

        disc_by_label = {s.bids_subject: s for s in discovery.subjects}

        for label in ordered_labels:
            items = by_label.get(label) or []
            if not items and label not in disc_by_label:
                continue
            disc = disc_by_label.get(label)
            study_uids = sorted(
                {
                    (getattr(s, "study_instance_uid", None) or "").strip()
                    for s in items
                    if (getattr(s, "study_instance_uid", None) or "").strip()
                }
            )
            files = int(sum(int(s.num_images or 0) for s in items))
            if disc is not None and disc.dicom_files:
                files = max(files, int(disc.dicom_files))
            total_files += files
            for uid in study_uids:
                total_studies.add(f"{label}::{uid}")
            original = ""
            if items:
                original = items[0].dicom_patient_id or ""
            if disc is not None and disc.dicom_patient_id:
                original = disc.dicom_patient_id
            series_uids = sorted(
                {
                    (s.series_instance_uid or "").strip()
                    for s in items
                    if (s.series_instance_uid or "").strip()
                }
            )
            if disc is not None and disc.series_uids:
                # Union: discovery-level UIDs + series that survived parser routing
                series_uids = sorted(set(series_uids) | set(disc.series_uids))
            subjects.append(
                SubjectSummary(
                    patient_id=label,
                    subject_label=sanitize_patient_id(label),
                    series_count=len(items) or (len(disc.series_uids) if disc else 0),
                    study_count=len(study_uids) or (len(disc.study_uids) if disc else 0),
                    dicom_files=files,
                    study_uids=study_uids,
                    series_uids=series_uids,
                    source_folder=(disc.source_folder if disc else "")
                    or (items[0].source_subject_folder if items else ""),
                    source_folder_path=(disc.source_folder_path if disc else "")
                    or "",
                    detection_method=(disc.detection_method if disc else discovery.detection_method),
                    original_patient_id=original,
                    reason=(disc.reason if disc else discovery.reason),
                )
            )
            seen.add(label)

        return cls(
            folder=root,
            number_of_subjects=len(subjects),
            number_of_studies=len(total_studies),
            number_of_series=len(series),
            number_of_dicom_files=total_files or discovery.n_dicom_files,
            subjects=subjects,
            series=list(series),
            subject_grouping=discovery.detection_method or "patient_id",
            detection_method=discovery.detection_method,
            detection_reason=discovery.reason,
            discovery_mode=discovery.mode,
        )

    @classmethod
    def from_series(
        cls,
        series: list[DicomSeries],
        *,
        folder: Path | str,
        discovery: DiscoveryResult | None = None,
        discovery_mode: DiscoveryMode | str = DiscoveryMode.AUTOMATIC,
    ) -> InputAnalysis:
        """Build analysis from series; optionally attach / run discovery routing."""
        series = list(series)
        root = Path(folder)
        if discovery is not None:
            return cls.from_discovery(series, discovery, folder=root)

        # Backward-compatible path: group by (already routed) patient_id on series
        by_patient: dict[str, list[DicomSeries]] = defaultdict(list)
        for item in series:
            pid = (item.patient_id or "Unknown").strip() or "Unknown"
            by_patient[pid].append(item)

        subjects: list[SubjectSummary] = []
        total_studies: set[str] = set()
        total_files = 0
        method = "patient_id"
        if any(s.subject_detection_method for s in series):
            method = next(
                (s.subject_detection_method for s in series if s.subject_detection_method),
                "patient_id",
            )
        for patient_id in sorted(by_patient.keys()):
            items = by_patient[patient_id]
            study_uids = sorted(
                {
                    (getattr(s, "study_instance_uid", None) or s.study_description or "").strip()
                    for s in items
                    if (getattr(s, "study_instance_uid", None) or s.study_description or "").strip()
                }
            )
            files = int(sum(int(s.num_images or 0) for s in items))
            total_files += files
            for uid in study_uids:
                total_studies.add(f"{patient_id}::{uid}")
            subjects.append(
                SubjectSummary(
                    patient_id=patient_id,
                    subject_label=sanitize_patient_id(patient_id),
                    series_count=len(items),
                    study_count=len(study_uids),
                    dicom_files=files,
                    study_uids=study_uids,
                    series_uids=sorted(
                        {
                            (s.series_instance_uid or "").strip()
                            for s in items
                            if (s.series_instance_uid or "").strip()
                        }
                    ),
                    source_folder=items[0].source_subject_folder if items else "",
                    source_folder_path="",
                    detection_method=items[0].subject_detection_method if items else method,
                    original_patient_id=items[0].dicom_patient_id if items else "",
                )
            )

        return cls(
            folder=str(folder),
            number_of_subjects=len(subjects),
            number_of_studies=len(total_studies),
            number_of_series=len(series),
            number_of_dicom_files=total_files,
            subjects=subjects,
            series=list(series),
            subject_grouping=method,
            detection_method=method,
            detection_reason="",
            discovery_mode=str(discovery_mode),
        )

    @classmethod
    def empty(cls, folder: Path | str, *, message: str = "No DICOM files detected.") -> InputAnalysis:
        return cls(folder=str(folder), message=message)


def sanitize_patient_id(patient_id: str) -> str:
    """Convert a DICOM PatientID / folder name into a BIDS-safe subject label."""
    cleaned = _NON_ALNUM.sub("", str(patient_id or "").strip())
    if not cleaned:
        return "unknown"
    return cleaned


def _pretty_method(method: str) -> str:
    mapping = {
        "patient_id": "PatientID",
        "folder_based": "Folder based grouping",
        "deep_folder": "Deep recursive folder inference",
        "single": "Single subject",
        "none": "None",
    }
    return mapping.get(method, method)
