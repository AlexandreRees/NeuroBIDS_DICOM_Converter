"""Sequence plugin package."""

from neuro_pipeline.plugins.base import SequenceDetection, SequencePlugin
from neuro_pipeline.plugins.loader import load_default_registry
from neuro_pipeline.plugins.registry import PluginRegistry, get_default_registry

__all__ = [
    "SequenceDetection",
    "SequencePlugin",
    "PluginRegistry",
    "get_default_registry",
    "load_default_registry",
]
