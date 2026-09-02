"""Sequence plugin registry with configurable priority."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from neuro_pipeline.plugins.base import SequenceDetection, SequencePlugin

LOGGER = logging.getLogger(__name__)


class PluginRegistry:
    """Register plugins and resolve the best sequence classification."""

    def __init__(self) -> None:
        self._plugins: list[SequencePlugin] = []
        self._user_plugin: SequencePlugin | None = None

    def register(self, plugin: SequencePlugin) -> None:
        self._plugins.append(plugin)
        self._plugins.sort(key=lambda p: getattr(p, "priority", 100))

    def register_many(self, plugins: Iterable[SequencePlugin]) -> None:
        for plugin in plugins:
            self.register(plugin)

    def set_user_config_plugin(self, plugin: SequencePlugin | None) -> None:
        """Priority-1 user YAML configuration plugin."""
        self._user_plugin = plugin

    def clear(self) -> None:
        self._plugins.clear()
        self._user_plugin = None

    def detect_sequence(self, metadata: Mapping[str, Any]) -> SequenceDetection:
        """Detect sequence with priority: user config → plugins → unknown."""
        # 1. User configuration
        if self._user_plugin is not None:
            hit = self._user_plugin.detect(metadata)
            if hit is not None and hit.confidence > 0:
                return hit

        # 2. Plugin rules (ordered by priority)
        best: SequenceDetection | None = None
        for plugin in self._plugins:
            try:
                hit = plugin.detect(metadata)
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("Plugin %s failed: %s", getattr(plugin, "name", "?"), exc)
                continue
            if hit is None:
                continue
            if best is None or hit.confidence > best.confidence:
                best = hit
                if hit.confidence >= 0.95:
                    break
        if best is not None and best.confidence > 0:
            return best

        # 3. Generic fallback (unknown / manual mapping)
        return SequenceDetection(
            datatype="unknown",
            suffix="unknown",
            confidence=0.0,
            label="Unknown sequence",
            plugin="fallback",
            requires_manual_mapping=True,
        )


_DEFAULT_REGISTRY: PluginRegistry | None = None


def get_default_registry() -> PluginRegistry:
    """Lazy singleton registry with built-in plugins + YAML user config."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        from neuro_pipeline.plugins.loader import load_default_registry

        _DEFAULT_REGISTRY = load_default_registry()
    return _DEFAULT_REGISTRY
