"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def naming_rules_file(tmp_path: Path) -> Path:
    path = tmp_path / "naming_rules.yaml"
    path.write_text(
        yaml.dump(
            {
                "rules": [
                    {"pattern": "mprage", "match": "contains", "name": "T1w"},
                    {"pattern": "flair", "match": "contains", "name": "FLAIR"},
                    {"pattern": "rest_ap", "match": "contains", "name": "REST_AP"},
                    {"pattern": "dwi", "match": "contains", "name": "DWI"},
                    {"pattern": "movie", "match": "contains", "name": "Movie"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def app_config_file(tmp_path: Path) -> Path:
    path = tmp_path / "default.yaml"
    path.write_text(
        yaml.dump(
            {
                "compression": True,
                "smart_naming": True,
                "threads": 2,
                "output_format": "nii.gz",
                "dcm2niix_path": "",
            }
        ),
        encoding="utf-8",
    )
    return path
