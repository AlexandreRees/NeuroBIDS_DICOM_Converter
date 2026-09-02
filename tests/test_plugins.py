"""Tests for sequence plugin architecture (synthetic metadata only)."""

from __future__ import annotations

from neuro_pipeline.plugins.base import SequenceDetection
from neuro_pipeline.plugins.loader import YamlConfigPlugin, load_default_registry
from neuro_pipeline.plugins.registry import PluginRegistry
from neuro_pipeline.plugins.sequences.anatomical import AnatomicalPlugin
from neuro_pipeline.plugins.sequences.diffusion import DiffusionPlugin


def test_plugin_detection_mprage() -> None:
    registry = load_default_registry()
    hit = registry.detect_sequence({"SeriesDescription": "t1_MPRAGE_sag"})
    assert hit.datatype == "anat"
    assert hit.suffix == "T1w"
    assert hit.confidence >= 0.9
    assert "T1" in hit.display_label or "weighted" in hit.display_label.lower()


def test_plugin_detection_dwi() -> None:
    registry = load_default_registry()
    hit = registry.detect_sequence({"ProtocolName": "ep2d_diff_dir64"})
    assert hit.datatype == "dwi"
    assert hit.suffix == "dwi"
    assert hit.confidence > 0


def test_unknown_sequence_requires_manual_mapping() -> None:
    registry = PluginRegistry()
    registry.register(AnatomicalPlugin())
    hit = registry.detect_sequence({"SeriesDescription": "custom_weird_localizer_xyz"})
    assert hit.requires_manual_mapping is True
    assert hit.datatype == "unknown"
    assert hit.display_label == "Unknown sequence"


def test_user_config_priority_over_builtin() -> None:
    yaml_cfg = {
        "plugins": {
            "anat": {
                "enabled": True,
                "patterns": [
                    {
                        "name": "CustomT2",
                        "regex": ".*MPRAGE.*",
                        "label": "Configured T2 alias",
                        "bids": {"datatype": "anat", "suffix": "T2w"},
                    }
                ],
            }
        }
    }
    registry = PluginRegistry()
    registry.set_user_config_plugin(YamlConfigPlugin(yaml_cfg))
    registry.register(AnatomicalPlugin())
    hit = registry.detect_sequence({"SeriesDescription": "MPRAGE"})
    assert hit.plugin == "user_config"
    assert hit.suffix == "T2w"
    assert hit.confidence == 0.98


def test_builtin_plugin_when_no_user_match() -> None:
    registry = PluginRegistry()
    registry.set_user_config_plugin(YamlConfigPlugin({"plugins": {}}))
    registry.register(DiffusionPlugin())
    hit = registry.detect_sequence({"SeriesDescription": "DTI_30dir"})
    assert hit.datatype == "dwi"
    assert hit.plugin == "diffusion"


def test_sequence_detection_to_dict() -> None:
    det = SequenceDetection(
        datatype="anat",
        suffix="T1w",
        confidence=0.97,
        plugin="anatomical",
    )
    data = det.to_dict()
    assert data["datatype"] == "anat"
    assert data["confidence"] == 0.97
