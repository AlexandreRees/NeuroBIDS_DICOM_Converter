"""Default configuration for MRIQC feature extraction.

MRIQC is an external tool — these defaults configure how the pipeline invokes
the official MRIQC BIDS App CLI. No IQM names or algorithms are defined here.
"""

from __future__ import annotations

from typing import Any

# All paths are resolved at runtime via ProjectPaths unless overridden in
# metadata/mriqc_config.yaml (project-local, optional).
DEFAULT_MRIQC_CONFIG: dict[str, Any] = {
    "run_mriqc": True,
    "n_procs": 1,
    "memory_gb": 4,
    "container_runtime": "docker",
    "container_path": "nipreps/mriqc:latest",
    "temporary_directory": None,
    "output_directory": None,
}

# MRIQC CLI modality flags in stable processing order.
MRIQC_MODALITY_ORDER: tuple[str, ...] = ("T1w", "T2w", "bold", "dwi")

# BIDS discovery rules: modality flag -> (expected datatype folder, filename regex).
MRIQC_MODALITY_SPECS: dict[str, dict[str, str]] = {
    "T1w": {"datatype": "anat", "filename_pattern": r"_T1w(?:\.nii(?:\.gz)?)?$"},
    "T2w": {"datatype": "anat", "filename_pattern": r"_T2w(?:\.nii(?:\.gz)?)?$"},
    "bold": {"datatype": "func", "filename_pattern": r"_bold(?:\.nii(?:\.gz)?)?$"},
    "dwi": {"datatype": "dwi", "filename_pattern": r"_dwi(?:\.nii(?:\.gz)?)?$"},
}

# Backward-compatible alias (structural modalities only).
STRUCTURAL_SUFFIXES: tuple[str, ...] = ("T1w", "T2w")

MRIQC_SKIP_JSON_NAMES: frozenset[str] = frozenset(
    {
        "dataset_description.json",
        "mriqc_run_summary.json",
        "mriqc_execution.json",
    }
)

__all__ = [
    "DEFAULT_MRIQC_CONFIG",
    "MRIQC_MODALITY_ORDER",
    "MRIQC_MODALITY_SPECS",
    "MRIQC_SKIP_JSON_NAMES",
    "STRUCTURAL_SUFFIXES",
]
