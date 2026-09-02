"""Filesystem helpers used by the GUI and converter."""

from __future__ import annotations

import os
import re
from pathlib import Path

from neuro_pipeline.utils.exceptions import (
    EmptyFolderError,
    OutputFolderError,
    PermissionDeniedError,
)


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename(value: str, fallback: str = "unnamed") -> str:
    """Return a Windows-safe filename stem."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", value.strip())
    cleaned = _WHITESPACE.sub("_", cleaned)
    cleaned = cleaned.strip("._")
    return cleaned or fallback


def ensure_readable_dir(path: Path) -> Path:
    """Validate that ``path`` exists, is a directory, and is readable."""
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Folder does not exist: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a folder: {resolved}")
    if not os.access(resolved, os.R_OK):
        raise PermissionDeniedError(f"Permission denied reading: {resolved}")
    return resolved


def ensure_writable_dir(path: Path, *, create: bool = True) -> Path:
    """Validate that ``path`` is writable, creating it when requested."""
    resolved = path.expanduser().resolve()
    if create:
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise PermissionDeniedError(f"Permission denied creating: {resolved}") from exc
        except OSError as exc:
            raise OutputFolderError(f"Cannot create output folder: {resolved}") from exc

    if not resolved.is_dir():
        raise OutputFolderError(f"Output path is not a folder: {resolved}")
    if not os.access(resolved, os.W_OK):
        raise PermissionDeniedError(f"Permission denied writing: {resolved}")
    return resolved


def assert_non_empty_folder(path: Path) -> None:
    """Raise if a directory has no files or subfolders."""
    try:
        next(path.iterdir())
    except StopIteration as exc:
        raise EmptyFolderError(f"The selected folder is empty:\n{path}") from exc
    except PermissionError as exc:
        raise PermissionDeniedError(f"Permission denied reading: {path}") from exc


def folder_has_content(path: Path) -> bool:
    """Return True if the directory exists and contains at least one entry."""
    if not path.exists() or not path.is_dir():
        return False
    try:
        return any(path.iterdir())
    except OSError:
        return False
