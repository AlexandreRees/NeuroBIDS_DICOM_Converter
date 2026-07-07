"""Per-artifact and per-step provenance tracking."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neuro_pipeline.utils.dicom_helpers import file_sha256
from neuro_pipeline.utils.execution_context import ExecutionContext


@dataclass
class ProvenanceRecord:
    """Provenance for one generated artifact."""

    step: str
    input_paths: list[str]
    output_path: str
    output_sha256: str
    execution: dict[str, Any]
    parameters: dict[str, Any] = field(default_factory=dict)
    completed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: str = "success"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepProvenanceLog:
    """Aggregated provenance for one pipeline stage."""

    step: str
    execution: dict[str, Any]
    records: list[dict[str, Any]] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    completed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def add_record(self, record: ProvenanceRecord) -> None:
        self.records.append(record.to_dict())

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "step": self.step,
            "execution": self.execution,
            "records": self.records,
            "validation": self.validation,
            "completed_at": self.completed_at,
            "record_count": len(self.records),
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def build_provenance_record(
    *,
    step: str,
    context: ExecutionContext,
    input_paths: list[Path | str],
    output_path: Path,
    parameters: dict[str, Any] | None = None,
    status: str = "success",
    message: str = "",
) -> ProvenanceRecord:
    """Build a provenance record, computing output checksum when the file exists."""
    checksum = file_sha256(output_path) if output_path.is_file() else ""
    return ProvenanceRecord(
        step=step,
        input_paths=[str(Path(path).resolve()) for path in input_paths],
        output_path=str(output_path.resolve()),
        output_sha256=checksum,
        execution=context.to_dict(),
        parameters=parameters or {},
        status=status,
        message=message,
    )


def start_step_provenance(step: str, context: ExecutionContext) -> StepProvenanceLog:
    """Initialize a step-level provenance log."""
    return StepProvenanceLog(step=step, execution=context.to_dict())
