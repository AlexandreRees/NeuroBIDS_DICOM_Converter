# NeuroBIDS — Installation

NeuroBIDS converts neuroimaging **DICOM** data to **BIDS-ready** outputs with a human-in-the-loop workflow.

**You do not need Python** for packaged Windows/macOS releases.  
**You do not need Ollama** for the core application. The Copilot is **optional**.

**NeuroBIDS never modifies the original DICOM files.**

---

## Windows (recommended for end users)

1. Download `NeuroPipeline_DICOM_Converter_Setup.exe` from the GitHub Release (or build it — see below).
2. Run the installer. Accept the default location under Program Files if unsure.
3. Optionally create a desktop shortcut when prompted.
4. Launch **NeuroPipeline DICOM Converter** from the Start Menu.
5. Uninstall anytime via Start Menu → **Uninstall NeuroPipeline DICOM Converter**.

No Python, pip, Git, or virtual environment is required.

`dcm2niix` is bundled when present at build time (`tools/dcm2niix.exe`). If the app reports that dcm2niix is missing, set its path under **Settings**.

### Build the Windows installer (developers)

On a Windows machine with Python 3.11+, PyInstaller, and [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

Artifact:

```text
release\NeuroPipeline_DICOM_Converter_Setup.exe
```

Also produced: `dist\NeuroPipeline\NeuroPipeline.exe` (onedir bundle).

Ollama / LLM models are **not** included in the installer.

---

## macOS

### Packaged app (when built on a Mac)

```bash
bash scripts/build_macos.sh
```

Artifact:

```text
release/NeuroBIDS.app
```

This script **refuses to run on Linux/Windows** and must be executed on macOS. Codesigning/notarization is not automated.

### Developer install (any OS)

```bash
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
python -m neuro_pipeline
```

---

## First workflow

```text
DISCOVER → MAP → AUDIT → PROTECT → RELEASE
```

| Stage | What you see | What NeuroBIDS does | What you review |
|-------|--------------|---------------------|-----------------|
| **Discover** | Folder picker, subject/session/acquisition counts | Read-only DICOM discovery | That the right dataset was selected |
| **Map** | Subjects, BIDS Preview, acquisition inspector | Plans BIDS names; never writes DICOM | Classification and entity edits |
| **Audit** | Deterministic issues list | DatasetContext checks (no fake scores) | Warnings worth fixing before convert |
| **Protect** | Privacy / read-only reminders | Confirms DICOM stay untouched | That exports omit PatientName |
| **Release** | Readiness checklist | Same deterministic checks | Whether the dataset is ready to share |

Then use **Conversion** (or **Queue**) to run dcm2niix and write NIfTI/BIDS **outputs only**.

Full detail: [USER_GUIDE.md](USER_GUIDE.md) · [neurobids_workflow.md](neurobids_workflow.md)

---

## Conversion (short)

1. Select a DICOM source folder (Discover / Conversion).
2. Wait for the scan to finish.
3. Review acquisition classification and BIDS Preview on **Map**.
4. Edit mappings if needed (plan only — DICOM unchanged).
5. Choose an output folder and run **Convert**.
6. Open the conversion report / validation results.

**NeuroBIDS never modifies the original DICOM files.**

---

## Optional Copilot

The Copilot answers questions and can **propose** plan edits as a ChangeSet. You must **Apply** or **Reject**. Nothing auto-applies.

| Mode | Needs |
|------|--------|
| Disabled (default) | Nothing — NeuroBIDS works fully |
| Local AI (Ollama) | Ollama running locally + a model name |
| OpenAI-compatible API | Base URL, model, API key |

Configure under **Settings → NeuroBIDS Copilot**, or via `NEUROBIDS_LLM_*` env vars ([CONFIGURATION.md](CONFIGURATION.md), [COPILOT.md](COPILOT.md)).

Local AI keeps inference on your machine. Remote APIs may send prompts/context to an external service.

---

## Demo / Preview (developers)

```bash
PYTHONPATH=src python -m neuro_pipeline.gui.preview
```

No real DICOM and no API key required.

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| Application does not launch | Reinstall from Setup.exe; on Windows check antivirus quarantine; developers: run from a venv and read Logs |
| dcm2niix unavailable | Settings → set path; ensure `tools/dcm2niix.exe` was present at build time; download from [dcm2niix releases](https://github.com/rordenlab/dcm2niix/releases) |
| Conversion failed | Open **Logs**; confirm DICOM still readable; free disk space; retry |
| Invalid / unreadable DICOM | Re-export from PACS; exclude bad series in Map |
| Invalid BIDS mapping | Fix entities on Map; BIDS-invalid ≠ conversion-invalid |
| Output directory already exists | Choose an empty folder or a new path |
| Permission denied | Pick a writable folder; check network-share rights |
| Disk space issue | Free space on the output volume |
| Copilot unavailable | Expected when provider=Disabled; open Settings to enable |
| Ollama unavailable | Start Ollama; Settings → Local AI → Test connection; or stay Disabled |
| Remote API unavailable | Check base URL, model, API key; use Test connection; review institutional data policy |

---

## Packaging verification (developers)

```bash
PYTHONPATH=src python scripts/verify_packaging.py
```

After a native build, artifacts under `dist/` / `release/` are also checked.
