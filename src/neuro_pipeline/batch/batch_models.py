"""Data models for batch conversion jobs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class BatchJobStatus(str, Enum):
    """Lifecycle status of one subject-level batch job."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class BatchJob:
    """One convertible dataset unit (typically one subject folder)."""

    job_id: str
    input_path: str
    output_path: str
    status: BatchJobStatus = BatchJobStatus.QUEUED
    created: str = field(default_factory=_utc_now)
    started: str | None = None
    finished: str | None = None
    series_count: int = 0
    converted_count: int = 0
    failed_count: int = 0
    error: str | None = None
    label: str = ""
    subject_id: str = ""  # BIDS subject label (required for BIDS batch)
    # Discovery routing label (may differ from raw DICOM PatientID).
    patient_id_filter: str = ""
    # Prefer series UID membership — robust across PatientID anonymization / remapping.
    series_uids: list[str] = field(default_factory=list)
    source_folder_path: str = ""
    original_patient_id: str = ""

    @classmethod
    def create(cls, input_path: Path | str, output_path: Path | str, *, label: str = "") -> BatchJob:
        inp = Path(input_path)
        return cls(
            job_id=uuid4().hex[:12],
            input_path=str(inp),
            output_path=str(output_path),
            label=label or inp.name,
            subject_id="",
            patient_id_filter="",
            series_uids=[],
            source_folder_path="",
            original_patient_id="",
        )

    @property
    def progress_fraction(self) -> float:
        if self.series_count <= 0:
            return 0.0
        done = self.converted_count + self.failed_count
        return min(1.0, done / self.series_count)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchJob:
        status = data.get("status", BatchJobStatus.QUEUED.value)
        if isinstance(status, BatchJobStatus):
            status_enum = status
        else:
            status_enum = BatchJobStatus(str(status))
        return cls(
            job_id=str(data["job_id"]),
            input_path=str(data["input_path"]),
            output_path=str(data["output_path"]),
            status=status_enum,
            created=str(data.get("created") or _utc_now()),
            started=data.get("started"),
            finished=data.get("finished"),
            series_count=int(data.get("series_count") or 0),
            converted_count=int(data.get("converted_count") or 0),
            failed_count=int(data.get("failed_count") or 0),
            error=data.get("error"),
            label=str(data.get("label") or Path(str(data["input_path"])).name),
            subject_id=str(data.get("subject_id") or ""),
            patient_id_filter=str(data.get("patient_id_filter") or ""),
            series_uids=[str(x) for x in data.get("series_uids") or []],
            source_folder_path=str(data.get("source_folder_path") or ""),
            original_patient_id=str(data.get("original_patient_id") or ""),
        )


@dataclass(slots=True)
class BatchState:
    """Persisted batch-session state for resume."""

    job_id: str
    status: BatchJobStatus
    completed_series: int = 0
    total_series: int = 0
    input_path: str = ""
    output_path: str = ""
    completed_series_uids: list[str] = field(default_factory=list)
    updated: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "completed_series": self.completed_series,
            "total_series": self.total_series,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "completed_series_uids": list(self.completed_series_uids),
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchState:
        status = data.get("status", BatchJobStatus.QUEUED.value)
        return cls(
            job_id=str(data.get("job_id") or ""),
            status=BatchJobStatus(str(status)),
            completed_series=int(data.get("completed_series") or 0),
            total_series=int(data.get("total_series") or 0),
            input_path=str(data.get("input_path") or ""),
            output_path=str(data.get("output_path") or ""),
            completed_series_uids=[str(x) for x in data.get("completed_series_uids") or []],
            updated=str(data.get("updated") or _utc_now()),
        )


@dataclass(slots=True)
class SeriesCheckpoint:
    """Per-series conversion checkpoint used to skip already-successful work."""

    source_hash: str
    output_hash: str
    status: str
    series_uid: str = ""
    output_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeriesCheckpoint:
        return cls(
            source_hash=str(data.get("source_hash") or ""),
            output_hash=str(data.get("output_hash") or ""),
            status=str(data.get("status") or ""),
            series_uid=str(data.get("series_uid") or ""),
            output_files=[str(x) for x in data.get("output_files") or []],
        )
