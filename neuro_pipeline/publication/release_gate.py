#!/usr/bin/env python3
"""Final gate for public-release datasets (Public_Dataset/ only)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from neuro_pipeline.reporting.openneuro_report import build_openneuro_readiness_report, write_openneuro_reports
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.config.extensions import PIPELINE_VERSION, build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)


def _load_release_manifest(paths: ProjectPaths) -> dict[str, object]:
    manifest_path = paths.anonymization_release / "release_manifest.json"
    if not manifest_path.is_file():
        raise FatalPipelineError(
            f"Release manifest not found: {manifest_path}. Run release_dataset first."
        )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FatalPipelineError(f"Invalid release manifest: {manifest_path}")
    return payload


def _check_public_dataset_exists(paths: ProjectPaths, blockers: list[dict[str, str]]) -> None:
    if not paths.public_dataset.is_dir():
        blockers.append(
            {
                "category": "release",
                "severity": "error",
                "message": f"Public dataset missing: {paths.public_dataset}",
            }
        )


def _check_validation_report(paths: ProjectPaths, blockers: list[dict[str, str]]) -> None:
    report_path = paths.public_dataset / "validation_report.md"
    if not report_path.is_file():
        blockers.append(
            {
                "category": "validation",
                "severity": "error",
                "message": "Missing validation_report.md in Public_Dataset",
            }
        )
        return
    text = report_path.read_text(encoding="utf-8")
    if "**Overall status:** PASS" not in text:
        blockers.append(
            {
                "category": "validation",
                "severity": "error",
                "message": "Anonymization validation did not pass",
            }
        )


def _check_private_separation(paths: ProjectPaths, blockers: list[dict[str, str]]) -> None:
    forbidden_names = {"Private", "subject_mapping.csv", "date_shift.csv"}
    for path in paths.public_dataset.rglob("*"):
        if path.name in forbidden_names:
            blockers.append(
                {
                    "category": "separation",
                    "severity": "error",
                    "message": f"Private artifact found in public dataset: {path.name}",
                }
            )


def _check_no_research_mapping_leak(
    paths: ProjectPaths,
    blockers: list[dict[str, str]],
) -> None:
    """Ensure internal participant mapping tables are not copied into Public_Dataset."""
    if not paths.participant_mapping_csv.is_file():
        return
    mapping = pd.read_csv(paths.participant_mapping_csv, dtype=str).fillna("")
    if "participant_id" not in mapping.columns:
        return
    internal_ids = set(mapping["participant_id"].unique())
    for path in paths.public_dataset.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".nii", ".gz"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for internal_id in internal_ids:
            if internal_id and internal_id in text:
                blockers.append(
                    {
                        "category": "separation",
                        "severity": "error",
                        "message": (
                            f"Internal participant ID {internal_id!r} found in "
                            f"{path.relative_to(paths.public_dataset)}"
                        ),
                    }
                )
                break


def write_release_gate_artifacts(
    paths: ProjectPaths,
    blockers: list[dict[str, str]],
    *,
    passed: bool,
) -> None:
    """Write release gate decision artifacts."""
    paths.ensure_metadata_dir()
    report = {
        "release_ready": passed,
        "pipeline_version": PIPELINE_VERSION,
        "public_dataset": str(paths.public_dataset.resolve()),
        "blocker_count": len(blockers),
        "blockers": blockers,
    }
    paths.release_gate_report_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if blockers:
        pd.DataFrame(blockers).to_csv(paths.release_blockers_csv, index=False)
    elif paths.release_blockers_csv.is_file():
        paths.release_blockers_csv.unlink()

    paths.release_ready_json.write_text(
        json.dumps({"release_ready": passed}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_release_gate(paths: ProjectPaths) -> None:
    """Verify Public_Dataset is safe for external sharing."""
    paths.ensure_metadata_dir()
    blockers: list[dict[str, str]] = []

    _check_public_dataset_exists(paths, blockers)
    _check_validation_report(paths, blockers)
    _check_private_separation(paths, blockers)
    _check_no_research_mapping_leak(paths, blockers)

    passed = len(blockers) == 0
    write_release_gate_artifacts(paths, blockers, passed=passed)

    openneuro_report = build_openneuro_readiness_report(
        paths,
        release_ready=passed,
        blockers=blockers,
    )
    write_openneuro_reports(paths, openneuro_report)

    manifest = _load_release_manifest(paths)
    steps = list(manifest.get("steps_completed", []))
    if "release_gate" not in steps:
        steps.append("release_gate")
    updated = build_manifest(
        paths.root,
        steps_completed=steps,
        extra={
            "pipeline_mode": "release",
            "release_ready": passed,
            "release_blockers": len(blockers),
            "openneuro_ready": openneuro_report.get("openneuro_ready"),
        },
    )
    write_manifest(paths.anonymization_release / "release_manifest.json", updated)

    if not passed:
        sample = "; ".join(blocker["message"] for blocker in blockers[:5])
        raise FatalPipelineError(
            f"Release gate FAILED with {len(blockers)} blocker(s): {sample}"
        )

    if not openneuro_report.get("openneuro_ready"):
        raise FatalPipelineError(
            "OpenNeuro readiness check failed — see metadata/openneuro_readiness_report.html"
        )

    LOGGER.info("Release gate PASSED — Public_Dataset is ready for OpenNeuro submission")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    return build_base_parser(
        description="Verify Public_Dataset/ is ready for external release."
    ).parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the public-release gate."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.metadata / "release_gate.log",
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    try:
        run_release_gate(paths)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
