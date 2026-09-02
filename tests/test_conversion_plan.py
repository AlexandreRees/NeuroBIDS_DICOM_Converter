"""Tests for BIDSConversionPlan preview (DICOM remains read-only)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.bids.exporter import BIDSExporter
from neuro_pipeline.converter.conversion_manager import ConversionManager
from neuro_pipeline.models import ConversionOptions, ConversionResult, DicomSeries, SeriesStatus


def _series(
    description: str,
    *,
    seq: str = "anat",
    fine: str = "ANAT_T1",
    patient_id: str = "SUB001",
    series_number: int = 1,
    uid: str = "",
) -> DicomSeries:
    root = Path("fake_dicom_readonly")
    return DicomSeries(
        patient_id=patient_id,
        study_description="Study",
        series_description=description,
        protocol_name=description,
        series_number=series_number,
        acquisition_number=1,
        modality="MR",
        num_images=10,
        source_dir=root,
        sample_file=root / "x.dcm",
        status=SeriesStatus.PENDING,
        sequence_type=seq,
        fine_sequence_type=fine,
        smart_name=description,
        series_instance_uid=uid or f"1.2.840.{series_number}",
        study_instance_uid="1.2.840.0",
        sequence_confidence=0.9,
    )


def test_preview_generation_does_not_modify_dicom(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    sample = dicom_dir / "img.dcm"
    original = b"DICOM_BYTES_UNCHANGED"
    sample.write_bytes(original)
    mtime_before = sample.stat().st_mtime_ns

    series = _series("t1_mprage")
    series.source_dir = dicom_dir
    series.sample_file = sample

    plan = BIDSConversionPlan.from_series(
        [series],
        dataset_root=dicom_dir,
        subject_override="001",
        session_override="01",
    )
    plan.apply_edit(series.series_instance_uid, run="02", task="")
    plan.refresh_filenames()
    # Refuse writing plan JSON into the DICOM folder
    with pytest.raises(ValueError, match="Refusing"):
        plan.save_json(dicom_dir / "conversion_plan.json")

    assert sample.read_bytes() == original
    assert sample.stat().st_mtime_ns == mtime_before
    assert list(dicom_dir.iterdir()) == [sample]


def test_changing_task_run_only_updates_plan() -> None:
    series = _series("rest_AP", seq="func", fine="FMRI_REST", uid="uid-rest")
    plan = BIDSConversionPlan.from_series(
        [series],
        subject_override="001",
        session_override="01",
    )
    before = plan.get("uid-rest")
    assert before is not None
    auto_name = before.intended_filename
    plan.apply_edit("uid-rest", task="movie", run="03")
    plan.refresh_filenames()
    after = plan.get("uid-rest")
    assert after is not None
    assert after.task == "movie"
    assert after.run == "03"
    assert "task-movie" in after.intended_filename
    assert "run-03" in after.intended_filename
    assert after.intended_filename != auto_name
    # Source metadata unchanged
    assert series.series_description == "rest_AP"
    assert series.series_instance_uid == "uid-rest"


def test_reset_restores_automatic_plan() -> None:
    series = _series("rest_AP", seq="func", fine="FMRI_REST", uid="uid-rest")
    plan = BIDSConversionPlan.from_series([series], subject_override="001")
    original = plan.get("uid-rest").intended_filename  # type: ignore[union-attr]
    plan.apply_edit("uid-rest", task="movie", run="09")
    plan.refresh_filenames()
    assert plan.get("uid-rest").task == "movie"  # type: ignore[union-attr]
    plan.reset_changes()
    restored = plan.get("uid-rest")
    assert restored is not None
    assert restored.task != "movie" or restored.run != "09"
    assert restored.intended_filename == original


def test_conversion_output_follows_validated_plan(tmp_path: Path) -> None:
    series = _series("t1_mprage", uid="uid-t1")
    plan = BIDSConversionPlan.from_series(
        [series],
        subject_override="001",
        session_override="01",
    )
    plan.apply_edit("uid-t1", run="02")
    plan.refresh_filenames()
    assert plan.validate().ok
    intended = plan.get("uid-t1").intended_filename  # type: ignore[union-attr]
    assert "run-02" in intended

    staging = tmp_path / "stg"
    staging.mkdir()
    nii = staging / "raw.nii.gz"
    nii.write_bytes(b"nii")
    (staging / "raw.json").write_text("{}", encoding="utf-8")
    result = ConversionResult(
        series=series,
        success=True,
        output_files=[nii, staging / "raw.json"],
    )
    export = BIDSExporter(
        tmp_path / "bids",
        subject_id="001",
        session_id="01",
        conversion_plan=plan,
    ).export([result], conversion_plan=plan)
    assert export.exported == 1
    assert export.items[0].target_nifti.name == intended
    assert export.items[0].target_nifti.exists()


def test_invalid_plan_does_not_abort_nifti_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BIDS plan errors must not raise — DICOM→NIfTI continues."""
    from neuro_pipeline.bids.conversion_plan import PlanValidationIssue, PlanValidationResult

    series = [
        _series("t1a", uid="u1", series_number=1),
        _series("t1b", uid="u2", series_number=2),
    ]
    plan = BIDSConversionPlan.from_series(series, subject_override="001")
    plan.refresh_filenames()
    monkeypatch.setattr(
        BIDSConversionPlan,
        "validate",
        lambda self: PlanValidationResult(
            ok=False,
            issues=[PlanValidationIssue("error", "forced duplicate BIDS entities")],
        ),
    )
    assert not plan.validate().ok

    manager = ConversionManager(dcm2niix_path="dcm2niix")
    converted: list[str] = []

    def _fake_convert(job, progress=None):  # noqa: ANN001
        converted.append(job.series.series_instance_uid)
        return ConversionResult(series=job.series, success=True, output_files=[])

    manager.converter.convert_series = _fake_convert  # type: ignore[method-assign]
    manager.converter.verify = lambda: Path("dcm2niix")  # type: ignore[method-assign]
    result = manager.run(
        series_list=series,
        input_folder=tmp_path,
        output_dir=tmp_path / "out",
        options=ConversionOptions(output_layout="nifti", subject_id="001"),
        conversion_plan=plan,
    )
    assert result.plan_validation_ok is False
    assert set(converted) == {"u1", "u2"}
    assert result.conversion_success is True



