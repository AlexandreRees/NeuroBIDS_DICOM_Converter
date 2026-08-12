"""Tests for YAML configuration loading."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.config.loader import load_app_config


def test_load_app_config(app_config_file: Path) -> None:
    config = load_app_config(app_config_file)
    assert config.compression is True
    assert config.smart_naming is True
    assert config.threads == 2
    assert config.output_format == "nii.gz"


def test_missing_config_uses_defaults(tmp_path: Path) -> None:
    missing = tmp_path / "absent.yaml"
    config = load_app_config(missing)
    assert config.compression is True
    assert config.threads == 4
