"""Orchestrate recursive discovery + subject mapping for the Convert pipeline.

Uses existing ``DicomParser`` for series classification (parser core unchanged).
Subject routing is applied in-memory after the scan.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from neuro_pipeline.discovery.models import DiscoveryMode, DiscoveryResult
from neuro_pipeline.discovery.recursive_discovery import RecursiveDicomScanner
from neuro_pipeline.discovery.subject_detection import SubjectDetector
from neuro_pipeline.models import DicomSeries
from neuro_pipeline.utils.exceptions import InvalidDicomFolderError

if TYPE_CHECKING:
    from neuro_pipeline.dicom import DicomParser

LOGGER = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]
StopCheck = Callable[[], bool]


class DatasetDiscovery:
    """Recursive DICOM discovery and subject reconstruction facade."""

    def __init__(
        self,
        *,
        scanner: RecursiveDicomScanner | None = None,
        detector: SubjectDetector | None = None,
        parser: DicomParser | None = None,
    ) -> None:
        from neuro_pipeline.dicom import DicomParser as _DicomParser

        self.scanner = scanner or RecursiveDicomScanner()
        self.detector = detector or SubjectDetector()
        self.parser = parser or _DicomParser()

    def discover(
        self,
        root_path: Path | str,
        *,
        mode: DiscoveryMode | str = DiscoveryMode.AUTOMATIC,
        progress: ProgressCallback | None = None,
        stop_check: StopCheck | None = None,
    ) -> DiscoveryResult:
        root = Path(root_path)
        mode_e = mode if isinstance(mode, DiscoveryMode) else DiscoveryMode(str(mode))
        records = self.scanner.scan(root, progress=progress, stop_check=stop_check)
        if not records:
            return DiscoveryResult(
                input_root=str(root),
                mode=mode_e.value,
                detection_method="none",
                reason="No DICOM files detected",
                message="No DICOM files detected.",
                n_dicom_files=0,
                n_series=0,
            )

        subjects, mapping, method, reason = self.detector.detect_subjects(
            records, root, mode=mode_e
        )
        n_series = len({r.series_instance_uid for r in records if r.series_instance_uid})
        return DiscoveryResult(
            input_root=str(root),
            mode=mode_e.value,
            detection_method=method,
            reason=reason,
            records=records,
            subjects=subjects,
            file_to_subject=mapping,
            n_dicom_files=len(records),
            n_series=n_series,
        )

    def scan_series(
        self,
        root_path: Path | str,
        *,
        mode: DiscoveryMode | str = DiscoveryMode.AUTOMATIC,
        progress: ProgressCallback | None = None,
        stop_check: StopCheck | None = None,
    ) -> tuple[list[DicomSeries], DiscoveryResult]:
        """Discover subjects, run existing ``DicomParser.scan``, apply routing."""
        root = Path(root_path)
        if progress:
            progress("Running recursive DICOM discovery…")
        discovery = self.discover(
            root, mode=mode, progress=progress, stop_check=stop_check
        )
        if not discovery.has_dicom:
            raise InvalidDicomFolderError(
                discovery.message or "No DICOM series were found in the selected folder."
            )

        if progress:
            progress("Building series with existing DICOM parser…")
        series = self.parser.scan(root, progress=progress, stop_check=stop_check)
        apply_discovery_routing(series, discovery)
        discovery.n_series = len(series)
        return series, discovery


def apply_discovery_routing(
    series_list: list[DicomSeries],
    discovery: DiscoveryResult,
) -> None:
    """Remap in-memory ``patient_id`` from discovery; never touch DICOM files.

    Preference order for assigning a series to a subject:
      1. Exact sample-file path match from discovery records
      2. Any discovery file under the same ``source_dir``
      3. SeriesInstanceUID only when that UID maps to a single subject
    """
    subject_by_label = {s.bids_subject: s for s in discovery.subjects}
    file_to_subject = discovery.file_to_subject

    # UID → set of subjects (detect collisions / copies across folders)
    uid_subjects: dict[str, set[str]] = defaultdict(set)
    uid_primary: dict[str, tuple[str, str, str, str]] = {}
    dir_to_label: dict[str, str] = {}

    for rec in discovery.records:
        label = file_to_subject.get(str(rec.filepath))
        if not label:
            continue
        subj = subject_by_label.get(label)
        folder = subj.source_folder if subj else ""
        method = subj.detection_method if subj else discovery.detection_method
        original = (rec.patient_id or "").strip()
        if rec.series_instance_uid:
            uid_subjects[rec.series_instance_uid].add(label)
            # Keep first seen as primary; collision handled below
            uid_primary.setdefault(
                rec.series_instance_uid, (label, original, folder, method)
            )
        parent_key = str(rec.parent_folder.resolve()) if rec.parent_folder else ""
        if parent_key:
            dir_to_label.setdefault(parent_key, label)

    for series in series_list:
        label = ""
        original = series.patient_id
        folder = ""
        method = discovery.detection_method

        sample = str(series.sample_file)
        if sample in file_to_subject:
            label = file_to_subject[sample]
        else:
            try:
                sample_resolved = str(Path(sample).resolve())
            except OSError:
                sample_resolved = sample
            label = file_to_subject.get(sample_resolved, "")

        if not label:
            try:
                src_key = str(Path(series.source_dir).resolve())
            except OSError:
                src_key = str(series.source_dir)
            label = dir_to_label.get(src_key, "")

        if not label:
            uid = series.series_instance_uid or ""
            subjects_for_uid = uid_subjects.get(uid) or set()
            if len(subjects_for_uid) == 1:
                info = uid_primary.get(uid)
                if info:
                    label, original, folder, method = info

        if not label:
            continue

        subj = subject_by_label.get(label)
        if subj is not None:
            folder = subj.source_folder or folder
            method = subj.detection_method or method
            if subj.dicom_patient_id and "," not in subj.dicom_patient_id:
                original = subj.dicom_patient_id

        if not series.dicom_patient_id:
            series.dicom_patient_id = original or series.patient_id
        series.patient_id = label
        series.source_subject_folder = folder
        series.subject_detection_method = method

    LOGGER.info(
        "Applied discovery routing (%s): %s subjects → %s series",
        discovery.detection_method,
        len(discovery.subjects),
        len(series_list),
    )
