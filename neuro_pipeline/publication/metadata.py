"""Publication-ready metadata generation for BIDS datasets."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from neuro_pipeline.config.constants import BIDS_SPEC_VERSION
from neuro_pipeline.config.extensions import PIPELINE_VERSION
from neuro_pipeline.utils.paths import ProjectPaths


def validate_dataset_description(dataset_description_path: Path) -> list[str]:
    """Return validation errors for dataset_description.json."""
    errors: list[str] = []
    if not dataset_description_path.is_file():
        return ["dataset_description.json missing"]
    payload = json.loads(dataset_description_path.read_text(encoding="utf-8"))
    required = ("Name", "BIDSVersion", "DatasetType")
    for key in required:
        if key not in payload or not str(payload[key]).strip():
            errors.append(f"dataset_description.json missing required field: {key}")
    if payload.get("DatasetType") not in {"raw", "derivative"}:
        errors.append("DatasetType should be 'raw' or 'derivative'")
    return errors


def write_research_readme(paths: ProjectPaths) -> None:
    """Write README for internal raw_bids dataset."""
    readme = paths.raw_bids / "README"
    readme.write_text(
        "\n".join(
            [
                "Neuro BIDS Pipeline — Internal Research Dataset",
                "",
                "This directory is the canonical internal BIDS raw dataset.",
                "Do not modify files manually after pipeline lock.",
                "",
                f"Pipeline version: {PIPELINE_VERSION}",
                f"Generated: {datetime.now(timezone.utc).isoformat()}",
                "",
                "Participant mapping tables remain in ../metadata/ (private).",
                "Public sharing requires the separate release pipeline (neuro-release).",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_changes_file(target_root: Path, *, version: str, notes: list[str]) -> None:
    """Write CHANGES file documenting dataset version."""
    lines = [f"# Version {version} — {datetime.now(timezone.utc).date().isoformat()}", ""]
    lines.extend(f"- {note}" for note in notes)
    (target_root / "CHANGES").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_citation_cff(target_root: Path, *, title: str, version: str) -> None:
    """Write a minimal CITATION.cff for the dataset."""
    content = "\n".join(
        [
            "cff-version: 1.2.0",
            f'title: "{title}"',
            "version: " + version,
            "license: CC0-1.0",
            "type: dataset",
            "authors:",
            "  - family-names: Neuro",
            "    given-names: BIDS Pipeline",
        ]
    )
    (target_root / "CITATION.cff").write_text(content + "\n", encoding="utf-8")


def write_default_license(target_root: Path, *, license_name: str = "CC0-1.0") -> None:
    """Write LICENSE file when absent."""
    license_path = target_root / "LICENSE"
    if license_path.exists():
        return
    if license_name.upper().startswith("CC0"):
        license_path.write_text(
            "Creative Commons CC0 1.0 Universal Public Domain Dedication\n",
            encoding="utf-8",
        )


def enrich_dataset_description(
    paths: ProjectPaths,
    *,
    dataset_version: str,
    extra_generated_by: dict[str, str] | None = None,
) -> None:
    """Update dataset_description.json with provenance and FAIR metadata."""
    path = paths.dataset_description_json
    payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    generated_by = list(payload.get("GeneratedBy", []))
    entry = {
        "Name": "neuro_pipeline",
        "Version": PIPELINE_VERSION,
        "Description": f"Research pipeline dataset version {dataset_version}",
    }
    if extra_generated_by:
        entry.update(extra_generated_by)
    generated_by.append(entry)
    payload.update(
        {
            "Name": payload.get("Name", "Neuro BIDS Pipeline Dataset"),
            "BIDSVersion": payload.get("BIDSVersion", BIDS_SPEC_VERSION),
            "DatasetType": "raw",
            "GeneratedBy": generated_by,
            "DatasetVersion": dataset_version,
            "HowToAcknowledge": "Cite the dataset DOI and pipeline version when publishing.",
        }
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
