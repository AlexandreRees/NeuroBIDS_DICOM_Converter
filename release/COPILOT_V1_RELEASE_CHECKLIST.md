# NeuroBIDS Copilot V1 — Release Checklist

**Version:** 1.0.0 (Copilot V1 public packaging)  
**Date:** 2026-09-02  
**Host used for verification:** Linux (HPC). Windows/macOS binaries must be built on native OS machines.

## Verification results

| Gate | Result |
|------|--------|
| Full pytest | **357 passed**, 8 skipped |
| Deterministic Copilot benchmark (`--no-level3`) | **144/144 passed** (100%) |
| Safety / no-auto-apply | **100%** compliance; automatic mutation rate **0%** |
| Provenance tests | **3 passed** |
| Privacy audit | Run `python scripts/privacy_audit.py` before publish |
| Real-LLM (`--live`) | **Not run** — Ollama not available on verification host |
| Secrets in repo | No committed API keys (env-only) |
| Patient / real DICOM | Not bundled; synthetic placeholders only under `examples/` |

## Protections verified by tests

- ChangeSet never auto-applied (`awaiting_approval`)
- Stale fingerprint blocks Apply
- Conversion-busy blocks Apply
- Forbidden tools (`apply_changeset`, …) rejected
- Provenance distinguishes **rejected** vs **applied** and exports reproducibly

## Packaging artifacts

| Artifact | Status on this host | Build command |
|----------|---------------------|---------------|
| Windows EXE + Setup | Scripts ready; **build on Windows** | `powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1` |
| macOS `.app` | Script ready; **build on macOS** | `bash scripts/build_macos.sh` |
| Demo / Preview | Ready | `python -m neuro_pipeline.gui.preview` |
| Synthetic dataset | Ready | `examples/synthetic_dataset/` |
| Benchmark report | Staged | `release/COPILOT_BENCHMARK_REPORT.md` |

## Docs

- [INSTALL.md](../docs/INSTALL.md)
- [CONFIGURATION.md](../docs/CONFIGURATION.md)
- [COPILOT.md](../docs/COPILOT.md)
- [README.md](../README.md)
- [CHANGELOG.md](../CHANGELOG.md)
- [tests/benchmarks/README.md](../tests/benchmarks/README.md)

## GitHub Release (manual — token required)

`gh` on the verification host is **not authenticated**. On a machine with a valid token:

```bash
git tag -a v1.0.0-copilot -m "NeuroBIDS Copilot V1"
git push origin v1.0.0-copilot

gh release create v1.0.0-copilot \
  --title "NeuroBIDS Copilot V1" \
  --notes-file release/RELEASE_NOTES_v1.0.0.md \
  release/NeuroPipeline_DICOM_Converter_Setup.exe \
  release/COPILOT_BENCHMARK_REPORT.md
```

Attach macOS/Windows binaries after native builds complete.
