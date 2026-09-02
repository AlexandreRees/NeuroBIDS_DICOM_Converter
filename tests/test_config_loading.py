"""Config loading tests for Windows defaults."""

from __future__ import annotations

from pathlib import Path

import yaml

from neuro_pipeline.config.loader import load_app_config
from neuro_pipeline.converter import Converter
from neuro_pipeline.models.config import AppConfig


def test_default_yaml_uses_auto_dcm2niix() -> None:
    root = Path(__file__).resolve().parents[1]
    cfg_path = root / "configs" / "default.yaml"
    assert cfg_path.exists()
    config = load_app_config(cfg_path)
    assert config.uses_auto_dcm2niix
    assert config.compression is True
    assert config.output_format == "nii.gz"
    assert config.validate_output is True
    assert config.logging_enabled is True


def test_nested_logging_block(tmp_path: Path) -> None:
    path = tmp_path / "default.yaml"
    path.write_text(
        yaml.dump(
            {
                "dcm2niix_path": "auto",
                "compression": True,
                "logging": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    config = load_app_config(path)
    assert isinstance(config, AppConfig)
    assert config.logging_enabled is False
    assert config.uses_auto_dcm2niix


def test_converter_accessible() -> None:
    converter = Converter(dcm2niix_path="auto")
    assert converter is not None
    assert hasattr(converter, "verify")
    assert hasattr(converter, "convert_series")
