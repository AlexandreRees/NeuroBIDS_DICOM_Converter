"""Regression tests: multi-subject filtering must never silently complete empty."""

from __future__ import annotations

from pathlib import Path

import pytest

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, generate_uid  # noqa: E402

from neuro_pipeline.batch.batch_manager import BatchManager
from neuro_pipeline.batch.batch_models import BatchJob, BatchJobStatus
from neuro_pipeline.batch.input_analysis import InputAnalysis, SubjectSummary
from neuro_pipeline.models import DicomSeries, SeriesStatus


def _write_dicom(path: Path, *, patient_id: str, series_uid: str | None = None) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientID = patient_id
    ds.StudyDescription = "Study"
    ds.SeriesDescription = "T1w"
    ds.ProtocolName = "T1w"
    ds.SeriesNumber = 1
    ds.Modality = "MR"
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    uid = series_uid or generate_uid()
    ds.SeriesInstanceUID = uid
    ds.save_as(str(path), enforce_file_format=True)
    return uid


def _series(
    *,
    patient_id: str,
    series_uid: str,
    dicom_patient_id: str = "",
    source_folder: str = "",
    source_dir: Path,
) -> DicomSeries:
    return DicomSeries(
        patient_id=patient_id,
        study_description="Study",
        series_description="T1w",
        protocol_name="T1w",
        series_number=1,
        acquisition_number=1,
        modality="MR",
        num_images=1,
        source_dir=source_dir,
        sample_file=source_dir / "x.dcm",
        status=SeriesStatus.PENDING,
        sequence_type="anat",
        series_instance_uid=series_uid,
        dicom_patient_id=dicom_patient_id or patient_id,
        source_subject_folder=source_folder,
    )


def test_filter_prefers_series_uids_over_raw_patient_id() -> None:
    """Classic bug: filter compared discovery label to raw DICOM PatientID."""
    root = Path("/tmp/fake")
    uid_a = "1.2.3.A"
    uid_b = "1.2.3.B"
    series = [
        _series(
            patient_id="subject01",  # discovery label
            series_uid=uid_a,
            dicom_patient_id="ANON",
            source_folder="subject01",
            source_dir=root / "subject01",
        ),
        _series(
            patient_id="subject02",
            series_uid=uid_b,
            dicom_patient_id="ANON",
            source_folder="subject02",
            source_dir=root / "subject02",
        ),
    ]
    job = BatchJob.create(root, root / "out", label="subject01")
    job.subject_id = "subject01"
    job.patient_id_filter = "subject01"  # would fail if compared to raw only after re-scan
    job.series_uids = [uid_a]
    # Simulate raw re-scan IDs (ANON for both)
    raw_rescanned = [
        _series(
            patient_id="ANON",
            series_uid=uid_a,
            dicom_patient_id="ANON",
            source_dir=root / "subject01",
        ),
        _series(
            patient_id="ANON",
            series_uid=uid_b,
            dicom_patient_id="ANON",
            source_dir=root / "subject02",
        ),
    ]
    matched = BatchManager._filter_series_for_job(job, raw_rescanned)
    assert len(matched) == 1
    assert matched[0].series_instance_uid == uid_a


def test_empty_filter_fails_not_completed(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    inp.mkdir()
    job = BatchJob.create(inp, tmp_path / "out", label="in")
    job.subject_id = "001"
    job.series_uids = ["does-not-exist"]
    job.patient_id_filter = "subjectX"

    mgr = BatchManager()
    pre = [
        _series(
            patient_id="P1",
            series_uid="other",
            source_dir=inp,
        )
    ]
    out = mgr.run_job(job, resume=False, preloaded_series=pre)
    assert out.status == BatchJobStatus.FAILED
    assert out.error and "No matching" in out.error


def test_plan_jobs_stores_series_uids(tmp_path: Path) -> None:
    analysis = InputAnalysis(
        folder=str(tmp_path),
        number_of_subjects=2,
        number_of_series=2,
        number_of_dicom_files=2,
        subjects=[
            SubjectSummary(
                patient_id="subject01",
                subject_label="subject01",
                series_count=1,
                study_count=1,
                dicom_files=1,
                series_uids=["uid-1"],
                source_folder="subject01",
                source_folder_path=str(tmp_path / "subject01"),
                original_patient_id="ANON",
            ),
            SubjectSummary(
                patient_id="subject02",
                subject_label="subject02",
                series_count=1,
                study_count=1,
                dicom_files=1,
                series_uids=["uid-2"],
                source_folder="subject02",
                source_folder_path=str(tmp_path / "subject02"),
                original_patient_id="ANON",
            ),
        ],
        series=[],
    )
    (tmp_path / "subject01").mkdir()
    (tmp_path / "subject02").mkdir()
    jobs = BatchManager().plan_jobs(analysis, tmp_path / "bids")
    assert len(jobs) == 2
    assert {tuple(j.series_uids) for j in jobs} == {("uid-1",), ("uid-2",)}
    assert all(j.source_folder_path for j in jobs)
    assert {Path(j.input_path).name for j in jobs} == {"subject01", "subject02"}


def test_discover_keeps_patientid_subjects_without_folder(tmp_path: Path) -> None:
    """Multiple PatientID subjects sharing root must not collapse via seen_paths."""
    root = tmp_path / "flat"
    root.mkdir()
    _write_dicom(root / "a.dcm", patient_id="001", series_uid=generate_uid())
    _write_dicom(root / "b.dcm", patient_id="002", series_uid=generate_uid())
    jobs = BatchManager().discover_datasets(root, output_root=tmp_path / "bids")
    assert len(jobs) == 2
    assert {j.patient_id_filter for j in jobs} == {"001", "002"}
