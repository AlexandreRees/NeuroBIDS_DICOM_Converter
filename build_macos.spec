# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for NeuroBIDS.app (macOS).

Build on macOS only::

    pyinstaller build_macos.spec --noconfirm --clean

Output::

    dist/NeuroBIDS.app
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "configs" / "default.yaml"), "configs"),
    (str(ROOT / "configs" / "naming_rules.yaml"), "configs"),
]
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
for dcm_rel in (
    ROOT / "tools" / "dcm2niix",
    ROOT / "dcm2niix",
    ROOT / "tools" / "dcm2niix.exe",
):
    if dcm_rel.is_file():
        binaries.append((str(dcm_rel), "."))
        break

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")

icon_candidates = [
    ROOT / "assets" / "NeuroPipeline.icns",
    ROOT / "assets" / "icon.icns",
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
        "nibabel",
        "numpy",
        "yaml",
        "pydantic",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "IPython"],
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
    name="NeuroBIDS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
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
    upx=False,
    upx_exclude=[],
    name="NeuroBIDS",
)

app = BUNDLE(
    coll,
    name="NeuroBIDS.app",
    icon=str(icon_path) if icon_path else None,
    bundle_identifier="com.alexandrerees.neurobids",
    info_plist={
        "CFBundleName": "NeuroBIDS",
        "CFBundleDisplayName": "NeuroBIDS",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
    },
)
