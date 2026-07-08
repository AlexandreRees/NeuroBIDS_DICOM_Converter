# Documentation templates

Bundled markdown templates for study-specific documentation. These complement the repository README and reference material under the top-level [`docs/`](../../docs/) directory.

## Templates

| Template | File | Purpose |
|----------|------|---------|
| `architecture` | `ARCHITECTURE.md` | Project-specific architecture and data-flow |
| `installation` | `INSTALLATION.md` | Full environment and deployment setup |
| `pipeline_overview` | `PIPELINE_OVERVIEW.md` | Study workflow and quality gates |
| `development` | `DEVELOPMENT.md` | Contributor and extension guide |

## Usage

```python
from pathlib import Path
from neuro_pipeline.docs import copy_templates_to, read_template, template_path

# Read a template
text = read_template("installation")

# Copy all templates into a project docs folder
copy_templates_to(Path("/data/my-study/docs"))
```

Replace `{{PLACEHOLDER}}` markers with project-specific values after copying.

## Related repository docs

| Document | Content |
|----------|---------|
| [`README.md`](../../README.md) | Quick start and package summary |
| [`PIPELINE_ARCHITECTURE.md`](../../docs/PIPELINE_ARCHITECTURE.md) | Technical architecture reference |
| [`PROJECT_INDEX.md`](../../docs/PROJECT_INDEX.md) | Module inventory |
| [`ARCHITECTURE_MIGRATION.md`](../../docs/ARCHITECTURE_MIGRATION.md) | Package migration map |
