# Changelog

## v1.0.0

Added:

- Windows desktop packaging (`build_windows.spec`, Inno Setup `setup.iss`)
- Automated PowerShell build (`scripts/build_windows.ps1`)
- Application icon + Windows version metadata
- End-user docs (`README_WINDOWS.md`, `docs/user_manual.md`)
- Auto `dcm2niix` discovery (bundled → PATH → user prompt)
- GUI UX: START CONVERSION, Validate output, Open NIfTI/report/logs
- PHI-safe conversion logging

## v0.2.0

Added:

- NIfTI validation
- DWI validation
- HTML reports
- sequence classification
- improved GUI

## v0.1.0

Initial application:

- DICOM scan
- dcm2niix wrapper
- PySide6 GUI + worker threads
- YAML configuration and smart naming
