"""Scanner auto-detection tests (synthetic DICOM headers only)."""

from __future__ import annotations

from pathlib import Path

import pytest

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, generate_uid  # noqa: E402

from neuro_pipeline.dicom.sequence_classifier import SequenceClassifier, SequenceType
from neuro_pipeline.scanner import AutoDetector, ScannerDetector
from neuro_pipeline.scanner.scanner_profiles import (
    load_all_profiles,
    select_profile_for_manufacturer,
)


def _write_vendor_dicom(
    path: Path,
    *,
    manufacturer: str,
    model: str,
    field: float,
    series_desc: str = "MPRAGE",
) -> None:
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientID = "P"
    ds.StudyDescription = "S"
    ds.SeriesDescription = series_desc
    ds.ProtocolName = series_desc
    ds.SeriesNumber = 1
    ds.Modality = "MR"
    ds.Manufacturer = manufacturer
    ds.ManufacturerModelName = model
    ds.SoftwareVersions = "syngo MR E11"
    ds.MagneticFieldStrength = field
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.save_as(str(path), enforce_file_format=True)


def test_siemens_detection(tmp_path: Path) -> None:
    _write_vendor_dicom(
        tmp_path / "a.dcm",
        manufacturer="SIEMENS",
        model="Prisma",
        field=3.0,
    )
    info = ScannerDetector().detect(tmp_path)
    assert info.manufacturer == "Siemens"
    assert "Prisma" in info.model
    assert info.magnetic_field_strength == pytest.approx(3.0)
    assert info.confidence == "HIGH"
    info2, profile = AutoDetector().detect(tmp_path)
    assert info2.profile_name == "siemens"
    assert profile.name == "siemens"


def test_ge_detection(tmp_path: Path) -> None:
    _write_vendor_dicom(
        tmp_path / "a.dcm",
        manufacturer="GE MEDICAL SYSTEMS",
        model="DISCOVERY MR750",
        field=3.0,
        series_desc="BRAVO",
    )
    info, profile = AutoDetector().detect(tmp_path)
    assert info.manufacturer == "GE"
    assert profile.name == "ge"


def test_philips_detection(tmp_path: Path) -> None:
    _write_vendor_dicom(
        tmp_path / "a.dcm",
        manufacturer="Philips Medical Systems",
        model="Achieva",
        field=1.5,
        series_desc="T1W_3D",
    )
    info, profile = AutoDetector().detect(tmp_path)
    assert info.manufacturer == "Philips"
    assert profile.name == "philips"
    assert info.field_label.endswith("T")


def test_generic_fallback() -> None:
    profiles = load_all_profiles()
    profile = select_profile_for_manufacturer("TotallyUnknownVendor", profiles)
    assert profile.name == "generic"


def test_classifier_uses_scanner_profile() -> None:
    profiles = load_all_profiles()
    siemens = profiles["siemens"]
    clf = SequenceClassifier()
    # Pattern unique-ish from profile
    out = clf.classify(series_description="localizer_MPRAGE_special", scanner_profile=siemens)
    assert out == SequenceType.ANAT
    # Without profile, unknown string may still match via legacy regex (MPRAGE)
    out2 = clf.classify(series_description="custom_bravo_scan", scanner_profile=profiles["ge"])
    assert out2 == SequenceType.ANAT
