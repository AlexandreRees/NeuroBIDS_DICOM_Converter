"""Batch BIDS export uses per-job Subject ID into a shared dataset root."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.batch.batch_manager import BatchManager
from neuro_pipeline.batch.batch_models import BatchJob


def test_discover_shares_dataset_root(tmp_path: Path) -> None:
    root = tmp_path / "dicoms"
    (root / "folderA").mkdir(parents=True)
    (root / "folderB").mkdir(parents=True)
    out = tmp_path / "dataset"
    jobs = BatchManager().discover_datasets(root, output_root=out)
    assert len(jobs) == 2
    assert all(Path(j.output_path) == out for j in jobs)
    assert {j.label for j in jobs} == {"folderA", "folderB"}


def test_batch_job_holds_subject_mapping(tmp_path: Path) -> None:
    job = BatchJob.create(tmp_path / "in", tmp_path / "dataset", label="folderA")
    job.subject_id = "001"
    assert job.subject_id == "001"
    assert Path(job.output_path).name == "dataset"


def test_run_job_requires_subject(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    inp.mkdir()
    job = BatchJob.create(inp, tmp_path / "dataset", label="in")
    # no subject_id
    out = BatchManager().run_job(job, resume=False)
    assert out.status.value == "FAILED"
    assert out.error and "Subject ID" in out.error
