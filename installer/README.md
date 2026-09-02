# Installer folder

Primary Windows packaging assets:

| File | Purpose |
|------|---------|
| `setup.iss` | Inno Setup → `NeuroPipeline_DICOM_Converter_Setup.exe` |
| `NeuroPipeline.ico` | EXE / installer / window icon |
| `version_info.txt` | Windows file version metadata |
| `BUILD_WINDOWS.md` | Build instructions |
| `build.bat` | Legacy helper (prefer `scripts/build_windows.ps1`) |

Recommended:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```
