"""BIDS naming must never block DICOM → NIfTI conversion."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.bids.naming import (
    build_bids_target,
    build_fallback_nifti_target,
    dwi_acquisition,
    is_adc_series,
)
from neuro_pipeline.converter.conversion_manager import ConversionManager
from neuro_pipeline.models import ConversionOptions, ConversionResult, DicomSeries, SeriesStatus


def _series(
    description: str,
    *,
    seq: str = "dwi",
    patient_id: str = "001",
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
        fine_sequence_type=seq.upper(),
        smart_name=description,
        series_instance_uid=uid or f"1.2.840.{series_number}.{abs(hash(description)) % 10**8}",
        study_instance_uid="1.2.840.0",
        sequence_confidence=0.9,
    )


def test_dwi_bipolar_has_acquisition_and_filename() -> None:
    series = _series("ep2d_diff_4scan-trace_p3 bipolar", uid="dwi-bip")
    plan = BIDSConversionPlan.from_series(
        [series], subject_override="001", session_override="01"
    )
    plan.refresh_filenames()
    item = plan.get("dwi-bip")
    assert item is not None
    assert item.include_in_conversion
    assert item.intended_filename
    assert item.acquisition or "acq-" in item.intended_filename
    acq = dwi_acquisition(series)
    assert "4scan" in acq.lower()
    assert "bipolar" in acq.lower()
    assert "adc" not in acq.lower()
    target = build_bids_target(series, "001", "01")
    assert target is not None
    assert target.filename_stem
    assert "bipolar" in target.filename_stem.lower()


def test_dwi_monopolar_has_acquisition_and_filename() -> None:
    series = _series("ep2d_diff_4scan-trace_p3 monopolar", uid="dwi-mono")
    plan = BIDSConversionPlan.from_series(
        [series], subject_override="001", session_override="01"
    )
    plan.refresh_filenames()
    item = plan.get("dwi-mono")
    assert item is not None
    assert item.intended_filename
    acq = dwi_acquisition(series)
    assert "monopolar" in acq.lower()
    assert acq != dwi_acquisition(
        _series("ep2d_diff_4scan-trace_p3 bipolar", uid="other")
    )
    target = build_bids_target(series, "001", "01")
    assert target is not None
    assert "monopolar" in target.filename_stem.lower()


def test_adc_has_fallback_filename_not_raw_bids() -> None:
    series = _series("ep2d_diff_4scan-trace_p3 bipolar_ADC", uid="adc-1")
    assert is_adc_series(series)
    assert build_bids_target(series, "001", "01") is None

    fallback = build_fallback_nifti_target(series, "001", "01")
    assert fallback.datatype == "derivatives"
    assert "ADC" in fallback.filename_stem.upper()
    assert fallback.filename_stem.startswith("sub-001_ses-01_")

    plan = BIDSConversionPlan.from_series(
        [series], subject_override="001", session_override="01"
    )
    plan.refresh_filenames()
    item = plan.get("adc-1")
    assert item is not None
    assert item.include_in_conversion is True
    assert item.intended_filename
    assert "ADC" in item.intended_filename.upper()
    # No planned filename must not appear as a blocking error after refresh
    result = plan.validate()
    assert not any("No planned filename" in i.message for i in result.issues)


def test_identical_series_get_unique_runs() -> None:
    a = _series("t1_mprage_sag_p2_iso_ORIG", seq="anat", uid="t1a", series_number=1)
    b = _series("t1_mprage_sag_p2_iso_ORIG", seq="anat", uid="t1b", series_number=2)
    plan = BIDSConversionPlan.from_series(
        [a, b], subject_override="001", session_override="01"
    )
    plan.refresh_filenames()
    names = {plan.get("t1a").intended_filename, plan.get("t1b").intended_filename}  # type: ignore[union-attr]
    assert len(names) == 2
    assert all(n for n in names)
    stems = {n.replace(".nii.gz", "") for n in names}
    # unique_stem injects run on the colliding second stem
    assert any("run-" in s for s in stems) or len(stems) == 2


def test_weird_non_bids_series_gets_fallback() -> None:
    series = _series("WEIRD SEQUENCE !!! ???", seq="unknown", uid="weird")
    plan = BIDSConversionPlan.from_series(
        [series], subject_override="001", session_override="01"
    )
    plan.refresh_filenames()
    item = plan.get("weird")
    assert item is not None
    assert item.intended_filename
    assert item.intended_filename.endswith(".nii.gz")
    assert "____" not in item.intended_filename
    validation = plan.validate()
    # May be BIDS-invalid, but conversion name exists
    assert item.include_in_conversion
    assert not any("No planned filename" in i.message for i in validation.issues)


def test_invalid_bids_plan_still_runs_nifti(tmp_path: Path, monkeypatch) -> None:
    from neuro_pipeline.bids.conversion_plan import PlanValidationIssue, PlanValidationResult

    series = [
        _series("ep2d_diff_4scan-trace_p3 bipolar_ADC", uid="adc-a", series_number=1),
        _series("ep2d_diff_3scan-trace_p3 bipolar_ADC", uid="adc-b", series_number=2),
    ]
    plan = BIDSConversionPlan.from_series(
        series, subject_override="001", session_override="01"
    )
    plan.refresh_filenames()
    monkeypatch.setattr(
        BIDSConversionPlan,
        "validate",
        lambda self: PlanValidationResult(
            ok=False,
            issues=[
                PlanValidationIssue("error", "forced BIDS invalidity"),
                PlanValidationIssue("warning", "ADC excluded from raw BIDS"),
            ],
        ),
    )
    assert plan.validate().ok is False

    converted: list[str] = []

    def _fake_convert(job, progress=None):  # noqa: ANN001
        converted.append(job.series.series_instance_uid)
        return ConversionResult(series=job.series, success=True, output_files=[])

    manager = ConversionManager(dcm2niix_path="auto")
    manager.converter.convert_series = _fake_convert  # type: ignore[method-assign]
    manager.converter.verify = lambda: Path("dcm2niix")  # type: ignore[method-assign]

    out = manager.run(
        series_list=series,
        input_folder=tmp_path,
        output_dir=tmp_path / "out",
        options=ConversionOptions(output_layout="nifti", subject_id="001"),
        conversion_plan=plan,
    )
    assert out.plan_validation_ok is False
    assert out.conversion_success is True
    assert set(converted) == {"adc-a", "adc-b"}
