"""Tests for automatic one-click folder analysis / conversion routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, generate_uid  # noqa: E402

from neuro_pipeline.batch import BatchJob, BatchManager, InputAnalysis, sanitize_patient_id
from neuro_pipeline.discovery import DatasetDiscovery, DetectionMethod, DiscoveryResult, SubjectRecord
from neuro_pipeline.models import DicomSeries, SeriesStatus


def _series(patient: str, *, n: int = 2, study_uid: str = "studyA") -> list[DicomSeries]:
    out: list[DicomSeries] = []
    for i in range(n):
        out.append(
            DicomSeries(
                patient_id=patient,
                study_description="Study",
                series_description=f"Series{i}",
                protocol_name="proto",
                series_number=i + 1,
                acquisition_number=None,
                modality="MR",
                num_images=10,
                source_dir=Path(f"/tmp/{patient}/s{i}"),
                sample_file=Path(f"/tmp/{patient}/s{i}/1.dcm"),
                status=SeriesStatus.PENDING,
                series_instance_uid=f"{patient}-uid-{i}",
                study_instance_uid=study_uid,
            )
        )
    return out


def _write_dicom(
    path: Path,
    *,
    patient_id: str,
    series_uid: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientID = patient_id
    ds.StudyDescription = "Study"
    ds.SeriesDescription = "T1"
    ds.ProtocolName = "t1"
    ds.SeriesNumber = 1
    ds.Modality = "MR"
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.save_as(str(path), enforce_file_format=True)


def test_sanitize_patient_id() -> None:
    assert sanitize_patient_id("SUB-001") == "SUB001"
    assert sanitize_patient_id("pat 7!") == "pat7"
    assert sanitize_patient_id("") == "unknown"


def test_input_analysis_groups_by_patient_id() -> None:
    series = _series("P001", n=3, study_uid="S1") + _series("P002", n=2, study_uid="S2")
    analysis = InputAnalysis.from_series(series, folder="/data/in")
    assert analysis.number_of_subjects == 2
    assert analysis.number_of_series == 5
    assert analysis.number_of_studies == 2
    text = analysis.summary_text()
    assert "Detected subjects: 2" in text
    assert "BIDS dataset" in text


def test_input_analysis_single_subject_text() -> None:
    series = _series("OnlyOne", n=4)
    analysis = InputAnalysis.from_series(series, folder="/data/in")
    text = analysis.summary_text()
    assert "Detected subjects: 1" in text
    assert "Series: 4" in text
    assert "BIDS dataset" in text


def test_plan_jobs_creates_one_job_per_patient(tmp_path: Path) -> None:
    series = _series("A1", n=2) + _series("B2", n=3)
    analysis = InputAnalysis.from_series(series, folder=tmp_path / "dicom")
    mgr = BatchManager()
    jobs = mgr.plan_jobs(analysis, tmp_path / "bids")
    assert len(jobs) == 2
    assert {j.patient_id_filter for j in jobs} == {"A1", "B2"}
    assert all(j.subject_id for j in jobs)
    assert all(Path(j.output_path) == tmp_path / "bids" for j in jobs)


def test_plan_jobs_applies_subject_override_only_for_single(tmp_path: Path) -> None:
    analysis = InputAnalysis.from_series(_series("P9", n=1), folder=tmp_path / "dicom")
    mgr = BatchManager()
    jobs = mgr.plan_jobs(analysis, tmp_path / "bids", subject_override="001")
    assert len(jobs) == 1
    assert jobs[0].subject_id == "001"


def test_convert_folder_routes_to_internal_jobs(tmp_path: Path) -> None:
    series = _series("X", n=1) + _series("Y", n=1)
    analysis = InputAnalysis.from_series(series, folder=tmp_path / "in")
    mgr = BatchManager()
    mgr.run_all = MagicMock(return_value=[])  # type: ignore[method-assign]
    mgr.analyze_folder = MagicMock(return_value=analysis)  # type: ignore[method-assign]
    mgr.convert_folder(tmp_path / "in", tmp_path / "out", subject_id="")
    assert mgr.run_all.called
    jobs = mgr.queue.all_jobs()
    assert len(jobs) == 2
    assert isinstance(jobs[0], BatchJob)


def test_input_analysis_from_discovery_folder_collision(tmp_path: Path) -> None:
    """Three patient folders with the same DICOM PatientID → three subjects."""
    root = tmp_path / "input"
    for folder in ("subA", "subB", "subC"):
        _write_dicom(root / folder / "series1" / "1.dcm", patient_id="SAME_ID")

    series, discovery = DatasetDiscovery().scan_series(root)
    analysis = InputAnalysis.from_discovery(series, discovery, folder=root)
    assert analysis.number_of_subjects == 3
    assert analysis.detection_method == DetectionMethod.FOLDER_BASED.value
    assert {s.patient_id for s in analysis.series} == {"subA", "subB", "subC"}
    assert all(s.dicom_patient_id == "SAME_ID" for s in analysis.series)
    text = analysis.summary_text()
    assert "Detected subjects: 3" in text
    assert "Folder based" in text


def test_input_analysis_keeps_patient_id_when_unique(tmp_path: Path) -> None:
    """Distinct PatientIDs are kept even with folder layout."""
    root = tmp_path / "input"
    for folder, pid in (("p1", "ID1"), ("p2", "ID2")):
        _write_dicom(root / folder / "s" / "1.dcm", patient_id=pid)

    series, discovery = DatasetDiscovery().scan_series(root)
    analysis = InputAnalysis.from_discovery(series, discovery, folder=root)
    assert analysis.number_of_subjects == 2
    assert analysis.detection_method == DetectionMethod.PATIENT_ID.value
    assert {s.patient_id for s in analysis.series} == {"ID1", "ID2"}


def test_plan_jobs_folder_routed_subjects(tmp_path: Path) -> None:
    root = tmp_path / "dicom"
    for folder in ("patient01", "patient02"):
        _write_dicom(root / folder / "mr" / "a.dcm", patient_id="ANON")

    series, discovery = DatasetDiscovery().scan_series(root)
    analysis = InputAnalysis.from_discovery(series, discovery, folder=root)
    jobs = BatchManager().plan_jobs(analysis, tmp_path / "bids")
    assert len(jobs) == 2
    assert {j.subject_id for j in jobs} == {"patient01", "patient02"}


def test_from_discovery_summary_includes_source(tmp_path: Path) -> None:
    discovery = DiscoveryResult(
        input_root=str(tmp_path),
        mode="automatic",
        detection_method="folder_based",
        reason="PatientID collision detected",
        subjects=[
            SubjectRecord(
                bids_subject="PatientA",
                source_folder="Patient_A",
                source_folder_path=str(tmp_path / "Patient_A"),
                dicom_patient_id="ANON",
                detection_method="folder_based",
                reason="PatientID collision detected",
                dicom_files=542,
                series_uids=["u1"] * 34,
            )
        ],
        n_dicom_files=542,
        n_series=34,
    )
    series = [
        DicomSeries(
            patient_id="PatientA",
            study_description="S",
            series_description="T1",
            protocol_name="t1",
            series_number=1,
            acquisition_number=None,
            modality="MR",
            num_images=542,
            source_dir=tmp_path / "Patient_A",
            sample_file=tmp_path / "Patient_A" / "1.dcm",
            status=SeriesStatus.PENDING,
            series_instance_uid="u1",
            study_instance_uid="st",
            dicom_patient_id="ANON",
            source_subject_folder="Patient_A",
            subject_detection_method="folder_based",
        )
    ]
    text = InputAnalysis.from_discovery(series, discovery, folder=tmp_path).summary_text()
    assert "Detection method: Folder based grouping" in text
    assert "PatientID collision" in text
    assert "Source:" in text and "Patient_A" in text
    assert "DICOM files: 542" in text
