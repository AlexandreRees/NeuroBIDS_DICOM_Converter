# NeuroBIDS Copilot V1 — Installation

## End users (Windows)

1. Download `NeuroPipeline_DICOM_Converter_Setup.exe` from the GitHub Release.
2. Run the installer (no Python required).
3. Install or point Settings to [dcm2niix](https://github.com/rordenlab/dcm2niix/releases).
4. Launch **NeuroPipeline / NeuroBIDS**.

Optional Copilot LLM (natural language):

```text
Settings → Copilot / environment variables (see docs/CONFIGURATION.md)
```

## End users (macOS)

Python developer install is supported today; a notarized `.app` build is prepared via `scripts/build_macos.sh` on a macOS machine.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m neuro_pipeline
```

## Developers (Linux / macOS / Windows)

```bash
git clone https://github.com/AlexandreRees/neuro_pipeline.git
cd neuro_pipeline
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"
python -m neuro_pipeline
```

### Demo / Preview mode (no real DICOM, no API key)

```bash
PYTHONPATH=src python -m neuro_pipeline.gui.preview
PYTHONPATH=src python -m neuro_pipeline.gui.preview --scenario audit
PYTHONPATH=src python -m neuro_pipeline.gui.preview --scenario changeset
```

### Synthetic example dataset

See [`examples/synthetic_dataset/README.md`](../examples/synthetic_dataset/README.md).

## Verify install

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src pytest tests/ -q
PYTHONPATH=src python -m neuro_pipeline.neurobids.copilot.benchmark --no-level3
```

## Safety guarantees (unchanged)

- Original DICOM is never modified
- Copilot mutations propose a ChangeSet and never auto-apply
- Stale proposals and conversion-busy states block Apply
- Provenance logs scrub secrets, paths, and PHI
