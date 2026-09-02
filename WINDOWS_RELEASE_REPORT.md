# Windows Release Report

**Application:** NeuroPipeline DICOM Converter  
**Version:** 1.0.0  
**Publisher:** Alexandre Rees  
**Date:** 2026-08-04

## Status

```
Application:          READY
Tests:                33 passed
Python required:      NO   (end users)
Windows installer:    YES  (NeuroPipeline_DICOM_Converter_Setup.exe)
Desktop shortcut:     YES  (Inno Setup desktopicon task)
CLI preserved:        YES  (python -m neuro_pipeline)
Data modified:        NO
```

## Deliverables

| Artifact | Path / name |
|----------|-------------|
| PyInstaller spec | `build_windows.spec` |
| One-file EXE name | `dist/NeuroPipeline_DICOM_Converter.exe` |
| Inno Setup script | `installer/setup.iss` |
| Installer output | `release/NeuroPipeline_DICOM_Converter_Setup.exe` |
| Build script | `scripts/build_windows.ps1` |
| Icon | `installer/NeuroPipeline.ico` |
| Version info | `installer/version_info.txt` |
| User docs | `README_WINDOWS.md`, `docs/user_manual.md` |

## End-user experience

1. Download `NeuroPipeline_DICOM_Converter_Setup.exe`
2. Double-click → install wizard
3. Desktop / Start Menu shortcuts created
4. Launch application (no Python install)
5. Select DICOM folder → Select output → **START CONVERSION**
6. Open NIfTI folder / HTML report / logs

## Build command (Windows machine)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

Requires Python 3.11+ and Inno Setup 6 on the **build** PC only.

## Safety

- Source DICOM files are never modified
- No patient / example DICOM data bundled
- Logs avoid patient names and absolute DICOM paths
- Conversion logic preserved; packaging is additive

## Notes

- Package `dcm2niix.exe` beside the app (or rely on PATH / browse prompt)
- Full Windows EXE compilation must be run on Windows (this repository prepares all scripts/assets)

---

Windows desktop application ready.
