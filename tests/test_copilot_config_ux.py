"""Copilot configuration UX + connection probe tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig
from neuro_pipeline.neurobids.copilot.llm.connection import (
    ConnectionProbeResult,
    probe_llm_connection,
)


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch: pytest.MonkeyPatch):
    for key in list(os.environ):
        if key.startswith("NEUROBIDS_LLM_"):
            monkeypatch.delenv(key, raising=False)
    yield


def test_default_provider_is_none() -> None:
    cfg = LLMConfig.from_env()
    assert cfg.provider == "none"
    assert cfg.is_configured is False


def test_apply_to_environ_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LLMConfig(provider="local", model="qwen3:30b", base_url="http://127.0.0.1:11434/v1")
    cfg.apply_to_environ(include_api_key=True)
    loaded = LLMConfig.from_env()
    assert loaded.provider == "local"
    assert loaded.model == "qwen3:30b"
    assert "11434" in loaded.base_url


def test_probe_none_is_invalid_configuration() -> None:
    result = probe_llm_connection(LLMConfig(provider="none"))
    assert result.status == "invalid_configuration"
    assert "not configured" in result.message.lower() or "disabled" in result.message.lower() or "AI" in result.message


def test_probe_remote_missing_key() -> None:
    result = probe_llm_connection(LLMConfig(provider="openai", model="gpt-4o-mini", api_key=""))
    assert result.status == "invalid_configuration"
    assert "api key" in result.message.lower()


def test_probe_local_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_req, timeout=0):  # noqa: ANN001
        import urllib.error

        raise urllib.error.URLError("Connection refused")

    result = probe_llm_connection(
        LLMConfig(provider="local", model="qwen3:30b", base_url="http://127.0.0.1:9/v1"),
        urlopen=boom,
    )
    assert result.status == "provider_unavailable"
    assert "ollama" in result.message.lower() or "unavailable" in result.message.lower()


def test_probe_connected_lists_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def read(self) -> bytes:
            return b'{"data":[{"id":"gpt-4o-mini"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def ok(_req, timeout=0):  # noqa: ANN001
        return _Resp()

    result = probe_llm_connection(
        LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-test",
            base_url="https://example.invalid/v1",
        ),
        urlopen=ok,
    )
    assert result.status == "connected"
    assert result.ok


def test_probe_model_unavailable() -> None:
    class _Resp:
        def read(self) -> bytes:
            return b'{"data":[{"id":"other-model"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def ok(_req, timeout=0):  # noqa: ANN001
        return _Resp()

    result = probe_llm_connection(
        LLMConfig(
            provider="openai",
            model="missing-model",
            api_key="sk-test",
            base_url="https://example.invalid/v1",
        ),
        urlopen=ok,
    )
    assert result.status == "model_unavailable"


def test_friendly_provider_unavailable_message() -> None:
    from neuro_pipeline.gui.copilot_controller import friendly_copilot_error

    msg = friendly_copilot_error("provider_unavailable")
    assert "works without" in msg.lower() or "not configured" in msg.lower()
    assert "traceback" not in msg.lower()


try:
    from PySide6.QtWidgets import QApplication
except Exception as exc:  # noqa: BLE001
    QApplication = None  # type: ignore
    _QT_SKIP = str(exc)
else:
    _QT_SKIP = ""


@pytest.fixture
def qapp():
    if QApplication is None:
        pytest.skip(f"PySide6 unusable: {_QT_SKIP}")
    app = QApplication.instance()
    if app is None:
        app = QApplication(["neurobids-config-ux-tests"])
    return app


@pytest.mark.skipif(QApplication is None, reason=f"PySide6 unusable: {_QT_SKIP}")
def test_settings_copilot_disabled_state(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    from neuro_pipeline.gui.settings_widget import SettingsWidget
    from neuro_pipeline.models.config import AppConfig

    monkeypatch.setenv("NEUROBIDS_LLM_PROVIDER", "none")
    w = SettingsWidget(AppConfig())
    assert w.radio_llm_none.isChecked()
    assert "optional" in w.llm_privacy.text().lower() or "without" in w.llm_privacy.text().lower()
    cfg = w.build_llm_config()
    assert cfg.provider == "none"
    # Sync test connection path
    w._test_connection()
    assert "invalid" in w.llm_status.text().lower() or "not configured" in w.llm_status.text().lower()


@pytest.mark.skipif(QApplication is None, reason=f"PySide6 unusable: {_QT_SKIP}")
def test_copilot_panel_empty_state_when_none(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    from neuro_pipeline.gui.neurobids_copilot_panel import NeuroBIDSCopilotPanel

    monkeypatch.setenv("NEUROBIDS_LLM_PROVIDER", "none")
    panel = NeuroBIDSCopilotPanel()
    panel.controller.reload_config_from_env()
    panel._refresh_availability()
    # Parent may not be shown in offscreen tests — use isHidden(), not isVisible().
    assert not panel.unavailable_box.isHidden()
    assert "not configured" in panel._unavail_title.text().lower()


@pytest.mark.skipif(QApplication is None, reason=f"PySide6 unusable: {_QT_SKIP}")
def test_controller_test_connection_sync(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    from neuro_pipeline.gui.copilot_controller import CopilotController

    monkeypatch.setenv("NEUROBIDS_LLM_PROVIDER", "none")
    ctrl = CopilotController()
    ctrl.reload_config_from_env()
    seen: list[ConnectionProbeResult] = []
    ctrl.connection_test_finished.connect(lambda r: seen.append(r))
    assert ctrl.test_connection(sync=True) is True
    assert seen and seen[0].status == "invalid_configuration"
