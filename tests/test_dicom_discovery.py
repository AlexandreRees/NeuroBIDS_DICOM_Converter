"""Recursive DICOM discovery and subject reconstruction tests."""

from __future__ import annotations

from pathlib import Path

import pytest

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, generate_uid  # noqa: E402

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.discovery import (
    DatasetDiscovery,
    DiscoveryMode,
    RecursiveDicomScanner,
    SubjectDetector,
)
from neuro_pipeline.utils.exceptions import InvalidDicomFolderError


def _write_dicom(
    path: Path,
    *,
    patient_id: str,
    series_desc: str = "T1w",
    series_uid: str | None = None,
    study_uid: str | None = None,
    series_number: int = 1,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    if patient_id:
        ds.PatientID = patient_id
    ds.StudyDescription = "TestStudy"
    ds.SeriesDescription = series_desc
    ds.ProtocolName = series_desc
    ds.SeriesNumber = series_number
    ds.AcquisitionNumber = 1
    ds.Modality = "MR"
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.save_as(str(path), enforce_file_format=True)


def test_deep_subject_data_dicom(tmp_path: Path) -> None:
    """subject/data/DICOM is discovered."""
    root = tmp_path / "Input"
    _write_dicom(
        root / "subject01" / "data" / "DICOM" / "img001.dcm",
        patient_id="P01",
    )
    records = RecursiveDicomScanner().scan(root)
    assert len(records) == 1
    series, discovery = DatasetDiscovery().scan_series(root)
    assert discovery.has_dicom
    assert len(series) == 1
    assert discovery.n_dicom_files == 1


def test_deep_visit_raw_mr_dicom(tmp_path: Path) -> None:
    """subject/session/raw/MR/DICOM is discovered alongside shallower trees."""
    root = tmp_path / "Input"
    _write_dicom(
        root / "subject01" / "data" / "DICOM" / "a.dcm",
        patient_id="ANON",
        series_uid=generate_uid(),
    )
    _write_dicom(
        root / "subject02" / "visit01" / "raw" / "MR" / "DICOM" / "b.dcm",
        patient_id="ANON",
        series_uid=generate_uid(),
    )
    series, discovery = DatasetDiscovery().scan_series(root, mode=DiscoveryMode.AUTOMATIC)
    assert discovery.n_dicom_files == 2
    assert len(discovery.subjects) == 2
    labels = {s.bids_subject for s in discovery.subjects}
    assert labels == {"subject01", "subject02"}
    assert {s.patient_id for s in series} == {"subject01", "subject02"}
    assert all(s.dicom_patient_id == "ANON" for s in series)


def test_same_patient_id_three_folders(tmp_path: Path) -> None:
    root = tmp_path / "Input"
    for name in ("SUB01", "SUB02", "SUB03"):
        _write_dicom(
            root / name / "MR" / "1.dcm",
            patient_id="ANON",
            series_uid=generate_uid(),
        )
    _, discovery = DatasetDiscovery().scan_series(root)
    assert len(discovery.subjects) == 3
    assert discovery.detection_method == "folder_based"
    assert "collision" in discovery.reason.lower() or "folder" in discovery.reason.lower()
    assert all(s.dicom_patient_id == "ANON" for s in discovery.subjects)


def test_missing_patient_id_uses_folder(tmp_path: Path) -> None:
    root = tmp_path / "Input"
    for name in ("Patient_A", "Patient_B"):
        path = root / name / "raw" / "img"
        # Write with empty PatientID by omitting tag after save rewrite
        _write_dicom(path, patient_id="TMP", series_uid=generate_uid())
        ds = pydicom.dcmread(str(path))
        if "PatientID" in ds:
            del ds.PatientID
        ds.save_as(str(path), enforce_file_format=True)

    _, discovery = DatasetDiscovery().scan_series(root)
    assert len(discovery.subjects) == 2
    assert discovery.detection_method in {"folder_based", "deep_folder"}
    folders = {s.source_folder for s in discovery.subjects}
    assert folders == {"Patient_A", "Patient_B"}
    assert {s.bids_subject for s in discovery.subjects} == {"PatientA", "PatientB"}


def test_nested_without_extension(tmp_path: Path) -> None:
    root = tmp_path / "Input"
    # No .dcm extension
    target = root / "subject99" / "session01" / "raw" / "IM_0001"
    _write_dicom(target, patient_id="SUB99", series_uid=generate_uid())
    records = RecursiveDicomScanner().scan(root)
    assert len(records) == 1
    assert records[0].filepath.name == "IM_0001"
    series, discovery = DatasetDiscovery().scan_series(root)
    assert discovery.has_dicom
    assert len(series) == 1


def test_no_dicom_clear_error(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    (root / "readme.txt").write_text("no dicom", encoding="utf-8")
    result = DatasetDiscovery().discover(root)
    assert not result.has_dicom
    assert "No DICOM" in result.message or "No DICOM" in result.reason
    with pytest.raises(InvalidDicomFolderError):
        DatasetDiscovery().scan_series(root)


def test_bids_preview_receives_folder_subjects(tmp_path: Path) -> None:
    root = tmp_path / "Input"
    for name in ("Patient_A", "Patient_B"):
        _write_dicom(
            root / name / "dicom" / "x.dcm",
            patient_id="ANON",
            series_uid=generate_uid(),
        )
    series, discovery = DatasetDiscovery().scan_series(root)
    plan = BIDSConversionPlan.from_series(series, dataset_root=root)
    subjects = {item.subject for item in plan.items}
    assert subjects == {"PatientA", "PatientB"}
    folders = {item.source_subject_folder for item in plan.items}
    assert folders == {"Patient_A", "Patient_B"}
    assert all(item.original_patient_id == "ANON" for item in plan.items)
    assert discovery.detection_method == "folder_based"


def test_unique_patient_ids_preferred(tmp_path: Path) -> None:
    root = tmp_path / "Input"
    _write_dicom(root / "folderA" / "a.dcm", patient_id="001", series_uid=generate_uid())
    _write_dicom(root / "folderB" / "b.dcm", patient_id="002", series_uid=generate_uid())
    _, discovery = DatasetDiscovery().scan_series(root, mode=DiscoveryMode.AUTOMATIC)
    assert discovery.detection_method == "patient_id"
    assert {s.bids_subject for s in discovery.subjects} == {"001", "002"}


def test_patient_id_only_mode_keeps_collision(tmp_path: Path) -> None:
    root = tmp_path / "Input"
    for name in ("A", "B"):
        _write_dicom(
            root / name / "x.dcm",
            patient_id="SAME",
            series_uid=generate_uid(),
        )
    _, discovery = DatasetDiscovery().scan_series(root, mode=DiscoveryMode.PATIENT_ID)
    assert len(discovery.subjects) == 1
    assert discovery.subjects[0].bids_subject == "SAME"


def test_mixed_depth_with_container_folder(tmp_path: Path) -> None:
    """Shallow subject + nested subject under a container must both be found.

    Classic failure mode of top-level-only discovery::

        Input/
          subject_shallow/…
          cohort/
            subject_deep/visit/raw/MR/DICOM/…
    """
    root = tmp_path / "Input"
    _write_dicom(
        root / "subject_shallow" / "img.dcm",
        patient_id="ANON",
        series_uid=generate_uid(),
    )
    _write_dicom(
        root / "cohort" / "subject_deep" / "visit01" / "raw" / "MR" / "DICOM" / "img.dcm",
        patient_id="ANON",
        series_uid=generate_uid(),
    )
    _, discovery = DatasetDiscovery().scan_series(root, mode=DiscoveryMode.AUTOMATIC)
    assert discovery.n_dicom_files == 2
    labels = {s.bids_subject for s in discovery.subjects}
    assert labels == {"subjectshallow", "subjectdeep"}
    folders = {s.source_folder for s in discovery.subjects}
    assert folders == {"subject_shallow", "subject_deep"}
    # Must not treat the container as the subject
    assert "cohort" not in folders


def test_batch_discover_uses_mixed_depth_folders(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    out = tmp_path / "bids"
    _write_dicom(
        root / "subject001" / "a.dcm",
        patient_id="ANON",
        series_uid=generate_uid(),
    )
    _write_dicom(
        root / "group" / "subject002" / "ses-01" / "raw" / "b.dcm",
        patient_id="ANON",
        series_uid=generate_uid(),
    )
    from neuro_pipeline.batch import BatchManager

    jobs = BatchManager().discover_datasets(root, output_root=out)
    labels = {j.label for j in jobs}
    assert "subject001" in labels
    assert "subject002" in labels
    assert "group" not in labels
    assert len(jobs) == 2


def test_subject_detector_scoring_prefers_subject_names() -> None:
    detector = SubjectDetector()
    score_sub = detector._score_folder_name("subject01", depth=0, under_root=True)
    score_dicom = detector._score_folder_name("DICOM", depth=0, under_root=True)
    assert score_sub > score_dicom


def test_mixed_nii_and_deep_siemens_protocol_trees(tmp_path: Path) -> None:
    """Synthetic layout: shallow NIfTI leftover + deep Siemens PROTOCOL trees.

    Depth and markers matter more than real-world name length (Windows MAX_PATH)::

        SyntheticDataset/
          SubjA_Session1/…_NII/…
          SubjA_Session02/…_DATA/STUDY-DST/DR_PROTOCOL_A/series/
          SubjB-session1/STUDY-STD/DR_PROTOCOL_B/series/
    """
    root = tmp_path / "SyntheticDataset"

    # Session1 — leftover DICOM under *_NII (must not hide other subjects)
    _write_dicom(
        root / "SubjA_Session1" / "SubjA_Session1_NII" / "leftover.dcm",
        patient_id="ANON",
        series_uid=generate_uid(),
    )

    protocol_a = (
        root
        / "SubjA_Session02"
        / "SubjA_Session02_DATA"
        / "STUDY-DST-1107"
        / "DR_PROTOCOL_A"
    )
    _write_dicom(
        protocol_a / "Serie01_T1" / "IM_0001",
        patient_id="ANON",
        series_uid=generate_uid(),
        series_desc="T1w",
    )
    _write_dicom(
        protocol_a / "Serie02_FLAIR" / "IM_0001",
        patient_id="ANON",
        series_uid=generate_uid(),
        series_desc="FLAIR",
    )

    protocol_b = (
        root
        / "SubjB-session1"
        / "STUDY-STD-1107"
        / "DR_PROTOCOL_B"
    )
    _write_dicom(
        protocol_b / "Serie01_T1" / "IM_0001",
        patient_id="ANON",
        series_uid=generate_uid(),
    )

    series, discovery = DatasetDiscovery().scan_series(root, mode=DiscoveryMode.AUTOMATIC)
    assert discovery.n_dicom_files == 4
    assert len(discovery.subjects) == 3

    paths = {s.source_folder_path for s in discovery.subjects}
    # Deep PROTOCOL roots preferred for conversion; NII export not a subject root
    assert any("DR_PROTOCOL_A" in p for p in paths)
    assert any("DR_PROTOCOL_B" in p for p in paths)
    assert not any(p.endswith("_NII") or Path(p).name.endswith("_NII") for p in paths)

    # Parser must also see extensionless Siemens files
    assert len(series) == 4


def test_batch_discovers_deep_siemens_under_synthetic_root(tmp_path: Path) -> None:
    root = tmp_path / "SyntheticDataset"
    out = tmp_path / "bids"
    protocol = (
        root
        / "SubjA_Session02"
        / "SubjA_Session02_DATA"
        / "STUDY-DST-1107"
        / "DR_PROTOCOL_A"
        / "Serie01"
    )
    _write_dicom(protocol / "IM_0001", patient_id="P02", series_uid=generate_uid())
    _write_dicom(
        root / "SubjA_Session1" / "SubjA_Session1_NII" / "x.dcm",
        patient_id="P01",
        series_uid=generate_uid(),
    )
    from neuro_pipeline.batch import BatchManager

    jobs = BatchManager().discover_datasets(root, output_root=out)
    assert len(jobs) == 2
    labels = " ".join(j.label for j in jobs)
    assert "PROTOCOL" in labels or "Session02" in labels or any(
        "PROTOCOL" in (j.source_folder_path or "") for j in jobs
    )
    assert any("PROTOCOL" in (j.input_path or "") for j in jobs)