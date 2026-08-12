"""Provenance data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SoftwareInfo:
    name: str = "NeuroPipeline"
    version: str = "1.0"


@dataclass(slots=True)
class ConversionInfo:
    date: str = ""
    dcm2niix_version: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PathHash:
    path: str = ""
    hash: str = ""


@dataclass(slots=True)
class ConversionProvenance:
    software: SoftwareInfo = field(default_factory=SoftwareInfo)
    conversion: ConversionInfo = field(default_factory=ConversionInfo)
    input: PathHash = field(default_factory=PathHash)
    output: PathHash = field(default_factory=PathHash)
    files: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
