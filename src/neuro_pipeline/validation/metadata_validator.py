"""JSON sidecar metadata validation (warnings only)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from neuro_pipeline.validation.models import MetadataValidationResult, ValidationStatus

LOGGER = logging.getLogger(__name__)

RECOMMENDED_FIELDS = (
    "Manufacturer",
    "MagneticFieldStrength",
    "RepetitionTime",
    "EchoTime",
    "FlipAngle",
    "SeriesDescription",
)


class MetadataValidator:
    """Check recommended DICOM-derived fields in dcm2niix JSON sidecars.

    Missing fields never cause FAIL — only WARNING or PASS.
    """

    def __init__(self, output_directory: Path | str) -> None:
        self.output_directory = Path(output_directory)

    def validate_all(self) -> list[MetadataValidationResult]:
        root = self.output_directory
        if not root.exists():
            return []
        return [self.validate_one(path) for path in sorted(root.rglob("*.json"))]

    def validate_one(self, path: Path) -> MetadataValidationResult:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            # Unreadable JSON is still only a warning for this module
            return MetadataValidationResult(
                path=path,
                status=ValidationStatus.WARNING,
                message=f"Could not parse JSON sidecar: {exc}",
            )

        if not isinstance(data, dict):
            return MetadataValidationResult(
                path=path,
                status=ValidationStatus.WARNING,
                message="JSON sidecar is not an object",
            )

        present: list[str] = []
        missing: list[str] = []
        for field in RECOMMENDED_FIELDS:
            if _has_value(data, field):
                present.append(field)
            else:
                missing.append(field)

        if missing:
            return MetadataValidationResult(
                path=path,
                status=ValidationStatus.WARNING,
                message=f"Missing recommended fields: {', '.join(missing)}",
                present_fields=present,
                missing_fields=missing,
            )
        return MetadataValidationResult(
            path=path,
            status=ValidationStatus.PASS,
            message="All recommended metadata fields present",
            present_fields=present,
            missing_fields=[],
        )


def _has_value(data: dict[str, Any], key: str) -> bool:
    if key not in data:
        return False
    value = data[key]
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True
