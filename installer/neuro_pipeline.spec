# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for NeuroPipeline DICOM Converter.

Build (from repository root)::

    pyinstaller installer/neuro_pipeline.spec --noconfirm --clean

Or run ``installer/build.bat`` on Windows.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "configs" / "default.yaml"), "configs"),
    (str(ROOT / "configs" / "naming_rules.yaml"), "configs"),
]

# Optional extra configs / templates if present
for rel in (
    Path("configs") / "sequence_plugins.yaml",
    Path("configs") / "qc_rules.yaml",
    Path("configs") / "bids_entities.yaml",
    Path("configs") / "sequence_rules.yaml",
):
    candidate = ROOT / rel
    if candidate.is_file():
        datas.append((str(candidate), str(rel.parent).replace("\\", "/")))

scanners_dir = ROOT / "configs" / "scanners"
if scanners_dir.is_dir():
    datas.append((str(scanners_dir), "configs/scanners"))

templates_dir = ROOT / "templates"
if templates_dir.is_dir():
    datas.append((str(templates_dir), "templates"))

try:
    datas += collect_data_files("pydicom")
except Exception:
    pass
try:
    datas += collect_data_files("nibabel")
except Exception:
    pass

binaries = []
# Ship dcm2niix next to the app (required for end-users — no separate install).
for dcm_rel in (
    ROOT / "tools" / "dcm2niix.exe",
    ROOT / "dcm2niix.exe",
    ROOT / "tools" / "dcm2niix",
    ROOT / "dcm2niix",
):
    if dcm_rel.is_file():
        binaries.append((str(dcm_rel), "."))
        break

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")

icon_candidates = [
    ROOT / "assets" / "NeuroPipeline.ico",
    ROOT / "assets" / "icon.ico",
    ROOT / "installer" / "NeuroPipeline.ico",
]
icon_path = next((p for p in icon_candidates if p.is_file()), None)

a = Analysis(
    [str(ROOT / "src" / "neuro_pipeline" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries + pyside_binaries,
    datas=datas + pyside_datas,
    hiddenimports=pyside_hidden + [
        "neuro_pipeline",
        "neuro_pipeline.app",
        "neuro_pipeline.gui.main_window",
        "neuro_pipeline.dicom.format_support",
        "neuro_pipeline.converter.conversion_manager",
        "neuro_pipeline.utils.resources",
        "pydicom",
        "pydicom.encoders.gdcm",
        "pydicom.encoders.pylibjpeg",
        "nibabel",
        "numpy",
        "yaml",
        "pydantic",
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
    [],
    exclude_binaries=True,
    name="NeuroPipeline",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI-only — no black console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NeuroPipeline",
)
