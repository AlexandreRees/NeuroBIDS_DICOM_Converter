"""PyInstaller / resource path helpers."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.utils.resources import get_app_root, get_resource_path, resolve_config


def test_get_app_root_is_repo() -> None:
    root = get_app_root()
    assert (root / "configs").is_dir() or (root / "src").is_dir()


def test_get_resource_path_configs() -> None:
    path = get_resource_path("configs/bids_entities.yaml")
    assert path.name == "bids_entities.yaml"
    assert "configs" in path.parts


def test_resolve_config_finds_bids_entities() -> None:
    path = resolve_config("bids_entities.yaml")
    assert path.exists()
    assert path.name == "bids_entities.yaml"


def test_resolve_config_finds_sequence_rules() -> None:
    path = resolve_config("sequence_rules.yaml")
    assert path.exists()


def test_resolve_config_scanners_dir() -> None:
    path = get_resource_path("configs/scanners")
    assert path.is_dir()
    assert (path / "siemens.yaml").exists() or any(path.glob("*.yaml"))
