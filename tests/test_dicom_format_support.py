"""Synthetic DICOM format-support tests (no external medical downloads)."""

from __future__ import annotations

from pathlib import Path

import pytest

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileDataset  # noqa: E402
from pydicom.uid import (  # noqa: E402
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    MRImageStorage,
    SecondaryCaptureImageStorage,
    generate_uid,
)

from neuro_pipeline.converter.dcm2niix import Converter
from neuro_pipeline.dicom.format_support import (
    Convertibility,
    DicomObjectClass,
    classify_sop_class,
    has_dicom_preamble,
    is_convertible_to_nifti,
    looks_like_dicom_candidate,
    probe_dicom_file,
)
from neuro_pipeline.dicom.parser import DicomParser
from neuro_pipeline.models import ConversionJob, ConversionOptions, DicomSeries

MR_IMAGE = str(MRImageStorage)
ENHANCED_MR = "1.2.840.10008.5.1.4.1.1.4.1"
MR_SPECTRO = "1.2.840.10008.5.1.4.1.1.4.2"
SEG_SOP = "1.2.840.10008.5.1.4.1.1.66.4"
BASIC_SR = "1.2.840.10008.5.1.4.1.1.88.11"
ENCAP_PDF = "1.2.840.10008.5.1.4.1.1.104.1"
JPEG_BASELINE = "1.2.840.10008.1.2.4.50"


def _write_dicom(
    path: Path,
    *,
    sop_class: str = MR_IMAGE,
    modality: str = "MR",
    transfer_syntax: str = ExplicitVRLittleEndian,
    series_uid: str | None = None,
    study_uid: str | None = None,
    number_of_frames: int | None = None,
    rows: int | None = 64,
    columns: int | None = 64,
    private_tag: bool = False,
    preamble: bool = True,
) -> None:
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = sop_class
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = transfer_syntax
    file_meta.ImplementationClassUID = generate_uid()

    preamble_bytes = (b"\0" * 128) if preamble else None
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=preamble_bytes)
    ds.PatientID = "ANON001"
    ds.StudyDescription = "FormatAudit"
    ds.SeriesDescription = "T1_MPRAGE"
    ds.ProtocolName = "t1_mprage"
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1
    ds.Modality = modality
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.Manufacturer = "TestVendor"
    ds.ManufacturerModelName = "SynthScanner"
    ds.ImageType = ["ORIGINAL", "PRIMARY", "M", "ND"]
    if rows is not None:
        ds.Rows = rows
    if columns is not None:
        ds.Columns = columns
    ds.BitsAllocated = 16
    ds.PhotometricInterpretation = "MONOCHROME2"
    if number_of_frames is not None:
        ds.NumberOfFrames = number_of_frames
    if private_tag:
        # Synthetic private creator + element (must not crash readers)
        block = ds.private_block(0x0029, "SIEMENS CSA HEADER", create=True)
        block.add_new(0x10, "OB", b"synthetic-csa")
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), enforce_file_format=preamble)


def test_extension_dcm_and_dicom(tmp_path: Path) -> None:
    _write_dicom(tmp_path / "a.dcm")
    _write_dicom(tmp_path / "b.dicom")
    assert looks_like_dicom_candidate(tmp_path / "a.dcm")
    assert looks_like_dicom_candidate(tmp_path / "b.dicom")
    assert probe_dicom_file(tmp_path / "a.dcm").is_dicom
    assert probe_dicom_file(tmp_path / "b.dicom").is_dicom


def test_extensionless_and_proprietary_with_preamble(tmp_path: Path) -> None:
    _write_dicom(tmp_path / "IM_0001")
    _write_dicom(tmp_path / "slice.v2")
    assert looks_like_dicom_candidate(tmp_path / "IM_0001")
    assert has_dicom_preamble(tmp_path / "slice.v2")
    assert looks_like_dicom_candidate(tmp_path / "slice.v2")
    series = DicomParser().scan(tmp_path)
    assert len(series) >= 1


def test_false_dcm_rejected(tmp_path: Path) -> None:
    fake = tmp_path / "not_really.dcm"
    fake.write_text("this is not dicom", encoding="utf-8")
    assert looks_like_dicom_candidate(fake)  # candidate by suffix
    probe = probe_dicom_file(fake)
    assert probe.is_dicom is False
    assert probe.object_class in {
        DicomObjectClass.NON_DICOM,
        DicomObjectClass.CORRUPTED_DICOM,
    }


def test_part10_preamble_and_transfer_syntax(tmp_path: Path) -> None:
    path = tmp_path / "part10.dcm"
    _write_dicom(path, transfer_syntax=ImplicitVRLittleEndian)
    probe = probe_dicom_file(path)
    assert probe.has_preamble is True
    assert probe.transfer_syntax_uid == str(ImplicitVRLittleEndian)
    assert "Implicit" in probe.transfer_syntax_name or probe.transfer_syntax_name == ""


def test_sop_class_and_modality_detection(tmp_path: Path) -> None:
    path = tmp_path / "mr.dcm"
    _write_dicom(path, sop_class=MR_IMAGE, modality="MR")
    probe = probe_dicom_file(path)
    assert probe.sop_class_uid == MR_IMAGE
    assert probe.modality == "MR"
    assert probe.object_class == DicomObjectClass.DICOM_IMAGE
    assert probe.convertibility == Convertibility.SUPPORTED


