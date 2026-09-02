"""Configurable QC rule loading."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from neuro_pipeline.config.paths import project_root, resource_root

LOGGER = logging.getLogger(__name__)

DEFAULT_RULES: dict[str, Any] = {
    "anat": {"require_json": True},
    "dwi": {"require_bvec": True, "require_bval": True, "require_json": True, "require_4d": True},
    "func": {"require_json": True, "require_4d": True},
    "fmap": {"require_json": True},
    "global": {"fail_on_empty": True, "fail_on_corrupt": True, "warn_on_duplicate": True},
}


def qc_rules_path() -> Path:
    candidates = [
        project_root() / "configs" / "qc_rules.yaml",
        resource_root() / "configs" / "qc_rules.yaml",
        Path.cwd() / "configs" / "qc_rules.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def load_qc_rules(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or qc_rules_path()
    rules = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULT_RULES.items()}
    if not cfg_path.is_file():
        return rules
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed to load QC rules: %s", exc)
        return rules
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(rules.get(key), dict):
                rules[key].update(value)
            else:
                rules[key] = value
    return rules
