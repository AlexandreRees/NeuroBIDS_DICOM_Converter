"""DICOM format probing and convertibility policy (read-only).

Does not decompress pixels. Does not modify DICOM files.
Distinction levels: detection → header parse → classification → conversion eligibility.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class DicomObjectClass(str, Enum):
    DICOM_IMAGE = "DICOM_IMAGE"
    DICOM_ENHANCED_MULTI_FRAME = "DICOM_ENHANCED_MULTI_FRAME"
    DICOM_SPECTROSCOPY = "DICOM_SPECTROSCOPY"
    DICOM_SEGMENTATION = "DICOM_SEGMENTATION"
    DICOM_STRUCTURED_REPORT = "DICOM_STRUCTURED_REPORT"
    DICOM_WAVEFORM = "DICOM_WAVEFORM"
    DICOM_SECONDARY_CAPTURE = "DICOM_SECONDARY_CAPTURE"
    DICOM_VIDEO = "DICOM_VIDEO"
    DICOM_OTHER = "DICOM_OTHER"
    NON_DICOM = "NON_DICOM"
    CORRUPTED_DICOM = "CORRUPTED_DICOM"


class Convertibility(str, Enum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_WITH_LIMITATIONS = "SUPPORTED_WITH_LIMITATIONS"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


# Storage SOP Class UID fragments / exact IDs (DICOM PS3.4 / well-known)
_MR_IMAGE = "1.2.840.10008.5.1.4.1.1.4"
_ENHANCED_MR = "1.2.840.10008.5.1.4.1.1.4.1"
_MR_SPECTRO = "1.2.840.10008.5.1.4.1.1.4.2"
_CT_IMAGE = "1.2.840.10008.5.1.4.1.1.2"
_ENHANCED_CT = "1.2.840.10008.5.1.4.1.1.2.1"
_PET_IMAGE = "1.2.840.10008.5.1.4.1.1.128"
_ENHANCED_PET = "1.2.840.10008.5.1.4.1.1.130"
_SC_IMAGE = "1.2.840.10008.5.1.4.1.1.7"
_SEG = "1.2.840.10008.5.1.4.1.1.66.4"
_SR_PREFIXES = (
    "1.2.840.10008.5.1.4.1.1.88.",
)
_WAVEFORM_PREFIXES = (
    "1.2.840.10008.5.1.4.1.1.9.",
)
_ENCAPSULATED = (
    "1.2.840.10008.5.1.4.1.1.104.1",  # PDF
    "1.2.840.10008.5.1.4.1.1.104.2",
    "1.2.840.10008.5.1.4.1.1.104.3",
    "1.2.840.10008.5.1.4.1.1.104.4",
    "1.2.840.10008.5.1.4.1.1.104.5",
)

_VIDEO_TS = {
    "1.2.840.10008.1.2.4.100",
    "1.2.840.10008.1.2.4.101",
    "1.2.840.10008.1.2.4.102",
    "1.2.840.10008.1.2.4.103",
    "1.2.840.10008.1.2.4.104",
    "1.2.840.10008.1.2.4.105",
    "1.2.840.10008.1.2.4.106",
    "1.2.840.10008.1.2.4.107",
    "1.2.840.10008.1.2.4.108",
}

TRANSFER_SYNTAX_NAMES: dict[str, str] = {
    "1.2.840.10008.1.2": "Implicit VR Little Endian",
    "1.2.840.10008.1.2.1": "Explicit VR Little Endian",
    "1.2.840.10008.1.2.1.99": "Deflated Explicit VR Little Endian",
    "1.2.840.10008.1.2.2": "Explicit VR Big Endian",
    "1.2.840.10008.1.2.4.50": "JPEG Baseline (Process 1)",
    "1.2.840.10008.1.2.4.51": "JPEG Extended (Process 2 & 4)",
    "1.2.840.10008.1.2.4.57": "JPEG Lossless, Non-Hierarchical",
    "1.2.840.10008.1.2.4.70": "JPEG Lossless, Non-Hierarchical, First-Order Prediction",
    "1.2.840.10008.1.2.4.80": "JPEG-LS Lossless",
    "1.2.840.10008.1.2.4.81": "JPEG-LS Near-Lossless",
    "1.2.840.10008.1.2.4.90": "JPEG 2000 Lossless",
    "1.2.840.10008.1.2.4.91": "JPEG 2000",
    "1.2.840.10008.1.2.4.92": "JPEG 2000 Part 2 Multi-component Lossless",
    "1.2.840.10008.1.2.4.93": "JPEG 2000 Part 2 Multi-component",
    "1.2.840.10008.1.2.5": "RLE Lossless",
}

# Fast candidate extensions (not proof of DICOM)
PREFERRED_SUFFIXES = {".dcm", ".ima", ".dicom", ""}


@dataclass(slots=True)
class DicomProbeResult:
    path: Path
    size: int = 0
    extension: str = ""
    is_dicom: bool = False
    has_preamble: bool = False
    sop_class_uid: str = ""
    sop_class_name: str = ""
    modality: str = ""
    transfer_syntax_uid: str = ""
    transfer_syntax_name: str = ""
    series_instance_uid: str = ""
    study_instance_uid: str = ""
    patient_id: str = ""
    series_number: int | None = None
    instance_number: int | None = None
    number_of_frames: int | None = None
    manufacturer: str = ""
    manufacturer_model_name: str = ""
    rows: int | None = None
    columns: int | None = None
    bits_allocated: int | None = None
    photometric_interpretation: str = ""
    image_type: list[str] = field(default_factory=list)
    series_description: str = ""
    protocol_name: str = ""
    object_class: DicomObjectClass = DicomObjectClass.NON_DICOM
    convertibility: Convertibility = Convertibility.NOT_APPLICABLE
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["object_class"] = self.object_class.value
        data["convertibility"] = self.convertibility.value
        return data


def has_dicom_preamble(path: Path | str) -> bool:
    """Return True if bytes 128:132 == DICM (Part 10)."""
    p = Path(path)
    try:
        with p.open("rb") as handle:
            header = handle.read(132)
        return len(header) >= 132 and header[128:132] == b"DICM"
    except OSError:
        return False


def looks_like_dicom_candidate(path: Path | str) -> bool:
    """Cheap candidacy: preferred suffix or Part-10 preamble."""
    p = Path(path)
    if not p.is_file():
        return False
    suffix = p.suffix.lower()
    if suffix in PREFERRED_SUFFIXES:
        return True
    # Proprietary / wrong extension: accept only with DICM magic
    return has_dicom_preamble(p)


def classify_sop_class(
    sop_class_uid: str,
    *,
    modality: str = "",
    number_of_frames: int | None = None,
    transfer_syntax_uid: str = "",
    rows: int | None = None,
    columns: int | None = None,
) -> tuple[DicomObjectClass, Convertibility]:
    """Map SOP Class (+ light context) to object class and convertibility."""
    uid = (sop_class_uid or "").strip()
    mod = (modality or "").strip().upper()
    ts = (transfer_syntax_uid or "").strip()

    if ts in _VIDEO_TS:
        return DicomObjectClass.DICOM_VIDEO, Convertibility.UNSUPPORTED

    if not uid:
        if mod in {"MR", "CT", "PT"} and rows and columns:
            return DicomObjectClass.DICOM_IMAGE, Convertibility.SUPPORTED_WITH_LIMITATIONS
        return DicomObjectClass.DICOM_OTHER, Convertibility.UNKNOWN

    if uid in _ENCAPSULATED or uid.startswith("1.2.840.10008.5.1.4.1.1.104."):
        return DicomObjectClass.DICOM_OTHER, Convertibility.NOT_APPLICABLE

    if any(uid.startswith(p) for p in _SR_PREFIXES):
        return DicomObjectClass.DICOM_STRUCTURED_REPORT, Convertibility.NOT_APPLICABLE

    if any(uid.startswith(p) for p in _WAVEFORM_PREFIXES):
        return DicomObjectClass.DICOM_WAVEFORM, Convertibility.NOT_APPLICABLE

    if uid.startswith(_SEG) or ".66." in uid and "Segmentation" in uid:
        return DicomObjectClass.DICOM_SEGMENTATION, Convertibility.NOT_APPLICABLE
    if uid.startswith("1.2.840.10008.5.1.4.1.1.66"):
        return DicomObjectClass.DICOM_SEGMENTATION, Convertibility.NOT_APPLICABLE

    if uid.startswith(_MR_SPECTRO) or uid == _MR_SPECTRO:
        return DicomObjectClass.DICOM_SPECTROSCOPY, Convertibility.NOT_APPLICABLE

    if uid.startswith(_ENHANCED_MR) or uid.startswith(_ENHANCED_CT) or uid.startswith(_ENHANCED_PET):
        return DicomObjectClass.DICOM_ENHANCED_MULTI_FRAME, Convertibility.SUPPORTED_WITH_LIMITATIONS

    if (
        uid.startswith(_MR_IMAGE)
        or uid.startswith(_CT_IMAGE)
        or uid.startswith(_PET_IMAGE)
        or uid.startswith("1.2.840.10008.5.1.4.1.1.2")
        or uid.startswith("1.2.840.10008.5.1.4.1.1.4")
        or uid.startswith("1.2.840.10008.5.1.4.1.1.128")
    ):
        klass = (
            DicomObjectClass.DICOM_ENHANCED_MULTI_FRAME
            if (number_of_frames or 0) > 1
            else DicomObjectClass.DICOM_IMAGE
        )
        return klass, Convertibility.SUPPORTED

    if uid.startswith(_SC_IMAGE) or uid.startswith("1.2.840.10008.5.1.4.1.1.7"):
        if rows and columns:
            return DicomObjectClass.DICOM_SECONDARY_CAPTURE, Convertibility.SUPPORTED_WITH_LIMITATIONS
        return DicomObjectClass.DICOM_SECONDARY_CAPTURE, Convertibility.NOT_APPLICABLE

    if mod in {"SR", "SEG", "PR", "ECG", "EEG"}:
        return DicomObjectClass.DICOM_OTHER, Convertibility.NOT_APPLICABLE

    if mod in {"MR", "CT", "PT", "NM"} and rows and columns:
        return DicomObjectClass.DICOM_IMAGE, Convertibility.SUPPORTED_WITH_LIMITATIONS

    return DicomObjectClass.DICOM_OTHER, Convertibility.UNKNOWN


def is_convertible_to_nifti(object_class: DicomObjectClass, convertibility: Convertibility) -> bool:
    if convertibility in {Convertibility.NOT_APPLICABLE, Convertibility.UNSUPPORTED}:
        return False
    if object_class in {
        DicomObjectClass.DICOM_SPECTROSCOPY,
        DicomObjectClass.DICOM_SEGMENTATION,
        DicomObjectClass.DICOM_STRUCTURED_REPORT,
        DicomObjectClass.DICOM_WAVEFORM,
        DicomObjectClass.DICOM_VIDEO,
        DicomObjectClass.DICOM_OTHER,
        DicomObjectClass.NON_DICOM,
        DicomObjectClass.CORRUPTED_DICOM,
    }:
        return False
    return object_class in {
        DicomObjectClass.DICOM_IMAGE,
        DicomObjectClass.DICOM_ENHANCED_MULTI_FRAME,
        DicomObjectClass.DICOM_SECONDARY_CAPTURE,
    }


def probe_dicom_file(path: Path | str) -> DicomProbeResult:
    """Read-only probe of one candidate file (headers only)."""
    p = Path(path)
    result = DicomProbeResult(path=p, extension=p.suffix.lower())
    try:
        result.size = p.stat().st_size
    except OSError as exc:
        result.message = f"stat failed: {exc}"
        result.object_class = DicomObjectClass.CORRUPTED_DICOM
        return result

    if result.size == 0:
        result.message = "Empty file"
        result.object_class = DicomObjectClass.CORRUPTED_DICOM
        return result

    result.has_preamble = has_dicom_preamble(p)

    try:
        from pydicom import dcmread
        from pydicom.errors import InvalidDicomError
    except ImportError:
        result.message = "pydicom not available"
        return result

    ds = None
    try:
        ds = dcmread(str(p), stop_before_pixels=True, force=False)
    except InvalidDicomError:
        try:
            ds = dcmread(str(p), stop_before_pixels=True, force=True)
            if not hasattr(ds, "SOPClassUID") and not hasattr(ds, "SeriesInstanceUID"):
                result.message = "Not a DICOM dataset"
                result.object_class = DicomObjectClass.NON_DICOM
                return result
        except Exception as exc:  # noqa: BLE001
            result.message = f"Unreadable: {exc}"
            result.object_class = (
                DicomObjectClass.CORRUPTED_DICOM if result.has_preamble else DicomObjectClass.NON_DICOM
            )
            return result
    except Exception as exc:  # noqa: BLE001
        result.message = f"Unreadable: {exc}"
        result.object_class = DicomObjectClass.CORRUPTED_DICOM
        return result

    sop_uid = str(getattr(ds, "SOPClassUID", "") or "")
    series_uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
    modality = str(getattr(ds, "Modality", "") or "")
    # Reject empty shells (e.g. preamble+DICM only) accepted by a lenient read.
    if not sop_uid and not series_uid and not modality:
        result.message = "DICOM shell without required identifying tags"
        result.object_class = (
            DicomObjectClass.CORRUPTED_DICOM if result.has_preamble else DicomObjectClass.NON_DICOM
        )
        return result

    result.is_dicom = True
    result.sop_class_uid = sop_uid
    result.modality = modality
    result.series_instance_uid = series_uid
    result.study_instance_uid = str(getattr(ds, "StudyInstanceUID", "") or "")
    # Prefer empty over logging raw identifiers when anonymisation tag present
    result.patient_id = str(getattr(ds, "PatientID", "") or "")
    result.series_number = _as_int(getattr(ds, "SeriesNumber", None))
    result.instance_number = _as_int(getattr(ds, "InstanceNumber", None))
    result.number_of_frames = _as_int(getattr(ds, "NumberOfFrames", None))
    result.manufacturer = str(getattr(ds, "Manufacturer", "") or "")
    result.manufacturer_model_name = str(getattr(ds, "ManufacturerModelName", "") or "")
    result.rows = _as_int(getattr(ds, "Rows", None))
    result.columns = _as_int(getattr(ds, "Columns", None))
    result.bits_allocated = _as_int(getattr(ds, "BitsAllocated", None))
    result.photometric_interpretation = str(getattr(ds, "PhotometricInterpretation", "") or "")
    result.series_description = str(getattr(ds, "SeriesDescription", "") or "")
    result.protocol_name = str(getattr(ds, "ProtocolName", "") or "")

    image_type = getattr(ds, "ImageType", None)
    if image_type is not None:
        try:
            result.image_type = [str(x) for x in image_type]
        except TypeError:
            result.image_type = [str(image_type)]

    ts = ""
    try:
        ts = str(getattr(ds, "file_meta", None) and ds.file_meta.get("TransferSyntaxUID", "") or "")
    except Exception:  # noqa: BLE001
        ts = ""
    if not ts:
        ts = str(getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", "") or "")
    result.transfer_syntax_uid = ts
    result.transfer_syntax_name = TRANSFER_SYNTAX_NAMES.get(ts, "")

    try:
        from pydicom.uid import UID

        if result.sop_class_uid:
            result.sop_class_name = str(UID(result.sop_class_uid).name)
    except Exception:  # noqa: BLE001
        result.sop_class_name = ""

    result.object_class, result.convertibility = classify_sop_class(
        result.sop_class_uid,
        modality=result.modality,
        number_of_frames=result.number_of_frames,
        transfer_syntax_uid=result.transfer_syntax_uid,
        rows=result.rows,
        columns=result.columns,
    )
    return result


def _as_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
