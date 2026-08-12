"""Tests for BIDS subject / session management."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.bids.exporter import BIDSExporter
from neuro_pipeline.bids.naming import build_bids_target
from neuro_pipeline.bids.subject_manager import SubjectManager
from neuro_pipeline.models import ConversionResult, DicomSeries, SeriesStatus


def test_validate_subject_id_accepts_prefixed_and_bare() -> None:
    mgr = SubjectManager()
    assert mgr.validate_subject_id("001") == "001"
    assert mgr.validate_subject_id("sub-001") == "001"
    assert mgr.validate_subject_id("sub-ABC12") == "ABC12"


def test_validate_subject_rejects_spaces_and_specials() -> None:
    mgr = SubjectManager()
    with pytest.raises(ValueError):
        mgr.validate_subject_id("sub 001")
    with pytest.raises(ValueError):
        mgr.validate_subject_id("sub-001!")
    with pytest.raises(ValueError):
        mgr.validate_subject_id("")


def test_session_optional() -> None:
    mgr = SubjectManager()
    assert mgr.validate_session_id("") is None
    assert mgr.validate_session_id(None) is None
    assert mgr.validate_session_id("ses-01") == "01"
    with pytest.raises(ValueError):
        mgr.validate_session_id("ses 01")


def test_create_bids_subject_with_and_without_session(tmp_path: Path) -> None:
    mgr = SubjectManager()
    no_ses = mgr.create_bids_subject(tmp_path, "001")
    assert no_ses == tmp_path / "sub-001"
    assert no_ses.is_dir()
    assert not (tmp_path / "sub-001" / "ses-01").exists()

    with_ses = mgr.create_bids_subject(tmp_path, "001", "01")
    assert with_ses == tmp_path / "sub-001" / "ses-01"
    assert with_ses.is_dir()


def test_exporter_session_layout(tmp_path: Path) -> None:
    series = DicomSeries(
        patient_id="ignore",
        study_description="Study",
        series_description="t1_mprage",
        protocol_name="t1_mprage",
        series_number=1,
        acquisition_number=1,
        modality="MR",
        num_images=5,
        source_dir=tmp_path,
        sample_file=tmp_path / "x.dcm",
        status=SeriesStatus.DONE,
        sequence_type="anat",
        smart_name="T1w",
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    nii = staging / "T1w.nii.gz"
    js = staging / "T1w.json"
    nii.write_bytes(b"nii")
    js.write_text('{"ProtocolName": "t1_mprage"}', encoding="utf-8")
    result = ConversionResult(series=series, success=True, output_files=[nii, js])

    export = BIDSExporter(
        tmp_path / "bids",
        subject_id="001",
        session_id="01",
    ).export([result])

    dest = tmp_path / "bids" / "sub-001" / "ses-01" / "anat" / "sub-001_ses-01_T1w.nii.gz"
    assert dest.exists()
    assert (dest.parent / "sub-001_ses-01_T1w.json").exists()
    assert export.exported == 1
    # No session-less anat for this subject when session provided
    assert not (tmp_path / "bids" / "sub-001" / "anat").exists()


def test_build_bids_target_includes_session() -> None:
    series = DicomSeries(
        patient_id="01",
        study_description="",
        series_description="t1_mprage",
        protocol_name="t1_mprage",
        series_number=1,
        acquisition_number=None,
        modality="MR",
        num_images=1,
        source_dir=Path("."),
        sample_file=Path("x.dcm"),
        sequence_type="anat",
    )
    target = build_bids_target(series, "01", "02")
    assert target is not None
    assert target.filename_stem == "sub-01_ses-02_T1w"
