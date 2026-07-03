"""Subject discovery and anonymized ID assignment."""

from __future__ import annotations

import hashlib
import logging
import secrets
from pathlib import Path

import pandas as pd

from mri_anonymization.models import SubjectMapping

LOGGER = logging.getLogger("mri_anonymization")


def discover_subjects(input_dir: Path) -> list[str]:
    """Discover BIDS subject directories under *input_dir*."""
    subjects = sorted(
        path.name
        for path in input_dir.iterdir()
        if path.is_dir() and path.name.startswith("sub-")
    )
    if not subjects:
        LOGGER.warning("No sub-* directories found in %s", input_dir)
    return subjects


def _seeded_int(seed: str, salt: str) -> int:
    """Derive a deterministic integer from seed and salt."""
    digest = hashlib.sha256(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def build_subject_mappings(
    original_subjects: list[str],
    seed: str | None,
) -> list[SubjectMapping]:
    """Assign anonymized subject IDs in deterministic sorted order."""
    mappings: list[SubjectMapping] = []
    for index, original_id in enumerate(sorted(original_subjects), start=1):
        anonymized_id = f"sub-{index:04d}"
        mappings.append(
            SubjectMapping(
                original_subject_id=original_id,
                anonymized_subject_id=anonymized_id,
            )
        )
    LOGGER.info("Assigned %d anonymized subject IDs", len(mappings))
    return mappings


def write_subject_mapping_csv(mappings: list[SubjectMapping], output_csv: Path) -> None:
    """Write secure subject mapping to the private directory."""
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    dataframe = pd.DataFrame(
        [
            {
                "original_subject_id": mapping.original_subject_id,
                "anonymized_subject_id": mapping.anonymized_subject_id,
            }
            for mapping in mappings
        ]
    )
    dataframe.to_csv(output_csv, index=False)
    LOGGER.info("Wrote subject mapping: %s", output_csv)


def remap_path_component(relative_path: Path, subject_map: dict[str, str]) -> Path:
    """Replace the subject folder in a relative BIDS path."""
    parts = list(relative_path.parts)
    if parts and parts[0] in subject_map:
        parts[0] = subject_map[parts[0]]
    return Path(*parts)


def replace_subject_ids_in_text(text: str, subject_map: dict[str, str]) -> str:
    """Replace original subject IDs embedded in text content."""
    updated = text
    for original_id, anonymized_id in sorted(subject_map.items(), key=lambda item: -len(item[0])):
        updated = updated.replace(original_id, anonymized_id)
    return updated
