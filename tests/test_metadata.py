"""Tests for smart DICOM metadata extraction (synthetic datasets only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, generate_uid  # noqa: E402

from neuro_pipeline.dicom.metadata import DicomMetadataExtractor, DicomSeriesMetadata


def _write_synthetic_dicom(path: Path, **overrides: object) -> Path:
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientID = "SUB001"
    ds.PatientName = "DOE^JOHN"
    ds.PatientAge = "045Y"
    ds.PatientSex = "M"
    ds.StudyInstanceUID = generate_uid()
    ds.StudyDate = "20200101"
    ds.StudyDescription = "Research Study"
    ds.SeriesInstanceUID = generate_uid()
    ds.SeriesNumber = 5
    ds.SeriesDescription = "ep2d_diff_4scan"
    ds.ProtocolName = "ep2d_diff"
    ds.Manufacturer = "Siemens"
    ds.ManufacturerModelName = "Prisma"
    ds.Modality = "MR"
    ds.MagneticFieldStrength = 3.0
    ds.RepetitionTime = 3000.0
    ds.EchoTime = 80.0
    ds.FlipAngle = 90.0
    ds.SliceThickness = 2.0
    ds.PixelSpacing = [2.0, 2.0]
    ds.Rows = 128
    ds.Columns = 128
    ds.ImageType = ["ORIGINAL", "PRIMARY", "DIFFUSION"]
    ds.DiffusionBValue = 1000
    for key, value in overrides.items():
        setattr(ds, key, value)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), write_like_original=False)
    return path


def test_extract_core_fields(tmp_path: Path) -> None:
    path = _write_synthetic_dicom(tmp_path / "a.dcm")
    meta = DicomMetadataExtractor().extract_from_file(path, num_images=12)
    assert isinstance(meta, DicomSeriesMetadata)
    assert meta.patient_id == "SUB001"
    assert meta.patient_name == "DOE^JOHN"
    assert meta.manufacturer == "Siemens"
    assert meta.magnetic_field_strength == 3.0
    assert meta.repetition_time == 3000.0
    assert meta.echo_time == 80.0
    assert meta.diffusion_present is True
    assert 1000 in meta.b_values
    assert meta.num_images == 12


def test_summary_excludes_patient_name(tmp_path: Path) -> None:
    path = _write_synthetic_dicom(tmp_path / "b.dcm")
    meta = DicomMetadataExtractor().extract_from_file(path)
    summary = meta.to_summary_dict()
    assert "PatientName" not in summary
    assert "patient_name" not in summary
    assert summary["scanner"] == "Siemens Prisma"
    assert summary["field_strength"] == 3.0
    assert summary["TR"] == 3000.0
    assert summary["TE"] == 80.0


def test_export_json_no_overwrite(tmp_path: Path) -> None:
    path = _write_synthetic_dicom(tmp_path / "c.dcm")
    meta = DicomMetadataExtractor().extract_from_file(path)
    dest = tmp_path / "metadata.json"
    DicomMetadataExtractor().export_json(meta, dest)
    dest.write_text('{"kept": true}\n', encoding="utf-8")
    again = DicomMetadataExtractor().export_json(meta, dest, overwrite=False)
    assert again == dest
    assert json.loads(dest.read_text(encoding="utf-8"))["kept"] is True


def test_missing_tags_do_not_crash(tmp_path: Path) -> None:
    path = _write_synthetic_dicom(
        tmp_path / "d.dcm",
        RepetitionTime=None,
        EchoTime=None,
        DiffusionBValue=None,
    )
    # Clear optional attributes
    from pydicom import dcmread

    ds = dcmread(str(path), force=True)
    for tag in ("RepetitionTime", "EchoTime", "DiffusionBValue", "PatientAge"):
        if tag in ds:
            delattr(ds, tag)
    ds.save_as(str(path), write_like_original=False)
    meta = DicomMetadataExtractor().extract_from_file(path)
    assert meta.repetition_time is None
    assert meta.echo_time is None
    assert meta.scanner.startswith("Siemens")


def test_unreadable_file_returns_empty_metadata(tmp_path: Path) -> None:
    junk = tmp_path / "not.dcm"
    junk.write_bytes(b"not-a-dicom")
    meta = DicomMetadataExtractor().extract_from_file(junk)
    assert meta.sample_file.endswith("not.dcm")
    assert meta.series_description == ""
