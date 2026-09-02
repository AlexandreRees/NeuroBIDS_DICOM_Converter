"""DICOM parser tests (synthetic datasets)."""

from __future__ import annotations

from pathlib import Path

import pytest

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, generate_uid  # noqa: E402

from neuro_pipeline.dicom import DicomParser
from neuro_pipeline.utils.exceptions import InvalidDicomFolderError, NonDicomFolderError


def _write_dicom(
    path: Path,
    *,
    patient_id: str,
    series_desc: str,
    series_uid: str,
    study_uid: str,
    series_number: int,
    modality: str = "MR",
) -> None:
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientID = patient_id
    ds.StudyDescription = "TestStudy"
    ds.SeriesDescription = series_desc
    ds.ProtocolName = series_desc
    ds.SeriesNumber = series_number
    ds.AcquisitionNumber = 1
    ds.Modality = modality
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.save_as(str(path), enforce_file_format=True)


def test_parser_groups_series(tmp_path: Path) -> None:
    study_uid = generate_uid()
    series_a = generate_uid()
    series_b = generate_uid()
    for i in range(3):
        _write_dicom(
            tmp_path / f"a_{i}.dcm",
            patient_id="P001",
            series_desc="MPRAGE",
            series_uid=series_a,
            study_uid=study_uid,
            series_number=1,
        )
    for i in range(2):
        _write_dicom(
            tmp_path / f"b_{i}.dcm",
            patient_id="P001",
            series_desc="FLAIR",
            series_uid=series_b,
            study_uid=study_uid,
            series_number=2,
        )

    series = DicomParser().scan(tmp_path)
    assert len(series) == 2
    by_desc = {s.series_description: s for s in series}
    assert by_desc["MPRAGE"].num_images == 3
    assert by_desc["FLAIR"].num_images == 2
    assert by_desc["MPRAGE"].modality == "MR"


def test_parser_rejects_non_dicom(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")
    with pytest.raises((InvalidDicomFolderError, NonDicomFolderError)):
        DicomParser().scan(tmp_path)
