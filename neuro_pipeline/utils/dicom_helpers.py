"""DICOM discovery, validation, and anonymization helpers."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

import pydicom
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError

from neuro_pipeline.utils.errors import FatalPipelineError, PipelineWarning

LOGGER = logging.getLogger(__name__)

DICOM_EXTENSIONS: frozenset[str] = frozenset(
    {".dcm", ".dicom", ".ima", ".img", ""}
)

# Tags removed or replaced during de-identification (group, element).
PHI_TAGS: tuple[tuple[int, int], ...] = (
    (0x0010, 0x0010),  # PatientName
    (0x0010, 0x0020),  # PatientID
    (0x0010, 0x0030),  # PatientBirthDate
    (0x0010, 0x1000),  # OtherPatientIDs
    (0x0010, 0x1001),  # OtherPatientNames
    (0x0010, 0x2160),  # EthnicGroup
    (0x0010, 0x2180),  # Occupation
    (0x0010, 0x21B0),  # AdditionalPatientHistory
    (0x0008, 0x0080),  # InstitutionName
    (0x0008, 0x0081),  # InstitutionAddress
    (0x0008, 0x0090),  # ReferringPhysicianName
    (0x0008, 0x1048),  # Physician(s) of Record
    (0x0008, 0x1050),  # PerformingPhysicianName
    (0x0008, 0x1060),  # Name of Physician(s) Reading Study
    (0x0008, 0x1070),  # OperatorsName
    (0x0020, 0x0010),  # StudyID
    (0x0008, 0x0050),  # AccessionNumber
    (0x0032, 0x1032),  # RequestingPhysician
    (0x0032, 0x1060),  # RequestedProcedureDescription
    (0x0040, 0x0244),  # PerformedProcedureStepStartDate
    (0x0040, 0x0245),  # PerformedProcedureStepStartTime
    (0x0040, 0xA075),  # VerifyingObserverName
    (0x0040, 0xA123),  # PersonName
)

KEEP_TAGS: tuple[tuple[int, int], ...] = (
    (0x0010, 0x0040),  # PatientSex — retained for BIDS participants.tsv
    (0x0010, 0x1010),  # PatientAge — optional demographic
)


def is_dicom_candidate(path: Path) -> bool:
    """Return True if a file path looks like a DICOM file."""
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix not in DICOM_EXTENSIONS:
        return False
    try:
        return pydicom.misc.is_dicom(str(path))
    except (OSError, ValueError):
        return False


def iter_dicom_files(root: Path) -> list[Path]:
    """Recursively collect DICOM files under *root* in deterministic order."""
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if is_dicom_candidate(path):
            candidates.append(path)
    return candidates


def read_dicom_safe(path: Path, stop_before_pixels: bool = True) -> Dataset:
    """Read a DICOM dataset, raising fatal error on corruption."""
    try:
        return pydicom.dcmread(
            str(path),
            stop_before_pixels=stop_before_pixels,
            force=False,
        )
    except InvalidDicomError as exc:
        raise FatalPipelineError(f"Corrupted DICOM file: {path}") from exc
    except OSError as exc:
        raise FatalPipelineError(f"Cannot read DICOM file: {path}") from exc


def get_tag_value(ds: Dataset, tag: tuple[int, int], default: str = "") -> str:
    """Safely extract a string tag value from a dataset."""
    elem = ds.get(tag)
    if elem is None or elem.value is None:
        return default
    return str(elem.value).strip()


def extract_dicom_metadata(path: Path) -> dict[str, str]:
    """Extract key metadata fields from a single DICOM file."""
    ds = read_dicom_safe(path, stop_before_pixels=True)
    modality = get_tag_value(ds, (0x0008, 0x0060), default="UNKNOWN")
    return {
        "source_path": str(path),
        "patient_id": get_tag_value(ds, (0x0010, 0x0020)),
        "patient_name": get_tag_value(ds, (0x0010, 0x0010)),
        "patient_sex": get_tag_value(ds, (0x0010, 0x0040)),
        "study_instance_uid": get_tag_value(ds, (0x0020, 0x000D)),
        "series_instance_uid": get_tag_value(ds, (0x0020, 0x000E)),
        "study_date": get_tag_value(ds, (0x0008, 0x0020)),
        "study_time": get_tag_value(ds, (0x0008, 0x0030)),
        "series_time": get_tag_value(ds, (0x0008, 0x0031)),
        "series_description": get_tag_value(ds, (0x0008, 0x103E)),
        "modality": modality,
        "protocol_name": get_tag_value(ds, (0x0018, 0x1030)),
        "series_number": get_tag_value(ds, (0x0020, 0x0011)),
        "instance_number": get_tag_value(ds, (0x0020, 0x0013)),
    }


def normalize_dicom_time(value: str) -> str:
    """Normalize a DICOM time string to a six-digit HHMMSS key."""
    if not value:
        return ""
    digits = "".join(character for character in value if character.isdigit())
    if not digits:
        return ""
    return digits[:6].ljust(6, "0")


def try_extract_dicom_metadata(path: Path) -> tuple[dict[str, str] | None, str | None]:
    """Extract metadata from *path*, returning an error message on failure."""
    try:
        return extract_dicom_metadata(path), None
    except InvalidDicomError as exc:
        return None, f"Corrupted DICOM file: {path} ({exc})"
    except OSError as exc:
        return None, f"Cannot read DICOM file: {path} ({exc})"
    except FatalPipelineError as exc:
        return None, exc.message


def anonymize_dataset(
    ds: Dataset,
    pseudonym_id: str,
    *,
    remove_private_tags: bool = True,
) -> Dataset:
    """Return a copy of *ds* with PHI tags cleared or replaced."""
    anon = ds.copy()
    if remove_private_tags:
        anon.remove_private_tags()

    anon.PatientID = pseudonym_id
    anon.PatientName = pseudonym_id
    if hasattr(anon, "PatientBirthDate"):
        anon.PatientBirthDate = ""
    if hasattr(anon, "OtherPatientIDs"):
        anon.OtherPatientIDs = ""

    for tag in PHI_TAGS:
        if tag in ((0x0010, 0x0020), (0x0010, 0x0010)):
            continue
        if tag in anon:
            anon[tag].value = ""

    anon.PatientIdentityRemoved = "YES"
    anon.DeidentificationMethod = "NeuroBIDS pipeline tag removal"
    return anon


def validate_anonymized_dataset(ds: Dataset, pseudonym_id: str) -> None:
    """Verify that a dataset meets de-identification requirements."""
    patient_name = get_tag_value(ds, (0x0010, 0x0010))
    if patient_name != pseudonym_id:
        raise FatalPipelineError(
            "Anonymization validation failed: PatientName "
            f"expected pseudonym {pseudonym_id!r}, got {patient_name!r}"
        )

    patient_id = get_tag_value(ds, (0x0010, 0x0020))
    if patient_id != pseudonym_id:
        raise FatalPipelineError(
            "Anonymization validation failed: PatientID "
            f"expected {pseudonym_id!r}, got {patient_id!r}"
        )

    for element in ds:
        group = element.tag.group
        if group % 2 == 1:
            raise FatalPipelineError(
                f"Anonymization validation failed: private DICOM tag remains ({element.tag})"
            )


def write_dicom_dataset(ds: Dataset, destination: Path) -> None:
    """Write a DICOM dataset atomically with strict error handling."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f"{destination.name}.tmp.{os.getpid()}")
    try:
        ds.save_as(str(temp_path), enforce_file_format=True)
        temp_path.replace(destination)
    except OSError as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise FatalPipelineError(
            f"Failed to write anonymized DICOM: {destination}"
        ) from exc


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute the SHA256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(text: str, length: int = 12) -> str:
    """Return a deterministic hex digest prefix for *text*."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest[:length]


def infer_bids_modality(modality: str, series_description: str) -> str:
    """Map DICOM modality/description to a BIDS modality folder label."""
    mod = modality.upper()
    desc = series_description.lower()
    if mod in {"MR", "MRI"}:
        if any(k in desc for k in ("fieldmap", "fmap", "sefm", "b0map", "field map")):
            return "fmap"
        if any(k in desc for k in ("epi", "phase", "magnitude")) and "fmap" in desc:
            return "fmap"
        if any(k in desc for k in ("bold", "fmri", "rest", "task")):
            return "func"
        if any(k in desc for k in ("dwi", "diff", "dti", "hardi")):
            return "dwi"
        if any(k in desc for k in ("flair", "t2", "t1", "mprage", "anat")):
            return "anat"
        return "anat"
    return "unknown"


def warn_missing_metadata(
    record: dict[str, str],
    required_fields: tuple[str, ...],
    context: str,
) -> list[str]:
    """Return warning messages for empty required metadata fields."""
    warnings: list[str] = []
    for field in required_fields:
        if not record.get(field):
            warnings.append(f"{context}: missing metadata field '{field}'")
    return warnings


def log_warnings(logger: logging.Logger, warnings: list[str]) -> None:
    """Log a list of pipeline warnings."""
    for message in warnings:
        logger.warning(message)
