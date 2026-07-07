"""Resumable pipeline execution via step checkpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class StepCheckpoint:
    """State for one completed pipeline step."""

    step: str
    status: str
    completed_at: str
    artifacts: list[str] = field(default_factory=list)
    execution_id: str = ""
    message: str = ""


@dataclass
class CheckpointStore:
    """Persistent checkpoint store for pipeline orchestration."""

    path: Path
    pipeline_mode: str
    steps: dict[str, StepCheckpoint] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, pipeline_mode: str) -> CheckpointStore:
        if not path.is_file():
            return cls(path=path, pipeline_mode=pipeline_mode)
        payload = json.loads(path.read_text(encoding="utf-8"))
        steps: dict[str, StepCheckpoint] = {}
        for name, data in payload.get("steps", {}).items():
            if isinstance(data, dict):
                steps[name] = StepCheckpoint(
                    step=name,
                    status=str(data.get("status", "unknown")),
                    completed_at=str(data.get("completed_at", "")),
                    artifacts=[str(item) for item in data.get("artifacts", [])],
                    execution_id=str(data.get("execution_id", "")),
                    message=str(data.get("message", "")),
                )
        return cls(path=path, pipeline_mode=pipeline_mode, steps=steps)

    def is_complete(self, step: str, required_artifacts: list[Path] | None = None) -> bool:
        """Return True if *step* completed and required artifacts exist."""
        checkpoint = self.steps.get(step)
        if checkpoint is None or checkpoint.status != "success":
            return False
        if required_artifacts:
            return all(path.is_file() or path.is_dir() for path in required_artifacts)
        return True

    def mark_complete(
        self,
        step: str,
        *,
        artifacts: list[Path] | None = None,
        execution_id: str = "",
        message: str = "",
    ) -> None:
        self.steps[step] = StepCheckpoint(
            step=step,
            status="success",
            completed_at=datetime.now(timezone.utc).isoformat(),
            artifacts=[str(path.resolve()) for path in artifacts or []],
            execution_id=execution_id,
            message=message,
        )
        self.save()

    def mark_failed(self, step: str, message: str) -> None:
        self.steps[step] = StepCheckpoint(
            step=step,
            status="failed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            message=message,
        )
        self.save()

    def save(self) -> None:
        payload: dict[str, Any] = {
            "pipeline_mode": self.pipeline_mode,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "steps": {
                name: {
                    "status": checkpoint.status,
                    "completed_at": checkpoint.completed_at,
                    "artifacts": checkpoint.artifacts,
                    "execution_id": checkpoint.execution_id,
                    "message": checkpoint.message,
                }
                for name, checkpoint in self.steps.items()
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
