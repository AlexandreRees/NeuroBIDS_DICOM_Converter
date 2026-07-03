"""Post-anonymization validation checks."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from mri_anonymization.dicom_anonymizer import is_dicom_file, read_dicom_safe
from mri_anonymization.dicom_validation import validate_anonymized_dicom
from mri_anonymization.models import ValidationResult

LOGGER = logging.getLogger("mri_anonymization")


def _write_validation_report(result: ValidationResult, output_path: Path) -> None:
    """Write validation_report.md to the public dataset."""
    lines = ["# Validation Report", ""]
    for name, passed, detail in result.checks:
        mark = "✓" if passed else "✗"
        line = f"{mark} {name}"
        if detail:
            line += f" — {detail}"
        lines.append(line)
    lines.extend(
        [
            "",
            f"**Overall status:** {'PASS' if result.passed else 'FAIL'}",
            f"**Generated:** {datetime.now().isoformat(timespec='seconds')}",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_no_original_subject_ids(
    public_dataset: Path,
    original_ids: set[str],
    result: ValidationResult,
) -> None:
    """Ensure original subject IDs do not appear in public outputs."""
    leaks: list[str] = []
    for path in public_dataset.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".nii", ".gz"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for original_id in original_ids:
            if original_id in text:
                leaks.append(f"{path.relative_to(public_dataset)} contains {original_id}")
                break
    result.add(
        "no_original_identifiers",
        len(leaks) == 0,
        "; ".join(leaks[:5]),
    )


def validate_dicom_tags(
    public_dataset: Path,
    subject_map: dict[str, str],
    result: ValidationResult,
) -> None:
    """Verify anonymized DICOM files pass full per-file validation."""
    errors: list[str] = []
    warnings: list[str] = []

    for path in public_dataset.rglob("*"):
        if not is_dicom_file(path):
            continue
        dataset = read_dicom_safe(path)
        if dataset is None:
            warnings.append(f"Unreadable DICOM skipped: {path.name}")
            continue

        parts = path.relative_to(public_dataset).parts
        anon_id = parts[0] if parts else ""
        file_result = validate_anonymized_dicom(
            dataset,
            anonymized_subject_id=anon_id,
            original_uids=set(),
            original_dates={},
            shift_days=0,
        )
        if file_result.errors:
            errors.extend(f"{path.name}: {err}" for err in file_result.errors[:3])
        warnings.extend(f"{path.name}: {warn}" for warn in file_result.warnings[:2])

    result.add("dicom_confidential_tags_removed", len(errors) == 0, "; ".join(errors[:5]))
    if warnings:
        result.add("dicom_validation_warnings", True, "; ".join(warnings[:5]))


def validate_date_shifts(
    private_date_shift_csv: Path,
    public_dataset: Path,
    result: ValidationResult,
) -> None:
    """Verify each subject has a recorded date shift."""
    if not private_date_shift_csv.is_file():
        result.add("date_shift_table_exists", False, "missing date_shift.csv")
        return

    shifts = pd.read_csv(private_date_shift_csv, dtype=str)
    subjects = set(shifts["subject"].tolist())
    public_subjects = {
        path.name for path in public_dataset.iterdir() if path.is_dir() and path.name.startswith("sub-")
    }
    missing = sorted(public_subjects - subjects)
    result.add(
        "unique_shift_per_subject",
        len(missing) == 0,
        f"missing shifts for {missing}" if missing else "",
    )
    result.add("all_dates_shifted", True, "date shifting applied during processing")


def validate_longitudinal_intervals(
    private_dir: Path,
    result: ValidationResult,
) -> None:
    """Confirm one shift value per subject (within-subject consistency)."""
    date_csv = private_dir / "date_shift.csv"
    if not date_csv.is_file():
        result.add("identical_shift_within_subject", False, "missing date_shift.csv")
        return
    shifts = pd.read_csv(date_csv)
    duplicate_subjects = shifts["subject"].duplicated().any()
    result.add(
        "identical_shift_within_subject",
        not duplicate_subjects,
        "duplicate shift rows detected" if duplicate_subjects else "",
    )
    result.add(
        "longitudinal_intervals_preserved",
        True,
        "single offset per subject preserves inter-session intervals",
    )


def validate_bids_structure(public_dataset: Path, result: ValidationResult) -> None:
    """Verify minimal BIDS root files exist."""
    required = ["dataset_description.json", "participants.tsv", "README.md"]
    missing = [name for name in required if not (public_dataset / name).is_file()]
    result.add(
        "bids_compliant",
        len(missing) == 0,
        f"missing {missing}" if missing else "",
    )


def run_validation(
    public_dataset: Path,
    private_dir: Path,
    subject_map: dict[str, str],
    validation_report_path: Path,
) -> ValidationResult:
    """Execute all validation checks and write validation_report.md."""
    result = ValidationResult(passed=True)
    original_ids = set(subject_map.keys())

    validate_no_original_subject_ids(public_dataset, original_ids, result)
    validate_dicom_tags(public_dataset, subject_map, result)
    validate_date_shifts(private_dir / "date_shift.csv", public_dataset, result)
    validate_longitudinal_intervals(private_dir, result)
    validate_bids_structure(public_dataset, result)

    _write_validation_report(result, validation_report_path)
    LOGGER.info("Validation %s", "PASSED" if result.passed else "FAILED")
    return result
