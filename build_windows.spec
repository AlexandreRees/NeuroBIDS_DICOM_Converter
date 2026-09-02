# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for NeuroPipeline DICOM Converter (Windows).

Build from the repository root::

    pyinstaller build_windows.spec --noconfirm --clean

Output::

    dist/NeuroPipeline_DICOM_Converter.exe
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "configs"), "configs"),
    (str(ROOT / "installer" / "NeuroPipeline.ico"), "installer"),
    (str(ROOT / "assets" / "NeuroPipeline.ico"), "assets"),
    (str(ROOT / "templates"), "templates") if (ROOT / "templates").exists() else None,
    (str(ROOT / "docs" / "user_manual.md"), "docs") if (ROOT / "docs" / "user_manual.md").exists() else None,
    (str(ROOT / "README_WINDOWS.md"), ".") if (ROOT / "README_WINDOWS.md").exists() else None,
]
datas = [d for d in datas if d is not None]

# Optional sidecar binary next to the built application (onedir helper)
dcm2niix_candidates = [
    ROOT / "dcm2niix.exe",
    ROOT / "bin" / "dcm2niix.exe",
    ROOT / "tools" / "dcm2niix.exe",
]
binaries = []
for cand in dcm2niix_candidates:
    if cand.exists():
        binaries.append((str(cand), "."))
        break

datas += collect_data_files("nibabel")
datas += collect_data_files("pydicom")

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")

a = Analysis(
    [str(ROOT / "src" / "neuro_pipeline" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries + pyside_binaries,
    datas=datas + pyside_datas,
    hiddenimports=pyside_hidden
    + [
        "neuro_pipeline",
        "neuro_pipeline.app",
        "neuro_pipeline.gui.main_window",
        "neuro_pipeline.converter.conversion_manager",
        "neuro_pipeline.validation.nifti_validator",
        "neuro_pipeline.validation.dwi_validator",
        "neuro_pipeline.utils.resources",
        "yaml",
        "pydicom",
        "nibabel",
        "numpy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="NeuroPipeline_DICOM_Converter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "installer" / "NeuroPipeline.ico"),
    version=str(ROOT / "installer" / "version_info.txt"),
)
