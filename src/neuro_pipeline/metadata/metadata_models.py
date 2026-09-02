"""JSON sidecar metadata models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


RECOMMENDED_FIELDS = (
    "Manufacturer",
    "MagneticFieldStrength",
    "SequenceName",
    "ProtocolName",
    "RepetitionTime",
    "EchoTime",
)


@dataclass(slots=True)
class SidecarInfo:
    """Metadata extracted from one dcm2niix JSON sidecar."""

    path: Path
    nifti_path: Path | None = None
    data: dict[str, Any] = field(default_factory=dict)
    present_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def manufacturer(self) -> str:
        return str(self.data.get("Manufacturer") or self.data.get("ManufacturersModelName") or "")

    @property
    def field_strength(self) -> str:
        val = self.data.get("MagneticFieldStrength")
        if val is None or val == "":
            return ""
        try:
            return f"{float(val):g}T"
        except (TypeError, ValueError):
            return str(val)

    @property
    def sequence_name(self) -> str:
        return str(
            self.data.get("SequenceName")
            or self.data.get("SeriesDescription")
            or self.data.get("ProtocolName")
            or ""
        )

    @property
    def protocol_name(self) -> str:
        return str(self.data.get("ProtocolName") or "")


@dataclass(slots=True)
class MetadataSummary:
    """Aggregate scanner/sequence notes for reports."""

    sidecars: list[SidecarInfo] = field(default_factory=list)
    missing_json_for: list[str] = field(default_factory=list)

    @property
    def scanner(self) -> str:
        for side in self.sidecars:
            if side.manufacturer:
                model = str(side.data.get("ManufacturersModelName") or "")
                return f"{side.manufacturer} {model}".strip()
        return "Unknown"

    @property
    def field_strength(self) -> str:
        for side in self.sidecars:
            if side.field_strength:
                return side.field_strength
        return "Unknown"

    @property
    def sequence(self) -> str:
        for side in self.sidecars:
            if side.sequence_name:
                return side.sequence_name
        return "Unknown"
