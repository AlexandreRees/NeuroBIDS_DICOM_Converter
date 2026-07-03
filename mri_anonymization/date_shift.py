"""Per-subject date shifting for DICOM and metadata."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from mri_anonymization.constants import METADATA_DATE_KEYS
from mri_anonymization.models import DateShift

LOGGER = logging.getLogger("mri_anonymization")

DICOM_DATE_PATTERN = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
ISO_DATE_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
DICOM_DATETIME_PATTERN = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")


def _seeded_shift_days(seed: str, subject: str, used: set[int]) -> int:
    """Generate a deterministic unique shift for one subject."""
    base = _seeded_int(seed, subject) % 7301 - 3650
    shift = base
    counter = 0
    while shift in used:
        counter += 1
        shift = (_seeded_int(seed, f"{subject}:{counter}") % 7301) - 3650
    used.add(shift)
    return shift


def _random_shift_days(used: set[int]) -> int:
    """Generate a cryptographically random unique shift in days."""
    while True:
        shift = secrets.randbelow(7301) - 3650
        if shift not in used:
            used.add(shift)
            return shift


def _seeded_int(seed: str, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def generate_date_shifts(
    subject_ids: list[str],
    seed: str | None,
) -> list[DateShift]:
    """Generate one unique date shift per anonymized subject."""
    used: set[int] = set()
    shifts: list[DateShift] = []
    for subject in sorted(subject_ids):
        if seed is None:
            shift_days = _random_shift_days(used)
        else:
            shift_days = _seeded_shift_days(seed, subject, used)
        shifts.append(DateShift(subject=subject, shift_days=shift_days))
    LOGGER.info("Generated date shifts for %d subjects", len(shifts))
    return shifts


def write_date_shift_csv(shifts: list[DateShift], output_csv: Path) -> None:
    """Persist date shifts to the private directory."""
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"subject": shift.subject, "shift_days": shift.shift_days} for shift in shifts]).to_csv(
        output_csv, index=False
    )
    LOGGER.info("Wrote date shifts: %s", output_csv)


def shift_dicom_date(value: str, shift_days: int) -> str:
    """Shift a DICOM date string (YYYYMMDD) by *shift_days*."""
    if not value or not DICOM_DATE_PATTERN.match(value.strip()):
        return value
    parsed = datetime.strptime(value.strip()[:8], "%Y%m%d")
    shifted = parsed + timedelta(days=shift_days)
    return shifted.strftime("%Y%m%d")


def shift_dicom_datetime(value: str, shift_days: int) -> str:
    """Shift a DICOM datetime string (YYYYMMDDHHMMSS...) by *shift_days*."""
    if not value:
        return value
    stripped = value.strip()
    match = DICOM_DATETIME_PATTERN.match(stripped)
    if not match:
        return shift_dicom_date(stripped, shift_days)
    parsed = datetime.strptime(stripped[:14], "%Y%m%d%H%M%S")
    shifted = parsed + timedelta(days=shift_days)
    fraction = stripped[14:]
    return shifted.strftime("%Y%m%d%H%M%S") + fraction


def shift_generic_date_string(value: str, shift_days: int) -> str:
    """Shift common metadata date string formats."""
    stripped = value.strip()
    if DICOM_DATE_PATTERN.match(stripped):
        return shift_dicom_date(stripped, shift_days)
    iso_match = ISO_DATE_PATTERN.match(stripped)
    if iso_match:
        parsed = datetime.strptime(stripped[:10], "%Y-%m-%d")
        return (parsed + timedelta(days=shift_days)).strftime("%Y-%m-%d")
    if DICOM_DATETIME_PATTERN.match(stripped):
        return shift_dicom_datetime(stripped, shift_days)
    return value


def shift_json_dates(payload: Any, shift_days: int) -> Any:
    """Recursively shift date-like fields in JSON-compatible structures."""
    if isinstance(payload, dict):
        shifted: dict[str, Any] = {}
        for key, value in payload.items():
            if key in METADATA_DATE_KEYS and isinstance(value, str):
                shifted[key] = shift_generic_date_string(value, shift_days)
            else:
                shifted[key] = shift_json_dates(value, shift_days)
        return shifted
    if isinstance(payload, list):
        return [shift_json_dates(item, shift_days) for item in payload]
    return payload


def shift_tabular_dates(dataframe: pd.DataFrame, shift_days: int) -> pd.DataFrame:
    """Shift date-like columns in a TSV/CSV table."""
    updated = dataframe.copy()
    for column in updated.columns:
        if column in METADATA_DATE_KEYS or column.lower().endswith("date"):
            updated[column] = updated[column].map(
                lambda value: shift_generic_date_string(str(value), shift_days)
                if str(value).strip()
                else value
            )
    return updated
