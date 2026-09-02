"""Batch conversion engine tests (synthetic folders, no real MRI data)."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.batch import BatchJob, BatchJobStatus, BatchManager


def test_discover_datasets_creates_jobs(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    out = tmp_path / "bids"
    (root / "subject001").mkdir(parents=True)
    (root / "subject002").mkdir(parents=True)
    mgr = BatchManager()
    jobs = mgr.discover_datasets(root, output_root=out)
    assert len(jobs) == 2
    assert {j.label for j in jobs} == {"subject001", "subject002"}
    assert all(j.status == BatchJobStatus.QUEUED for j in jobs)
    # Shared BIDS dataset root; subjects become sub-<id> via mapping
    assert all(Path(j.output_path) == out for j in jobs)


def test_batch_job_roundtrip_dict() -> None:
    job = BatchJob.create("/tmp/in/sub-01", "/tmp/out/sub-01", label="sub-01")
    data = job.to_dict()
    restored = BatchJob.from_dict(data)
    assert restored.job_id == job.job_id
    assert restored.status == BatchJobStatus.QUEUED
    assert restored.label == "sub-01"