def test_multi_frame_detection(tmp_path: Path) -> None:
    path = tmp_path / "enhanced.dcm"
    _write_dicom(path, sop_class=ENHANCED_MR, number_of_frames=48, rows=128, columns=128)
    probe = probe_dicom_file(path)
    assert probe.number_of_frames == 48
    assert probe.object_class == DicomObjectClass.DICOM_ENHANCED_MULTI_FRAME
    assert probe.convertibility == Convertibility.SUPPORTED_WITH_LIMITATIONS


def test_compressed_transfer_syntax_header_only(tmp_path: Path) -> None:
    """Detection of JPEG Baseline UID — not pixel decompression."""
    path = tmp_path / "jpeg_hdr.dcm"
    _write_dicom(path, transfer_syntax=JPEG_BASELINE)
    probe = probe_dicom_file(path)
    assert probe.is_dicom
    assert probe.transfer_syntax_uid == JPEG_BASELINE
    assert "JPEG" in probe.transfer_syntax_name


def test_corrupted_and_zero_byte(tmp_path: Path) -> None:
    zero = tmp_path / "empty.dcm"
    zero.write_bytes(b"")
    probe_z = probe_dicom_file(zero)
    assert probe_z.object_class == DicomObjectClass.CORRUPTED_DICOM

    junk = tmp_path / "trunc.dcm"
    junk.write_bytes(b"\0" * 128 + b"DICM" + b"\xff\xfe")
    probe_j = probe_dicom_file(junk)
    assert probe_j.is_dicom is False


def test_private_tags_do_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "private.dcm"
    _write_dicom(path, private_tag=True)
    probe = probe_dicom_file(path)
    assert probe.is_dicom is True


def test_non_convertible_sop_classes() -> None:
    for sop, expected in (
        (MR_SPECTRO, DicomObjectClass.DICOM_SPECTROSCOPY),
        (SEG_SOP, DicomObjectClass.DICOM_SEGMENTATION),
        (BASIC_SR, DicomObjectClass.DICOM_STRUCTURED_REPORT),
        (ENCAP_PDF, DicomObjectClass.DICOM_OTHER),
    ):
        klass, conv = classify_sop_class(sop, modality="MR")
        assert klass == expected
        assert is_convertible_to_nifti(klass, conv) is False


def test_parser_marks_sr_non_convertible(tmp_path: Path) -> None:
    _write_dicom(
        tmp_path / "report.dcm",
        sop_class=BASIC_SR,
        modality="SR",
        rows=None,
        columns=None,
    )
    series = DicomParser().scan(tmp_path)
    assert len(series) == 1
    assert series[0].convertible_to_nifti is False
    assert series[0].dicom_object_class == DicomObjectClass.DICOM_STRUCTURED_REPORT.value


def test_converter_skips_non_convertible(tmp_path: Path) -> None:
    sample = tmp_path / "sr.dcm"
    sample.write_bytes(b"")
    series = DicomSeries(
        patient_id="ANON",
        study_description="x",
        series_description="SR",
        protocol_name="",
        series_number=1,
        acquisition_number=None,
        modality="SR",
        num_images=1,
        source_dir=tmp_path,
        sample_file=sample,
        series_instance_uid="1.2.3",
        dicom_object_class=DicomObjectClass.DICOM_STRUCTURED_REPORT.value,
        convertibility=Convertibility.NOT_APPLICABLE.value,
        convertible_to_nifti=False,
        sop_class_uid=BASIC_SR,
    )
    job = ConversionJob(
        series=series,
        output_dir=tmp_path / "out",
        options=ConversionOptions(),
    )
    result = Converter(dcm2niix_path="auto").convert_series(job)
    assert result.success is False
    assert "non-convertible" in (result.error or "").lower()
    assert result.command == []


def test_mixed_folder_ignores_non_dicom(tmp_path: Path) -> None:
    _write_dicom(tmp_path / "img.dcm")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "meta.json").write_text("{}", encoding="utf-8")
    (tmp_path / "readme.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / ".DS_Store").write_bytes(b"\0\0")
    (tmp_path / "Thumbs.db").write_bytes(b"MZ")
    series = DicomParser().scan(tmp_path)
    assert len(series) == 1
    assert series[0].modality == "MR"
    assert series[0].transfer_syntax_uid == str(ExplicitVRLittleEndian)


def test_dcm2niix_discovery_search_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_exe = tmp_path / "tools" / "dcm2niix.exe"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_bytes(b"MZ")

    from neuro_pipeline.config import paths as path_mod

    monkeypatch.setattr(path_mod, "project_root", lambda: tmp_path)
    monkeypatch.setattr(path_mod, "resource_root", lambda: tmp_path)
    monkeypatch.setattr(path_mod, "is_frozen", lambda: False)

    resolved = Converter(dcm2niix_path="auto").verify()
    assert resolved == fake_exe.resolve()


def test_secondary_capture_classification() -> None:
    klass, conv = classify_sop_class(
        str(SecondaryCaptureImageStorage),
        modality="SC",
        rows=256,
        columns=256,
    )
    assert klass == DicomObjectClass.DICOM_SECONDARY_CAPTURE
    assert conv == Convertibility.SUPPORTED_WITH_LIMITATIONS
    assert is_convertible_to_nifti(klass, conv) is True
