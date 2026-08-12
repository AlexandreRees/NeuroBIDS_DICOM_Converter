"""Abstract sequence plugin interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class SequenceDetection:
    """Result of sequence plugin detection."""

    datatype: str = "unknown"
    suffix: str = "unknown"
    confidence: float = 0.0
    label: str = ""
    plugin: str = ""
    pattern_name: str = ""
    requires_manual_mapping: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def display_label(self) -> str:
        if self.requires_manual_mapping or self.datatype == "unknown":
            return "Unknown sequence"
        if self.label:
            return self.label
        return f"{self.suffix} ({self.datatype})"


class SequencePlugin(ABC):
    """Pluggable sequence detector (no hard-coded study protocols)."""

    name: str = "base"
    priority: int = 100

    @abstractmethod
    def detect(self, metadata: Mapping[str, Any]) -> SequenceDetection | None:
        """Return a detection when this plugin matches, else None."""

    def _blob(self, metadata: Mapping[str, Any]) -> str:
        parts = [
            str(metadata.get("SeriesDescription", "") or ""),
            str(metadata.get("ProtocolName", "") or ""),
            str(metadata.get("SequenceName", "") or ""),
            str(metadata.get("series_description", "") or ""),
            str(metadata.get("protocol_name", "") or ""),
            str(metadata.get("sequence_name", "") or ""),
            " ".join(str(x) for x in (metadata.get("ImageType") or [])),
        ]
        return " ".join(parts)
