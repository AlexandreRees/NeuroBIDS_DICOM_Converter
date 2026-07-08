#!/usr/bin/env python3
"""Validate the BIDS dataset using bids-validator."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

from neuro_pipeline.validation.bids_integrity import run_bids_integrity_checks, write_integrity_report
from neuro_pipeline.utils.raw_bids_guard import assert_raw_bids_immutable
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.execution_context import ExecutionContext
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.config.extensions import build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.workflows.steps import RESEARCH_STEP_NAMES
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

RESEARCH_STEPS_THROUGH_VALIDATION: list[str] = list(
    RESEARCH_STEP_NAMES[: RESEARCH_STEP_NAMES.index("validate_dataset") + 1]
)
RESEARCH_STEPS_THROUGH_QC: list[str] = list(
    RESEARCH_STEP_NAMES[: RESEARCH_STEP_NAMES.index("quality_control") + 1]
)

LOGGER = logging.getLogger(__name__)


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
        "bids-validator not found. Install via npm or pass --validator-path."
    )


def get_validator_version(command_prefix: list[str]) -> str:
    """Capture the bids-validator version string."""
    command = [*command_prefix, "--version"]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    version = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0 or not version:
        LOGGER.warning("Could not determine bids-validator version")
        return "unknown"
    LOGGER.info("bids-validator version: %s", version)
    return version


def validate_bids_preflight(paths: ProjectPaths) -> None:
    """Verify required BIDS files exist before running bids-validator."""
    if not paths.raw_bids.is_dir():
        raise FatalPipelineError(f"BIDS dataset not found: {paths.raw_bids}")

    if not paths.dataset_description_json.is_file():
        raise FatalPipelineError(
            f"Missing required BIDS file: {paths.dataset_description_json}"
        )

    if not paths.participants_tsv.is_file():
        raise FatalPipelineError(
            f"Missing required BIDS file: {paths.participants_tsv}"
        )

    subject_dirs = sorted(
        path
        for path in paths.raw_bids.iterdir()
        if path.is_dir() and path.name.startswith("sub-")
    )
    if not subject_dirs:
        raise FatalPipelineError(
            f"No sub-* directories found in BIDS dataset: {paths.raw_bids}"
        )


def run_validator(
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
    LOGGER.info("Running validator: %s", " ".join(command))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def normalize_severity(value: object) -> str:
    """Normalize validator severity values for consistent aggregation."""
    normalized = str(value).strip().lower()
    if normalized == "error":
        return "error"
    if normalized == "warning":
        return "warning"
    return "info"


def extract_issues_from_dict(payload: dict[str, object]) -> list[dict[str, object]] | None:
    """Extract issue lists from known nested validator JSON layouts."""
    issues = payload.get("issues")
    if isinstance(issues, list):
        return issues

    results = payload.get("results")
    if isinstance(results, list):
        return results
    if isinstance(results, dict):
        nested_issues = results.get("issues")
        if isinstance(nested_issues, list):
            return nested_issues

    summary = payload.get("summary")
    if isinstance(summary, dict):
        summary_issues = summary.get("issues")
        if isinstance(summary_issues, list):
            return summary_issues

    return None


def parse_validation_payload(payload: object) -> list[dict[str, object]]:
    """Parse validator JSON payload into a flat issue list."""
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            raise FatalPipelineError("Validation JSON payload is an empty string")
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise FatalPipelineError(
                f"Validation JSON string is not valid JSON: {exc}"
            ) from exc

    if payload is None:
        raise FatalPipelineError("Validation JSON payload is null")

    if isinstance(payload, list):
        if not payload:
            return []
        if not all(isinstance(item, dict) for item in payload):
            raise FatalPipelineError(
                "Validation JSON list contains non-object entries"
            )
        return payload

    if isinstance(payload, dict):
        if not payload:
            raise FatalPipelineError("Validation JSON object is empty")
        issues = extract_issues_from_dict(payload)
        if issues is not None:
            if not all(isinstance(item, dict) for item in issues):
                raise FatalPipelineError(
                    "Validation JSON issues contain non-object entries"
                )
            return issues
        raise FatalPipelineError(
            "Unrecognized validation JSON object structure; "
            "expected 'issues', 'results', or 'summary.issues'"
        )

    raise FatalPipelineError(
        f"Unrecognized validation JSON payload type: {type(payload).__name__}"
    )


def load_validation_json(report_json: Path) -> list[dict[str, object]]:
    """Load and parse validator JSON report."""
    if not report_json.is_file():
        raise FatalPipelineError(
            f"Validation report JSON not found after execution: {report_json}"
        )

    raw_text = report_json.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise FatalPipelineError(
            f"Validation report JSON is empty: {report_json}"
        )

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise FatalPipelineError(
            f"Validation report JSON is malformed: {report_json} ({exc})"
        ) from exc

    return parse_validation_payload(payload)


def flatten_validation_report(
    report: list[dict[str, object]],
    *,
    validator_returncode: int,
    dataset_valid: bool,
) -> pd.DataFrame:
    """Flatten validator JSON issues into a tabular summary."""
    rows: list[dict[str, str]] = []

    if not dataset_valid:
        rows.append(
            {
                "key": "validator_exit_code",
                "severity": "error",
                "file": "",
                "message": (
                    f"bids-validator exit code {validator_returncode}: "
                    "dataset marked invalid"
                ),
            }
        )

    for issue in report:
        rows.append(
            {
                "key": str(issue.get("key", "")),
                "severity": normalize_severity(issue.get("severity", "")),
                "file": str(issue.get("file", "")),
                "message": str(issue.get("reason", issue.get("message", ""))),
            }
        )

    if not rows and dataset_valid:
        rows.append(
            {
                "key": "",
                "severity": "pass",
                "file": "",
                "message": "No validation issues reported",
            }
        )

    return pd.DataFrame(rows).sort_values(
        by=["severity", "key", "file"],
        kind="mergesort",
    )


def run_validation(
    paths: ProjectPaths,
    validator_path: str | None,
    use_npx: bool,
    fail_on_error: bool,
    strict_acquisitions: bool = False,
    strict_geometry: bool = False,
) -> pd.DataFrame:
    """Validate BIDS dataset and write reports."""
    paths.ensure_metadata_dir()
    paths.ensure_derivatives_dir()
    paths.validate_writable(paths.metadata)
    paths.validate_writable(paths.derivatives / "validation")

    validate_bids_preflight(paths)
    assert_raw_bids_immutable(paths)

    command_prefix = resolve_bids_validator(validator_path, use_npx)
    validator_version = get_validator_version(command_prefix)
    result = run_validator(command_prefix, paths.raw_bids, paths.validation_report_json)

    if not paths.validation_report_json.is_file():
        raise FatalPipelineError(
            f"Validation report JSON not written: {paths.validation_report_json}"
        )

    if result.returncode not in {0, 1}:
        raise FatalPipelineError(
            f"bids-validator execution failed (code {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    dataset_valid = result.returncode == 0
    if not dataset_valid:
        LOGGER.error(
            "bids-validator exit code 1: dataset is invalid; parsing report anyway"
        )

    issues = load_validation_json(paths.validation_report_json)
    summary = flatten_validation_report(
        issues,
        validator_returncode=result.returncode,
        dataset_valid=dataset_valid,
    )
    summary.to_csv(paths.validation_summary_csv, index=False)
    LOGGER.info("Wrote validation summary: %s", paths.validation_summary_csv)

    error_count = int((summary["severity"] == "error").sum())
    warning_count = int((summary["severity"] == "warning").sum())
    info_count = int((summary["severity"] == "info").sum())
    LOGGER.info(
        "Validation complete: valid=%s, %d errors, %d warnings, %d info",
        dataset_valid,
        error_count,
        warning_count,
        info_count,
    )

    if fail_on_error and not dataset_valid:
        raise FatalPipelineError(
            "BIDS dataset is invalid (bids-validator exit code 1)"
        )

    if fail_on_error and error_count > 0:
        raise FatalPipelineError(
            f"BIDS validation reported {error_count} error(s)"
        )

    integrity = run_bids_integrity_checks(paths)
    integrity_path = paths.derivatives / "validation" / "bids_integrity_report.json"
    write_integrity_report(integrity, integrity_path)
    integrity_errors = sum(1 for item in integrity.findings if item.severity == "error")
    LOGGER.info(
        "BIDS integrity: passed=%s, %d errors, %d warnings",
        integrity.passed,
        integrity_errors,
        sum(1 for item in integrity.findings if item.severity == "warning"),
    )
    if fail_on_error and not integrity.passed:
        sample = "; ".join(item.message for item in integrity.findings[:5] if item.severity == "error")
        raise FatalPipelineError(f"BIDS integrity checks failed: {sample}")

    from neuro_pipeline.acquisition.consistency import run_acquisition_validation

    acquisition_report = run_acquisition_validation(
        paths,
        fail_on_error=strict_acquisitions,
    )
    acquisition_errors = sum(1 for row in acquisition_report.rows if row.status == "error")
    acquisition_missing = sum(1 for row in acquisition_report.rows if row.status == "missing")
    LOGGER.info(
        "Acquisition validation: passed=%s, errors=%d, missing=%d",
        acquisition_report.passed,
        acquisition_errors,
        acquisition_missing,
    )

    from neuro_pipeline.conversion.geometry_validation import run_geometry_validation
    from neuro_pipeline.derivatives.metadata import write_derivatives_dataset_description

    geometry_report = run_geometry_validation(
        paths,
        fail_on_error=strict_geometry,
    )
    write_derivatives_dataset_description(paths)

    context = ExecutionContext.capture(
        project_root=paths.root,
        parameters={
            "fail_on_error": fail_on_error,
            "use_npx": use_npx,
            "strict_acquisitions": strict_acquisitions,
            "strict_geometry": strict_geometry,
        },
        software_versions={"bids-validator": validator_version},
    )
    context.write_json(paths.metadata / "validate_dataset_context.json")

    manifest = build_manifest(
        paths.root,
        steps_completed=RESEARCH_STEPS_THROUGH_VALIDATION,
        execution_context=context,
        project_paths=paths,
        parameters=context.parameters,
        extra={
            "bids_validator_version": validator_version,
            "bids_validator_returncode": result.returncode,
            "validation_valid": dataset_valid,
            "validation_errors": error_count,
            "validation_warnings": warning_count,
            "validation_info": info_count,
            "bids_integrity_passed": integrity.passed,
            "bids_integrity_errors": integrity_errors,
            "acquisition_validation_passed": acquisition_report.passed,
            "acquisition_validation_errors": acquisition_errors,
            "acquisition_validation_missing": acquisition_missing,
            "geometry_validation_passed": geometry_report.passed,
            "geometry_validation_errors": geometry_report.error_count,
            "geometry_validation_warnings": geometry_report.warning_count,
        },
    )
    write_manifest(paths.pipeline_manifest_json, manifest)

    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Validate raw_bids/ using bids-validator."
    )
    parser.add_argument(
        "--validator-path",
        type=str,
        default=None,
        help="Path to bids-validator executable.",
    )
    parser.add_argument(
        "--use-npx",
        action="store_true",
        help="Run bids-validator via npx.",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit with fatal error when validator reports errors.",
    )
    parser.add_argument(
        "--strict-acquisitions",
        action="store_true",
        help="Fail when acquisition validation reports errors.",
    )
    parser.add_argument(
        "--strict-geometry",
        action="store_true",
        help="Fail when DICOM → NIfTI geometry validation reports errors.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for BIDS validation."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    log_file = paths.metadata / "validate_dataset.log"
    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=log_file,
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting BIDS validation for %s", paths.root)
    try:
        run_validation(
            paths,
            args.validator_path,
            args.use_npx,
            args.fail_on_error,
            strict_acquisitions=args.strict_acquisitions,
            strict_geometry=args.strict_geometry,
        )
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("BIDS validation completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
