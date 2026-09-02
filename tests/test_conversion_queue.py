"""Tests for ConversionQueueManager (optional layer above BatchManager)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from neuro_pipeline.batch.batch_models import BatchJob, BatchJobStatus
from neuro_pipeline.workers.conversion_queue import (
    ConversionJob,
    ConversionQueueManager,
    QueueJobStatus,
)


def _ok_batch_job(subject: str = "001") -> BatchJob:
    job = BatchJob.create(Path("in"), Path("out"), label=subject)
    job.subject_id = subject
    job.status = BatchJobStatus.COMPLETED
    return job


def test_jobs_execute_sequentially(tmp_path: Path) -> None:
    manager = ConversionQueueManager(
        state_path=tmp_path / "conversion_queue.json",
        log_path=tmp_path / "conversion_queue.log",
    )
    manager.add_job(
        ConversionJob.create(subject="001", session="01", input_path=tmp_path, output_path=tmp_path / "o1")
    )
    manager.add_job(
        ConversionJob.create(subject="002", session="01", input_path=tmp_path, output_path=tmp_path / "o2")
    )

    order: list[str] = []

    def fake_convert(folder, output_root, **kwargs):  # noqa: ANN001
        # subject from options
        options = kwargs.get("options")
        order.append(options.subject_id if options else "")
        return [_ok_batch_job(options.subject_id if options else "x")]

    with patch("neuro_pipeline.batch.BatchManager") as BM:
        instance = BM.return_value
        instance.convert_folder.side_effect = fake_convert
        manager.run()

    assert order == ["001", "002"]
    assert all(j.status == QueueJobStatus.COMPLETED for j in manager.jobs)


def test_pause_stops_new_jobs(tmp_path: Path) -> None:
    manager = ConversionQueueManager(
        state_path=tmp_path / "q.json",
        log_path=tmp_path / "q.log",
    )
    manager.add_job(
        ConversionJob.create(subject="001", session="", input_path=tmp_path, output_path=tmp_path / "o")
    )
    manager.add_job(
        ConversionJob.create(subject="002", session="", input_path=tmp_path, output_path=tmp_path / "o2")
    )
    started: list[str] = []

    def fake_convert(folder, output_root, **kwargs):  # noqa: ANN001
        options = kwargs.get("options")
        started.append(options.subject_id)
        manager.pause_queue()
        return [_ok_batch_job(options.subject_id)]

    with patch("neuro_pipeline.batch.BatchManager") as BM:
        BM.return_value.convert_folder.side_effect = fake_convert
        manager.run()

    assert started == ["001"]
    # Second job should remain paused/queued, not completed
    statuses = {j.subject: j.status for j in manager.jobs}
    assert statuses["001"] in {QueueJobStatus.COMPLETED, QueueJobStatus.PAUSED}
    assert statuses["002"] in {QueueJobStatus.PAUSED, QueueJobStatus.QUEUED}


def test_resume_continues_queue(tmp_path: Path) -> None:
    manager = ConversionQueueManager(
        state_path=tmp_path / "q.json",
        log_path=tmp_path / "q.log",
    )
    j1 = ConversionJob.create(subject="001", session="", input_path=tmp_path, output_path=tmp_path / "o")
    j2 = ConversionJob.create(subject="002", session="", input_path=tmp_path, output_path=tmp_path / "o2")
    j2.status = QueueJobStatus.PAUSED
    manager.add_job(j1)
    manager.add_job(j2)
    with patch("neuro_pipeline.batch.BatchManager") as BM:
        BM.return_value.convert_folder.return_value = [_ok_batch_job("001")]
        manager.resume_queue()
        assert j2.status == QueueJobStatus.QUEUED
        manager.run()
    assert all(j.status == QueueJobStatus.COMPLETED for j in manager.jobs)


def test_failed_jobs_can_retry(tmp_path: Path) -> None:
    manager = ConversionQueueManager(
        state_path=tmp_path / "q.json",
        log_path=tmp_path / "q.log",
    )
    job = ConversionJob.create(subject="001", session="", input_path=tmp_path, output_path=tmp_path / "o")
    job.status = QueueJobStatus.FAILED
    job.error_message = "boom"
    manager.add_job(job)
    assert manager.retry_failed() == 1
    assert job.status == QueueJobStatus.QUEUED
    assert job.error_message == ""


def test_queue_survives_restart(tmp_path: Path) -> None:
    state = tmp_path / "conversion_queue.json"
    log = tmp_path / "conversion_queue.log"
    manager = ConversionQueueManager(state_path=state, log_path=log)
    manager.add_job(
        ConversionJob.create(subject="sub-009", session="01", input_path=tmp_path, output_path=tmp_path / "o")
    )
    manager.jobs[0].status = QueueJobStatus.CONVERTING
    manager.save()

    restored = ConversionQueueManager(state_path=state, log_path=log)
    assert restored.load() == 1
    assert restored.jobs[0].subject == "sub-009"
    # In-progress jobs recover as QUEUED
    assert restored.jobs[0].status == QueueJobStatus.QUEUED
