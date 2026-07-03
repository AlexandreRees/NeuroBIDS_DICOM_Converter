"""Anonymization of BIDS JSON, TSV, CSV, and other metadata files."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pandas as pd

from mri_anonymization.date_shift import shift_json_dates, shift_tabular_dates
from mri_anonymization.subject_id import replace_subject_ids_in_text

LOGGER = logging.getLogger("mri_anonymization")


def is_json_sidecar(path: Path) -> bool:
    """Return True if path is a JSON metadata file."""
    return path.suffix.lower() == ".json"


def is_tabular_metadata(path: Path) -> bool:
    """Return True if path is a TSV/CSV metadata table."""
    lowered = path.suffix.lower()
    return lowered in {".tsv", ".csv"}


def is_nifti(path: Path) -> bool:
    """Return True if path is a NIfTI file."""
    name = path.name.lower()
    return name.endswith(".nii.gz") or name.endswith(".nii")


def process_json_file(
    source_path: Path,
    destination_path: Path,
    subject_map: dict[str, str],
    shift_days: int,
) -> None:
    """Anonymize a JSON sidecar or metadata file."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    text = source_path.read_text(encoding="utf-8")
    text = replace_subject_ids_in_text(text, subject_map)
    payload = json.loads(text)
    payload = shift_json_dates(payload, shift_days)
    destination_path.write_text(
        json.dumps(payload, indent=4, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def process_tabular_file(
    source_path: Path,
    destination_path: Path,
    subject_map: dict[str, str],
    shift_days: int,
) -> None:
    """Anonymize a TSV/CSV metadata table."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    separator = "\t" if source_path.suffix.lower() == ".tsv" else ","
    dataframe = pd.read_csv(source_path, sep=separator, dtype=str).fillna("")
    if "participant_id" in dataframe.columns:
        dataframe["participant_id"] = dataframe["participant_id"].map(
            lambda value: subject_map.get(str(value), value)
        )
    dataframe = shift_tabular_dates(dataframe, shift_days)
    dataframe.to_csv(destination_path, sep=separator, index=False)


def copy_binary_file(source_path: Path, destination_path: Path) -> None:
    """Copy a binary file unchanged (e.g., NIfTI before defacing)."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)


def process_text_file(
    source_path: Path,
    destination_path: Path,
    subject_map: dict[str, str],
) -> None:
    """Anonymize plain-text metadata files."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    text = replace_subject_ids_in_text(source_path.read_text(encoding="utf-8"), subject_map)
    destination_path.write_text(text, encoding="utf-8")
