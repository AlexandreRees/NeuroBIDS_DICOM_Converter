"""DICOM PS3.15 and metadata constants for anonymization."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# DICOM PS3.15 Basic Application Level Confidentiality Profile
# Tags cleared (empty string) or replaced with pseudonym where noted.
# ---------------------------------------------------------------------------
PHI_DICOM_TAGS: tuple[tuple[int, int], ...] = (
    (0x0010, 0x0010),  # PatientName → replaced with pseudonym
    (0x0010, 0x0020),  # PatientID → replaced with pseudonym
    (0x0010, 0x0030),  # PatientBirthDate
    (0x0010, 0x1000),  # OtherPatientIDs
    (0x0010, 0x1001),  # OtherPatientNames
    (0x0010, 0x2160),  # EthnicGroup
    (0x0010, 0x2180),  # Occupation
    (0x0010, 0x21B0),  # AdditionalPatientHistory
    (0x0010, 0x4000),  # PatientComments
    (0x0008, 0x0080),  # InstitutionName
    (0x0008, 0x0081),  # InstitutionAddress
    (0x0008, 0x0090),  # ReferringPhysicianName
    (0x0008, 0x0092),  # ReferringPhysicianAddress
    (0x0008, 0x0094),  # ReferringPhysicianTelephoneNumbers
    (0x0008, 0x1048),  # PhysiciansOfRecord
    (0x0008, 0x1050),  # PerformingPhysicianName
    (0x0008, 0x1060),  # NameOfPhysiciansReadingStudy
    (0x0008, 0x1070),  # OperatorsName
    (0x0008, 0x1010),  # StationName
    (0x0008, 0x1030),  # StudyDescription (may contain PHI)
    (0x0008, 0x0050),  # AccessionNumber
    (0x0018, 0x1000),  # DeviceSerialNumber
    (0x0020, 0x0010),  # StudyID
    (0x0032, 0x1032),  # RequestingPhysician
    (0x0032, 0x1060),  # RequestedProcedureDescription
    (0x0040, 0x0241),  # PerformedStationAETitle
    (0x0040, 0x0242),  # PerformedStationName
    (0x0040, 0x0243),  # PerformedLocation
    (0x0040, 0xA075),  # VerifyingObserverName
    (0x0040, 0xA123),  # PersonName
    (0x0020, 0x4000),  # ImageComments
    (0x0032, 0x4000),  # StudyComments
    (0x4008, 0x010C),  # IdentifyingComments
    (0x4008, 0x0111),  # UniformResourceLocator
)

# Tags replaced with pseudonym rather than cleared.
PSEUDONYM_DICOM_TAGS: frozenset[tuple[int, int]] = frozenset(
    {
        (0x0010, 0x0010),
        (0x0010, 0x0020),
    }
)

# UID tags remapped to prevent linkage (SOP Class UID excluded).
UID_DICOM_TAGS: frozenset[tuple[int, int]] = frozenset(
    {
        (0x0020, 0x000D),  # StudyInstanceUID
        (0x0020, 0x000E),  # SeriesInstanceUID
        (0x0008, 0x0018),  # SOPInstanceUID
        (0x0020, 0x0052),  # FrameOfReferenceUID
        (0x0002, 0x0003),  # MediaStorageSOPInstanceUID (file meta)
        (0x0008, 0x1155),  # ReferencedSOPInstanceUID
        (0x0020, 0x0200),  # SynchronizationFrameOfReferenceUID
        (0x0020, 0x0051),  # RelatedFrameOfReferenceUID
    }
)

# SOP Class UID is standard and must not be remapped.
PRESERVE_UID_TAGS: frozenset[tuple[int, int]] = frozenset({(0x0008, 0x0016)})

# DICOM date tags shifted by per-subject offset.
DATE_DICOM_TAGS: tuple[tuple[int, int], ...] = (
    (0x0008, 0x0020),  # StudyDate
    (0x0008, 0x0021),  # SeriesDate
    (0x0008, 0x0022),  # AcquisitionDate
    (0x0008, 0x0023),  # ContentDate
    (0x0008, 0x0012),  # InstanceCreationDate
    (0x0040, 0x0244),  # PerformedProcedureStepStartDate
    (0x0040, 0x0250),  # PerformedProcedureStepEndDate
    (0x0010, 0x0030),  # PatientBirthDate (cleared, but shift if retained)
)

DATETIME_DICOM_TAGS: tuple[tuple[int, int], ...] = (
    (0x0008, 0x002A),  # AcquisitionDateTime
    (0x0040, 0x0245),  # PerformedProcedureStepStartTime (paired date tag)
)

# Required de-identification provenance tags.
REQUIRED_ANON_TAGS: tuple[tuple[int, int], ...] = (
    (0x0012, 0x0062),  # PatientIdentityRemoved
    (0x0012, 0x0063),  # DeidentificationMethod
)

# Burned-in annotation and overlay-related tags.
BURNED_IN_TAG: tuple[int, int] = (0x0028, 0x0301)
OVERLAY_GROUP_START: int = 0x6000
OVERLAY_GROUP_END: int = 0x601F

# JSON / tabular field names likely to contain calendar dates.
METADATA_DATE_KEYS: frozenset[str] = frozenset(
    {
        "StudyDate",
        "SeriesDate",
        "AcquisitionDate",
        "ContentDate",
        "InstanceCreationDate",
        "AcquisitionDateTime",
        "PerformedProcedureStepStartDate",
        "PerformedProcedureStepEndDate",
        "StudyDateTime",
        "ScanDate",
        "Date",
        "date",
        "birthdate",
        "PatientBirthDate",
    }
)

DICOM_EXTENSIONS: frozenset[str] = frozenset({".dcm", ".dicom", ".ima", ".img", ""})

NIFTI_SUFFIXES: tuple[str, ...] = (".nii.gz", ".nii")

ANATOMICAL_MARKERS: tuple[str, ...] = ("_T1w", "_T2w", "_PDw", "_FLAIR", "_MPRAGE")

PIPELINE_VERSION: str = "2.0.0"

DEIDENTIFICATION_METHOD: str = (
    "PS3.15 Basic Profile; pseudonym; date shift; UID remap"
)

# Policy: PatientName and PatientID are set to the anonymized subject pseudonym.
PATIENT_NAME_POLICY: str = "pseudonym"
