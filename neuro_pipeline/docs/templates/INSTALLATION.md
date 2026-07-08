# Installation

> **Template:** Environment setup for a neuro-bids-pipeline **project**.  
> The repository README covers quick start only; use this document for full deployment notes.

---

## 1. Scope

| Item | Detail |
|------|--------|
| Target environment | `{{ENVIRONMENT}}` (workstation / HPC / container) |
| Python requirement | ≥ 3.11 |
| Pipeline version | `{{PIPELINE_VERSION}}` |

---

## 2. Prerequisites

Install system dependencies before the Python package:

| Tool | Purpose | Verification |
|------|---------|--------------|
| Python 3.11+ | Pipeline runtime | `python3 --version` |
| dcm2niix | DICOM → NIfTI | `dcm2niix --version` |
| Node.js + npm | bids-validator (optional) | `node --version` |
| bids-validator | BIDS compliance | `bids-validator --version` or `npx bids-validator --version` |
| git | Provenance capture | `git --version` |

Document site-specific modules or containers required on HPC:

```text
{{HPC_MODULES_OR_CONTAINER}}
```

---

## 3. Install the pipeline package

From a clone of the neuro-bids-pipeline repository:

```bash
cd {{REPO_PATH}}
pip install -e ".[dev]"
```

For production installs without development tools, omit `[dev]`.

Verify console scripts:

```bash
neuro-pipeline --help
neuro-release --help
```

---

## 4. Container installation (optional)

When using the provided Docker image, record the image tag and mount points for **this** deployment:

| Setting | Value |
|---------|-------|
| Image | `{{CONTAINER_IMAGE}}` |
| Project mount | `{{HOST_PROJECT}}` → `{{CONTAINER_PROJECT}}` |
| Provenance env | `NEURO_PIPELINE_IMAGE`, `NEURO_PIPELINE_IMAGE_DIGEST` |

Build and run instructions live in `container/Dockerfile` at the repository root.

---

## 5. Initialise a project directory

Create the expected top-level folders before the first run:

```bash
mkdir -p {{PROJECT_ROOT}}/{raw_original,metadata,logs}
```

Describe how DICOM should be organised under `raw_original/` for this study:

```text
{{RAW_ORIGINAL_LAYOUT}}
```

---

## 6. Configuration

Record study-specific settings (do not commit secrets):

| Setting | Location / command | Value |
|---------|-------------------|-------|
| Default project root | `{{DEFAULT_PROJECT_ROOT}}` | |
| dcm2niix path | `--dcm2niix-path` | `{{DCM2NIIX_PATH}}` |
| Release seed | `--seed` | stored in `{{SECRET_STORE}}` |
| Strict validation | `--fail-on-error` | `{{YES_NO}}` |

Pipeline constants and defaults are defined in `neuro_pipeline.config.constants` and `neuro_pipeline.config.defaults`.

---

## 7. Post-install verification

Run a minimal smoke test on a small fixture or single subject:

```bash
neuro-inventory --project-root {{PROJECT_ROOT}}
```

Expected artifact: `metadata/inventory.csv`

---

## 8. Troubleshooting

| Symptom | Likely cause | Resolution |
|---------|--------------|------------|
| `dcm2niix not found` | Not on `PATH` | Install or pass `--dcm2niix-path` |
| `bids-validator not found` | npm package missing | Install globally or use `--use-npx` |
| `raw_original/` missing | Project root misconfigured | Check `--project-root` |
| `{{CUSTOM_ISSUE}}` | `{{CAUSE}}` | `{{FIX}}` |

---

## 9. Maintenance

| Task | Frequency | Command / action |
|------|-----------|------------------|
| Update pipeline | `{{FREQUENCY}}` | `git pull && pip install -e .` |
| Pin tool versions | `{{FREQUENCY}}` | Update `container/versions.env` |
| Review checkpoints | After failed runs | Inspect `metadata/*_checkpoints.json` |
