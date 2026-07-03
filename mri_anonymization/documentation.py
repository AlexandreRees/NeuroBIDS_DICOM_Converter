"""Automatic generation of public anonymization documentation."""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime
from pathlib import Path

from mri_anonymization.constants import PIPELINE_VERSION
from mri_anonymization.models import PipelineStats, ValidationResult


def generate_anonymization_md(
    output_path: Path,
    stats: PipelineStats,
    *,
    enable_defacing: bool,
    deterministic: bool,
    validation: ValidationResult,
) -> None:
    """Generate ANONYMIZATION.md for the public dataset."""
    validation_lines = [
        f"{'✓' if passed else '✗'} {name}" + (f" — {detail}" if detail else "")
        for name, passed, detail in validation.checks
    ]
    limitations = stats.warnings[:20] if stats.warnings else ["None"]

    content = f"""# Dataset Anonymization Report

## Pipeline Information

- **Pipeline version:** {PIPELINE_VERSION}
- **Processing date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}
- **Python version:** {sys.version.split()[0]}
- **Operating system:** {platform.system()} {platform.release()}

## Dataset Summary

- **Subjects processed:** {stats.n_subjects}
- **Sessions processed:** {stats.n_sessions}
- **Total files:** {stats.n_files}
- **DICOM files:** {stats.n_dicom_files}
- **Metadata files:** {stats.n_metadata_files}
- **NIfTI files:** {stats.n_nifti_files}

## Anonymization Steps Performed

- Subject IDs replaced with anonymized identifiers (`sub-0001`, `sub-0002`, …)
- DICOM identifiers removed per DICOM PS3.15 Basic Application Level Confidentiality Profile
- Private DICOM tags removed
- Date shifting performed using per-subject random offsets
- Defacing: **{"enabled" if enable_defacing else "disabled"}**
- Reproducibility mode: **{"deterministic (--seed)" if deterministic else "random (cryptographic)"}**

## Date Shifting Policy

A unique random day offset was generated independently for each participant. The same offset was applied to all imaging sessions belonging to that participant, preserving longitudinal intervals while removing absolute calendar dates.

Offsets were applied to DICOM date tags and to dates in JSON sidecars, TSV, and CSV metadata files.

## Defacing

{"Facial defacing was applied to anatomical MRI volumes using pydeface (FSL deface fallback)." if enable_defacing else "Facial defacing was not applied to this dataset."}

- Successfully defaced: {stats.n_defaced}
- Skipped: {stats.n_defacing_skipped}
- Failed: {stats.n_defacing_failed}

## Validation Summary

{chr(10).join(validation_lines)}

## Known Limitations

{chr(10).join(f"- {item}" for item in limitations)}

## Data Release Notes

Subject mapping and date shift tables are stored separately and are **not** included in this public dataset.
"""
    output_path.write_text(content, encoding="utf-8")


def write_bids_root_files(
    public_dataset: Path,
    dataset_name: str,
    license_text: str,
) -> None:
    """Write standard BIDS root documentation files."""
    public_dataset.mkdir(parents=True, exist_ok=True)

    dataset_description = {
        "Name": dataset_name,
        "BIDSVersion": "1.8.0",
        "DatasetType": "raw",
        "License": license_text,
        "GeneratedBy": [
            {
                "Name": "mri_anonymization",
                "Version": PIPELINE_VERSION,
                "Description": "Public release anonymization pipeline",
            }
        ],
    }
    (public_dataset / "dataset_description.json").write_text(
        json.dumps(dataset_description, indent=2) + "\n",
        encoding="utf-8",
    )

    readme = public_dataset / "README.md"
    if not readme.is_file():
        readme.write_text(
            f"# {dataset_name}\n\nAnonymized neuroimaging dataset prepared for public release.\n",
            encoding="utf-8",
        )

    changes = public_dataset / "CHANGES"
    if not changes.is_file():
        changes.write_text(
            f"{datetime.now().strftime('%Y-%m-%d')}\n  - Initial anonymized public release\n",
            encoding="utf-8",
        )

    license_file = public_dataset / "LICENSE"
    if not license_file.is_file():
        license_file.write_text(
            f"{license_text}\n\nSee dataset repository for full license terms.\n",
            encoding="utf-8",
        )
