# NeuroBIDS / Copilot configuration

## Application config

Primary YAML: `configs/default.yaml`

| Key | Meaning |
|-----|---------|
| `compression` | Write `.nii.gz` |
| `one_folder_per_patient` | Group outputs per subject |
| `preserve_json` | Keep dcm2niix JSON sidecars |
| `smart_naming` | Apply naming rules |
| `threads` | Conversion worker threads |
| `output_format` | e.g. `nii.gz` / BIDS |
| `dcm2niix_path` | Optional explicit path to dcm2niix |

Naming rules: `configs/naming_rules.yaml` (or user override under the user config root).

User writable data lives under:

- Windows: `%LOCALAPPDATA%\NeuroPipeline`
- Linux/macOS: `$XDG_STATE_HOME/NeuroPipeline` or `~/.local/state/NeuroPipeline`

## Copilot LLM (optional)

**Default: disabled.** NeuroBIDS works without an LLM and without Ollama.

Configure in **Settings → NeuroBIDS Copilot**, or with environment variables (useful for packaged EXE launches via a shortcut or shell):

| Variable | Example | Notes |
|----------|---------|-------|
| `NEUROBIDS_LLM_PROVIDER` | `none` / `local` / `openai` / `compatible` / `azure` | Default `none` |
| `NEUROBIDS_LLM_MODEL` | `gpt-4o-mini` or `qwen3:30b` | Required for live use |
| `NEUROBIDS_LLM_API_KEY` | *(secret)* | Required except `local` |
| `NEUROBIDS_LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama default for `local` |
| `NEUROBIDS_LLM_TIMEOUT` | `300` | Seconds (local defaults higher) |
| `NEUROBIDS_LLM_MAX_TOOL_CALLS` | `5` | Agent loop cap |
| `NEUROBIDS_LLM_MAX_RETRIES` | `2` | HTTP retries |
| `NEUROBIDS_LLM_RETRY_BACKOFF` | `0.5` | Seconds |
| `NEUROBIDS_COPILOT_PROVENANCE` | `1` / `0` | Persist audit JSONL |

### Local Ollama example

```bash
export NEUROBIDS_LLM_PROVIDER=local
export NEUROBIDS_LLM_MODEL=qwen3:30b
export NEUROBIDS_LLM_BASE_URL=http://localhost:11434/v1
```

### Remote OpenAI-compatible example

```bash
export NEUROBIDS_LLM_PROVIDER=openai
export NEUROBIDS_LLM_MODEL=gpt-4o-mini
export NEUROBIDS_LLM_API_KEY=...   # never commit
export NEUROBIDS_LLM_BASE_URL=https://api.openai.com/v1
```

Never commit API keys. The provider redacts secrets from logs/errors. The GUI never displays the key value.

### Windows packaged app

Set variables in a shortcut, PowerShell session, or System Environment Variables before launching the EXE. Settings → Apply also sets them for the **current session** only.

## Provenance

When enabled, Copilot writes versioned JSONL under:

`…/NeuroPipeline/logs/copilot_provenance/events.jsonl`

Records scrub API keys, absolute paths, PatientName, and binary/pixel payloads.

## Benchmark (developers)

```bash
# Deterministic FakeLLM (CI / release gate)
PYTHONPATH=src python -m neuro_pipeline.neurobids.copilot.benchmark --no-level3
```

See [`tests/benchmarks/README.md`](../tests/benchmarks/README.md).
