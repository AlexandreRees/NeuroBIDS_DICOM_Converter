"""DICOM de-identification per PS3.15 Basic Application Level Confidentiality Profile."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError

from mri_anonymization.constants import (
    BURNED_IN_TAG,
    DATE_DICOM_TAGS,
    DATETIME_DICOM_TAGS,
    DEIDENTIFICATION_METHOD,
    DICOM_EXTENSIONS,
    OVERLAY_GROUP_END,
    OVERLAY_GROUP_START,
    PHI_DICOM_TAGS,
    PRESERVE_UID_TAGS,
    PSEUDONYM_DICOM_TAGS,
    UID_DICOM_TAGS,
)
from mri_anonymization.date_shift import shift_dicom_date, shift_dicom_datetime
from mri_anonymization.dicom_utils import (
    collect_date_values,
    collect_uid_values,
    get_tag_string,
    iter_all_elements,
)
from mri_anonymization.dicom_validation import (
    DicomValidationResult,
    validate_anonymized_dicom,
)
from mri_anonymization.uid_remapper import UidRemapper

LOGGER = logging.getLogger("mri_anonymization")


@dataclass
class DicomProcessResult:
    """Outcome of anonymizing a single DICOM file."""

    success: bool
    validation: DicomValidationResult
    message: str = ""


def is_dicom_file(path: Path) -> bool:
    """Return True if *path* appears to be a DICOM file."""
    if not path.is_file():
        return False
    if path.suffix.lower() not in DICOM_EXTENSIONS and path.suffix != "":
        return False
    try:
        return pydicom.misc.is_dicom(str(path))
    except (OSError, ValueError):
        return False


def detect_burned_in_warnings(dataset: Dataset) -> list[str]:
    """Detect potential burned-in PHI before anonymization."""
    warnings: list[str] = []
    burned_in = get_tag_string(dataset, BURNED_IN_TAG).upper()
    if burned_in == "YES":
        warnings.append("BurnedInAnnotation=YES before anonymization")
    if get_tag_string(dataset, (0x0020, 0x4000)):
        warnings.append("ImageComments present before anonymization")
    for element in dataset:
        if OVERLAY_GROUP_START <= element.tag.group <= OVERLAY_GROUP_END:
            warnings.append(f"Overlay group {element.tag.group:04X} present")
    if (0x0070, 0x0001) in dataset:
        warnings.append("GraphicAnnotationSequence present")
    return warnings


def _clear_phi_tags(anon: Dataset, pseudonym_id: str, preserve_patient_sex: bool) -> None:
    """Clear or pseudonymize PHI tags in the main dataset."""
    anon.PatientID = pseudonym_id
    anon.PatientName = pseudonym_id

    if hasattr(anon, "PatientBirthDate"):
        anon.PatientBirthDate = ""
    if hasattr(anon, "OtherPatientIDs"):
        anon.OtherPatientIDs = ""
    if not preserve_patient_sex and hasattr(anon, "PatientSex"):
        anon.PatientSex = ""

    for tag in PHI_DICOM_TAGS:
        if tag in PSEUDONYM_DICOM_TAGS:
            continue
        if tag in anon:
            anon[tag].value = ""


def _shift_date_tags(anon: Dataset, shift_days: int) -> None:
    """Shift configured date and datetime tags."""
    for tag in DATE_DICOM_TAGS:
        if tag in anon and anon[tag].value:
            anon[tag].value = shift_dicom_date(str(anon[tag].value), shift_days)
    for tag in DATETIME_DICOM_TAGS:
        if tag in anon and anon[tag].value:
            anon[tag].value = shift_dicom_datetime(str(anon[tag].value), shift_days)


def _remap_uid_element(element, remapper: UidRemapper) -> None:
    """Remap a single UI element value."""
    if element.value is None:
        return
    if isinstance(element.value, (list, tuple)):
        element.value = [remapper.remap(str(v)) for v in element.value]
    else:
        element.value = remapper.remap(str(element.value))


def _remap_uids_recursive(dataset: Dataset, remapper: UidRemapper) -> None:
    """Recursively remap UID tags in dataset and nested sequences."""
    for element in list(dataset):
        tag = element.tag
        if tag in PRESERVE_UID_TAGS:
            continue
        if element.VR == "UI" or tag in UID_DICOM_TAGS:
            _remap_uid_element(element, remapper)
        elif element.VR == "SQ" and element.value:
            for item in element.value:
                _remap_uids_recursive(item, remapper)


def _anonymize_file_meta(anon: Dataset, remapper: UidRemapper) -> None:
    """Anonymize File Meta Information group."""
    if not hasattr(anon, "file_meta") or not anon.file_meta:
        return
    for element in anon.file_meta:
        if element.tag in PRESERVE_UID_TAGS:
            continue
        if element.VR == "UI" or element.tag in UID_DICOM_TAGS:
            _remap_uid_element(element, remapper)
    # MediaStorageSOPInstanceUID must match SOPInstanceUID
    sop_uid = get_tag_string(anon, (0x0008, 0x0018))
    if sop_uid and hasattr(anon, "file_meta"):
        anon.file_meta.MediaStorageSOPInstanceUID = sop_uid


def anonymize_dicom_dataset(
    dataset: Dataset,
    anonymized_subject_id: str,
    shift_days: int,
    remapper: UidRemapper,
    *,
    preserve_patient_sex: bool = True,
) -> tuple[Dataset, list[str]]:
    """Return a de-identified copy of a DICOM dataset and pre-processing warnings."""
    pre_warnings = detect_burned_in_warnings(dataset)
    original_uids = collect_uid_values(dataset)

    anon = dataset.copy()
    anon.remove_private_tags()

    _clear_phi_tags(anon, anonymized_subject_id, preserve_patient_sex)
    _shift_date_tags(anon, shift_days)
    _remap_uids_recursive(anon, remapper)
    _anonymize_file_meta(anon, remapper)

    anon.PatientIdentityRemoved = "YES"
    anon.DeidentificationMethod = DEIDENTIFICATION_METHOD

    # Ensure no original UID survived in the main dataset
    for uid in original_uids:
        if uid in collect_uid_values(anon):
            LOGGER.warning(
                "Original UID may remain after remap for subject %s",
                anonymized_subject_id,
            )

    return anon, pre_warnings


def write_dicom_atomic(dataset: Dataset, destination: Path) -> None:
    """Write DICOM dataset atomically."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f"{destination.name}.tmp.{os.getpid()}")
    try:
        dataset.save_as(str(temp_path), enforce_file_format=True)
        temp_path.replace(destination)
    except OSError:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def read_dicom_safe(path: Path) -> Dataset | None:
    """Read DICOM dataset, returning None on failure."""
    try:
        return pydicom.dcmread(str(path), stop_before_pixels=False, force=False)
    except (InvalidDicomError, OSError) as exc:
        LOGGER.warning("Cannot read DICOM %s: %s", path, exc)
        return None


def process_dicom_file(
    source_path: Path,
    destination_path: Path,
    anonymized_subject_id: str,
    shift_days: int,
    preserve_patient_sex: bool,
) -> DicomProcessResult:
    """Read, anonymize, validate, and write one DICOM file without raising."""
    try:
        dataset = pydicom.dcmread(str(source_path), stop_before_pixels=False, force=False)
    except (InvalidDicomError, OSError) as exc:
        validation = DicomValidationResult(passed=False)
        validation.add_error(f"Cannot read DICOM: {exc}")
        return DicomProcessResult(success=False, validation=validation, message=str(exc))

    original_uids = collect_uid_values(dataset)
    original_dates = collect_date_values(dataset)
    remapper = UidRemapper(anonymized_subject_id)

    try:
        anonymized, pre_warnings = anonymize_dicom_dataset(
            dataset,
            anonymized_subject_id,
            shift_days,
            remapper,
            preserve_patient_sex=preserve_patient_sex,
        )
        validation = validate_anonymized_dicom(
            anonymized,
            anonymized_subject_id=anonymized_subject_id,
            original_uids=original_uids,
            original_dates=original_dates,
            shift_days=shift_days,
            pre_anonymization_warnings=pre_warnings,
        )
        if not validation.passed:
            return DicomProcessResult(
                success=False,
                validation=validation,
                message="; ".join(validation.errors),
            )
        write_dicom_atomic(anonymized, destination_path)
        if validation.warnings:
            for warning in validation.warnings:
                LOGGER.warning("DICOM %s: %s", source_path.name, warning)
        return DicomProcessResult(success=True, validation=validation)
    except Exception as exc:
        validation = DicomValidationResult(passed=False)
        validation.add_error(str(exc))
        return DicomProcessResult(success=False, validation=validation, message=str(exc))


# Re-export for backward compatibility
validate_dicom_anonymization = validate_anonymized_dicom
