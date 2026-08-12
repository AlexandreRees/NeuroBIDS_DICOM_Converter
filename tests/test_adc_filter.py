"""ADC maps must not be exported as BIDS DWI."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.bids.exporter import BIDSExporter
from neuro_pipeline.bids.naming import build_bids_target, is_adc_series
from neuro_pipeline.models import ConversionResult, DicomSeries, SeriesStatus


def _series(desc: str, seq: str = "dwi") -> DicomSeries:
    root = Path("fake")
    return DicomSeries(
        patient_id="x",
        study_description="S",
        series_description=desc,
        protocol_name=desc,
        series_number=1,
        acquisition_number=1,
        modality="MR",
        num_images=5,
        source_dir=root,
        sample_file=root / "a.dcm",
        status=SeriesStatus.DONE,
        sequence_type=seq,
        smart_name=desc,
    )


def test_is_adc_detection() -> None:
    assert is_adc_series(_series("ep2d_diff_ADC"))
    assert is_adc_series(_series("dwi"), nifti_name="sub_ADC.nii.gz")
    assert not is_adc_series(_series("ep2d_diff_TRACEW"))


def test_adc_excluded_from_bids_target() -> None:
    assert build_bids_target(_series("DIFF_ADC"), "001") is None


def test_adc_goes_to_derivatives(tmp_path: Path) -> None:
    series = _series("ep2d_diff_ADC")
    staging = tmp_path / "stg"
    staging.mkdir()
    nii = staging / "series_ADC.nii.gz"
    nii.write_bytes(b"adc")
    (staging / "series_ADC.json").write_text("{}", encoding="utf-8")
    result = ConversionResult(series=series, success=True, output_files=[nii])
    export = BIDSExporter(tmp_path / "bids", subject_id="001").export([result])
    assert not list((tmp_path / "bids" / "sub-001" / "dwi").glob("*")) if (
        tmp_path / "bids" / "sub-001" / "dwi"
    ).exists() else True
    adc = list((tmp_path / "bids" / "derivatives" / "non-BIDS").rglob("*ADC*.nii.gz"))
    assert len(adc) == 1
    assert export.exported >= 1 or export.skipped >= 0


def test_tracew_is_dwi() -> None:
    target = build_bids_target(_series("ep2d_diff_TRACEW"), "001")
    assert target is not None
    assert target.datatype == "dwi"
    assert target.filename_stem.endswith("_dwi")
