"""OpenNeuro / Scientific Data publication readiness reporting."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neuro_pipeline.reports.generator import write_html_report, write_json_report
from neuro_pipeline.utils.paths import ProjectPaths


def build_openneuro_readiness_report(
    paths: ProjectPaths,
    *,
    release_ready: bool,
    blockers: list[dict[str, str]],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate OpenNeuro readiness status from release artifacts."""
    validation_report = paths.public_dataset / "validation_report.md"
    validation_pass = False
    if validation_report.is_file():
        validation_pass = "**Overall status:** PASS" in validation_report.read_text(encoding="utf-8")

    public_bids_valid = False
    public_validation_summary = (
        paths.anonymization_release / "validation" / "bids_validation_summary.csv"
    )
    if public_validation_summary.is_file():
        import pandas as pd

        summary = pd.read_csv(public_validation_summary, dtype=str).fillna("")
        public_bids_valid = int((summary["severity"] == "error").sum()) == 0

    checklist = [
        {
            "criterion": "Public_Dataset exists",
            "status": "pass" if paths.public_dataset.is_dir() else "fail",
        },
        {
            "criterion": "bids-validator PASS on Public_Dataset",
            "status": "pass" if public_bids_valid else "fail",
        },
        {
            "criterion": "Anonymization validation PASS",
            "status": "pass" if validation_pass else "fail",
        },
        {
            "criterion": "dataset_description.json present",
            "status": "pass"
            if (paths.public_dataset / "dataset_description.json").is_file()
            else "fail",
        },
        {
            "criterion": "participants.tsv present",
            "status": "pass"
            if (paths.public_dataset / "participants.tsv").is_file()
            else "fail",
        },
        {
            "criterion": "README present",
            "status": "pass" if (paths.public_dataset / "README").is_file() else "warn",
        },
        {
            "criterion": "CHANGES present",
            "status": "pass" if (paths.public_dataset / "CHANGES").is_file() else "warn",
        },
        {
            "criterion": "CITATION.cff present",
            "status": "pass"
            if (paths.public_dataset / "CITATION.cff").is_file()
            else "warn",
        },
        {
            "criterion": "LICENSE present",
            "status": "pass" if (paths.public_dataset / "LICENSE").is_file() else "warn",
        },
        {
            "criterion": "No release blockers",
            "status": "pass" if release_ready else "fail",
        },
    ]

    openneuro_ready = (
        release_ready
        and validation_pass
        and public_bids_valid
        and all(item["status"] != "fail" for item in checklist)
    )

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "openneuro_ready": openneuro_ready,
        "release_ready": release_ready,
        "public_dataset": str(paths.public_dataset.resolve()),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "checklist": checklist,
    }
    if extra:
        report.update(extra)
    return report


def write_openneuro_reports(
    paths: ProjectPaths,
    report: dict[str, Any],
) -> None:
    """Write JSON and HTML OpenNeuro readiness reports."""
    json_path = paths.metadata / "openneuro_readiness_report.json"
    html_path = paths.metadata / "openneuro_readiness_report.html"
    write_json_report(json_path, report)
    write_html_report(
        html_path,
        title="OpenNeuro Readiness Report",
        summary={
            "openneuro_ready": report.get("openneuro_ready"),
            "release_ready": report.get("release_ready"),
            "blocker_count": report.get("blocker_count"),
            "public_dataset": report.get("public_dataset"),
        },
        sections=[
            ("Submission Checklist", list(report.get("checklist", []))),
            ("Blockers", list(report.get("blockers", []))),
        ],
    )
