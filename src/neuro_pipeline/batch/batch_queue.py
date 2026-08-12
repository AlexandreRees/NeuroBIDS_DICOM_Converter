"""In-memory batch job queue."""

from __future__ import annotations

from collections import deque
from typing import Iterable

from neuro_pipeline.batch.batch_models import BatchJob, BatchJobStatus
from neuro_pipeline.batch.exceptions import BatchJobNotFoundError


class BatchQueue:
    """FIFO queue of :class:`BatchJob` items with id lookup."""

    def __init__(self) -> None:
        self._jobs: dict[str, BatchJob] = {}
        self._order: deque[str] = deque()

    def __len__(self) -> int:
        return len(self._order)

    def clear(self) -> None:
        self._jobs.clear()
        self._order.clear()

    def add(self, job: BatchJob) -> BatchJob:
        self._jobs[job.job_id] = job
        self._order.append(job.job_id)
        return job

    def extend(self, jobs: Iterable[BatchJob]) -> None:
        for job in jobs:
            self.add(job)

    def get(self, job_id: str) -> BatchJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise BatchJobNotFoundError(f"Unknown batch job: {job_id}") from exc

    def all_jobs(self) -> list[BatchJob]:
        return [self._jobs[jid] for jid in self._order if jid in self._jobs]

    def queued_jobs(self) -> list[BatchJob]:
        return [j for j in self.all_jobs() if j.status in {BatchJobStatus.QUEUED, BatchJobStatus.PAUSED}]

    def next_runnable(self) -> BatchJob | None:
        for job in self.all_jobs():
            if job.status in {BatchJobStatus.QUEUED, BatchJobStatus.PAUSED}:
                return job
        return None

    def replace_all(self, jobs: Iterable[BatchJob]) -> None:
        self.clear()
        self.extend(jobs)
