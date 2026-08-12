"""Application resource path helpers (dev + PyInstaller)."""

from __future__ import annotations

import sys
from pathlib import Path


def get_app_root() -> Path:
    """Return the install / repository root.

    Frozen (PyInstaller): directory containing the executable.
    Development: repository root (``…/NeuroPipeline_DICOM_Converter``).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # src/neuro_pipeline/utils/resources.py → parents[3] = project root
    return Path(__file__).resolve().parents[3]


def get_resource_path(relative: str | Path) -> Path:
    """Resolve a path relative to the application root.

    Example::

        get_resource_path("configs/bids_entities.yaml")
    """
    return get_app_root() / relative


def get_meipass_resource(relative: str | Path) -> Path | None:
    """Optional one-file bundle resource under ``sys._MEIPASS`` when present."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        path = Path(sys._MEIPASS) / relative  # type: ignore[arg-type]
        if path.exists():
            return path
    return None


def resolve_config(relative_under_configs: str) -> Path:
    """Find ``configs/<name>`` next to the exe, in MEIPASS, or in the repo."""
    name = relative_under_configs.lstrip("/\\")
    if name.startswith("configs/"):
        rel = name
    else:
        rel = f"configs/{name}"
    candidates = [
        get_resource_path(rel),
        get_meipass_resource(rel),
        Path.cwd() / rel,
    ]
    for path in candidates:
        if path is not None and path.exists():
            return path
    return get_resource_path(rel)
