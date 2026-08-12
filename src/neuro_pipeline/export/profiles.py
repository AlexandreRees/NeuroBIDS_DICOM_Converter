"""Export profile definitions (research BIDS / clinical / archive)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExportProfileId(str, Enum):
    BIDS = "bids"
    CLINICAL = "clinical"
    ARCHIVE = "archive"


@dataclass(frozen=True, slots=True)
class ExportProfile:
    """Descriptor for a packaging profile."""

    id: ExportProfileId
    label: str
    description: str


PROFILES: dict[str, ExportProfile] = {
    "bids": ExportProfile(
        id=ExportProfileId.BIDS,
        label="Research BIDS",
        description="BIDS dataset scaffolding for universities / OpenNeuro",
    ),
    "clinical": ExportProfile(
        id=ExportProfileId.CLINICAL,
        label="Clinical",
        description="Hospital-oriented NIfTI layout with minimal metadata (no PHI)",
    ),
    "archive": ExportProfile(
        id=ExportProfileId.ARCHIVE,
        label="Archive",
        description="Long-term archive: NIfTI + JSON + logs + checksums",
    ),
}


def get_profile(name: str) -> ExportProfile:
    key = (name or "").strip().lower()
    if key not in PROFILES:
        raise ValueError(
            f"Unknown export profile '{name}'. Choose: {', '.join(sorted(PROFILES))}"
        )
    return PROFILES[key]
