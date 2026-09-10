# dcm2niix (Windows) for Classic / Main packaging

Expected local path after download (NOT committed to Git):
  tools\dcm2niix.exe

`*.exe` remains gitignored. Do not commit tools\dcm2niix.exe.

When absent, the Windows build / GitHub Actions runs:

  scripts\ensure_dcm2niix.ps1

which downloads ONLY this pinned official build:

  Tag:    v1.0.20250506
  URL:    https://github.com/rordenlab/dcm2niix/releases/download/v1.0.20250506/dcm2niix_win.zip
  SHA256: 04ebd85205380c2a78b4a77b3b032bd8d8ff8f6f7c09feaf47f246f2a9efd282
  Upstream: https://github.com/rordenlab/dcm2niix

Validation performed by the helper:
  - ZIP SHA256 verified before extract
  - file exists after extract
  - Windows PE (MZ) header
  - minimum size
  - version/output logging when possible

License notes: see third_party\licenses\README.md

The installer copies tools\dcm2niix.exe next to NeuroPipeline_DICOM_Converter.exe
so the PI does not install dcm2niix separately.
