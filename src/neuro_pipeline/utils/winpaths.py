"""Windows-safe path helpers (long paths > MAX_PATH)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform.startswith("win")


def to_long_path(path: Path | str) -> str:
    """Return a path string suitable for open/scandir on Windows.

    Uses the ``\\\\?\\`` extended-length prefix for absolute local paths.
    UNC paths use ``\\\\?\\UNC\\...``. No-op on non-Windows.
    """
    p = Path(path)
    text = str(p)
    if not is_windows():
        return text

    # Already extended
    if text.startswith("\\\\?\\"):
        return text

    try:
        abs_path = p if p.is_absolute() else p.resolve()
    except OSError:
        abs_path = p.absolute()

    raw = os.path.normpath(str(abs_path))
    if raw.startswith("\\\\?\\"):
        return raw
    if raw.startswith("\\\\"):
        # \\server\share\... → \\?\UNC\server\share\...
        return "\\\\?\\UNC\\" + raw.lstrip("\\")
    return "\\\\?\\" + raw


def from_long_path(path: Path | str) -> Path:
    """Strip ``\\\\?\\`` prefix when present so Path comparisons stay normal."""
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + text[8:])
    if text.startswith("\\\\?\\"):
        return Path(text[4:])
    return Path(text)


def safe_scandir(path: Path | str):
    """``os.scandir`` with Windows long-path support."""
    return os.scandir(to_long_path(path))


def safe_open_path(path: Path | str) -> str:
    """Path string for ``open`` / ``dcmread`` that tolerates Windows long paths."""
    return to_long_path(path)
