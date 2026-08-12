# Building NeuroPipeline DICOM Converter for Windows

This document describes how to produce:

- `dist\NeuroPipeline_DICOM_Converter.exe` (portable, no Python required)
- `release\NeuroPipeline_DICOM_Converter_Setup.exe` (install wizard)

## Prerequisites (build machine only)

- Windows 10/11
- Python 3.11+
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`ISCC.exe` on PATH)
- Optional: `dcm2niix.exe` placed in `tools\` to ship with the installer

End users do **not** need Python.

## Automated build (recommended)

From PowerShell in the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

This will:

1. Clean previous build artifacts
2. Install dependencies
3. Run `pytest`
4. Run PyInstaller (`build_windows.spec`)
5. Compile the Inno Setup installer into `release\`

## Manual steps

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
pip install pyinstaller
pytest
pyinstaller build_windows.spec --noconfirm --clean
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\installer\setup.iss
```

## Verify before distributing

1. Copy `NeuroPipeline_DICOM_Converter_Setup.exe` to a clean Windows PC without Python.
2. Double-click the installer → complete the wizard.
3. Confirm Desktop / Start Menu shortcuts.
4. Launch the app; confirm the GUI opens.
5. Confirm `configs\` is present next to the install.
6. Place or detect `dcm2niix.exe`, convert a tiny test dataset, open the HTML report.

## Application metadata

| Field | Value |
|-------|-------|
| Name | NeuroPipeline DICOM Converter |
| Version | 1.0.0 |
| Publisher | Alexandre Rees |
| Description | Medical imaging DICOM to NIfTI converter |
| Executable | NeuroPipeline_DICOM_Converter.exe |
| Installer | NeuroPipeline_DICOM_Converter_Setup.exe |

## Notes

- Source conversion logic is unchanged by packaging.
- Source DICOM data is never modified.
- Do not bundle patient/example DICOM data in the installer.
