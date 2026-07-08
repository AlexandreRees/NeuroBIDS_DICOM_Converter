"""Extension-point definitions for downstream neuroimaging tools."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from neuro_pipeline.utils.execution_context import ExecutionContext
    from neuro_pipeline.utils.paths import ProjectPaths

from neuro_pipeline.config.constants import PIPELINE_VERSION

EXTENSION_HOOKS: dict[str, dict[str, str]] = {
    "mriqc": {
        "stage": "post_qc",
        "input_key": "raw_bids",
        "output_key": "derivatives/mriqc",
        "description": "MRIQC Image Quality Metric extraction per detected modality (feature extraction only).",
    },
    "fmriprep": {
        "stage": "post_conversion",
        "input_key": "raw_bids",
        "output_key": "derivatives/fmriprep",
        "description": "Preprocessing pipeline for task and resting-state fMRI.",
    },
    "qsiprep": {
        "stage": "post_conversion",
        "input_key": "raw_bids",
        "output_key": "derivatives/qsiprep",
        "description": "Preprocessing pipeline for diffusion MRI.",
    },
    "release_anonymization": {
        "stage": "public_release",
        "input_key": "raw_bids",
        "output_key": "anonymization_release/Public_Dataset",
        "description": "PS3.15 anonymization for external dataset sharing.",
    },
}


def build_manifest(
    project_root: Path,
    *,
    steps_completed: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    execution_context: ExecutionContext | None = None,
    project_paths: ProjectPaths | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a machine-readable manifest for extension tools."""
    root = project_root.resolve()
    derivatives = root / "derivatives" / "neuro_pipeline"
    manifest: dict[str, Any] = {
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paths": {
            "project_root": str(root),
            "raw_original": str(root / "raw_original"),
            "raw_bids": str(root / "raw_bids"),
            "metadata": str(root / "metadata"),
            "derivatives": str(derivatives),
            "anonymization_release": str(root / "anonymization_release"),
            "public_dataset": str(root / "anonymization_release" / "Public_Dataset"),
        },
        "artifacts": {
            "inventory": str(root / "metadata" / "inventory.csv"),
            "participant_mapping": str(root / "metadata" / "participant_mapping.csv"),
            "conversion_report": str(derivatives / "conversion" / "conversion_report.csv"),
            "conversion_logs": str(derivatives / "conversion" / "logs"),
            "validation_report": str(derivatives / "validation" / "bids_validation_report.json"),
            "validation_summary": str(derivatives / "validation" / "bids_validation_summary.csv"),
            "acquisition_validation": str(derivatives / "validation" / "acquisition_validation.csv"),
            "geometry_validation": str(derivatives / "validation" / "geometry_validation.csv"),
            "qc_summary": str(derivatives / "qc" / "qc_summary.csv"),
            "qc_detail": str(derivatives / "qc" / "qc_detail.csv"),
            "pipeline_qc_summary": str(derivatives / "qc" / "pipeline_qc_summary.html"),
            "mriqc_run_summary": str(root / "derivatives" / "mriqc" / "mriqc_run_summary.json"),
            "mriqc_reports": str(derivatives / "qc" / "mriqc_reports"),
            "derivatives_dataset_description": str(derivatives / "dataset_description.json"),
            "release_ready": str(root / "metadata" / "release_ready.json"),
        },
        "steps_completed": steps_completed or [],
        "extension_hooks": EXTENSION_HOOKS,
    }
    if execution_context is not None or project_paths is not None:
        from neuro_pipeline.derivatives.metadata import build_provenance_block

        paths = project_paths or __import__(
            "neuro_pipeline.utils.paths", fromlist=["ProjectPaths"]
        ).ProjectPaths(root=root)
        manifest["provenance"] = build_provenance_block(
            paths,
            context=execution_context,
            parameters=parameters,
        )
    if extra:
        manifest.update(extra)
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Persist manifest JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
