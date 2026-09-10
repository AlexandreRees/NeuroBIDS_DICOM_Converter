# Third-party licenses

This application (NeuroPipeline DICOM Converter) is licensed under the MIT
License (see the repository root `LICENSE`).

Third-party components retain their own licenses and are **not** re-licensed
as MIT by this project.

## dcm2niix

`dcm2niix` is a separate conversion tool used by this application (typically
provided as `tools/dcm2niix.exe` for Windows builds, or found on `PATH`).

- Upstream project: https://github.com/rordenlab/dcm2niix
- License: retained by the dcm2niix authors/distributors (see the upstream
  repository). **This is not MIT simply because this application uses MIT.**

Do not remove or overwrite any license notices that ship with a dcm2niix
binary distribution.

## Other Python / system dependencies

Runtime dependencies declared in `pyproject.toml` / `requirements.txt`
(PySide6, pydicom, nibabel, etc.) retain their own licenses as published by
their respective maintainers.
