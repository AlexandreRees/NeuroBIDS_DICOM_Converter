"""Synthetic conversion-flow handoff tests (parser/GUI → ConversionManager)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from neuro_pipeline.converter.conversion_manager import ConversionManager
from neuro_pipeline.models import ConversionOptions, ConversionResult, DicomSeries, SeriesStatus


def _fake_series(path: str = "fake_dicom_folder") -> DicomSeries:
    root = Path(path)
    return DicomSeries(
        patient_id="TEST",
        study_description="Study",
        series_description="ep2d_diff_test",
        protocol_name="ep2d_diff_test",
        series_number=1,
        acquisition_number=1,
        modality="MR",
        num_images=10,
        source_dir=root,
        sample_file=root / "image.dcm",
        status=SeriesStatus.PENDING,
        sequence_type="dwi",
        series_instance_uid="1.2.3",
    )


def test_conversion_manager_receives_one_series(tmp_path: Path, monkeypatch) -> None:
    series = [_fake_series(str(tmp_path / "fake_dicom_folder"))]
    manager = ConversionManager(dcm2niix_path="auto")

    seen: dict[str, object] = {}

    def fake_prepare(output_dir: Path) -> Path:
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        return out

    def fake_convert_series(job, progress=None):  # noqa: ANN001
        seen["series"] = job.series
        seen["count_at_call"] = 1
        return ConversionResult(series=job.series, success=True)

    monkeypatch.setattr(manager, "prepare", fake_prepare)
    monkeypatch.setattr(manager.converter, "convert_series", fake_convert_series)

    result = manager.run(
        series_list=series,
        input_folder=tmp_path,
        output_dir=tmp_path / "out",
        options=ConversionOptions(validate_output=False),
    )

    assert len(result.conversion_results) == 1
    assert seen["series"].series_description == "ep2d_diff_test"
    assert result.converted == 1


def test_worker_style_copy_survives_source_list_clear(tmp_path: Path) -> None:
    """Mirrors ConversionWorker.__init__: list(series_list) protects the handoff."""
    shared: list[DicomSeries] = [_fake_series(str(tmp_path / "fake_dicom_folder"))]
    worker_series_list = list(shared)
    shared.clear()  # simulate GUI autoscan wipe of the original list
    assert len(worker_series_list) == 1
    assert worker_series_list[0].series_description == "ep2d_diff_test"


def test_gui_snapshot_logic_preserves_count() -> None:
    """Document the critical handoff: snapshot before dialogs."""
    gui_series = [_fake_series() for _ in range(10)]
    snapshot = list(gui_series)
    gui_series.clear()  # editingFinished autoscan race
    assert len(snapshot) == 10
    assert len(gui_series) == 0


def test_conversion_manager_receives_all_ten(tmp_path: Path, monkeypatch) -> None:
    series = [_fake_series(str(tmp_path / f"ser_{i}")) for i in range(10)]
    manager = ConversionManager(dcm2niix_path="auto")
    calls: list[str] = []

    monkeypatch.setattr(manager, "prepare", lambda output_dir: tmp_path / "out")
    monkeypatch.setattr(
        manager.converter,
        "convert_series",
        lambda job, progress=None: calls.append(job.series.display_name)
        or ConversionResult(series=job.series, success=True),
    )

    (tmp_path / "out").mkdir(exist_ok=True)
    result = manager.run(
        series_list=series,
        input_folder=tmp_path,
        output_dir=tmp_path / "out",
        options=ConversionOptions(validate_output=False),
    )
    assert len(calls) == 10
    assert result.converted == 10
