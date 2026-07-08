#!/usr/bin/env python3
"""Generate deterministic internal BIDS pseudonyms from inventory.

This step assigns private participant/session labels (e.g. sub-001, ses-01)
used throughout the research pipeline. It does **not** perform public-release
anonymization — that is handled separately by mri_anonymization.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.dicom_helpers import stable_hash
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.config.extensions import build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)

SUBJECT_KEY_COLUMNS: tuple[str, ...] = (
    "cohort",
    "source_subject_folder",
    "source_subject_path",
)

def load_inventory(inventory_csv: Path) -> pd.DataFrame:
    """Load and validate the inventory CSV."""
    if not inventory_csv.is_file():
        raise FatalPipelineError(
            f"Inventory file not found: {inventory_csv}. Run inventory.py first."
        )
    df = pd.read_csv(inventory_csv, dtype=str).fillna("")
    required = {
        "cohort",
        "source_subject_folder",
        "source_subject_path",
        "session_label",
        "patient_id_raw",
        "patient_sex",
        "study_instance_uid",
    }
    missing = required - set(df.columns)
    if missing:
        raise FatalPipelineError(
            f"Inventory missing required columns: {sorted(missing)}"
        )
    return df

def subject_key_tuple(row: pd.Series) -> tuple[str, str, str]:
    """Return the canonical subject identity tuple for a row."""
    return (
        row["cohort"],
        row["source_subject_folder"],
        row["source_subject_path"],
    )

def validate_intra_subject_patient_ids(inventory: pd.DataFrame) -> None:
    """Ensure patient_id_raw is consistent within each subject."""
    for subject_key, group in inventory.groupby(list(SUBJECT_KEY_COLUMNS), sort=False):
        patient_ids = sorted(
            {
                value.strip()
                for value in group["patient_id_raw"]
                if value.strip()
            }
        )
        if len(patient_ids) > 1:
            cohort, folder, path = subject_key
            raise FatalPipelineError(
                "Conflicting patient_id_raw values within subject "
                f"{cohort}/{folder} ({path}): {patient_ids}"
            )

def validate_cross_subject_patient_ids(inventory: pd.DataFrame) -> None:
    """Ensure the same patient_id_raw is not assigned to multiple subjects."""
    patient_id_to_subjects: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for _, row in inventory.iterrows():
        patient_id = row["patient_id_raw"].strip()
        if not patient_id:
            continue
        patient_id_to_subjects[patient_id].add(subject_key_tuple(row))

    conflicts = {
        patient_id: sorted(subjects)
        for patient_id, subjects in patient_id_to_subjects.items()
        if len(subjects) > 1
    }
    if conflicts:
        details = "; ".join(
            f"{patient_id} -> {subjects}"
            for patient_id, subjects in sorted(conflicts.items())
        )
        raise FatalPipelineError(
            f"Same patient_id_raw appears across multiple subjects: {details}"
        )

def check_patient_sex_consistency(inventory: pd.DataFrame) -> None:
    """Warn when a subject has multiple non-empty patient_sex values."""
    for subject_key, group in inventory.groupby(list(SUBJECT_KEY_COLUMNS), sort=False):
        sex_values = sorted(
            {value.strip() for value in group["patient_sex"] if value.strip()}
        )
        if len(sex_values) > 1:
            cohort, folder, path = subject_key
            LOGGER.warning(
                "Inconsistent patient_sex for subject %s/%s (%s): %s",
                cohort,
                folder,
                path,
                sex_values,
            )

def aggregate_study_instance_uids(inventory: pd.DataFrame) -> pd.DataFrame:
    """Collect sorted unique StudyInstanceUIDs per subject from inventory."""
    uid_rows: list[dict[str, str]] = []
    for subject_key, group in inventory.groupby(list(SUBJECT_KEY_COLUMNS), sort=False):
        cohort, folder, path = subject_key
        study_uids = "|".join(
            sorted(
                {
                    value.strip()
                    for value in group["study_instance_uid"]
                    if value.strip()
                }
            )
        )
        uid_rows.append(
            {
                "cohort": cohort,
                "source_subject_folder": folder,
                "source_subject_path": path,
                "study_instance_uids": study_uids,
            }
        )
    return pd.DataFrame(uid_rows)

def compute_source_hash(
    cohort: str,
    source_subject_path: str,
    source_subject_folder: str,
    study_instance_uids: str,
) -> str:
    """Compute a deterministic source hash including study UIDs when available."""
    return stable_hash(
        f"{cohort}|{source_subject_path}|{source_subject_folder}|{study_instance_uids}"
    )

def validate_source_hash_integrity(mapping: pd.DataFrame) -> None:
    """Detect source_hash collisions mapped to different participant IDs."""
    hash_to_participants: dict[str, set[str]] = defaultdict(set)
    for _, row in mapping.iterrows():
        hash_to_participants[row["source_hash"]].add(row["participant_id"])

    conflicts = {
        source_hash: sorted(participant_ids)
        for source_hash, participant_ids in hash_to_participants.items()
        if len(participant_ids) > 1
    }
    if conflicts:
        details = "; ".join(
            f"{source_hash} -> {participant_ids}"
            for source_hash, participant_ids in sorted(conflicts.items())
        )
        raise FatalPipelineError(
            f"Same source_hash mapped to different participant_id values: {details}"
        )

def build_participant_table(inventory: pd.DataFrame) -> pd.DataFrame:
    """Assign deterministic BIDS participant IDs to unique subjects."""
    validate_intra_subject_patient_ids(inventory)
    validate_cross_subject_patient_ids(inventory)
    check_patient_sex_consistency(inventory)

    subject_keys = (
        inventory[list(SUBJECT_KEY_COLUMNS)]
        .drop_duplicates()
        .sort_values(
            by=list(SUBJECT_KEY_COLUMNS),
            kind="mergesort",
        )
        .reset_index(drop=True)
    )

    participant_ids: list[str] = []
    for index, row in subject_keys.iterrows():
        participant_ids.append(f"sub-{index + 1:03d}")

    subject_keys = subject_keys.copy()
    subject_keys["participant_id"] = participant_ids

    sex_rows: list[dict[str, str]] = []
    for subject_key, group in inventory.groupby(list(SUBJECT_KEY_COLUMNS), sort=False):
        cohort, folder, path = subject_key
        sex_values = sorted(
            {value.strip() for value in group["patient_sex"] if value.strip()}
        )
        sex_rows.append(
            {
                "cohort": cohort,
                "source_subject_folder": folder,
                "source_subject_path": path,
                "patient_sex": sex_values[0] if sex_values else "",
            }
        )
    sex_map = pd.DataFrame(sex_rows)

    study_uid_map = aggregate_study_instance_uids(inventory)

    mapping = subject_keys.merge(
        sex_map,
        on=list(SUBJECT_KEY_COLUMNS),
        how="left",
    )
    mapping = mapping.merge(
        study_uid_map,
        on=list(SUBJECT_KEY_COLUMNS),
        how="left",
    )
    mapping["source_hash"] = mapping.apply(
        lambda row: compute_source_hash(
            row["cohort"],
            row["source_subject_path"],
            row["source_subject_folder"],
            row["study_instance_uids"],
        ),
        axis=1,
    )

    dup_ids = mapping["participant_id"].duplicated()
    if dup_ids.any():
        raise FatalPipelineError("Duplicate participant IDs generated")

    dup_hash = mapping["source_hash"].duplicated()
    if dup_hash.any():
        raise FatalPipelineError("Duplicate source hash detected in mapping")

    validate_source_hash_integrity(mapping)

    return mapping

def build_session_mapping(
    inventory: pd.DataFrame,
    participants: pd.DataFrame,
) -> pd.DataFrame:
    """Merge inventory with participant IDs at the session level."""
    merge_keys = list(SUBJECT_KEY_COLUMNS)
    participant_columns = merge_keys + ["participant_id", "source_hash"]
    merged = inventory.merge(
        participants[participant_columns],
        on=merge_keys,
        how="left",
        validate="many_to_one",
    )

    if len(merged) != len(inventory):
        raise FatalPipelineError(
            "Session mapping row count differs from inventory; "
            f"expected {len(inventory)}, got {len(merged)}"
        )

    inventory_columns = list(inventory.columns)
    for column in inventory_columns:
        if not merged[column].equals(inventory[column].reset_index(drop=True)):
            raise FatalPipelineError(
                f"Session mapping altered inventory column '{column}'"
            )

    if merged["participant_id"].isna().any() or (merged["participant_id"] == "").any():
        raise FatalPipelineError(
            "Session mapping contains rows without a participant_id assignment"
        )

    merged = merged.sort_values(
        by=["participant_id", "session_label", "series_number", "series_instance_uid"],
        kind="mergesort",
    ).reset_index(drop=True)
    return merged

def write_participants_tsv(participants: pd.DataFrame, output_path: Path) -> None:
    """Write a BIDS-style participants.tsv to metadata (for review)."""
    tsv = participants[["participant_id", "cohort", "patient_sex"]].copy()
    tsv = tsv.rename(columns={"patient_sex": "sex"})
    tsv = tsv.drop_duplicates(subset=["participant_id"]).sort_values(
        "participant_id", kind="mergesort"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tsv.to_csv(output_path, sep="\t", index=False)
    LOGGER.info("Wrote participants preview: %s", output_path)

def run_mapping(paths: ProjectPaths) -> pd.DataFrame:
    """Generate participant mapping artifacts."""
    paths.ensure_metadata_dir()
    paths.validate_writable(paths.metadata)

    inventory = load_inventory(paths.inventory_csv)
    participants = build_participant_table(inventory)
    session_mapping = build_session_mapping(inventory, participants)

    participants_out = participants[
        [
            "participant_id",
            "cohort",
            "source_subject_folder",
            "source_subject_path",
            "source_hash",
            "patient_sex",
        ]
    ].copy()
    participants_out.to_csv(paths.participant_mapping_csv, index=False)
    LOGGER.info(
        "Wrote participant mapping: %s (%d subjects)",
        paths.participant_mapping_csv,
        len(participants_out),
    )

    session_out = paths.metadata / "session_mapping.csv"
    session_mapping.to_csv(session_out, index=False)
    LOGGER.info("Wrote session mapping: %s (%d rows)", session_out, len(session_mapping))

    preview_tsv = paths.metadata / "participants_preview.tsv"
    write_participants_tsv(participants, preview_tsv)

    cohort_counts = participants.groupby("cohort", sort=True).size()
    for cohort, count in cohort_counts.items():
        LOGGER.info("Cohort '%s': %d subjects mapped", cohort, count)

    manifest = build_manifest(
        paths.root,
        steps_completed=["inventory", "generate_mapping"],
        extra={
            "n_participants": len(participants_out),
            "cohort_counts": cohort_counts.to_dict(),
        },
    )
    write_manifest(paths.pipeline_manifest_json, manifest)

    return participants_out

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Generate deterministic BIDS participant IDs."
    )
    return parser.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    """Entry point for participant mapping."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    log_file = paths.metadata / "generate_mapping.log"
    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=log_file,
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting participant mapping for %s", paths.root)
    try:
        run_mapping(paths)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("Participant mapping completed successfully")
    return 0

if __name__ == "__main__":
    sys.exit(main())
