# Third-party licenses

This application (NeuroPipeline DICOM Converter) is licensed under the MIT
License (see the repository root `LICENSE`).

Third-party components retain their own licenses and are **not** re-licensed
as MIT by this project.

## dcm2niix

`dcm2niix` is a separate conversion tool used by Classic / Main Windows
installers. The Windows binary is **not versioned in Git**; CI / local builds
download it into `tools/dcm2niix.exe` when absent.

- Upstream project: https://github.com/rordenlab/dcm2niix
- Pinned Windows CI/download source:
  - Tag: `v1.0.20250506`
  - URL: https://github.com/rordenlab/dcm2niix/releases/download/v1.0.20250506/dcm2niix_win.zip
  - SHA256: `04ebd85205380c2a78b4a77b3b032bd8d8ff8f6f7c09feaf47f246f2a9efd282`
- License: retained by the dcm2niix authors/distributors (see the upstream
  repository). **This is not MIT simply because this application uses MIT.**

Do not remove or overwrite any license notices that ship with a dcm2niix
binary distribution.

Classic / Main packaging must keep dcm2niix available to end users without a
separate manual install (copied next to the app by Inno Setup).

## Other Python / system dependencies

Runtime dependencies declared in `pyproject.toml` / `requirements.txt`
(PySide6, pydicom, nibabel, etc.) retain their own licenses as published by
their respective maintainers.

Classic / Main does **not** require Ollama or any LLM runtime.
