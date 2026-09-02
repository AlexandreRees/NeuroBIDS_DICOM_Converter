"""Smart DICOM metadata extraction (read-only, crash-safe)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator

    _HAS_PYDANTIC = True
except ImportError:  # pragma: no cover - exercised when pydantic absent
    _HAS_PYDANTIC = False
    BaseModel = object  # type: ignore[misc, assignment]
    ConfigDict = dict  # type: ignore[misc, assignment]
    Field = lambda default=None, **kwargs: default  # type: ignore[misc, assignment]

    def field_validator(*_a, **_k):  # type: ignore[misc]
        def deco(fn):
            return fn

        return deco


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if _HAS_PYDANTIC:

    class DicomSeriesMetadata(BaseModel):
        """Validated DICOM series metadata for reporting / classification."""

        model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

        patient_id: str = ""
        patient_name: str | None = Field(
            default=None,
            description="Never exported in public summaries",
        )
        patient_age: str | None = None
        patient_sex: str | None = None
        study_instance_uid: str = ""
        study_date: str | None = None
        study_description: str = ""
        series_instance_uid: str = ""
        series_number: int | None = None
        series_description: str = ""
        protocol_name: str = ""
        manufacturer: str = ""
        manufacturer_model_name: str = ""
        modality: str = ""
        image_type: list[str] = Field(default_factory=list)
        magnetic_field_strength: float | None = None
        repetition_time: float | None = None
        echo_time: float | None = None
        flip_angle: float | None = None
        slice_thickness: float | None = None
        pixel_spacing: list[float] | None = None
        rows: int | None = None
        columns: int | None = None
        b_values: list[float] = Field(default_factory=list)
        diffusion_directions: list[list[float]] = Field(default_factory=list)
        diffusion_present: bool = False
        sample_file: str = ""
        source_dir: str = ""
        num_images: int = 0

        @field_validator("series_number", "rows", "columns", "num_images", mode="before")
        @classmethod
        def _coerce_int(cls, value: Any) -> int | None:
            if value == 0:
                return 0
            return _optional_int(value)

        @field_validator(
            "magnetic_field_strength",
            "repetition_time",
            "echo_time",
            "flip_angle",
            "slice_thickness",
            mode="before",
        )
        @classmethod
        def _coerce_float(cls, value: Any) -> float | None:
            return _optional_float(value)

        @property
        def scanner(self) -> str:
            parts = [p for p in (self.manufacturer, self.manufacturer_model_name) if p]
            return " ".join(parts) if parts else "Unknown"

        @property
        def sequence(self) -> str:
            return self.protocol_name or self.series_description or "Unknown"

        def to_summary_dict(self) -> dict[str, Any]:
            return _summary_dict(self)

else:
    from dataclasses import asdict, dataclass, field

    @dataclass
    class DicomSeriesMetadata:  # type: ignore[no-redef]
        """Validated DICOM series metadata (dataclass fallback without pydantic)."""

        patient_id: str = ""
        patient_name: str | None = None
        patient_age: str | None = None
        patient_sex: str | None = None
        study_instance_uid: str = ""
        study_date: str | None = None
        study_description: str = ""
        series_instance_uid: str = ""
        series_number: int | None = None
        series_description: str = ""
        protocol_name: str = ""
        manufacturer: str = ""
        manufacturer_model_name: str = ""
        modality: str = ""
        image_type: list[str] = field(default_factory=list)
        magnetic_field_strength: float | None = None
        repetition_time: float | None = None
        echo_time: float | None = None
        flip_angle: float | None = None
        slice_thickness: float | None = None
        pixel_spacing: list[float] | None = None
        rows: int | None = None
        columns: int | None = None
        b_values: list[float] = field(default_factory=list)
        diffusion_directions: list[list[float]] = field(default_factory=list)
        diffusion_present: bool = False
        sample_file: str = ""
        source_dir: str = ""
        num_images: int = 0

        def __post_init__(self) -> None:
            self.series_number = _optional_int(self.series_number)
            self.rows = _optional_int(self.rows)
            self.columns = _optional_int(self.columns)
            self.num_images = _optional_int(self.num_images) or 0
            self.magnetic_field_strength = _optional_float(self.magnetic_field_strength)
            self.repetition_time = _optional_float(self.repetition_time)
            self.echo_time = _optional_float(self.echo_time)
            self.flip_angle = _optional_float(self.flip_angle)
            self.slice_thickness = _optional_float(self.slice_thickness)

        @property
        def scanner(self) -> str:
            parts = [p for p in (self.manufacturer, self.manufacturer_model_name) if p]
            return " ".join(parts) if parts else "Unknown"

        @property
        def sequence(self) -> str:
            return self.protocol_name or self.series_description or "Unknown"

        def to_summary_dict(self) -> dict[str, Any]:
            return _summary_dict(self)

        def model_dump(self) -> dict[str, Any]:
            return asdict(self)


def _summary_dict(meta: Any) -> dict[str, Any]:
    """Compact export for ``metadata.json`` (no PatientName)."""
    modality_guess = getattr(meta, "modality", "") or ""
    if getattr(meta, "diffusion_present", False) and not modality_guess:
        modality_guess = "DWI"
    payload: dict[str, Any] = {
        "scanner": meta.scanner,
        "field_strength": meta.magnetic_field_strength,
        "sequence": meta.sequence,
        "modality": modality_guess,
        "TR": meta.repetition_time,
        "TE": meta.echo_time,
        "series_description": meta.series_description,
        "protocol_name": meta.protocol_name,
        "manufacturer": meta.manufacturer,
        "manufacturer_model_name": meta.manufacturer_model_name,
        "study_date": meta.study_date,
        "patient_id": meta.patient_id,
        "patient_age": meta.patient_age,
        "patient_sex": meta.patient_sex,
        "flip_angle": meta.flip_angle,
        "slice_thickness": meta.slice_thickness,
        "pixel_spacing": meta.pixel_spacing,
        "rows": meta.rows,
        "columns": meta.columns,
        "b_values": meta.b_values or None,
        "diffusion_present": meta.diffusion_present,
        "series_instance_uid": meta.series_instance_uid,
        "study_instance_uid": meta.study_instance_uid,
        "num_images": meta.num_images,
    }
    keep_even_empty = {
        "scanner",
        "sequence",
        "modality",
        "field_strength",
        "TR",
        "TE",
    }
    return {
        k: v
        for k, v in payload.items()
        if v not in (None, "", [], False) or k in keep_even_empty
    }


class DicomMetadataExtractor:
    """Extract useful DICOM series metadata without modifying source files."""

    def extract_from_file(
        self,
        path: Path | str,
        *,
        num_images: int = 0,
        source_dir: Path | str | None = None,
    ) -> DicomSeriesMetadata:
        """Read one DICOM file (stop before pixels) and return metadata."""
        path = Path(path)
        try:
            from pydicom import dcmread

            ds = dcmread(str(path), stop_before_pixels=True, force=True)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Metadata extract failed for %s: %s", path, exc)
            return DicomSeriesMetadata(
                sample_file=str(path),
                source_dir=str(source_dir or path.parent),
                num_images=num_images,
            )
        return self.extract_from_dataset(
            ds,
            sample_file=path,
            num_images=num_images,
            source_dir=source_dir or path.parent,
        )

    def extract_from_dataset(
        self,
        ds: Any,
        *,
        sample_file: Path | str | None = None,
        num_images: int = 0,
        source_dir: Path | str | None = None,
    ) -> DicomSeriesMetadata:
        """Build ``DicomSeriesMetadata`` from an open pydicom dataset."""
        image_type = _as_str_list(getattr(ds, "ImageType", None))
        pixel_spacing = _as_float_list(getattr(ds, "PixelSpacing", None))
        b_values = _extract_b_values(ds)
        directions = _extract_directions(ds)
        diffusion_present = bool(b_values or directions) or any(
            hasattr(ds, tag) and getattr(ds, tag) not in (None, "", [])
            for tag in ("DiffusionBValue", "DiffusionGradientDirectionSequence")
        )

        patient_name = None
        try:
            pn = getattr(ds, "PatientName", None)
            if pn is not None:
                patient_name = str(pn)
        except Exception:  # noqa: BLE001
            patient_name = None

        return DicomSeriesMetadata(
            patient_id=str(getattr(ds, "PatientID", "") or ""),
            patient_name=patient_name,
            patient_age=_safe_str(getattr(ds, "PatientAge", None)),
            patient_sex=_safe_str(getattr(ds, "PatientSex", None)),
            study_instance_uid=str(getattr(ds, "StudyInstanceUID", "") or ""),
            study_date=_safe_str(getattr(ds, "StudyDate", None)),
            study_description=str(getattr(ds, "StudyDescription", "") or ""),
            series_instance_uid=str(getattr(ds, "SeriesInstanceUID", "") or ""),
            series_number=_safe_int(getattr(ds, "SeriesNumber", None)),
            series_description=str(getattr(ds, "SeriesDescription", "") or ""),
            protocol_name=str(getattr(ds, "ProtocolName", "") or ""),
            manufacturer=str(getattr(ds, "Manufacturer", "") or ""),
            manufacturer_model_name=str(getattr(ds, "ManufacturerModelName", "") or ""),
            modality=str(getattr(ds, "Modality", "") or ""),
            image_type=image_type,
            magnetic_field_strength=_safe_float(getattr(ds, "MagneticFieldStrength", None)),
            repetition_time=_safe_float(getattr(ds, "RepetitionTime", None)),
            echo_time=_safe_float(getattr(ds, "EchoTime", None)),
            flip_angle=_safe_float(getattr(ds, "FlipAngle", None)),
            slice_thickness=_safe_float(getattr(ds, "SliceThickness", None)),
            pixel_spacing=pixel_spacing,
            rows=_safe_int(getattr(ds, "Rows", None)),
            columns=_safe_int(getattr(ds, "Columns", None)),
            b_values=b_values,
            diffusion_directions=directions,
            diffusion_present=diffusion_present,
            sample_file=str(sample_file or ""),
            source_dir=str(source_dir or ""),
            num_images=num_images,
        )

    def export_json(
        self,
        metadata: DicomSeriesMetadata,
        destination: Path | str,
        *,
        overwrite: bool = False,
    ) -> Path | None:
        """Write compact ``metadata.json`` (never includes PatientName)."""
        dest = Path(destination)
        if dest.exists() and not overwrite:
            LOGGER.info("metadata.json exists — not overwriting: %s", dest)
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(metadata.to_summary_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return dest


def _safe_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _safe_int(value: Any) -> int | None:
    return _optional_int(value)


def _safe_float(value: Any) -> float | None:
    return _optional_float(value)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(x) for x in value]
    except TypeError:
        return [str(value)]


def _as_float_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        return [float(x) for x in value]
    except (TypeError, ValueError):
        try:
            return [float(value)]
        except (TypeError, ValueError):
            return None


def _extract_b_values(ds: Any) -> list[float]:
    values: list[float] = []
    for tag in ("DiffusionBValue", "B_value"):
        if hasattr(ds, tag):
            raw = getattr(ds, tag)
            try:
                if isinstance(raw, (list, tuple)):
                    values.extend(float(x) for x in raw)
                else:
                    values.append(float(raw))
            except (TypeError, ValueError):
                pass
    seq = getattr(ds, "MRDiffusionSequence", None)
    if seq:
        try:
            for item in seq:
                bv = getattr(item, "DiffusionBValue", None)
                if bv is not None:
                    values.append(float(bv))
        except Exception:  # noqa: BLE001
            pass
    return sorted({round(v, 6) for v in values})


def _extract_directions(ds: Any) -> list[list[float]]:
    out: list[list[float]] = []
    seq = getattr(ds, "DiffusionGradientDirectionSequence", None)
    if not seq:
        return out
    try:
        for item in seq:
            vec = getattr(item, "DiffusionGradientOrientation", None)
            if vec is None:
                continue
            out.append([float(x) for x in vec])
    except Exception:  # noqa: BLE001
        return out
    return out
