# Development guide

> **Template:** Local development and extension practices for neuro-bids-pipeline contributors.  
> This document complements the README testing section with workflow and conventions.

---

## 1. Development environment

| Requirement | Version / notes |
|-------------|-----------------|
| Python | ≥ 3.11 |
| Editable install | `pip install -e ".[dev]"` from repository root |
| Test runner | `pytest` via `[dev]` extra |

Optional tools:

```text
{{OPTIONAL_DEV_TOOLS}}
```

---

## 2. Repository layout for developers

Source packages live under `scripts/`:

```text
scripts/
├── neuro_pipeline/     # Research pipeline packages
│   ├── acquisition/
│   ├── conversion/
│   ├── validation/
│   ├── qc/
│   ├── workflows/      # Orchestration only — no scientific logic
│   ├── config/         # constants.py, defaults.py
│   └── docs/           # Markdown templates (this package)
└── mri_anonymization/  # Public-release anonymization
```

Tests: `tests/` at repository root. Detailed module inventory: [`docs/PROJECT_INDEX.md`](../../docs/PROJECT_INDEX.md).

---

## 3. Running individual pipeline steps

Debug a single stage without the full orchestrator:

```bash
export PROJECT={{PROJECT_ROOT}}

neuro-inventory   --project-root "$PROJECT"
neuro-mapping     --project-root "$PROJECT"
neuro-convert     --project-root "$PROJECT"
neuro-validate    --project-root "$PROJECT"
neuro-qc          --project-root "$PROJECT"
neuro-derivatives --project-root "$PROJECT"
```

Release steps:

```bash
neuro-release-anonymize --project-root "$PROJECT" --seed "$SECRET"
neuro-validate-public     --project-root "$PROJECT"
neuro-release-gate        --project-root "$PROJECT"
```

---

## 4. Testing

```bash
python -m pytest tests/ -v
```

Guidelines:

- Add tests beside existing modules (`tests/test_<module>.py`).
- Prefer real pydicom/nibabel fixtures over mocks for conversion and validation logic.
- Do not change scientific behaviour when refactoring — tests must remain green.

Target coverage areas for new features:

| Area | Example test file |
|------|-------------------|
| Acquisition validation | `tests/test_acquisition_consistency.py` |
| Workflows | `tests/test_workflows.py` |
| Provenance | `tests/test_provenance_package.py` |
| Config | `{{YOUR_TEST_FILE}}` |

---

## 5. Coding conventions

| Rule | Detail |
|------|--------|
| Package boundaries | Scientific logic stays in domain packages; orchestration in `workflows/` |
| Configuration | Shared constants → `config/constants.py`; tunable defaults → `config/defaults.py` |
| Paths | Use `ProjectPaths` from `utils/paths.py` — avoid hardcoded directory names |
| Logging | Use `configure_logging` from `utils/logging_config.py` |
| Imports | Prefer `from neuro_pipeline.<package>.<module> import ...` |
| Compatibility | Legacy root shims exist — new code should use canonical package paths |

See [`docs/ARCHITECTURE_MIGRATION.md`](../../docs/ARCHITECTURE_MIGRATION.md) for the migration map.

---

## 6. Adding a new pipeline stage

Checklist for contributors:

1. Implement logic in the appropriate domain package (not `workflows/`).
2. Expose a CLI with `build_base_parser` and register in `pyproject.toml`.
3. Add the step to `workflows/steps.py` if it belongs in an orchestrated pipeline.
4. Register required artifacts in `utils/step_artifacts.py`.
5. Update stage contracts in `config/stage_contracts.py` if applicable.
6. Add tests and document outputs in [`docs/PROJECT_INDEX.md`](../../docs/PROJECT_INDEX.md).

---

## 7. Documentation templates

Copy bundled templates into a project’s `docs/` folder:

```python
from pathlib import Path
from neuro_pipeline.docs import copy_templates_to

copy_templates_to(Path("/path/to/project/docs"))
```

Available templates: `architecture`, `installation`, `pipeline_overview`, `development`.

Replace `{{PLACEHOLDER}}` fields with study-specific values.

---

## 8. Release checklist (maintainers)

| Task | Done |
|------|------|
| Full test suite passes | ☐ |
| Version bumped in `config/constants.py` / `config/extensions.py` | ☐ |
| Container pins updated in `container/versions.env` | ☐ |
| Migration notes updated if packages moved | ☐ |
| Templates reviewed for placeholder accuracy | ☐ |

---

## 9. Contacts

| Role | Name | Contact |
|------|------|---------|
| Pipeline maintainer | `{{MAINTAINER}}` | `{{EMAIL}}` |
| Study data manager | `{{DATA_MANAGER}}` | `{{EMAIL}}` |
