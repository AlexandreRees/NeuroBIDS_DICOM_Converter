"""Shared BIDS validation using the official bids-validator."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from neuro_pipeline.utils.errors import FatalPipelineError

LOGGER = logging.getLogger(__name__)


@dataclass
class BidsValidationResult:
    """Outcome of running bids-validator on one dataset."""

    dataset_path: Path
    report_json: Path
    summary_csv: Path
    validator_version: str
    dataset_valid: bool
    error_count: int
    warning_count: int
    info_count: int
    summary: pd.DataFrame


def resolve_bids_validator(
    validator_path: str | None,
    use_npx: bool,
) -> list[str]:
    """Resolve bids-validator command prefix."""
    if validator_path:
        resolved = Path(validator_path)
        if not resolved.is_file():
            raise FatalPipelineError(f"bids-validator not found at: {resolved}")
        return [str(resolved)]

    if use_npx:
        npx = shutil.which("npx")
        if not npx:
            raise FatalPipelineError("npx not found on PATH for bids-validator")
        return [npx, "--yes", "bids-validator"]

    direct = shutil.which("bids-validator")
    if direct:
        return [direct]

    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", "bids-validator"]

    raise FatalPipelineError(
        "bids-validator not found. Install via npm, use Docker, or pass --validator-path."
    )


def get_validator_version(command_prefix: list[str]) -> str:
    """Capture the bids-validator version string."""
    result = subprocess.run(
        [*command_prefix, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    version = (result.stdout or result.stderr or "").strip()
    return version if version else "unknown"


def run_validator_cli(
    command_prefix: list[str],
    dataset_path: Path,
    report_json: Path,
) -> subprocess.CompletedProcess[str]:
    """Execute bids-validator and capture JSON output."""
    report_json.parent.mkdir(parents=True, exist_ok=True)
    command = [
        *command_prefix,
        str(dataset_path),
        "--json",
        "--out",
        str(report_json),
        "--verbose",
    ]
    LOGGER.info("Running bids-validator: %s", " ".join(command))
    return subprocess.run(command, capture_output=True, text=True, check=False)


def normalize_severity(value: object) -> str:
    normalized = str(value).strip().lower()
    if normalized == "error":
        return "error"
    if normalized == "warning":
        return "warning"
    return "info"


def extract_issues_from_dict(payload: dict[str, object]) -> list[dict[str, object]] | None:
    issues = payload.get("issues")
    if isinstance(issues, list):
        return issues
    results = payload.get("results")
    if isinstance(results, list):
        return results
    if isinstance(results, dict):
        nested = results.get("issues")
        if isinstance(nested, list):
            return nested
    summary = payload.get("summary")
    if isinstance(summary, dict):
        nested = summary.get("issues")
        if isinstance(nested, list):
            return nested
    return None


def parse_validation_payload(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, str):
        payload = json.loads(payload.strip() or "[]")
    if payload is None:
        raise FatalPipelineError("Validation JSON payload is null")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        issues = extract_issues_from_dict(payload)
        if issues is not None:
            return [item for item in issues if isinstance(item, dict)]
    raise FatalPipelineError("Unsupported bids-validator JSON layout")


def load_validation_json(report_json: Path) -> list[dict[str, object]]:
    if not report_json.is_file():
        raise FatalPipelineError(f"Validation report not found: {report_json}")
    return parse_validation_payload(json.loads(report_json.read_text(encoding="utf-8")))


def flatten_validation_report(
    issues: list[dict[str, object]],
    *,
    validator_returncode: int,
    dataset_valid: bool,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for issue in issues:
        rows.append(
            {
                "key": str(issue.get("key", "")),
                "severity": normalize_severity(issue.get("severity", "info")),
                "file": str(issue.get("file", "")),
                "message": str(issue.get("reason", issue.get("message", ""))),
            }
        )
    if not rows:
        rows.append(
            {
                "key": "",
                "severity": "pass" if dataset_valid else "error",
                "file": "",
                "message": "No validation issues reported"
                if dataset_valid
                else f"bids-validator exit code {validator_returncode}",
            }
        )
    return pd.DataFrame(rows).sort_values(by=["severity", "key", "file"], kind="mergesort")


def validate_bids_dataset(
    dataset_path: Path,
    *,
    report_json: Path,
    summary_csv: Path,
    validator_path: str | None = None,
    use_npx: bool = False,
    fail_on_error: bool = True,
) -> BidsValidationResult:
    """Run official bids-validator on *dataset_path* and write reports."""
    if not dataset_path.is_dir():
        raise FatalPipelineError(f"BIDS dataset not found: {dataset_path}")

    command_prefix = resolve_bids_validator(validator_path, use_npx)
    validator_version = get_validator_version(command_prefix)
    LOGGER.info("bids-validator version: %s", validator_version)

    result = run_validator_cli(command_prefix, dataset_path, report_json)
    if result.returncode not in {0, 1}:
        raise FatalPipelineError(
            f"bids-validator execution failed (code {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    if not report_json.is_file():
        raise FatalPipelineError(f"Validation report JSON not written: {report_json}")

    dataset_valid = result.returncode == 0
    issues = load_validation_json(report_json)
    summary = flatten_validation_report(
        issues,
        validator_returncode=result.returncode,
        dataset_valid=dataset_valid,
    )
    summary_csv.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_csv, index=False)

    error_count = int((summary["severity"] == "error").sum())
    warning_count = int((summary["severity"] == "warning").sum())
    info_count = int((summary["severity"] == "info").sum())

    LOGGER.info(
        "BIDS validation: valid=%s, %d errors, %d warnings, %d info",
        dataset_valid,
        error_count,
        warning_count,
        info_count,
    )

    if fail_on_error and (not dataset_valid or error_count > 0):
        raise FatalPipelineError(
            f"BIDS validation failed with {error_count} error(s); see {summary_csv}"
        )

    return BidsValidationResult(
        dataset_path=dataset_path,
        report_json=report_json,
        summary_csv=summary_csv,
        validator_version=validator_version,
        dataset_valid=dataset_valid,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        summary=summary,
    )
