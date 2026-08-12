# Windows install / build notes

## Requirements

- Windows 10/11
- Python 3.11+ on `PATH`
- [dcm2niix](https://github.com/rordenlab/dcm2niix/releases) on `PATH` (or bundled next to the exe)
- Optional: Inno Setup for installer packaging (`installer/`)

## Developer build

From the repository root:

```powershell
pwsh -File deployment/windows/build.ps1
```

The script:

1. Verifies Python
2. Installs dependencies (`pip install -e ".[dev]"`)
3. Checks `dcm2niix`
4. Runs `pytest`
5. Builds with PyInstaller

## End-user installer

See also:

- `README_WINDOWS.md`
- `installer/BUILD_WINDOWS.md`
- `installer/setup.iss` / `installer/NeuroPipeline.iss`

## Runtime

No hardcoded study paths. Users choose DICOM input and NIfTI/BIDS output folders in the GUI.
