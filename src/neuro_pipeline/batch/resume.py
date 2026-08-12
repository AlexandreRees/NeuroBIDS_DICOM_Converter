"""Resume / checkpoint helpers for batch conversion."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Iterable

from neuro_pipeline.batch.batch_models import BatchJobStatus, BatchState, SeriesCheckpoint
from neuro_pipeline.batch.exceptions import BatchResumeError

LOGGER = logging.getLogger(__name__)

STATE_FILENAME = "state.json"
CHECKPOINT_DIRNAME = "checkpoints"
SERIES_HASH_FILENAME = "series_hash.json"


def state_path(output_root: Path) -> Path:
    return Path(output_root) / STATE_FILENAME


def checkpoint_dir(output_root: Path) -> Path:
    return Path(output_root) / CHECKPOINT_DIRNAME


def series_checkpoint_path(output_root: Path, series_uid: str) -> Path:
    safe = hashlib.sha1(series_uid.encode("utf-8")).hexdigest()[:16]
    return checkpoint_dir(output_root) / f"{safe}_{SERIES_HASH_FILENAME}"


def compute_source_hash(files: Iterable[Path]) -> str:
    """Stable hash of source DICOM paths + sizes + mtimes."""
    h = hashlib.sha256()
    for path in sorted(Path(p) for p in files):
        try:
            st = path.stat()
        except OSError:
            continue
        payload = f"{path.name}|{st.st_size}|{int(st.st_mtime)}\n"
        h.update(payload.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def compute_output_hash(files: Iterable[Path]) -> str:
    """Hash existing NIfTI / sidecar outputs for skip verification."""
    h = hashlib.sha256()
    for path in sorted(Path(p) for p in files):
        try:
            st = path.stat()
        except OSError:
            continue
        payload = f"{path.name}|{st.st_size}|{int(st.st_mtime)}\n"
        h.update(payload.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def write_state(output_root: Path, state: BatchState) -> Path:
    path = state_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    return path


def load_state(output_root: Path) -> BatchState | None:
    path = state_path(output_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchResumeError(f"Cannot read batch state: {path}") from exc
    return BatchState.from_dict(data)


def has_resumable_state(output_root: Path) -> bool:
    state = load_state(output_root)
    if state is None:
        return False
    return state.status in {
        BatchJobStatus.RUNNING,
        BatchJobStatus.PAUSED,
        BatchJobStatus.QUEUED,
        BatchJobStatus.FAILED,
    } and state.completed_series < max(state.total_series, 1)


def write_series_checkpoint(output_root: Path, checkpoint: SeriesCheckpoint) -> Path:
    path = series_checkpoint_path(output_root, checkpoint.series_uid or checkpoint.source_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checkpoint.to_dict(), indent=2), encoding="utf-8")
    return path


def load_series_checkpoint(output_root: Path, series_uid: str) -> SeriesCheckpoint | None:
    path = series_checkpoint_path(output_root, series_uid)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return SeriesCheckpoint.from_dict(data)


def should_skip_series(
    *,
    output_root: Path,
    series_uid: str,
    source_hash: str,
) -> bool:
    """Return True when a successful checkpoint matches the current source hash."""
    ckpt = load_series_checkpoint(output_root, series_uid)
    if ckpt is None:
        return False
    if ckpt.status.lower() not in {"completed", "success", "done", "ok"}:
        return False
    if ckpt.source_hash != source_hash:
        return False
    # Outputs referenced by the checkpoint must still exist
    for rel in ckpt.output_files:
        if not (Path(output_root) / rel).exists() and not Path(rel).exists():
            return False
    return True
