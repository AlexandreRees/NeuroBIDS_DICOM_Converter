"""Validation helpers ensuring raw_bids contains only BIDS raw data."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.utils.errors import FatalPipelineError

ALLOWED_ROOT_JSON: frozenset[str] = frozenset(
    {
        "dataset_description.json",
        "genetic_info.json",
        "samples.json",
        "participants.json",
        "phenotype.json",
    }
)

PIPELINE_ARTIFACT_MARKERS: tuple[str, ...] = (
    "qc_",
    "validation_",
    "defacing_",
    "conversion_",
    "pipeline_",
    "publication_",
)


def is_nifti(path: Path) -> bool:
    """Return True if *path* is a NIfTI file."""
    name = path.name.lower()
    return name.endswith(".nii.gz") or name.endswith(".nii")


def is_allowed_raw_bids_json(json_path: Path, raw_bids: Path) -> bool:
    """Return True if a JSON file is permitted inside raw_bids."""
    relative = json_path.relative_to(raw_bids)
    lowered_name = json_path.name.lower()

    if any(marker in lowered_name for marker in PIPELINE_ARTIFACT_MARKERS):
        return False

    if len(relative.parts) == 1 and json_path.name in ALLOWED_ROOT_JSON:
        return True

    parent = json_path.parent
    stem = json_path.name[:-5]
    if (parent / f"{stem}.nii.gz").is_file() or (parent / f"{stem}.nii").is_file():
        return True

    return False


def validate_raw_bids_purity(raw_bids: Path) -> list[str]:
    """Return blocker messages for pipeline artifacts found in raw_bids."""
    blockers: list[str] = []

    if not raw_bids.is_dir():
        blockers.append(f"raw_bids directory missing: {raw_bids}")
        return blockers

    for path in sorted(raw_bids.rglob("*")):
        if not path.is_file():
            continue

        if path.suffix.lower() == ".csv":
            blockers.append(f"Forbidden CSV in raw_bids: {path.relative_to(raw_bids)}")
            continue

        if path.suffix.lower() == ".json" and not is_allowed_raw_bids_json(path, raw_bids):
            blockers.append(
                f"Forbidden JSON in raw_bids: {path.relative_to(raw_bids)}"
            )

    return blockers


def assert_raw_bids_purity(raw_bids: Path) -> None:
    """Raise if raw_bids contains non-BIDS pipeline artifacts."""
    blockers = validate_raw_bids_purity(raw_bids)
    if blockers:
        raise FatalPipelineError(
            "raw_bids purity check failed: " + "; ".join(blockers[:10])
        )