def test_excluded_series_not_converted(tmp_path: Path) -> None:
    keep = _series("t1_mprage", uid="keep")
    drop = _series("localizer", uid="drop", seq="unknown", fine="LOCALIZER")
    plan = BIDSConversionPlan.from_series(
        [keep, drop],
        subject_override="001",
    )
    plan.apply_edit("drop", include_in_conversion=False)
    plan.refresh_filenames()
    # Unknown datatype may fail validate — force keep-only valid plan
    for item in plan.items:
        if item.source_series_uid == "drop":
            continue
        item.datatype = "anat"
        item.suffix = "T1w"
    plan.refresh_filenames()
    included = plan.included_series([keep, drop])
    assert [s.series_instance_uid for s in included] == ["keep"]


def test_json_roundtrip_user_choices(tmp_path: Path) -> None:
    series = _series("rest_AP", seq="func", fine="FMRI_REST", uid="uid-rest")
    plan = BIDSConversionPlan.from_series(
        [series],
        dataset_root=tmp_path / "in",
        output_root=tmp_path / "out",
        subject_override="001",
        session_override="01",
    )
    plan.apply_edit("uid-rest", task="movie", run="02")
    plan.refresh_filenames()
    path = plan.save_json(tmp_path / "out" / "conversion_plan.json")
    loaded = BIDSConversionPlan.load_json(
        path,
        [series],
        dataset_root=tmp_path / "in",
        output_root=tmp_path / "out",
        subject_override="001",
        session_override="01",
    )
    item = loaded.get("uid-rest")
    assert item is not None
    assert item.task == "movie"
    assert item.run == "02"
