"""Extension-point definitions for downstream neuroimaging tools.

Future tools (MRIQC, fMRIPrep, QSIPrep) should read
``metadata/pipeline_manifest.json`` and operate on paths declared here
without modifying core pipeline scripts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "1.0.0"

EXTENSION_HOOKS: dict[str, dict[str, str]] = {
    "pydeface": {
        "stage": "defacing",
        "input_key": "raw_bids",
        "output_key": "derivatives/neuro_pipeline",
        "description": "Deface anatomical MRI volumes in the BIDS dataset.",
    },
    "mriqc": {
        "stage": "post_qc",
        "input_key": "raw_bids",
        "output_key": "derivatives/mriqc",
        "description": "Automated QC metrics for structural and functional MRI.",
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
}


def build_manifest(
    project_root: Path,
    *,
    steps_completed: list[str] | None = None,
    extra: dict[str, Any] | None = None,
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
            "staging": str(root / "staging"),
            "raw_bids": str(root / "raw_bids"),
            "metadata": str(root / "metadata"),
            "derivatives": str(derivatives),
        },
        "artifacts": {
            "inventory": str(root / "metadata" / "inventory.csv"),
            "participant_mapping": str(root / "metadata" / "participant_mapping.csv"),
            "deidentify_report": str(root / "metadata" / "deidentify_report.csv"),
            "conversion_report": str(derivatives / "conversion" / "conversion_report.csv"),
            "conversion_logs": str(derivatives / "conversion" / "logs"),
            "validation_report": str(derivatives / "validation" / "bids_validation_report.json"),
            "validation_summary": str(derivatives / "validation" / "bids_validation_summary.csv"),
            "qc_summary": str(derivatives / "qc" / "qc_summary.csv"),
            "qc_detail": str(derivatives / "qc" / "qc_detail.csv"),
            "defacing_report": str(derivatives / "defacing" / "defacing_report.json"),
            "publication_gate_report": str(root / "metadata" / "publication_gate_report.json"),
            "publication_ready": str(root / "metadata" / "publication_ready.json"),
        },
        "steps_completed": steps_completed or [],
        "extension_hooks": EXTENSION_HOOKS,
    }
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
