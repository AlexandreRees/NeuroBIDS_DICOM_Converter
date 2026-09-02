"""Shared recursive file walk for DICOM discovery (unlimited depth)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from neuro_pipeline.utils.winpaths import from_long_path, safe_scandir

LOGGER = logging.getLogger(__name__)

_SKIP_FILE_NAMES = {"dicomdir", "thumbs.db", ".ds_store", "desktop.ini"}
_SKIP_DIR_NAMES = {
    ".git",
    ".svn",
    "__pycache__",
    "derivatives",
    "nifti",
    "niftis",
    "node_modules",
    ".neuro_pipeline",
    ".batch",
}
# Exact-name skips only — names like SUBT01_…_NII are handled at scoring time.
_SKIP_SUFFIXES = {
    ".nii",
    ".gz",
    ".json",
    ".bval",
    ".bvec",
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".html",
    ".htm",
    ".xml",
    ".pdf",
    ".py",
    ".yaml",
    ".yml",
    ".log",
    ".zip",
    ".tar",
    ".7z",
}


def iter_candidate_files(root: Path | str) -> Iterator[Path]:
    """Yield candidate files under ``root`` at any depth.

    - Does not trust extensions as proof of DICOM
    - Skips only obvious non-DICOM payloads (NIfTI, JSON, images, archives…)
    - Uses Windows long-path-safe directory listing
    - Continues on listing errors (logs a warning so deep trees are not silent)
    """
    root_path = Path(root)
    stack = [root_path]
    skipped_dirs = 0

    while stack:
        current = stack.pop()
        try:
            with safe_scandir(current) as entries:
                for entry in entries:
                    name = entry.name
                    if name.startswith(".") and name not in {".", ".."}:
                        if entry.is_dir(follow_symlinks=False):
                            continue
                    if entry.is_dir(follow_symlinks=False):
                        if name.lower() in _SKIP_DIR_NAMES:
                            continue
                        # Prefer Path without \\?\ so later relative_to works
                        stack.append(from_long_path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if name.lower() in _SKIP_FILE_NAMES:
                        continue
                    path = from_long_path(entry.path)
                    suffixes = (
                        {s.lower() for s in path.suffixes[-2:]} if path.suffixes else set()
                    )
                    if path.suffix.lower() in _SKIP_SUFFIXES or ".nii" in suffixes:
                        continue
                    yield path
        except PermissionError:
            skipped_dirs += 1
            LOGGER.warning("Permission denied listing (skipped): %s", current)
        except OSError as exc:
            skipped_dirs += 1
            LOGGER.warning("Skip listing %s (%s)", current, exc)

    if skipped_dirs:
        LOGGER.warning(
            "Directory walk skipped %s folder(s) under %s (permissions/path length).",
            skipped_dirs,
            root_path,
        )
