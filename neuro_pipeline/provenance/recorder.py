"""Capture and persist execution provenance for a pipeline run."""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neuro_pipeline.config.constants import EXECUTION_PROVENANCE_FILENAME, PIPELINE_VERSION
from neuro_pipeline.utils.execution_context import ExecutionContext

LOGGER = logging.getLogger(__name__)

_RUN_STARTED_AT = datetime.now(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _duration_seconds(started_at: datetime, finished_at: datetime) -> float:
    return max(0.0, (finished_at - started_at).total_seconds())


def _detect_software_version(command: list[str]) -> str | None:
    """Return a version string when an external tool responds, else None."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0 or not output:
        return None
    return output.splitlines()[0].strip()


def _collect_software_versions() -> dict[str, str]:
    """Best-effort detection of tool versions available in the environment."""
    versions: dict[str, str] = {"python": sys.version.split()[0]}

    dcm2niix = shutil.which("dcm2niix")
    if dcm2niix:
        detected = _detect_software_version([dcm2niix, "--version"])
        if not detected:
            detected = _detect_software_version([dcm2niix, "-h"])
        if detected:
            versions["dcm2niix"] = detected

    bids_validator = shutil.which("bids-validator")
    if bids_validator:
        detected = _detect_software_version([bids_validator, "--version"])
        if detected:
            versions["bids-validator"] = detected

    return versions


def _build_provenance_payload(
    *,
    output_dir: Path,
    started_at: datetime,
    finished_at: datetime,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Assemble the provenance document for one pipeline run."""
    context = ExecutionContext.capture(
        project_root=project_root or output_dir,
        software_versions=_collect_software_versions(),
    )
    duration = _duration_seconds(started_at, finished_at)

    payload: dict[str, Any] = {
        "pipeline_version": context.pipeline_version or PIPELINE_VERSION,
        "git_commit": context.git_commit,
        "git_dirty": context.git_dirty,
        "execution_id": context.execution_id,
        "execution_date": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "execution_duration_seconds": round(duration, 3),
        "python_version": context.python_version,
        "operating_system": context.platform or platform.platform(),
        "software_versions": dict(context.software_versions),
        "container_image": context.container_image,
        "container_digest": context.container_digest,
        "output_dir": str(output_dir.resolve()),
    }
    return payload


def save_provenance(output_dir: Path | str) -> Path:
    """Record execution provenance for the current pipeline run.

    Writes ``execution_provenance.json`` under *output_dir* with pipeline version,
    git commit (when available), execution timestamps, Python version, operating
    system, detected software versions, and elapsed duration since this module
    was loaded in the current process.

    Returns the absolute path to the written provenance file.
    """
    target_dir = Path(output_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    finished_at = _utc_now()
    payload = _build_provenance_payload(
        output_dir=target_dir,
        started_at=_RUN_STARTED_AT,
        finished_at=finished_at,
        project_root=target_dir,
    )

    output_path = target_dir / EXECUTION_PROVENANCE_FILENAME
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    LOGGER.info("Wrote execution provenance: %s", output_path)
    return output_path
