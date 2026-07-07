"""Detect anatomical MRI volumes that require defacing for public release."""

from __future__ import annotations

from pathlib import Path

NIFTI_SUFFIXES: tuple[str, ...] = (".nii.gz", ".nii")
ANATOMICAL_MARKERS: tuple[str, ...] = ("_T1w", "_T2w", "_PDw", "_FLAIR", "_MPRAGE", "_UNIT1")


def is_nifti(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".nii.gz") or name.endswith(".nii")


def is_anatomical_volume(path: Path) -> bool:
    """Return True if *path* is an anatomical MRI NIfTI (OpenNeuro defacing candidate)."""
    if not path.is_file() or not is_nifti(path) or "_defaced" in path.name:
        return False
    if any(marker in path.name for marker in ANATOMICAL_MARKERS):
        return True
    return "anat" in path.parts


def dataset_has_anatomical_mri(dataset_root: Path) -> bool:
    """Return True if any anatomical MRI volume exists under *dataset_root*."""
    if not dataset_root.is_dir():
        return False
    for path in dataset_root.rglob("*"):
        if is_anatomical_volume(path):
            return True
    return False
