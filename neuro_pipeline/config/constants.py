"""Global constants used across the neuro-bids-pipeline."""

from __future__ import annotations

# --- Versioning ---
PIPELINE_VERSION: str = "2.1.0"

# Target BIDS specification version (https://bids-specification.readthedocs.io/)
BIDS_SPEC_VERSION: str = "1.9.0"

# Pin bids-validator npm package version for reproducible validation in Docker.
BIDS_VALIDATOR_NPM_VERSION: str = "1.14.7"

# --- Cohort layout ---
COHORT_NAMES: tuple[str, ...] = ("Controls", "Data_ON", "Data_TON", "Glaucoma")

# --- File formats ---
NIFTI_SUFFIXES: tuple[str, ...] = (".nii.gz", ".nii")

# --- BIDS layout ---
BIDS_MODALITY_FOLDERS: frozenset[str] = frozenset(
    {"anat", "func", "dwi", "fmap", "extra"}
)
CORE_BIDS_MODALITIES: frozenset[str] = frozenset({"anat", "func", "dwi"})

DERIVATIVES_SUBDIRS: tuple[str, ...] = (
    "conversion",
    "validation",
    "qc",
)

DERIVATIVES_DATASET_NAME: str = "neuro-bids-pipeline derivatives"

# --- Inventory ---
REQUIRED_INVENTORY_METADATA: tuple[str, ...] = (
    "study_instance_uid",
    "series_instance_uid",
    "modality",
)

INVENTORY_WARNING_SEVERITIES: frozenset[str] = frozenset({"warning", "error"})

# --- Reporting / provenance filenames ---
EXECUTION_PROVENANCE_FILENAME: str = "execution_provenance.json"

# --- Validation report schemas ---
GEOMETRY_VALIDATION_CSV_COLUMNS: tuple[str, ...] = (
    "participant",
    "session",
    "series_uid",
    "datatype",
    "status",
    "warning",
    "details",
)

__all__ = [
    "BIDS_MODALITY_FOLDERS",
    "BIDS_SPEC_VERSION",
    "BIDS_VALIDATOR_NPM_VERSION",
    "COHORT_NAMES",
    "CORE_BIDS_MODALITIES",
    "DERIVATIVES_DATASET_NAME",
    "DERIVATIVES_SUBDIRS",
    "EXECUTION_PROVENANCE_FILENAME",
    "GEOMETRY_VALIDATION_CSV_COLUMNS",
    "INVENTORY_WARNING_SEVERITIES",
    "NIFTI_SUFFIXES",
    "PIPELINE_VERSION",
    "REQUIRED_INVENTORY_METADATA",
]
