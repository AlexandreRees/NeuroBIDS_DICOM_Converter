"""raw_bids immutability enforcement after research pipeline lock."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from neuro_pipeline.utils.checksums import build_checksum_manifest, verify_checksum_manifest
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.extensions import PIPELINE_VERSION
from neuro_pipeline.utils.paths import ProjectPaths


def lock_raw_bids(paths: ProjectPaths, *, dataset_version: str) -> dict[str, object]:
    """Write checksum manifest and lock file for raw_bids/."""
    manifest = build_checksum_manifest(
        paths.raw_bids,
        dataset_version=dataset_version,
        pipeline_version=PIPELINE_VERSION,
    )
    checksum_path = paths.metadata / "raw_bids_checksums.json"
    checksum_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lock_payload = {
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset_version,
        "pipeline_version": PIPELINE_VERSION,
        "checksum_manifest": str(checksum_path.resolve()),
        "file_count": manifest.get("file_count", 0),
        "immutable": True,
    }
    lock_path = paths.metadata / "raw_bids_lock.json"
    lock_path.write_text(json.dumps(lock_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock_payload


def assert_raw_bids_immutable(paths: ProjectPaths) -> None:
    """Verify raw_bids/ matches the locked checksum manifest."""
    lock_path = paths.metadata / "raw_bids_lock.json"
    checksum_path = paths.metadata / "raw_bids_checksums.json"
    if not lock_path.is_file() or not checksum_path.is_file():
        return
    manifest = json.loads(checksum_path.read_text(encoding="utf-8"))
    errors = verify_checksum_manifest(paths.raw_bids, manifest)
    if errors:
        sample = "; ".join(errors[:5])
        raise FatalPipelineError(
            f"raw_bids immutability violation — dataset changed after lock: {sample}"
        )


def is_raw_bids_locked(paths: ProjectPaths) -> bool:
    return (paths.metadata / "raw_bids_lock.json").is_file()
