"""Tests for professional QC dashboard generator."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.models import ConversionResult, DicomSeries, SeriesStatus
from neuro_pipeline.qc.dashboard import QCDashboardContext, QCDashboardGenerator
from neuro_pipeline.validation.models import ValidationSummary


def _series(name: str = "t1_mprage", seq: str = "anat") -> DicomSeries:
    root = Path("fake")
    return DicomSeries(
        patient_id="01",
        study_description="S",
        series_description=name,
        protocol_name=name,
        series_number=1,
        acquisition_number=1,
        modality="MR",
        num_images=10,
        source_dir=root,
        sample_file=root / "x.dcm",
        status=SeriesStatus.DONE,
        sequence_type=seq,
    )


def test_qc_dashboard_writes_html(tmp_path: Path) -> None:
    nii = tmp_path / "sub-01_T1w.nii.gz"
    nii.write_bytes(b"nifti")
    result = ConversionResult(
        series=_series(),
        success=True,
        output_files=[nii],
    )
    path = QCDashboardGenerator(tmp_path).write(
        QCDashboardContext(
            conversion_results=[result],
            validation=ValidationSummary(),
            output_folder=tmp_path,
            input_folder=tmp_path / "in",
            scanner="Siemens Prisma",
            field_strength="3T",
            series_detected=1,
        )
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "QC Dashboard" in text
    assert "Siemens Prisma" in text
    assert "sub-01_T1w.nii.gz" in text
    assert "Total series" in text


def test_qc_dashboard_does_not_overwrite(tmp_path: Path) -> None:
    existing = tmp_path / "qc_report.html"
    existing.write_text("original", encoding="utf-8")
    result = ConversionResult(series=_series(), success=True, output_files=[])
    path = QCDashboardGenerator(tmp_path).write(
        QCDashboardContext(conversion_results=[result], series_detected=1)
    )
    assert path != existing
    assert existing.read_text(encoding="utf-8") == "original"
    assert path.exists()


def test_qc_dashboard_lists_failed(tmp_path: Path) -> None:
    failed = ConversionResult(
        series=_series("bad", "unknown"),
        success=False,
        error="boom",
        output_files=[],
    )
    path = QCDashboardGenerator(tmp_path).write(
        QCDashboardContext(conversion_results=[failed], series_detected=1)
    )
    text = path.read_text(encoding="utf-8")
    assert "Failed" in text


def test_warning_panel_mentions_missing_json(tmp_path: Path) -> None:
    nii = tmp_path / "run.nii.gz"
    nii.write_bytes(b"x")
    result = ConversionResult(
        series=_series("ep2d_diff", "dwi"),
        success=True,
        output_files=[nii],
    )
    path = QCDashboardGenerator(tmp_path).write(
        QCDashboardContext(conversion_results=[result], series_detected=1)
    )
    text = path.read_text(encoding="utf-8")
    assert "missing" in text.lower()
