"""Tests for packaging verification and Windows installer alignment."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_build_windows_spec_exists() -> None:
    spec = ROOT / "build_windows.spec"
    assert spec.exists()
    text = spec.read_text(encoding="utf-8")
    assert "NeuroPipeline_DICOM_Converter" in text
    assert "PySide6" in text


def test_macos_spec_exists() -> None:
    spec = ROOT / "build_macos.spec"
    assert spec.is_file()
    text = spec.read_text(encoding="utf-8")
    assert "NeuroBIDS.app" in text
    assert "BUNDLE" in text


def test_installer_assets_exist() -> None:
    assert (ROOT / "installer" / "setup.iss").exists()
    assert (ROOT / "installer" / "neuro_pipeline.spec").exists()
    assert (ROOT / "installer" / "version_info.txt").exists()
    assert (ROOT / "installer" / "BUILD_WINDOWS.md").exists()
    assert (ROOT / "installer" / "NeuroPipeline.ico").exists()
    assert (ROOT / "scripts" / "build_windows.ps1").exists()
    assert (ROOT / "scripts" / "build_macos.sh").exists()
    assert (ROOT / "scripts" / "verify_packaging.py").exists()
    assert (ROOT / "README_WINDOWS.md").exists()
    assert (ROOT / "docs" / "user_manual.md").exists()
    assert (ROOT / "docs" / "INSTALL.md").exists()


def test_setup_iss_packages_onedir_and_uninstall() -> None:
    text = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert "NeuroPipeline_DICOM_Converter_Setup" in text
    assert "desktopicon" in text
    assert "Program Files" in text or "{autopf}" in text
    assert r"dist\NeuroPipeline\*" in text or "dist\\NeuroPipeline\\*" in text
    assert "NeuroPipeline.exe" in text
    assert "{uninstallexe}" in text
    # Must not expect the old onefile EXE name as the only payload
    assert "NeuroPipeline_DICOM_Converter.exe" not in text.split("[Files]")[1].split("[Icons]")[0]


def test_build_windows_ps1_uses_onedir_pipeline() -> None:
    text = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "neuro_pipeline.spec" in text
    assert "setup.iss" in text
    assert "verify_packaging.py" in text
    assert "NeuroPipeline_DICOM_Converter_Setup.exe" in text


def test_build_macos_refuses_non_darwin() -> None:
    text = (ROOT / "scripts" / "build_macos.sh").read_text(encoding="utf-8")
    assert "Darwin" in text
    assert "exit 2" in text
    assert "NeuroBIDS.app" in text


def test_verify_packaging_script_passes_static() -> None:
    import runpy
    import sys

    script = ROOT / "scripts" / "verify_packaging.py"
    # Execute as __main__ with no artifact requirement
    old = sys.argv[:]
    try:
        sys.argv = [str(script)]
        ns = runpy.run_path(str(script), run_name="not_main")
        assert ns["main"]([]) == 0
    finally:
        sys.argv = old


def test_configs_and_templates_present() -> None:
    assert (ROOT / "configs" / "default.yaml").exists()
    assert (ROOT / "configs" / "naming_rules.yaml").exists()
    assert (ROOT / "templates").is_dir()


def test_cli_entrypoint_preserved() -> None:
    main_py = ROOT / "src" / "neuro_pipeline" / "__main__.py"
    assert main_py.exists()
    text = main_py.read_text(encoding="utf-8")
    assert "run_app" in text


def test_install_docs_mention_no_python_no_ollama() -> None:
    text = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "python" in lower
    assert "ollama" in lower
    assert "optional" in lower
    assert "never modifies" in lower and "dicom" in lower
