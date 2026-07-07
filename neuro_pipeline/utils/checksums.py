"""SHA256 checksum manifests for dataset versions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from neuro_pipeline.utils.dicom_helpers import file_sha256


@dataclass(frozen=True)
class ChecksumEntry:
    """One file entry in a checksum manifest."""

    relative_path: str
    sha256: str
    size_bytes: int


def iter_dataset_files(
    root: Path,
    *,
    exclude_prefixes: Iterable[str] = (),
) -> list[Path]:
    """Collect regular files under *root* in deterministic order."""
    excluded = tuple(exclude_prefixes)
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if any(relative.startswith(prefix) for prefix in excluded):
            continue
        files.append(path)
    return files


def build_checksum_manifest(
    root: Path,
    *,
    dataset_version: str,
    pipeline_version: str,
    exclude_prefixes: Iterable[str] = (),
) -> dict[str, object]:
    """Build a checksum manifest for all files under *root*."""
    entries: list[dict[str, object]] = []
    for path in iter_dataset_files(root, exclude_prefixes=exclude_prefixes):
        stat = path.stat()
        entries.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "sha256": file_sha256(path),
                "size_bytes": stat.st_size,
            }
        )
    return {
        "dataset_version": dataset_version,
        "pipeline_version": pipeline_version,
        "root": str(root.resolve()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(entries),
        "files": entries,
    }


def write_checksum_manifest(path: Path, manifest: dict[str, object]) -> None:
    """Write checksum manifest JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def verify_checksum_manifest(root: Path, manifest: dict[str, object]) -> list[str]:
    """Return list of integrity errors when comparing *root* to *manifest*."""
    errors: list[str] = []
    expected_files = {
        entry["relative_path"]: entry
        for entry in manifest.get("files", [])
        if isinstance(entry, dict) and "relative_path" in entry
    }
    observed = {
        path.relative_to(root).as_posix(): path
        for path in iter_dataset_files(root)
    }

    for relative, entry in expected_files.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"Missing file: {relative}")
            continue
        expected_hash = str(entry.get("sha256", ""))
        if expected_hash and file_sha256(path) != expected_hash:
            errors.append(f"Checksum mismatch: {relative}")

    for relative in sorted(set(observed) - set(expected_files)):
        errors.append(f"Unexpected file not in manifest: {relative}")

    return errors
