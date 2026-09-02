"""Path helpers that work in development and PyInstaller-frozen builds.

Directory roles
---------------
``resource_root()``
    Packaged / installed application resources (read-only at runtime).
    Under PyInstaller 6 onedir this is typically ``…/_internal``.
    Contains default configs, bundled binaries referenced via ``sys._MEIPASS``, etc.

``project_root()`` / ``get_app_root()``
    Repository root in development, or the install folder next to the EXE
    when frozen. Treat as **read-only** after installation in Program Files.

``user_data_root()``
    Writable per-user runtime data under::

        %LOCALAPPDATA%\\NeuroPipeline          (Windows)
        $XDG_STATE_HOME/NeuroPipeline         (Linux/macOS)

    Use this (and the ``user_*_root()`` helpers) for logs, queue state,
    user config overrides, and temp files. Never write runtime data into
    ``project_root()`` / Program Files.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

from neuro_pipeline.utils.resources import get_app_root, get_resource_path, resolve_config

LOGGER = logging.getLogger(__name__)

_APP_DIR_NAME = "NeuroPipeline"


def is_frozen() -> bool:
    """Return True when running inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Return the repository / install root (read-only after installation)."""
    return get_app_root()


def resource_root() -> Path:
    """Return packaged resources root (read-only; ``sys._MEIPASS`` when frozen)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[arg-type]
    return get_app_root()


def user_data_root() -> Path:
    """Writable per-user data root (never under Program Files).

    Windows: ``%LOCALAPPDATA%\\NeuroPipeline``
    Other:   ``$XDG_STATE_HOME/NeuroPipeline`` or ``~/.local/state/NeuroPipeline``
    """
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            base = Path(local)
        else:
            base = Path.home() / "AppData" / "Local"
    else:
        xdg = os.environ.get("XDG_STATE_HOME")
        base = Path(xdg) if xdg else (Path.home() / ".local" / "state")
    path = base / _APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_subdir(name: str) -> Path:
    path = user_data_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_log_root() -> Path:
    """``user_data_root()/logs`` — conversion.log, queue logs."""
    return _ensure_subdir("logs")


def user_config_root() -> Path:
    """``user_data_root()/config`` — user-editable config / naming rules JSON."""
    return _ensure_subdir("config")


def user_queue_root() -> Path:
    """``user_data_root()/queue`` — persisted conversion queue state."""
    return _ensure_subdir("queue")


def user_state_root() -> Path:
    """``user_data_root()/state`` — miscellaneous writable state."""
    return _ensure_subdir("state")


def user_temp_root() -> Path:
    """``user_data_root()/tmp`` — short-lived working files."""
    return _ensure_subdir("tmp")


def user_copilot_provenance_root() -> Path:
    """``user_data_root()/logs/copilot_provenance`` — Copilot audit JSONL."""
    path = user_log_root() / "copilot_provenance"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_state_dir() -> Path:
    """Backward-compatible alias for :func:`user_state_root`."""
    return user_state_root()


def is_dir_writable(path: Path | str) -> bool:
    """Return True when ``path`` exists (or can be created) and is writable."""
    directory = Path(path)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".neuropipeline_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def resolve_writable_log_dir(preferred: Path | str | None = None) -> Path:
    """Pick a writable log directory with safe fallbacks (never Program Files).

    Order:
      1. ``preferred`` when set and writable
      2. :func:`user_log_root`
      3. ``%TEMP%/NeuroPipeline/logs``
    """
    candidates: list[Path] = []
    if preferred is not None and str(preferred).strip():
        candidates.append(Path(preferred).expanduser())
    candidates.append(user_log_root())
    candidates.append(Path(tempfile.gettempdir()) / _APP_DIR_NAME / "logs")

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            key = candidate.resolve()
        except OSError:
            key = candidate
        if key in seen:
            continue
        seen.add(key)
        if is_dir_writable(candidate):
            return candidate.resolve() if candidate.exists() else candidate

    # Last resort: temp path even if probe failed earlier
    fallback = Path(tempfile.gettempdir()) / _APP_DIR_NAME / "logs"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def default_conversion_log_path() -> Path:
    """Default ``conversion.log`` path under the user log directory."""
    return resolve_writable_log_dir() / "conversion.log"


def default_config_path() -> Path:
    """Path to packaged configs/default.yaml (read-only resource)."""
    return resolve_config("default.yaml")


def default_naming_rules_path() -> Path:
    """Path to packaged configs/naming_rules.yaml (read-only resource)."""
    return resolve_config("naming_rules.yaml")


def default_bids_naming_rules_json() -> Path:
    """User-editable BIDS smart naming rules (JSON) under user config root."""
    return user_config_root() / "naming_rules.json"


def default_curation_rules_root() -> Path:
    """Dataset-specific curation rules (JSON files) under user config root.

    Never written into the DICOM dataset folder. The directory is created
    when a store is saved, not on read.
    """
    return user_config_root() / "curation_rules"


def default_conversion_queue_path() -> Path:
    """Persisted conversion queue state (user queue root)."""
    return user_queue_root() / "conversion_queue.json"


def default_conversion_queue_log_path() -> Path:
    """Queue manager log file (user log root)."""
    return user_log_root() / "conversion_queue.log"


def bundled_config_candidates(filename: str) -> list[Path]:
    """Candidate locations for a *packaged* config file (dev, installed, next to exe)."""
    roots = [
        get_resource_path(f"configs/{filename}"),
        resource_root() / "configs" / filename,
        Path.cwd() / "configs" / filename,
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in roots:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique
