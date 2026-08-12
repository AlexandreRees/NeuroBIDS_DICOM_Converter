"""DICOM-based MRI scanner auto-detection."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Iterable

from pydicom import dcmread
from pydicom.errors import InvalidDicomError

from neuro_pipeline.scanner.models import ScannerInfo
from neuro_pipeline.scanner.scanner_profiles import (
    ScannerProfile,
    load_all_profiles,
    select_profile_for_manufacturer,
)

LOGGER = logging.getLogger(__name__)


def _as_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _normalize_manufacturer(raw: str) -> str:
    text = (raw or "").strip()
    low = text.lower()
    if "siemens" in low:
        return "Siemens"
    if "ge medical" in low or low.startswith("ge") or "general electric" in low:
        return "GE"
    if "philips" in low:
        return "Philips"
    return text or "Unknown"


class ScannerDetector:
    """Read Manufacturer / Model / Field strength from DICOM headers."""

    def __init__(self, *, max_files: int = 40) -> None:
        self.max_files = max_files

    def inspect_file(self, path: Path) -> dict[str, object]:
        ds = dcmread(str(path), stop_before_pixels=True, force=True)
        return {
            "manufacturer": str(getattr(ds, "Manufacturer", "") or ""),
            "model": str(getattr(ds, "ManufacturerModelName", "") or ""),
            "software_version": str(getattr(ds, "SoftwareVersions", "") or ""),
            "magnetic_field_strength": _as_float(getattr(ds, "MagneticFieldStrength", None)),
            "series_description": str(getattr(ds, "SeriesDescription", "") or ""),
            "protocol_name": str(getattr(ds, "ProtocolName", "") or ""),
        }

    def detect_from_tags(self, samples: Iterable[dict[str, object]]) -> ScannerInfo:
        samples = list(samples)
        if not samples:
            return ScannerInfo(confidence="LOW", profile_name="generic")

        manuf_counts: Counter[str] = Counter()
        model_counts: Counter[str] = Counter()
        soft_counts: Counter[str] = Counter()
        fields: list[float] = []
        sequences: list[str] = []

        for sample in samples:
            manuf = _normalize_manufacturer(str(sample.get("manufacturer") or ""))
            model = str(sample.get("model") or "").strip() or "Unknown"
            soft = str(sample.get("software_version") or "").strip()
            field = sample.get("magnetic_field_strength")
            if manuf:
                manuf_counts[manuf] += 1
            if model:
                model_counts[model] += 1
            if soft:
                soft_counts[soft] += 1
            if isinstance(field, (int, float)):
                fields.append(float(field))
            for key in ("series_description", "protocol_name"):
                val = str(sample.get(key) or "").strip()
                if val and val not in sequences:
                    sequences.append(val)

        manufacturer = manuf_counts.most_common(1)[0][0] if manuf_counts else "Unknown"
        model = model_counts.most_common(1)[0][0] if model_counts else "Unknown"
        software = soft_counts.most_common(1)[0][0] if soft_counts else ""
        field_strength = None
        if fields:
            field_strength = sum(fields) / len(fields)

        confidence = "LOW"
        if manufacturer != "Unknown" and model != "Unknown":
            confidence = "HIGH"
        elif manufacturer != "Unknown":
            confidence = "MEDIUM"

        profile = select_profile_for_manufacturer(manufacturer)
        return ScannerInfo(
            manufacturer=manufacturer,
            model=model,
            software_version=software,
            magnetic_field_strength=field_strength,
            detected_sequences=sequences[:50],
            profile_name=profile.name,
            confidence=confidence,
        )

    def detect(self, dicom_folder: Path | str) -> ScannerInfo:
        root = Path(dicom_folder)
        samples: list[dict[str, object]] = []
        if not root.is_dir():
            return ScannerInfo(confidence="LOW", profile_name="generic")

        count = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".dcm", ".ima", ".dicom", ""}:
                continue
            try:
                samples.append(self.inspect_file(path))
                count += 1
            except (InvalidDicomError, Exception):  # noqa: BLE001
                continue
            if count >= self.max_files:
                break
        return self.detect_from_tags(samples)


class AutoDetector:
    """High-level API: detect scanner and load matching profile."""

    def __init__(self) -> None:
        self.detector = ScannerDetector()
        self.profiles = load_all_profiles()

    def detect(self, dicom_folder: Path | str) -> tuple[ScannerInfo, ScannerProfile]:
        info = self.detector.detect(dicom_folder)
        profile = select_profile_for_manufacturer(info.manufacturer, self.profiles)
        info.profile_name = profile.name
        return info, profile
