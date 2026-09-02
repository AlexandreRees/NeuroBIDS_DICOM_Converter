# Changelog

## v1.0.0 — NeuroBIDS Copilot V1

Added:

- NeuroBIDS Copilot (typed tools → ChangeSet Apply/Reject; never auto-applies)
- Stale-plan and conversion-busy Apply protection
- Privacy-safe Copilot provenance logging (schema v1, JSONL + export)
- OpenAI-compatible LLM provider including local/Ollama
- Deterministic Copilot benchmark suite + optional `--live` evaluation
- UI Preview/Demo mode (`python -m neuro_pipeline.gui.preview`)
- Synthetic example dataset (`examples/synthetic_dataset/`)
- Windows desktop packaging (`build_windows.spec`, Inno Setup `setup.iss`)
- macOS build helper (`scripts/build_macos.sh`)
- Docs: Install, Configuration, Copilot, workflow guide
- Automated PowerShell Windows build (`scripts/build_windows.ps1`)
- Application icon + Windows version metadata
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
