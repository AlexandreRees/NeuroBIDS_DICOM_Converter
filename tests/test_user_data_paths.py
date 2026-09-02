"""User-data root and logging must never write into the install tree."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from neuro_pipeline.config.paths import (
    default_conversion_log_path,
    default_conversion_queue_path,
    is_dir_writable,
    project_root,
    resolve_writable_log_dir,
    resource_root,
    user_config_root,
    user_data_root,
    user_log_root,
    user_queue_root,
    user_state_root,
    user_temp_root,
)
from neuro_pipeline.logging.setup import configure_logging, get_conversion_log_path
from neuro_pipeline.models.config import AppConfig


@pytest.fixture(autouse=True)
def _reset_logging_flag() -> None:
    root = logging.getLogger()
    if getattr(root, "_neuro_pipeline_configured", False):
        root.handlers.clear()
        setattr(root, "_neuro_pipeline_configured", False)
        setattr(root, "_neuro_pipeline_log_file", None)
    yield
    root = logging.getLogger()
    root.handlers.clear()
    setattr(root, "_neuro_pipeline_configured", False)
    setattr(root, "_neuro_pipeline_log_file", None)


def test_user_data_root_writable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = user_data_root()
    assert root.is_dir()
    assert is_dir_writable(root)
    assert root.name == "NeuroPipeline"


def test_user_subdirs_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert user_log_root().is_dir()
    assert user_config_root().is_dir()
    assert user_queue_root().is_dir()
    assert user_state_root().is_dir()
    assert user_temp_root().is_dir()
    assert default_conversion_queue_path().parent == user_queue_root()


def test_configure_logging_uses_user_data_not_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # Point project_root at a path that must never receive logs
    install = tmp_path / "ProgramFiles" / "NeuroPipeline"
    install.mkdir(parents=True)
    monkeypatch.setattr(
        "neuro_pipeline.config.paths.project_root",
        lambda: install,
    )
    log_file = configure_logging("")
    assert log_file.is_file()
    assert "ProgramFiles" not in str(log_file)
    assert str(user_log_root()) in str(log_file.resolve())
    assert log_file.name == "conversion.log"
    # Must not create install/logs
    assert not (install / "logs").exists()


def test_configure_logging_fallback_when_preferred_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    blocked = tmp_path / "blocked_logs"
    blocked.mkdir()
    real_is_writable = is_dir_writable

    def _fake_writable(path: Path | str) -> bool:
        p = Path(path)
        try:
            if blocked in p.parents or p == blocked:
                return False
        except Exception:  # noqa: BLE001
            pass
        return real_is_writable(p)

    monkeypatch.setattr(
        "neuro_pipeline.config.paths.is_dir_writable",
        _fake_writable,
    )
    directory = resolve_writable_log_dir(blocked)
    assert directory != blocked
    assert is_dir_writable(directory)


def test_resolved_log_dir_defaults_to_user_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config = AppConfig(log_dir="")
    resolved = config.resolved_log_dir(tmp_path / "ProgramFiles" / "NeuroPipeline")
    assert resolved == user_log_root().resolve() or resolved == user_log_root()
    assert "ProgramFiles" not in str(resolved)


def test_get_conversion_log_path_matches_configure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    configured = configure_logging("")
    via_helper = get_conversion_log_path("")
    assert via_helper == configured


def test_log_path_helpers_agree_with_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GUI LogWidget.log_path() delegates to get_conversion_log_path (same contract)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config = AppConfig(log_dir="")
    via_config = config.resolved_log_dir() / "conversion.log"
    via_helper = get_conversion_log_path(config.log_dir or None)
    configured = configure_logging(config.log_dir)
    assert via_helper == configured
    assert via_config.resolve() == configured.resolve()


def test_default_conversion_log_not_under_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    log_path = default_conversion_log_path()
    assert project_root() not in log_path.parents or "NeuroPipeline" in str(log_path)
    # Stronger: log lives under user_data_root
    assert user_data_root() in log_path.parents or log_path.parent == user_log_root()


def test_resource_root_distinct_from_user_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalApp"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    # Even when frozen flag is off, resources are not user data
    assert resource_root() != user_data_root()
