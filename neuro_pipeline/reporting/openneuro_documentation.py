"""Write public-release documentation for OpenNeuro submission."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from neuro_pipeline.config.constants import BIDS_SPEC_VERSION
from neuro_pipeline.publication.metadata import (
    validate_dataset_description,
    write_changes_file,
    write_citation_cff,
    write_default_license,
)
from neuro_pipeline.utils.execution_context import ExecutionContext
from neuro_pipeline.config.extensions import PIPELINE_VERSION


def write_openneuro_documentation(
    public_dataset: Path,
    *,
    dataset_name: str,
    dataset_version: str,
    license_name: str = "CC0-1.0",
    defacing_applied: bool,
    context: ExecutionContext | None = None,
) -> None:
    """Write BIDS root files expected by OpenNeuro reviewers."""
    public_dataset.mkdir(parents=True, exist_ok=True)

    generated_by = [
        {
            "Name": "neuro_pipeline",
            "Version": PIPELINE_VERSION,
            "Description": "OpenNeuro public-release pipeline",
        },
        {
            "Name": "mri_anonymization",
            "Version": PIPELINE_VERSION,
            "Description": "DICOM PS3.15 anonymization and metadata cleaning",
        },
    ]
    if context and context.software_versions.get("bids-validator"):
        generated_by.append(
            {
                "Name": "bids-validator",
                "Version": context.software_versions["bids-validator"],
            }
        )
    if context and context.software_versions.get("dcm2niix"):
        generated_by.append(
            {
                "Name": "dcm2niix",
                "Version": context.software_versions["dcm2niix"],
            }
        )

    dataset_description = {
        "Name": dataset_name,
        "BIDSVersion": BIDS_SPEC_VERSION,
        "DatasetType": "raw",
        "License": license_name,
        "Authors": ["See CITATION.cff"],
        "HowToAcknowledge": "Cite the dataset DOI and acknowledge the OpenNeuro repository.",
        "DatasetVersion": dataset_version,
        "GeneratedBy": generated_by,
        "EthicsApprovals": [],
        "ReferencesAndLinks": [],
    }
    (public_dataset / "dataset_description.json").write_text(
        json.dumps(dataset_description, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    readme = public_dataset / "README"
    readme.write_text(
        "\n".join(
            [
                f"# {dataset_name}",
                "",
                "Anonymized neuroimaging dataset prepared for OpenNeuro.",
                "",
                "## Processing summary",
                "",
                f"- BIDS specification: {BIDS_SPEC_VERSION}",
                f"- Pipeline version: {PIPELINE_VERSION}",
                f"- Facial defacing: {'applied' if defacing_applied else 'not applied'}",
                "",
                "See `ANONYMIZATION.md` and `PROVENANCE.json` for de-identification details.",
                "Subject mapping tables are **not** included in this public dataset.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    write_changes_file(
        public_dataset,
        version=dataset_version,
        notes=[
            "Initial OpenNeuro public release",
            f"BIDS {BIDS_SPEC_VERSION}, pipeline {PIPELINE_VERSION}",
            f"Defacing: {'yes' if defacing_applied else 'no'}",
        ],
    )
    write_citation_cff(public_dataset, title=dataset_name, version=dataset_version)
    write_default_license(public_dataset, license_name=license_name)

    errors = validate_dataset_description(public_dataset / "dataset_description.json")
    if errors:
        raise ValueError("dataset_description.json invalid: " + "; ".join(errors))


def write_provenance_json(
    output_path: Path,
    *,
    context: ExecutionContext,
    dataset_version: str,
    pipeline_mode: str,
    extra: dict[str, object] | None = None,
) -> None:
    """Write PROVENANCE.json for a public dataset (FAIR requirement)."""
    payload: dict[str, object] = {
        "pipeline_mode": pipeline_mode,
        "dataset_version": dataset_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution": context.to_dict(),
    }
    if extra:
        payload.update(extra)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
