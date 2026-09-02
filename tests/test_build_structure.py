"""Tests that Windows packaging assets and structure are present."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_windows_spec_exists() -> None:
    spec = ROOT / "build_windows.spec"
    assert spec.exists()
    text = spec.read_text(encoding="utf-8")
    assert "NeuroPipeline_DICOM_Converter" in text
    assert "PySide6" in text


def test_installer_assets_exist() -> None:
    assert (ROOT / "installer" / "setup.iss").exists()
    assert (ROOT / "installer" / "version_info.txt").exists()
    assert (ROOT / "installer" / "BUILD_WINDOWS.md").exists()
    assert (ROOT / "installer" / "NeuroPipeline.ico").exists()
    assert (ROOT / "scripts" / "build_windows.ps1").exists()
    assert (ROOT / "README_WINDOWS.md").exists()
    assert (ROOT / "docs" / "user_manual.md").exists()


def test_setup_iss_defines_desktop_shortcut() -> None:
    text = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert "NeuroPipeline_DICOM_Converter_Setup" in text
    assert "desktopicon" in text
    assert "Program Files" in text or "{autopf}" in text


def test_configs_and_templates_present() -> None:
    assert (ROOT / "configs" / "default.yaml").exists()
    assert (ROOT / "configs" / "naming_rules.yaml").exists()
    assert (ROOT / "templates").is_dir()


def test_cli_entrypoint_preserved() -> None:
    main_py = ROOT / "src" / "neuro_pipeline" / "__main__.py"
    assert main_py.exists()
    text = main_py.read_text(encoding="utf-8")
    assert "run_app" in text
