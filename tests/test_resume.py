"""Resume / checkpoint tests (synthetic)."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.batch.batch_models import BatchJobStatus, BatchState
from neuro_pipeline.batch.resume import (
    SeriesCheckpoint,
    compute_source_hash,
    has_resumable_state,
    load_state,
    should_skip_series,
    write_series_checkpoint,
    write_state,
)


def test_state_json_roundtrip(tmp_path: Path) -> None:
    state = BatchState(
        job_id="001",
        status=BatchJobStatus.RUNNING,
        completed_series=35,
        total_series=100,
        input_path=str(tmp_path / "in"),
        output_path=str(tmp_path),
        completed_series_uids=["uid-a", "uid-b"],
    )
    write_state(tmp_path, state)
    loaded = load_state(tmp_path)
    assert loaded is not None
    assert loaded.job_id == "001"
    assert loaded.completed_series == 35
    assert loaded.total_series == 100
    assert has_resumable_state(tmp_path)


def test_skip_completed_series_same_hash(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.dcm"
    f.write_bytes(b"dicom-bytes")
    source_hash = compute_source_hash([f])
    out_file = tmp_path / "out.nii.gz"
    out_file.write_bytes(b"nii")
    write_series_checkpoint(
        tmp_path,
        SeriesCheckpoint(
            source_hash=source_hash,
            output_hash="abc",
            status="completed",
            series_uid="SERIES1",
            output_files=[out_file.name],
        ),
    )
    assert should_skip_series(output_root=tmp_path, series_uid="SERIES1", source_hash=source_hash)


def test_do_not_skip_when_hash_changes(tmp_path: Path) -> None:
    write_series_checkpoint(
        tmp_path,
        SeriesCheckpoint(
            source_hash="old",
            output_hash="abc",
            status="completed",
            series_uid="SERIES1",
            output_files=[],
        ),
    )
    assert not should_skip_series(
        output_root=tmp_path,
        series_uid="SERIES1",
        source_hash="new",
    )
