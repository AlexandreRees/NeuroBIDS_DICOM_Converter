"""Tests for HTML report generation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

nibabel = pytest.importorskip("nibabel")
import nibabel as nib  # noqa: E402

from neuro_pipeline.models import ConversionResult, DicomSeries, SeriesStatus
from neuro_pipeline.validation import (
    NiftiValidator,
    ReportContext,
    ReportGenerator,
    run_full_validation,
)


def test_html_report_generated(tmp_path: Path) -> None:
    nifti = tmp_path / "T1w.nii.gz"
    nib.save(nib.Nifti1Image(np.ones((5, 5, 5), dtype=np.float32), np.eye(4)), str(nifti))

    series = DicomSeries(
        patient_id="P1",
        study_description="Study",
        series_description="MPRAGE",
        protocol_name="MPRAGE",
        series_number=1,
        acquisition_number=1,
        modality="MR",
        num_images=5,
        source_dir=tmp_path,
        sample_file=tmp_path / "x.dcm",
        status=SeriesStatus.DONE,
        sequence_type="anat",
    )
    conversion = ConversionResult(
        series=series,
        success=True,
        output_files=[nifti],
    )
    validation = run_full_validation(tmp_path)
    assert NiftiValidator(tmp_path).validate_all()

    report = ReportGenerator(tmp_path).write(
        ReportContext(
            input_folder=tmp_path / "in",
            output_folder=tmp_path,
            conversion_results=[conversion],
            validation=validation,
            series_detected=1,
        )
    )
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "NeuroPipeline Conversion Report" in text
    assert "Conversion completed successfully" in text or "Conversion finished" in text
    assert "Sequences detected" in text
    assert "Sequences converted" in text
    assert "MPRAGE" in text
    assert "Software version" in text
    assert "BIDS validation" in text
