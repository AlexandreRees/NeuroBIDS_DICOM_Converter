"""YAML configuration loader."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from neuro_pipeline.config.paths import (
    bundled_config_candidates,
    default_config_path,
    default_naming_rules_path,
    project_root,
)
from neuro_pipeline.models.config import AppConfig

LOGGER = logging.getLogger(__name__)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return data


def find_config_file(filename: str = "default.yaml") -> Path | None:
    """Locate the first existing config file among known candidates."""
    for candidate in bundled_config_candidates(filename):
        if candidate.exists():
            return candidate
    return None


def load_app_config(path: Path | None = None) -> AppConfig:
    """Load application settings from YAML, falling back to defaults."""
    config_path = path or find_config_file("default.yaml") or default_config_path()
    data = _read_yaml(config_path) if config_path.exists() else {}
    config = AppConfig.from_mapping(data)

    if not config.naming_rules_path:
        naming = find_config_file("naming_rules.yaml") or default_naming_rules_path()
        config.naming_rules_path = str(naming)

    LOGGER.debug("Loaded config from %s", config_path)
    LOGGER.debug("Project root: %s", project_root())
    return config
