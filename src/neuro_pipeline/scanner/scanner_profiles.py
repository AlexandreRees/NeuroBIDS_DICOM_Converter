"""Load vendor-specific scanner YAML profiles."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from neuro_pipeline.utils.resources import get_resource_path

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ScannerProfile:
    """Configurable sequence-pattern profile for one manufacturer family."""

    name: str
    manufacturer_keys: list[str] = field(default_factory=list)
    sequence_patterns: dict[str, list[str]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def match_sequence(self, text: str) -> str | None:
        """Return the first sequence category matched by configurable patterns."""
        blob = (text or "").lower()
        for category, patterns in self.sequence_patterns.items():
            for pattern in patterns:
                if pattern and pattern.lower() in blob:
                    return category
        return None


def scanner_config_dir() -> Path:
    candidates = [
        get_resource_path("configs/scanners"),
        Path.cwd() / "configs" / "scanners",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def load_profile(path: Path) -> ScannerProfile:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    manufacturer = data.get("manufacturer", path.stem)
    if isinstance(manufacturer, str):
        keys = [manufacturer]
    elif isinstance(manufacturer, list):
        keys = [str(x) for x in manufacturer]
    else:
        keys = [path.stem]
    patterns = data.get("sequence_patterns") or {}
    normalized = {
        str(cat): [str(p) for p in (pats or [])]
        for cat, pats in patterns.items()
    }
    return ScannerProfile(
        name=path.stem.lower(),
        manufacturer_keys=keys,
        sequence_patterns=normalized,
        raw=data,
    )


def load_all_profiles(directory: Path | None = None) -> dict[str, ScannerProfile]:
    root = directory or scanner_config_dir()
    profiles: dict[str, ScannerProfile] = {}
    if not root.is_dir():
        LOGGER.warning("Scanner profile directory missing: %s", root)
        return profiles
    for path in sorted(root.glob("*.yaml")):
        try:
            profile = load_profile(path)
            profiles[profile.name] = profile
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to load scanner profile %s: %s", path, exc)
    return profiles


def select_profile_for_manufacturer(
    manufacturer: str,
    profiles: dict[str, ScannerProfile] | None = None,
) -> ScannerProfile:
    profiles = profiles if profiles is not None else load_all_profiles()
    manuf = (manufacturer or "").lower()
    for name, profile in profiles.items():
        if name == "generic":
            continue
        for key in profile.manufacturer_keys:
            if key.lower() in manuf or manuf in key.lower():
                return profile
    return profiles.get("generic") or ScannerProfile(name="generic")
