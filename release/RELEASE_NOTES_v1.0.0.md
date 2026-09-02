# NeuroBIDS Copilot V1

Public packaging of the NeuroBIDS Copilot on top of the NeuroPipeline DICOM→BIDS converter.

## Highlights

- Typed-tool Copilot with ChangeSet Apply/Reject (never auto-applies)
- Stale-plan and conversion-busy Apply guards
- Privacy-safe provenance logging (schema v1, exportable JSON)
- Deterministic Copilot benchmark: **144/144** FakeLLM evaluations passed
- UI Preview/Demo mode without real DICOM or API keys
- Synthetic example dataset under `examples/synthetic_dataset/`

## Safety

- Source DICOM remains read-only
- No patient DICOM / PHI bundled
- LLM API keys via environment only
- Optional local Ollama (`NEUROBIDS_LLM_PROVIDER=local`)

## Install

See `docs/INSTALL.md` and `docs/CONFIGURATION.md`.

### Windows

Download `NeuroPipeline_DICOM_Converter_Setup.exe` (built on Windows via `scripts/build_windows.ps1`).

### macOS

Developer install, or build with `scripts/build_macos.sh` on macOS.

### Demo

```bash
python -m neuro_pipeline.gui.preview
```

## Benchmark

Deterministic report: `release/COPILOT_BENCHMARK_REPORT.md`

Optional live LLM benchmark is **not** a release gate:

```bash
python -m neuro_pipeline.neurobids.copilot.benchmark --live
```

## Changelog

See `CHANGELOG.md` (v1.0.0 Copilot notes).
