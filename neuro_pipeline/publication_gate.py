#!/usr/bin/env python3
"""Strict BIDS publication gate — final release blocker."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.extensions import PIPELINE_VERSION, build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root
from neuro_pipeline.utils.raw_bids_purity import validate_raw_bids_purity

LOGGER = logging.getLogger(__name__)

REQUIRED_PIPELINE_STEPS: tuple[str, ...] = (
    "inventory",
    "generate_mapping",
    "deidentify_dicom",
    "convert_to_bids",
    "defacing",
    "derivatives_build",
    "validate_dataset",
    "quality_control",
)

ANAT_SUFFIX_MARKERS: tuple[str, ...] = ("_T1w", "_T2w")


def load_json(path: Path) -> dict[str, object]:
    """Load a JSON object from disk."""
    if not path.is_file():
        raise FatalPipelineError(f"Missing required JSON: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FatalPipelineError(f"Expected JSON object in {path}")
    return payload


def load_manifest(paths: ProjectPaths) -> dict[str, object]:
    """Load pipeline manifest."""
    return load_json(paths.pipeline_manifest_json)


def check_required_steps(manifest: dict[str, object], blockers: list[dict[str, str]]) -> None:
    """Verify all required pipeline steps completed."""
    completed = set(manifest.get("steps_completed", []))
    missing = sorted(set(REQUIRED_PIPELINE_STEPS) - completed)
    for step in missing:
        blockers.append(
            {
                "category": "pipeline",
                "severity": "error",
                "message": f"Missing pipeline step: {step}",
            }
        )


def check_validation_status(paths: ProjectPaths, blockers: list[dict[str, str]]) -> int:
    """Verify BIDS validator reported zero errors."""
    if not paths.validation_summary_csv.is_file():
        blockers.append(
            {
                "category": "validation",
                "severity": "error",
                "message": "Missing validation summary CSV",
            }
        )
        return 0

    summary = pd.read_csv(paths.validation_summary_csv, dtype=str).fillna("")
    error_count = int((summary["severity"].str.lower() == "error").sum())
    warning_count = int((summary["severity"].str.lower() == "warning").sum())

    if error_count > 0:
        blockers.append(
            {
                "category": "validation",
                "severity": "error",
                "message": f"BIDS validator errors: {error_count}",
            }
        )

    manifest = load_json(paths.pipeline_manifest_json) if paths.pipeline_manifest_json.is_file() else {}
    if manifest.get("validation_valid") is False:
        blockers.append(
            {
                "category": "validation",
                "severity": "error",
                "message": "Manifest reports validation_valid=false",
            }
        )

    return warning_count


def check_data_completeness(
    paths: ProjectPaths,
    blockers: list[dict[str, str]],
) -> None:
    """Verify participants, sessions, and directory consistency."""
    mapping = pd.read_csv(paths.participant_mapping_csv, dtype=str).fillna("")
    session_mapping = pd.read_csv(paths.session_mapping_csv, dtype=str).fillna("")

    mapped_participants = set(mapping["participant_id"].unique())
    bids_participants = {
        path.name
        for path in paths.raw_bids.iterdir()
        if path.is_dir() and path.name.startswith("sub-")
    }

    for participant_id in sorted(mapped_participants - bids_participants):
        blockers.append(
            {
                "category": "completeness",
                "severity": "error",
                "message": f"Mapped participant missing in raw_bids: {participant_id}",
            }
        )

    expected_sessions = {
        (row["participant_id"], row["session_label"])
        for _, row in session_mapping.iterrows()
    }
    for participant_id, session_label in sorted(expected_sessions):
        session_dir = paths.raw_bids / participant_id / session_label
        if not session_dir.is_dir():
            blockers.append(
                {
                    "category": "completeness",
                    "severity": "error",
                    "message": f"Missing session directory: {participant_id}/{session_label}",
                }
            )

    for participant_dir in sorted(paths.raw_bids.iterdir()):
        if not participant_dir.is_dir() or not participant_dir.name.startswith("sub-"):
            continue
        if participant_dir.name not in mapped_participants:
            blockers.append(
                {
                    "category": "completeness",
                    "severity": "error",
                    "message": f"Orphan subject directory in raw_bids: {participant_dir.name}",
                }
            )


def is_target_anatomical(path: Path) -> bool:
    """Return True if volume requires defacing completeness checks."""
    if "_defaced" in path.name:
        return False
    return any(marker in path.name for marker in ANAT_SUFFIX_MARKERS)


def check_defacing_completeness(
    paths: ProjectPaths,
    manifest: dict[str, object],
    blockers: list[dict[str, str]],
) -> None:
    """Verify every T1w/T2w has defaced output and session QC log."""
    if manifest.get("defacing_skipped"):
        blockers.append(
            {
                "category": "defacing",
                "severity": "error",
                "message": "Defacing was skipped; dataset not publication-ready",
            }
        )
        return

    for input_path in sorted(paths.raw_bids.rglob("*")):
        if not input_path.is_file() or not is_target_anatomical(input_path):
            continue

        if input_path.name.endswith(".nii.gz"):
            defaced_name = input_path.name.replace(".nii.gz", "_defaced.nii.gz")
        else:
            defaced_name = input_path.name.replace(".nii", "_defaced.nii")

        relative = input_path.relative_to(paths.raw_bids)
        defaced_path = paths.derivatives / relative.parent / defaced_name
        participant_id = relative.parts[0]
        session_label = relative.parts[1] if len(relative.parts) > 1 else ""
        session_log = paths.defacing_session_log(participant_id, session_label)

        if not defaced_path.is_file():
            blockers.append(
                {
                    "category": "defacing",
                    "severity": "error",
                    "message": f"Missing defaced output for {relative}",
                }
            )

        if session_label.startswith("ses-") and not session_log.is_file():
            blockers.append(
                {
                    "category": "defacing",
                    "severity": "error",
                    "message": f"Missing defacing QC log: {session_log.relative_to(paths.root)}",
                }
            )


def check_provenance(
    paths: ProjectPaths,
    manifest: dict[str, object],
    blockers: list[dict[str, str]],
) -> None:
    """Verify provenance fields for each participant."""
    mapping = pd.read_csv(paths.participant_mapping_csv, dtype=str).fillna("")

    if "source_hash" not in mapping.columns:
        blockers.append(
            {
                "category": "provenance",
                "severity": "error",
                "message": "participant_mapping missing source_hash column",
            }
        )
        return

    for _, row in mapping.iterrows():
        if not str(row.get("source_hash", "")).strip():
            blockers.append(
                {
                    "category": "provenance",
                    "severity": "error",
                    "message": f"Missing source_hash for {row['participant_id']}",
                }
            )

    if not manifest.get("pipeline_version"):
        blockers.append(
            {
                "category": "provenance",
                "severity": "error",
                "message": "pipeline_version missing from manifest",
            }
        )

    if not manifest.get("dcm2niix_version"):
        blockers.append(
            {
                "category": "provenance",
                "severity": "error",
                "message": "dcm2niix_version missing from manifest",
            }
        )


def check_raw_bids_purity(paths: ProjectPaths, blockers: list[dict[str, str]]) -> None:
    """Ensure raw_bids contains no pipeline artifacts."""
    for message in validate_raw_bids_purity(paths.raw_bids):
        blockers.append(
            {
                "category": "raw_bids_purity",
                "severity": "error",
                "message": message,
            }
        )


def write_gate_artifacts(
    paths: ProjectPaths,
    blockers: list[dict[str, str]],
    *,
    passed: bool,
    warning_count: int,
) -> None:
    """Write publication gate report artifacts."""
    paths.ensure_metadata_dir()

    report = {
        "publication_ready": passed,
        "pipeline_version": PIPELINE_VERSION,
        "validation_warnings": warning_count,
        "blocker_count": len(blockers),
        "blockers": blockers,
    }
    paths.publication_gate_report_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if blockers:
        pd.DataFrame(blockers).to_csv(paths.publication_blockers_csv, index=False)
    elif paths.publication_blockers_csv.is_file():
        paths.publication_blockers_csv.unlink()

    ready_payload = {"publication_ready": passed}
    paths.publication_ready_json.write_text(
        json.dumps(ready_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_publication_gate(paths: ProjectPaths) -> None:
    """Execute publication gate checks and write final decision."""
    paths.ensure_metadata_dir()

    blockers: list[dict[str, str]] = []
    manifest = load_manifest(paths)

    check_required_steps(manifest, blockers)
    warning_count = check_validation_status(paths, blockers)
    check_data_completeness(paths, blockers)
    check_defacing_completeness(paths, manifest, blockers)
    check_provenance(paths, manifest, blockers)
    check_raw_bids_purity(paths, blockers)

    passed = len(blockers) == 0
    write_gate_artifacts(paths, blockers, passed=passed, warning_count=warning_count)

    updated_manifest = build_manifest(
        paths.root,
        steps_completed=[*list(REQUIRED_PIPELINE_STEPS), "publication_gate"],
        extra={
            "publication_ready": passed,
            "publication_blockers": len(blockers),
            "validation_warnings": warning_count,
            "dcm2niix_version": manifest.get("dcm2niix_version", ""),
            "bids_validator_version": manifest.get("bids_validator_version", ""),
        },
    )
    write_manifest(paths.pipeline_manifest_json, updated_manifest)

    if not passed:
        sample = "; ".join(blocker["message"] for blocker in blockers[:5])
        raise FatalPipelineError(
            f"Publication gate FAILED with {len(blockers)} blocker(s): {sample}"
        )

    LOGGER.info("Publication gate PASSED")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Strict BIDS publication gate (final release blocker)."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for publication gate."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.metadata / "publication_gate.log",
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Running publication gate for %s", paths.root)
    try:
        run_publication_gate(paths)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
