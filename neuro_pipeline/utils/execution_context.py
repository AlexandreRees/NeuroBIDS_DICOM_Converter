"""Execution environment and reproducibility context for pipeline runs."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neuro_pipeline.config.constants import PIPELINE_VERSION


@dataclass
class ExecutionContext:
    """Immutable snapshot of the environment for one pipeline run or step."""

    pipeline_version: str
    execution_id: str
    started_at: str
    python_version: str
    platform: str
    git_commit: str
    git_dirty: bool
    parameters: dict[str, Any] = field(default_factory=dict)
    software_versions: dict[str, str] = field(default_factory=dict)
    deterministic_seed: str | None = None

    container_image: str = ""
    container_digest: str = ""

    @classmethod
    def capture(
        cls,
        *,
        parameters: dict[str, Any] | None = None,
        software_versions: dict[str, str] | None = None,
        deterministic_seed: str | None = None,
        project_root: Path | None = None,
    ) -> ExecutionContext:
        """Capture current execution context."""
        commit, dirty = _resolve_git_state(project_root)
        started = datetime.now(timezone.utc)
        execution_id = hashlib.sha256(
            f"{started.isoformat()}|{commit}|{PIPELINE_VERSION}".encode()
        ).hexdigest()[:16]
        return cls(
            pipeline_version=PIPELINE_VERSION,
            execution_id=execution_id,
            started_at=started.isoformat(),
            python_version=sys.version.split()[0],
            platform=platform.platform(),
            git_commit=commit,
            git_dirty=dirty,
            parameters=parameters or {},
            software_versions=software_versions or {},
            deterministic_seed=deterministic_seed,
            container_image=_env("NEURO_PIPELINE_IMAGE"),
            container_digest=_env("NEURO_PIPELINE_IMAGE_DIGEST"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return asdict(self)

    def write_json(self, path: Path) -> None:
        """Persist context to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _resolve_git_state(project_root: Path | None) -> tuple[str, bool]:
    """Return (commit_hash, is_dirty) or unknown values if git is unavailable."""
    cwd = project_root or Path.cwd()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
        )
        if commit.returncode != 0:
            return "unknown", False
        hash_value = commit.stdout.strip()
        is_dirty = bool(dirty.stdout.strip()) if dirty.returncode == 0 else False
        return hash_value, is_dirty
    except OSError:
        return "unknown", False
