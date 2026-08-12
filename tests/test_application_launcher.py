"""Tests for the application launcher entry points."""

from __future__ import annotations

from pathlib import Path

import neuro_pipeline
from neuro_pipeline import __main__ as main_mod
from neuro_pipeline.app import _find_app_icon, run_app


def test_version_is_release_ready() -> None:
    assert neuro_pipeline.__version__ == "1.0.0"


def test_main_module_exposes_main() -> None:
    assert callable(main_mod.main)


def test_run_app_is_callable() -> None:
    assert callable(run_app)


def test_icon_lookup_does_not_raise() -> None:
    icon = _find_app_icon()
    assert icon is None or isinstance(icon, Path)
