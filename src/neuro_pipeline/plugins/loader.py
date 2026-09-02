"""Load YAML-configured and built-in sequence plugins."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from neuro_pipeline.config.paths import project_root, resource_root
from neuro_pipeline.plugins.base import SequenceDetection, SequencePlugin
from neuro_pipeline.plugins.registry import PluginRegistry
from neuro_pipeline.plugins.sequences.anatomical import AnatomicalPlugin
from neuro_pipeline.plugins.sequences.diffusion import DiffusionPlugin
from neuro_pipeline.plugins.sequences.fieldmaps import FieldmapPlugin
from neuro_pipeline.plugins.sequences.functional import FunctionalPlugin

LOGGER = logging.getLogger(__name__)


class YamlConfigPlugin(SequencePlugin):
    """Priority-1 detector driven by ``configs/sequence_plugins.yaml``."""

    name = "user_config"
    priority = 0

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config or {})
        self._compiled: list[tuple[str, re.Pattern[str], dict[str, str], str]] = []
        plugins = self.config.get("plugins") or {}
        for group_name, group in plugins.items():
            if not isinstance(group, dict):
                continue
            if group.get("enabled", True) is False:
                continue
            for pattern in group.get("patterns") or []:
                if not isinstance(pattern, dict):
                    continue
                regex = str(pattern.get("regex") or "").strip()
                if not regex:
                    continue
                bids = pattern.get("bids") or {}
                try:
                    compiled = re.compile(regex, re.I)
                except re.error as exc:
                    LOGGER.warning("Invalid sequence plugin regex %r: %s", regex, exc)
                    continue
                self._compiled.append(
                    (
                        str(pattern.get("name") or group_name),
                        compiled,
                        {
                            "datatype": str(bids.get("datatype") or group_name),
                            "suffix": str(bids.get("suffix") or "unknown"),
                        },
                        str(pattern.get("label") or pattern.get("name") or ""),
                    )
                )

    def detect(self, metadata: Mapping[str, Any]) -> SequenceDetection | None:
        blob = self._blob(metadata)
        for name, regex, bids, label in self._compiled:
            if regex.search(blob):
                return SequenceDetection(
                    datatype=bids["datatype"],
                    suffix=bids["suffix"],
                    confidence=0.98,
                    label=label or f"{bids['suffix']} MRI",
                    plugin=self.name,
                    pattern_name=name,
                )
        return None


def sequence_plugins_config_path() -> Path:
    candidates = [
        project_root() / "configs" / "sequence_plugins.yaml",
        resource_root() / "configs" / "sequence_plugins.yaml",
        Path.cwd() / "configs" / "sequence_plugins.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def load_yaml_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or sequence_plugins_config_path()
    if not cfg_path.is_file():
        return {}
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed to load sequence plugin config: %s", exc)
        return {}


def load_default_registry(config_path: Path | None = None) -> PluginRegistry:
    registry = PluginRegistry()
    cfg = load_yaml_config(config_path)
    registry.set_user_config_plugin(YamlConfigPlugin(cfg))
    registry.register_many(
        [
            AnatomicalPlugin(),
            DiffusionPlugin(),
            FunctionalPlugin(),
            FieldmapPlugin(),
        ]
    )
    return registry
