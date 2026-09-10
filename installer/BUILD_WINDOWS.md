# Building NeuroPipeline DICOM Converter for Windows

**Product line:** NeuroBIDS DICOM Converter — Classic / Main
**Not this product line:** Copilot development branch / `neurobids-copilot-v1.0.0`
**Copilot:** NO · **Ollama:** NOT REQUIRED · **Version:** 1.0.0 (Classic/Main)

This document describes how to produce:

- `dist\NeuroPipeline_DICOM_Converter.exe` (portable, no Python required)
- `release\NeuroPipeline_DICOM_Converter_Setup.exe` (install wizard)

## Prerequisites (build machine only)

- Windows 10/11
- Python 3.11+
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`ISCC.exe`)
- `tools\dcm2niix.exe` **or** allow `scripts\ensure_dcm2niix.ps1` to download the pinned Windows build (ZIP is SHA256-verified; the `.exe` is **not** committed to Git)

Pinned dcm2niix source:

- Tag: `v1.0.20250506`
- URL: https://github.com/rordenlab/dcm2niix/releases/download/v1.0.20250506/dcm2niix_win.zip
- SHA256: `04ebd85205380c2a78b4a77b3b032bd8d8ff8f6f7c09feaf47f246f2a9efd282`
End users do **not** need Python, Git, dcm2niix (separate), or Ollama.

## GitHub Actions (recommended for PI distribution)

On branch **`main`** only, workflow:

`.github/workflows/build-windows-installer.yml`

Produces a downloadable Actions **artifact** named:

`NeuroPipeline_DICOM_Converter_Setup`

containing:

`NeuroPipeline_DICOM_Converter_Setup.exe`

The workflow does **not** create tags or GitHub Releases.

### Trigger

1. Merge packaging PR into **`main`**
2. Open the repository on GitHub → **Actions**
3. Select **Build Windows Installer (Classic / Main)**
4. Click **Run workflow** (branch **`main`**)
5. After success → open the run → **Artifacts** → download
6. Extract and send `NeuroPipeline_DICOM_Converter_Setup.exe` to your PI

## Automated local build

From PowerShell in the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

This will:

1. Print Classic/Main identity + refuse Copilot refs
2. Clean previous `build/` / `dist/` / old release binaries
3. Install dependencies
4. Run `pytest`
5. Ensure/validate `tools\dcm2niix.exe` (download if absent; SHA256 + PE + version)
6. Run PyInstaller (`build_windows.spec`)
7. Compile Inno Setup (`installer\setup.iss`)
8. Verify packaging (`scripts\verify_windows_package.ps1`)

## Manual steps

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File .\scripts\ensure_dcm2niix.ps1
pytest
pyinstaller build_windows.spec --noconfirm --clean
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\installer\setup.iss
powershell -ExecutionPolicy Bypass -File .\scripts\verify_windows_package.ps1
```

## Verify before distributing to your PI

1. Copy `NeuroPipeline_DICOM_Converter_Setup.exe` to a clean Windows PC without Python.
2. Double-click the installer → complete the wizard.
3. Confirm Desktop / Start Menu shortcuts.
4. Launch the app; confirm navigation: Convert · Queue · Settings · Logs.
5. Confirm `dcm2niix.exe` is present next to the installed EXE.
6. Convert a tiny test dataset; confirm original DICOM files are untouched.
7. Confirm Copilot/Ollama are not required.

## Application metadata

| Field | Value |
|-------|-------|
| Product line | Classic / Main |
| Name | NeuroPipeline DICOM Converter |
| Version | 1.0.0 |
| Publisher | Alexandre Rees |
| Executable | NeuroPipeline_DICOM_Converter.exe |
| Installer | NeuroPipeline_DICOM_Converter_Setup.exe |
| Copilot | NO |

## Notes

- Source conversion logic is unchanged by packaging.
- Source DICOM data is never modified.
- Do not bundle patient/example DICOM data in the installer.
- Do not build this installer from `neurobids-copilot-v1.0.0`.
- CI GUI smoke is informational on headless runners; file checks remain mandatory.
- Real desktop install/conversion must still be tested manually before PI delivery.
