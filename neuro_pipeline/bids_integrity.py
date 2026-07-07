"""Advanced BIDS integrity checks beyond bids-validator."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from neuro_pipeline.utils.paths import ProjectPaths

SUBJECT_PATTERN = re.compile(r"^sub-[a-zA-Z0-9]+$")
SESSION_PATTERN = re.compile(r"^ses-[a-zA-Z0-9]+$")
RUN_PATTERN = re.compile(r"run-\d+")
TASK_PATTERN = re.compile(r"task-[a-zA-Z0-9]+")
NIFTI_SUFFIXES = (".nii.gz", ".nii")


@dataclass
class IntegrityFinding:
    """One integrity check finding."""

    severity: str
    category: str
    subject: str
    session: str
    message: str


@dataclass
class IntegrityReport:
    """Aggregated BIDS integrity report."""

    passed: bool = True
    findings: list[IntegrityFinding] = field(default_factory=list)

    def add(self, severity: str, category: str, message: str, subject: str = "", session: str = "") -> None:
        self.findings.append(
            IntegrityFinding(
                severity=severity,
                category=category,
                subject=subject,
                session=session,
                message=message,
            )
        )
        if severity == "error":
            self.passed = False

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "error_count": sum(1 for item in self.findings if item.severity == "error"),
            "warning_count": sum(1 for item in self.findings if item.severity == "warning"),
            "findings": [item.__dict__ for item in self.findings],
        }


def _is_nifti(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".nii.gz") or name.endswith(".nii")


def run_bids_integrity_checks(paths: ProjectPaths) -> IntegrityReport:
    """Run extended BIDS integrity checks on raw_bids/."""
    report = IntegrityReport()
    raw_bids = paths.raw_bids

    if not paths.participant_mapping_csv.is_file():
        report.add("error", "mapping", "Missing participant_mapping.csv")
        return report

    mapping = pd.read_csv(paths.participant_mapping_csv, dtype=str).fillna("")
    session_mapping = pd.read_csv(paths.session_mapping_csv, dtype=str).fillna("")

    expected_participants = set(mapping["participant_id"].unique())
    expected_sessions = {
        (row["participant_id"], row["session_label"])
        for _, row in session_mapping.iterrows()
    }

    observed_participants = {
        path.name
        for path in raw_bids.iterdir()
        if path.is_dir() and path.name.startswith("sub-")
    }

    for participant_id in sorted(expected_participants - observed_participants):
        report.add(
            "error",
            "completeness",
            f"Mapped participant missing in raw_bids: {participant_id}",
            subject=participant_id,
        )

    for participant_id in sorted(observed_participants - expected_participants):
        report.add(
            "error",
            "completeness",
            f"Unexpected participant directory: {participant_id}",
            subject=participant_id,
        )

    for participant_id, session_label in sorted(expected_sessions):
        session_dir = raw_bids / participant_id / session_label
        if not session_dir.is_dir():
            report.add(
                "error",
                "longitudinal",
                f"Missing expected session directory: {participant_id}/{session_label}",
                subject=participant_id,
                session=session_label,
            )

    modality_coverage: dict[str, set[str]] = defaultdict(set)
    duplicate_keys: dict[tuple[str, str, str], list[str]] = defaultdict(list)

    for subject_dir in sorted(raw_bids.iterdir()):
        if not subject_dir.is_dir() or not subject_dir.name.startswith("sub-"):
            continue
        if not SUBJECT_PATTERN.match(subject_dir.name):
            report.add(
                "warning",
                "naming",
                f"Non-standard subject folder name: {subject_dir.name}",
                subject=subject_dir.name,
            )

        for path in subject_dir.rglob("*"):
            if not path.is_file() or not _is_nifti(path):
                continue
            relative = path.relative_to(raw_bids)
            parts = relative.parts
            participant = parts[0]
            session = parts[1] if len(parts) > 1 and parts[1].startswith("ses-") else ""
            modality = parts[2] if session else parts[1]
            modality_coverage[participant].add(modality)

            stem = path.name.replace(".nii.gz", "").replace(".nii", "")
            duplicate_keys[(participant, session, stem)].append(str(relative))

            if not path.with_name(path.name.replace(".nii.gz", ".json").replace(".nii", ".json")).is_file():
                if path.name.endswith(".nii.gz"):
                    sidecar = path.with_name(path.name.replace(".nii.gz", ".json"))
                else:
                    sidecar = path.with_suffix(".json")
                if not sidecar.is_file():
                    report.add(
                        "warning",
                        "metadata",
                        f"Missing JSON sidecar for {relative}",
                        subject=participant,
                        session=session,
                    )

    for participant_id, modalities in sorted(modality_coverage.items()):
        if "anat" not in modalities:
            report.add(
                "warning",
                "modality_coverage",
                f"No anatomical (anat) data found for {participant_id}",
                subject=participant_id,
            )

    for key, files in duplicate_keys.items():
        if len(files) > 1:
            participant, session, stem = key
            report.add(
                "error",
                "duplicates",
                f"Duplicate acquisition filename stem '{stem}': {files}",
                subject=participant,
                session=session,
            )

    participants_tsv = paths.participants_tsv
    if participants_tsv.is_file():
        participants = pd.read_csv(participants_tsv, sep="\t", dtype=str).fillna("")
        bids_ids = set(participants.get("participant_id", pd.Series(dtype=str)))
        if not expected_participants.issubset(bids_ids):
            missing = sorted(expected_participants - bids_ids)
            report.add(
                "error",
                "metadata",
                f"participants.tsv missing mapped IDs: {missing}",
            )

    return report


def write_integrity_report(report: IntegrityReport, output_path: Path) -> None:
    """Write machine-readable integrity report JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
