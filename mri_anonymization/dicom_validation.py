"""Structured validation for anonymized DICOM datasets."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydicom.dataset import Dataset

from mri_anonymization.constants import (
    BURNED_IN_TAG,
    DATE_DICOM_TAGS,
    DATETIME_DICOM_TAGS,
    DEIDENTIFICATION_METHOD,
    OVERLAY_GROUP_END,
    OVERLAY_GROUP_START,
    PATIENT_NAME_POLICY,
    PHI_DICOM_TAGS,
    PRESERVE_UID_TAGS,
    PSEUDONYM_DICOM_TAGS,
    REQUIRED_ANON_TAGS,
    UID_DICOM_TAGS,
)
from mri_anonymization.dicom_utils import get_tag_string, iter_all_elements
from mri_anonymization.uid_remapper import is_valid_dicom_uid


@dataclass
class DicomValidationResult:
    """Structured outcome of per-file DICOM anonymization validation."""

    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        """Record a non-fatal validation warning."""
        self.warnings.append(message)

    def add_error(self, message: str) -> None:
        """Record a fatal validation error."""
        self.errors.append(message)
        self.passed = False


def _tag_is_empty(value: str) -> bool:
    """Return True if a tag value is empty or whitespace."""
    return not value.strip()


def validate_patient_identity(
    dataset: Dataset,
    anonymized_subject_id: str,
    result: DicomValidationResult,
) -> None:
    """Validate PatientName/PatientID against the configured pseudonym policy."""
    patient_id = get_tag_string(dataset, (0x0010, 0x0020))
    patient_name = get_tag_string(dataset, (0x0010, 0x0010))

    if patient_id != anonymized_subject_id:
        result.add_error(
            f"PatientID expected {anonymized_subject_id!r}, got {patient_id!r}"
        )

    if PATIENT_NAME_POLICY == "pseudonym":
        if patient_name != anonymized_subject_id:
            result.add_error(
                f"PatientName expected pseudonym {anonymized_subject_id!r}, "
                f"got {patient_name!r}"
            )
    elif _tag_is_empty(patient_name):
        result.add_error("PatientName is empty (empty policy)")


def validate_phi_tags_cleared(dataset: Dataset, result: DicomValidationResult) -> None:
    """Verify all configured PHI tags are cleared or pseudonymized."""
    for tag in PHI_DICOM_TAGS:
        if tag in PSEUDONYM_DICOM_TAGS:
            continue
        value = get_tag_string(dataset, tag)
        if not _tag_is_empty(value):
            result.add_error(f"PHI tag {tag} not cleared: {value!r}")


def validate_no_private_tags(dataset: Dataset, result: DicomValidationResult) -> None:
    """Verify no private (odd-group) tags remain in dataset or file meta."""
    for element in iter_all_elements(dataset, include_file_meta=True):
        if element.tag.group % 2 == 1:
            result.add_error(f"Private tag remains: {element.tag}")
            return


def validate_required_anonymization_tags(
    dataset: Dataset,
    result: DicomValidationResult,
) -> None:
    """Verify de-identification provenance tags are present."""
    identity_removed = get_tag_string(dataset, (0x0012, 0x0062))
    if identity_removed.upper() != "YES":
        result.add_error(
            f"PatientIdentityRemoved expected 'YES', got {identity_removed!r}"
        )

    method = get_tag_string(dataset, (0x0012, 0x0063))
    if not method:
        result.add_error("DeidentificationMethod is missing")
    elif DEIDENTIFICATION_METHOD not in method and method != DEIDENTIFICATION_METHOD:
        result.add_warning(
            f"DeidentificationMethod may be incomplete: {method!r}"
        )


def validate_uid_tags(
    dataset: Dataset,
    original_uids: set[str],
    result: DicomValidationResult,
) -> None:
    """Verify UID tags were remapped and do not retain original values."""
    for element in iter_all_elements(dataset, include_file_meta=True):
        if element.tag in PRESERVE_UID_TAGS:
            continue
        if element.VR != "UI" and element.tag not in UID_DICOM_TAGS:
            continue
        if element.value is None:
            continue
        values = element.value if isinstance(element.value, (list, tuple)) else [element.value]
        for value in values:
            uid = str(value).strip()
            if not uid:
                continue
            if uid in original_uids:
                result.add_error(f"Original UID retained at {element.tag}: {uid}")
            if not is_valid_dicom_uid(uid):
                result.add_error(f"Invalid UID syntax at {element.tag}: {uid}")


def validate_dates_shifted(
    dataset: Dataset,
    original_dates: dict[tuple[int, int], str],
    shift_days: int,
    result: DicomValidationResult,
) -> None:
    """Verify date tags differ from originals when a shift was applied."""
    if shift_days == 0:
        return
    for tag in (*DATE_DICOM_TAGS, *DATETIME_DICOM_TAGS):
        original = original_dates.get(tag, "")
        current = get_tag_string(dataset, tag)
        if original and current and original == current:
            result.add_error(f"Date tag {tag} was not shifted: {current!r}")


def validate_burned_in_annotations(
    dataset: Dataset,
    result: DicomValidationResult,
) -> None:
    """Warn or fail when burned-in PHI may remain in pixel or overlay data."""
    burned_in = get_tag_string(dataset, BURNED_IN_TAG).upper()
    if burned_in == "YES":
        result.add_error(
            "BurnedInAnnotation is YES — PHI may be embedded in pixels"
        )
    elif burned_in == "NO":
        pass
    elif burned_in:
        result.add_warning(f"Unexpected BurnedInAnnotation value: {burned_in!r}")

    for element in dataset:
        if OVERLAY_GROUP_START <= element.tag.group <= OVERLAY_GROUP_END:
            result.add_warning(
                f"Overlay element present ({element.tag}) — may contain burned-in PHI"
            )

    if (0x0070, 0x0001) in dataset:
        result.add_warning(
            "GraphicAnnotationSequence present — review for burned-in identifiers"
        )


def validate_uid_internal_consistency(
    dataset: Dataset,
    result: DicomValidationResult,
) -> None:
    """Verify SOPInstanceUID matches File Meta MediaStorageSOPInstanceUID."""
    sop_uid = get_tag_string(dataset, (0x0008, 0x0018))
    if not hasattr(dataset, "file_meta") or not dataset.file_meta:
        return
    media_uid = get_tag_string(dataset.file_meta, (0x0002, 0x0003))
    if sop_uid and media_uid and sop_uid != media_uid:
        result.add_error(
            "MediaStorageSOPInstanceUID does not match SOPInstanceUID "
            f"({media_uid!r} vs {sop_uid!r})"
        )


def validate_anonymized_dicom(
    dataset: Dataset,
    *,
    anonymized_subject_id: str,
    original_uids: set[str],
    original_dates: dict[tuple[int, int], str],
    shift_days: int,
    pre_anonymization_warnings: list[str] | None = None,
) -> DicomValidationResult:
    """Run full validation suite on an anonymized DICOM dataset."""
    result = DicomValidationResult()

    if pre_anonymization_warnings:
        for message in pre_anonymization_warnings:
            result.add_warning(message)

    validate_patient_identity(dataset, anonymized_subject_id, result)
    validate_phi_tags_cleared(dataset, result)
    validate_no_private_tags(dataset, result)
    validate_required_anonymization_tags(dataset, result)
    validate_uid_tags(dataset, original_uids, result)
    validate_uid_internal_consistency(dataset, result)
    validate_dates_shifted(dataset, original_dates, shift_days, result)
    validate_burned_in_annotations(dataset, result)

    return result
