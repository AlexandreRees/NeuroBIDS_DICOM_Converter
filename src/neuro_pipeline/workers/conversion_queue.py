"""Advanced conversion queue manager (optional layer above BatchManager).

Does not modify ConversionManager / DicomParser / BIDSExporter / dcm2niix.
Jobs are executed by calling existing BatchManager / ConversionManager as consumers.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence

from neuro_pipeline.config.paths import (
    default_conversion_queue_log_path,
    default_conversion_queue_path,
)
from neuro_pipeline.models import ConversionOptions

LOGGER = logging.getLogger(__name__)


class QueueJobStatus(str, Enum):
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    CONVERTING = "CONVERTING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


@dataclass(slots=True)
class ConversionJob:
    """One queued subject/session conversion (queue layer — not models.ConversionJob)."""

    job_id: str
    subject: str
    session: str
    input_path: str
    output_path: str
    status: QueueJobStatus = QueueJobStatus.QUEUED
    progress: float = 0.0
    start_time: str = ""
    end_time: str = ""
    error_message: str = ""
    current_step: str = ""
    current_series: str = ""

    @classmethod
    def create(
        cls,
        *,
        subject: str,
        session: str,
        input_path: Path | str,
        output_path: Path | str,
        job_id: str | None = None,
    ) -> ConversionJob:
        return cls(
            job_id=job_id or uuid.uuid4().hex[:12],
            subject=(subject or "").strip(),
            session=(session or "").strip(),
            input_path=str(input_path),
            output_path=str(output_path),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "subject": self.subject,
            "session": self.session,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "status": self.status.value,
            "progress": self.progress,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "error": self.error_message,
            "error_message": self.error_message,
            "current_step": self.current_step,
            "current_series": self.current_series,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversionJob:
        status_raw = str(data.get("status") or QueueJobStatus.QUEUED.value)
        try:
            status = QueueJobStatus(status_raw)
        except ValueError:
            status = QueueJobStatus.QUEUED
        # Recover unfinished work as QUEUED / FAILED as appropriate
        if status in {
            QueueJobStatus.ANALYZING,
            QueueJobStatus.CONVERTING,
            QueueJobStatus.VALIDATING,
            QueueJobStatus.PAUSED,
        }:
            status = QueueJobStatus.QUEUED
        return cls(
            job_id=str(data.get("job_id") or uuid.uuid4().hex[:12]),
            subject=str(data.get("subject") or ""),
            session=str(data.get("session") or ""),
            input_path=str(data.get("input_path") or ""),
            output_path=str(data.get("output_path") or ""),
            status=status,
            progress=float(data.get("progress") or 0.0),
            start_time=str(data.get("start_time") or ""),
            end_time=str(data.get("end_time") or ""),
            error_message=str(data.get("error_message") or data.get("error") or ""),
            current_step=str(data.get("current_step") or ""),
            current_series=str(data.get("current_series") or ""),
        )


ProgressHook = Callable[[ConversionJob], None]
LogHook = Callable[[str], None]


class ConversionQueueManager:
    """Sequential conversion queue with pause / resume / retry / persistence."""

    def __init__(
        self,
        *,
        state_path: Path | str | None = None,
        log_path: Path | str | None = None,
        options: ConversionOptions | None = None,
    ) -> None:
        self.state_path = Path(state_path) if state_path else default_conversion_queue_path()
        self.log_path = Path(log_path) if log_path else default_conversion_queue_log_path()
        self.options = options or ConversionOptions(output_layout="bids")
        self.jobs: list[ConversionJob] = []
        self._pause = threading.Event()
        self._pause.clear()  # not paused
        self._cancel_current = False
        self._running = False
        self._lock = threading.RLock()
        self._job_updated: ProgressHook | None = None
        self._setup_logger()

    def _setup_logger(self) -> None:
        self._qlog = logging.getLogger("neuro_pipeline.conversion_queue")
        self._qlog.setLevel(logging.INFO)
        self._qlog.propagate = False
        if not any(
            isinstance(h, logging.FileHandler)
            and Path(getattr(h, "baseFilename", "")) == self.log_path.resolve()
            for h in self._qlog.handlers
        ):
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(self.log_path, encoding="utf-8")
            handler.setFormatter(
                logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
            )
            self._qlog.addHandler(handler)

    def _log(self, job: ConversionJob | None, message: str) -> None:
        jid = job.job_id if job else "-"
        sub = job.subject if job else "-"
        self._qlog.info("job=%s subject=%s | %s", jid, sub, message)
        LOGGER.info("queue: %s", message)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_job(self, job: ConversionJob) -> ConversionJob:
        with self._lock:
            self.jobs.append(job)
            self._log(job, f"status → {job.status.value} (added)")
            self.save()
        return job

    def remove_job(self, job_id: str) -> bool:
        with self._lock:
            before = len(self.jobs)
            self.jobs = [j for j in self.jobs if j.job_id != job_id]
            removed = len(self.jobs) < before
            if removed:
                self._log(None, f"removed job {job_id}")
                self.save()
            return removed

    def reorder(self, job_ids: Sequence[str]) -> None:
        with self._lock:
            by_id = {j.job_id: j for j in self.jobs}
            ordered = [by_id[i] for i in job_ids if i in by_id]
            remaining = [j for j in self.jobs if j.job_id not in set(job_ids)]
            self.jobs = ordered + remaining
            self.save()

    def get(self, job_id: str) -> ConversionJob | None:
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        return None

    def pause_queue(self) -> None:
        self._pause.set()
        self._log(None, "queue paused")
        with self._lock:
            for job in self.jobs:
                if job.status == QueueJobStatus.QUEUED:
                    job.status = QueueJobStatus.PAUSED
            self.save()

    def resume_queue(self) -> None:
        with self._lock:
            for job in self.jobs:
                if job.status == QueueJobStatus.PAUSED:
                    job.status = QueueJobStatus.QUEUED
            self.save()
        self._pause.clear()
        self._log(None, "queue resumed")

    def cancel_job(self, job_id: str) -> None:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return
            if job.status in {
                QueueJobStatus.QUEUED,
                QueueJobStatus.PAUSED,
                QueueJobStatus.FAILED,
            }:
                job.status = QueueJobStatus.CANCELLED
                job.end_time = _utc_now()
                self._log(job, "status → CANCELLED")
                self.save()
            elif job.status in {
                QueueJobStatus.ANALYZING,
                QueueJobStatus.CONVERTING,
                QueueJobStatus.VALIDATING,
            }:
                self._cancel_current = True
                self._log(job, "cancel requested for running job")

    def retry_failed(self) -> int:
        n = 0
        with self._lock:
            for job in self.jobs:
                if job.status == QueueJobStatus.FAILED:
                    job.status = QueueJobStatus.QUEUED
                    job.progress = 0.0
                    job.error_message = ""
                    job.start_time = ""
                    job.end_time = ""
                    job.current_step = ""
                    n += 1
                    self._log(job, "status → QUEUED (retry)")
            self.save()
        return n

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> Path:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "jobs": [j.to_dict() for j in self.jobs]}
        self.state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self.state_path

    def load(self) -> int:
        if not self.state_path.is_file():
            return 0
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to load conversion queue: %s", exc)
            return 0
        raw = data.get("jobs") if isinstance(data, dict) else None
        jobs: list[ConversionJob] = []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    jobs.append(ConversionJob.from_dict(entry))
        self.jobs = jobs
        unfinished = sum(
            1
            for j in self.jobs
            if j.status in {QueueJobStatus.QUEUED, QueueJobStatus.PAUSED, QueueJobStatus.FAILED}
        )
        self._log(None, f"recovered {len(self.jobs)} jobs ({unfinished} unfinished)")
        return len(self.jobs)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def run(
        self,
        *,
        job_updated: ProgressHook | None = None,
        stop_check: Callable[[], bool] | None = None,
        conversion_plan_factory: Callable[[ConversionJob], Any] | None = None,
    ) -> list[ConversionJob]:
        """Process QUEUED jobs sequentially via existing BatchManager."""
        if self._running:
            raise RuntimeError("Queue is already running")
        self._running = True
        self._cancel_current = False
        self._job_updated = job_updated
        self.resume_queue()
        try:
            while True:
                if stop_check and stop_check():
                    break
                if self._pause.is_set():
                    # Do not start new work while paused; exit when nothing remains queued.
                    if self._next_queued() is None:
                        break
                    time.sleep(0.2)
                    continue
                job = self._next_queued()
                if job is None:
                    break
                self._run_one(job, conversion_plan_factory=conversion_plan_factory)
            return list(self.jobs)
        finally:
            self._running = False
            self.save()

    def _next_queued(self) -> ConversionJob | None:
        with self._lock:
            for job in self.jobs:
                if job.status == QueueJobStatus.QUEUED:
                    return job
        return None

    def _emit(self, job: ConversionJob) -> None:
        if self._job_updated:
            self._job_updated(job)
        self.save()

    def _run_one(
        self,
        job: ConversionJob,
        *,
        conversion_plan_factory: Callable[[ConversionJob], Any] | None = None,
    ) -> None:
        from neuro_pipeline.batch import BatchManager
        from neuro_pipeline.converter import ConversionManager

        job.status = QueueJobStatus.ANALYZING
        job.progress = 5.0
        job.start_time = job.start_time or _utc_now()
        job.current_step = "Analyzing DICOM folder"
        job.error_message = ""
        self._log(job, "status → ANALYZING")
        self._emit(job)

        if self._pause.is_set() or self._cancel_current:
            self._finish_interrupted(job)
            return

        try:
            manager = BatchManager(
                conversion_manager=ConversionManager(
                    dcm2niix_path=self.options.dcm2niix_path,
                )
            )
            plan = None
            if conversion_plan_factory is not None:
                plan = conversion_plan_factory(job)

            job.status = QueueJobStatus.CONVERTING
            job.progress = 15.0
            job.current_step = "Converting"
            self._log(job, "status → CONVERTING")
            self._emit(job)

            def _progress(_batch_job, message: str) -> None:  # noqa: ANN001
                job.current_series = message
                job.current_step = message
                # Mild progress bump while converting
                job.progress = min(90.0, max(job.progress, 20.0) + 1.0)
                if "validat" in message.lower():
                    job.status = QueueJobStatus.VALIDATING
                    job.current_step = message
                self._emit(job)

            def _stop() -> bool:
                return self._pause.is_set() or self._cancel_current

            options = ConversionOptions(
                compress=self.options.compress,
                one_folder_per_patient=self.options.one_folder_per_patient,
                preserve_json=self.options.preserve_json,
                smart_naming=self.options.smart_naming,
                validate_output=self.options.validate_output,
                output_layout="bids",
                subject_id=job.subject.removeprefix("sub-"),
                session_id=job.session.removeprefix("ses-"),
                threads=self.options.threads,
                dcm2niix_path=self.options.dcm2niix_path,
            )

            batch_jobs = manager.convert_folder(
                job.input_path,
                job.output_path,
                options=options,
                subject_id=options.subject_id,
                session_id=options.session_id,
                conversion_plan=plan,
                progress=_progress,
                stop_check=_stop,
            )

            if self._cancel_current:
                job.status = QueueJobStatus.CANCELLED
                job.end_time = _utc_now()
                self._cancel_current = False
                self._log(job, "status → CANCELLED")
                self._emit(job)
                return

            if self._pause.is_set():
                job.status = QueueJobStatus.PAUSED
                self._log(job, "status → PAUSED")
                self._emit(job)
                return

            failed = [
                j
                for j in batch_jobs
                if getattr(getattr(j, "status", None), "value", "") == "FAILED"
            ]
            job.status = QueueJobStatus.VALIDATING
            job.progress = 95.0
            job.current_step = "Validating"
            self._emit(job)

            if failed:
                job.status = QueueJobStatus.FAILED
                job.error_message = "; ".join(
                    f"{j.label}: {j.error or 'failed'}" for j in failed[:5]
                )
                job.progress = 100.0
                job.end_time = _utc_now()
                self._log(job, f"status → FAILED ({job.error_message})")
            else:
                job.status = QueueJobStatus.COMPLETED
                job.progress = 100.0
                job.current_step = "Completed"
                job.end_time = _utc_now()
                self._log(job, "status → COMPLETED")
            self._emit(job)
        except Exception as exc:  # noqa: BLE001
            job.status = QueueJobStatus.FAILED
            job.error_message = str(exc)
            job.end_time = _utc_now()
            job.progress = 100.0
            self._log(job, f"status → FAILED ({exc})")
            self._emit(job)

    def _finish_interrupted(self, job: ConversionJob) -> None:
        if self._cancel_current:
            job.status = QueueJobStatus.CANCELLED
            self._cancel_current = False
            job.end_time = _utc_now()
            self._log(job, "status → CANCELLED")
        else:
            job.status = QueueJobStatus.PAUSED
            self._log(job, "status → PAUSED")
        self._emit(job)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
