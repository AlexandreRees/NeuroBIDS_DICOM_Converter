"""Tests for filesystem helpers and converter command building."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.converter import Converter
from neuro_pipeline.models import ConversionOptions
from neuro_pipeline.utils.exceptions import Dcm2niixNotFoundError, EmptyFolderError
from neuro_pipeline.utils.filesystem import assert_non_empty_folder, sanitize_filename


def test_sanitize_filename() -> None:
    assert sanitize_filename("a b/c:d") == "a_b_c_d"
    assert sanitize_filename("   ") == "unnamed"


def test_empty_folder_detected(tmp_path: Path) -> None:
    with pytest.raises(EmptyFolderError):
        assert_non_empty_folder(tmp_path)


def test_converter_verify_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit missing path must raise — even if a project/bundled binary exists."""
    monkeypatch.setattr("shutil.which", lambda _: None)

    fake_project = tmp_path / "project"
    (fake_project / "tools").mkdir(parents=True)
    bundled = fake_project / "tools" / "dcm2niix.exe"
    bundled.write_bytes(b"MZ")

    from neuro_pipeline.config import paths as path_mod

    monkeypatch.setattr(path_mod, "project_root", lambda: fake_project)
    monkeypatch.setattr(path_mod, "resource_root", lambda: fake_project)

    converter = Converter(dcm2niix_path=str(tmp_path / "missing_dcm2niix"))
    with pytest.raises(Dcm2niixNotFoundError):
        converter.verify()


def test_converter_verify_auto_finds_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    tools = tmp_path / "tools"
    tools.mkdir()
    fake = tools / "dcm2niix.exe"
    fake.write_bytes(b"MZ")

    from neuro_pipeline.config import paths as path_mod

    monkeypatch.setattr(path_mod, "project_root", lambda: tmp_path)
    monkeypatch.setattr(path_mod, "resource_root", lambda: tmp_path)
    monkeypatch.setattr(path_mod, "is_frozen", lambda: False)

    resolved = Converter(dcm2niix_path="auto").verify()
    assert resolved == fake.resolve()


def test_build_command_uses_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "dcm2niix"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)

    converter = Converter(dcm2niix_path=str(fake))
    options = ConversionOptions(compress=True, preserve_json=True, smart_naming=False)
    cmd = converter.build_command(
        input_dir=tmp_path / "in",
        output_dir=tmp_path / "out",
        options=options,
        filename_pattern="%p_%s",
    )
    assert cmd[0] == str(fake.resolve())
    assert "-z" in cmd and "y" in cmd
    assert "-b" in cmd and "y" in cmd
