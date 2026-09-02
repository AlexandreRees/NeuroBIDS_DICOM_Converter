# Developer documentation

## Overview

NeuroPipeline DICOM Converter is a layered PySide6 application. The GUI never calls `subprocess` directly. All conversion goes through `Converter`, usually from a `ConversionWorker` on a `QThread`.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install -e ".[dev]"
pytest
python -m neuro_pipeline
```

### UI Preview / Demo Mode

Launch the real NeuroBIDS `MainWindow` with a tiny synthetic dataset (no real DICOM, no API key):

```bash
python -m neuro_pipeline.gui.preview
python -m neuro_pipeline.gui.preview --scenario audit
python -m neuro_pipeline.gui.preview --scenario changeset
```

| Scenario | Behavior |
|----------|----------|
| `normal` | Map workspace + Copilot open; inspector seeded |
| `audit` | Audit page focused; localizer left included for review |
| `changeset` | Auto-asks sequential rename; Proposed Changes ready for Reject/Apply |

Copilot uses `PreviewDemoProvider` (Fake LLM) so Ask → tool → ChangeSet → Reject/Apply works offline.

### Production LLM (OpenAI-compatible)

Optional. Configure via environment variables only (never commit keys):

```bash
export NEUROBIDS_LLM_PROVIDER=openai   # or azure | local | none
export NEUROBIDS_LLM_MODEL=gpt-4o-mini
export NEUROBIDS_LLM_API_KEY=...       # required except provider=local
export NEUROBIDS_LLM_BASE_URL=https://api.openai.com/v1   # optional override
export NEUROBIDS_LLM_TIMEOUT=60
export NEUROBIDS_LLM_MAX_RETRIES=2
```

The HTTP client expects a JSON assistant object (`message` | `clarify` | `tool_call`).
`CopilotAgent` still validates every tool name/arguments against `ToolRegistry` and never auto-applies mutations.

## Key modules

| Module | Responsibility |
|--------|----------------|
| `app.py` | Qt bootstrap, stylesheet, config/log init |
| `dicom/parser.py` | Scan folders, extract series metadata |
| `converter/dcm2niix.py` | Locate/run dcm2niix, capture I/O, rename |
| `utils/naming.py` | YAML-driven smart filenames |
| `workers/` | Background scan + convert workers |
| `gui/main_window.py` | Desktop UI |
| `config/loader.py` | Load `configs/default.yaml` |
| `logging/setup.py` | Rotating `logs/conversion.log` |

## Adding a naming rule

Edit `configs/naming_rules.yaml`:

```yaml
- pattern: task_faces
  match: contains
  name: faces
```

More specific patterns must appear **before** broader ones.

## Error handling convention

Raise subclasses of `NeuroPipelineError` for expected failures. Workers catch broader exceptions and emit `failed` signals. The GUI shows dialogs and never lets uncaught exceptions kill the process during conversion.

## Testing strategy

- Unit tests for naming, config, command building, filesystem helpers
- Synthetic DICOM files via pydicom for parser tests
- GUI tests optional (`pytest-qt`); keep logic out of widgets when possible

## Packaging notes

PyInstaller reads `installer/neuro_pipeline.spec`. Config YAML files are bundled as data. At runtime, `config/paths.py` resolves:

1. Directory next to the executable (frozen)
2. Repository `configs/` (development)
3. Extracted `_MEIPASS` resources

Place `dcm2niix.exe` next to `NeuroPipeline.exe` for end users, or ship it in `bin/`.

## Extending toward a full platform

Keep new capabilities behind new packages (`bids/`, `qc/`, …) and wire them through workers rather than expanding `MainWindow` forever. Shared models and config remain the integration point.
