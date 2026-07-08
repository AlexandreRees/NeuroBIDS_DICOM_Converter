"""Access and copy bundled markdown documentation templates."""

from __future__ import annotations

import shutil
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

TEMPLATE_FILES: dict[str, str] = {
    "architecture": "ARCHITECTURE.md",
    "installation": "INSTALLATION.md",
    "pipeline_overview": "PIPELINE_OVERVIEW.md",
    "development": "DEVELOPMENT.md",
}


def list_templates() -> list[str]:
    """Return sorted template identifiers."""
    return sorted(TEMPLATE_FILES)


def template_path(name: str) -> Path:
    """Resolve the on-disk path for a named template."""
    key = name.lower().replace("-", "_")
    if key not in TEMPLATE_FILES:
        known = ", ".join(sorted(TEMPLATE_FILES))
        raise KeyError(f"Unknown template {name!r}. Available: {known}")
    path = TEMPLATES_DIR / TEMPLATE_FILES[key]
    if not path.is_file():
        raise FileNotFoundError(f"Template file missing: {path}")
    return path


def read_template(name: str) -> str:
    """Return the markdown contents of a named template."""
    return template_path(name).read_text(encoding="utf-8")


def copy_templates_to(destination: Path | str) -> list[Path]:
    """Copy all templates into *destination* and return written paths."""
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename in TEMPLATE_FILES.values():
        source = TEMPLATES_DIR / filename
        output = target / filename
        shutil.copy2(source, output)
        written.append(output)
    return written
