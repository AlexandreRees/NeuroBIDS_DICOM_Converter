"""Scanner metadata models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ScannerInfo:
    """Detected MRI scanner attributes from DICOM header tags."""

    manufacturer: str = "Unknown"
    model: str = "Unknown"
    software_version: str = ""
    magnetic_field_strength: float | None = None
    detected_sequences: list[str] = field(default_factory=list)
    profile_name: str = "generic"
    confidence: str = "LOW"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def field_label(self) -> str:
        if self.magnetic_field_strength is None:
            return "—"
        val = self.magnetic_field_strength
        if abs(val - round(val)) < 1e-6:
            return f"{int(round(val))}T"
        return f"{val:g}T"
