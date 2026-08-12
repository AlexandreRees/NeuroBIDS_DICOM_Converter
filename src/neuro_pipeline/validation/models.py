"""Validation status enums and result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ValidationStatus(str, Enum):
    """Outcome severity for a validation check."""

    PASS = "PASS"
    INFO = "INFO"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass(slots=True)
class ValidationResult:
    """Result of validating one NIfTI (or related) artifact."""

    path: Path
    status: ValidationStatus
    message: str
    filename: str = ""
    dimensions: tuple[int, ...] | None = None
    voxel_size: tuple[float, ...] | None = None
    datatype: str = ""
    orientation: str = ""
    affine: list[list[float]] | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.filename:
            self.filename = self.path.name


@dataclass(slots=True)
class DWIValidationResult:
    """Result of validating one diffusion series/bundle."""

    nifti_path: Path
    status: ValidationStatus
    message: str
    n_volumes: int | None = None
    n_gradients: int | None = None
    has_bval: bool = False
    has_bvec: bool = False
    has_json: bool = False
    kind: str = ""  # "dwi" | "adc" | ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MetadataValidationResult:
    """Result of validating one JSON sidecar."""

    path: Path
    status: ValidationStatus
    message: str
    present_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationSummary:
    """Aggregated validation outcomes for an output directory."""

    nifti_results: list[ValidationResult] = field(default_factory=list)
    dwi_results: list[DWIValidationResult] = field(default_factory=list)
    metadata_results: list[MetadataValidationResult] = field(default_factory=list)

    @property
    def overall_status(self) -> ValidationStatus:
        all_statuses = (
            [r.status for r in self.nifti_results]
            + [r.status for r in self.dwi_results]
            + [r.status for r in self.metadata_results]
        )
        if any(s == ValidationStatus.FAIL for s in all_statuses):
            return ValidationStatus.FAIL
        if any(s == ValidationStatus.WARNING for s in all_statuses):
            return ValidationStatus.WARNING
        # INFO is informational only and does not downgrade overall status.
        return ValidationStatus.PASS

    @property
    def passes(self) -> list[str]:
        msgs: list[str] = []
        for item in self.dwi_results:
            if item.status == ValidationStatus.PASS:
                msgs.append(f"{item.nifti_path.name}: {item.message}")
        for item in self.nifti_results:
            if item.status == ValidationStatus.PASS:
                msgs.append(f"{item.filename}: {item.message}")
        return msgs

    @property
    def infos(self) -> list[str]:
        msgs: list[str] = []
        for group in (self.nifti_results, self.dwi_results, self.metadata_results):
            for item in group:
                if item.status == ValidationStatus.INFO:
                    path = getattr(item, "path", None) or getattr(item, "nifti_path", "")
                    name = Path(path).name if path else "?"
                    msgs.append(f"{name}: {item.message}")
        return msgs

    @property
    def warnings(self) -> list[str]:
        msgs: list[str] = []
        for group in (self.nifti_results, self.dwi_results, self.metadata_results):
            for item in group:
                if item.status == ValidationStatus.WARNING:
                    path = getattr(item, "path", None) or getattr(item, "nifti_path", "")
                    msgs.append(f"{Path(path)}: {item.message}")
        return msgs

    @property
    def errors(self) -> list[str]:
        msgs: list[str] = []
        for group in (self.nifti_results, self.dwi_results, self.metadata_results):
            for item in group:
                if item.status == ValidationStatus.FAIL:
                    path = getattr(item, "path", None) or getattr(item, "nifti_path", "")
                    msgs.append(f"{path}: {item.message}")
        return msgs
