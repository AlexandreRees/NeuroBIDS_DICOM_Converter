#!/usr/bin/env python3
"""BIDS physiological quality-control pipeline (Scientific Data / OpenNeuro ready).

Purpose
-------
Cardiac, respiratory, and scanner-trigger recordings support physiological noise
modeling (e.g. RETROICOR). Incomplete signals, flat/saturated traces, missing
StartTime, or unreliable volume triggers silently invalidate phase estimation.
This pipeline inventories BIDS ``*_physio.tsv.gz`` recordings, quantifies signal
and trigger QC, aligns physiology to BOLD runs, and writes PHI-safe derivatives.

Safety policy
-------------
* Read-only on the BIDS tree (never writes under ``bids/``).
* Never modifies ``*_physio.tsv.gz`` / sidecars.
* Public tables and reports use paths relative to ``--bids_dir`` only.
* Optional content hashes are internal (JSON) and never required for release.

Compute Canada / Slurm
----------------------
    module load scipy-stack
    python code/physiology_qc.py --bids_dir bids --output_dir derivatives/physiology_qc

Why missing segments invalidate RETROICOR
----------------------------------------
RETROICOR assigns cardiac/respiratory phase per volume. Continuous gaps break
phase continuity across TRs; large gaps leave holes in the nuisance design.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import re
import sys
import tempfile
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    from scipy import signal as sp_signal
except ImportError:  # pragma: no cover
    sp_signal = None

try:
    import nibabel as nib
except ImportError:  # pragma: no cover
    nib = None

LOGGER = logging.getLogger("physiology_qc")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_TASKS = ("rest", "fmri", "movie")
RECORDING_TYPES = ("pulse", "respiratory", "trigger", "ecg")

FLAT_STD_THRESHOLD = 1e-6
SATURATION_FRAC = 0.99
LARGE_GAP_SECONDS = 2.0
TR_MATCH_TOLERANCE = 0.05  # 5% relative
MIN_TRIGGERS_OK = 10
MIN_DURATION_SECONDS = 5.0
DEFAULT_FS_FALLBACK = None  # never invent FS for scoring; mark BAD_SAMPLING

CHANNEL_FROM_SIEMENS = {
    "PULS": "cardiac",
    "PULSE": "cardiac",
    "ECG": "ecg",
    "RESP": "respiratory",
    "EXT": "trigger",
    "EXT2": "trigger",
}
CHANNEL_FROM_RECORDING = {
    "pulse": "cardiac",
    "respiratory": "respiratory",
    "trigger": "trigger",
    "ecg": "ecg",
}

BIDS_ENTITY_RE = re.compile(
    r"(?:^|_)(?P<key>sub|ses|task|run|recording|part)-(?P<value>[A-Za-z0-9]+)"
)

# Public summary columns (TSV)
SUMMARY_COLUMNS = [
    "participant_id",
    "session_id",
    "task",
    "run",
    "recording_type",
    "channel",
    "file_path_relative",
    "sampling_frequency",
    "sample_count",
    "duration_seconds",
    "StartTime",
    "StartTimeConfidence",
    "SiemensChannel",
    "nan_fraction",
    "min",
    "max",
    "mean",
    "std",
    "p01",
    "p50",
    "p99",
    "flags",
    "PhysioQualityScore",
    "PhysioQualityCategory",
    "qc_status",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PhysioRecord:
    """In-memory physiology recording (one file / one primary channel)."""

    participant_id: str | None
    session_id: str | None
    task: str | None
    run: str | None
    recording_type: str
    channel: str
    file_path_relative: str
    signal: np.ndarray
    sampling_frequency: float | None
    start_time: float | None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def run_key(self) -> tuple[str | None, str | None, str | None, str | None]:
        return (self.participant_id, self.session_id, self.task, self.run)


@dataclass
class SignalQC:
    sample_count: int
    duration_seconds: float | None
    n_missing: int
    nan_fraction: float
    min: float | None
    max: float | None
    mean: float | None
    std: float | None
    p01: float | None
    p50: float | None
    p99: float | None
    flags: list[str]
    longest_gap_seconds: float


@dataclass
class TriggerQC:
    trigger_count: int
    median_interval: float | None
    mean_interval: float | None
    std_interval: float | None
    estimated_TR: float | None
    bold_TR: float | None
    n_bold_volumes: int | None
    TR_difference: float | None
    TR_relative_diff: float | None
    trigger_status: str
    trigger_indices: np.ndarray


# ---------------------------------------------------------------------------
# Path / BIDS helpers (PHI-safe)
# ---------------------------------------------------------------------------


def relative_to_bids(path: Path, bids_dir: Path) -> str:
    """Return a POSIX-relative path under the BIDS root (no absolute/user paths)."""
    try:
        return path.resolve().relative_to(bids_dir.resolve()).as_posix()
    except ValueError:
        # Outside bids_dir: keep filename only (never leak absolute roots).
        LOGGER.warning("Path outside bids_dir; emitting basename only: %s", path.name)
        return path.name


def optional_file_hash(path: Path, enabled: bool) -> str | None:
    """Optional SHA-256 for internal traceability (not required in public TSV)."""
    if not enabled:
        return None
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_bids_entities(path: Path) -> dict[str, str | None]:
    stem = path.name
    for suffix in (".tsv.gz", ".nii.gz", ".json", ".tsv", ".nii"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    out: dict[str, str | None] = {
        "participant_id": None,
        "session_id": None,
        "task": None,
        "run": None,
        "recording": None,
        "part": None,
    }
    key_map = {
        "sub": "participant_id",
        "ses": "session_id",
        "task": "task",
        "run": "run",
        "recording": "recording",
        "part": "part",
    }
    for match in BIDS_ENTITY_RE.finditer(stem):
        out[key_map[match.group("key")]] = match.group("value")
    return out


def discover_physio_files(bids_dir: Path, tasks: Sequence[str] | None) -> list[Path]:
    files = sorted(
        p
        for p in bids_dir.rglob("*_physio.tsv.gz")
        if "derivatives" not in p.parts
    )
    if tasks:
        task_set = {t.lower() for t in tasks}
        filtered: list[Path] = []
        for p in files:
            ent = parse_bids_entities(p)
            if ent["task"] is None or ent["task"].lower() in task_set:
                filtered.append(p)
        return filtered
    return files


def discover_bold_files(bids_dir: Path, tasks: Sequence[str] | None) -> list[Path]:
    """Magnitude BOLD NIfTIs only (exclude part-phase)."""
    files = sorted(
        p
        for p in bids_dir.rglob("*_bold.nii.gz")
        if "derivatives" not in p.parts
    )
    out: list[Path] = []
    for p in files:
        ent = parse_bids_entities(p)
        if ent.get("part") == "phase":
            continue
        if tasks:
            task_set = {t.lower() for t in tasks}
            if ent["task"] is None or ent["task"].lower() not in task_set:
                continue
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Unreadable JSON %s: %s", path.name, exc)
        return {}


def sidecar_path(tsv_path: Path) -> Path:
    return Path(str(tsv_path).removesuffix(".tsv.gz") + ".json")


def read_physio_tsv(path: Path) -> pd.DataFrame:
    """Read a BIDS physiology TSV (tab-separated, optionally headerless)."""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        first = handle.readline().rstrip("\n")
    # BIDS physio is tab-separated; never let the csv sniffer invent a delimiter
    # from characters inside a single-column header (e.g. "cardiac").
    tokens = first.split("\t")
    looks_numeric = False
    if tokens:
        try:
            float(tokens[0].replace("n/a", "nan").replace("N/A", "nan"))
            looks_numeric = True
        except ValueError:
            looks_numeric = False

    common = dict(
        sep="\t",
        compression="gzip",
        na_values=["n/a", "N/A", "NA", ""],
        # Single-column files must not be expanded into character columns.
    )
    if looks_numeric:
        df = pd.read_csv(path, header=None, **common)
        df.columns = [f"col_{i}" for i in range(df.shape[1])]
    else:
        df = pd.read_csv(path, header=0, **common)
    # Drop accidental empty columns from trailing tabs.
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed:")]]
    df = df.dropna(axis=1, how="all")
    return df


def infer_channel(
    meta: dict[str, Any],
    entities: dict[str, str | None],
    columns: Sequence[str],
    col_index: int = 0,
) -> tuple[str, str]:
    """Return (recording_type, channel) using the required priority order.

    Priority: JSON Columns → recording entity → SiemensChannel → filename.
    """
    recording = (entities.get("recording") or "").lower()
    siemens = str(meta.get("SiemensChannel") or "").upper()
    fname_blob = " ".join(
        str(x).lower()
        for x in (
            entities.get("recording"),
            Path(str(meta.get("_filename", ""))).name,
            *[str(c) for c in columns],
        )
    )

    # 1) JSON Columns
    json_cols = meta.get("Columns")
    label = None
    if isinstance(json_cols, list) and col_index < len(json_cols):
        label = str(json_cols[col_index]).lower()
    elif col_index < len(columns):
        # named header may already encode the channel
        label = str(columns[col_index]).lower()

    def from_label(lab: str | None) -> str | None:
        if not lab:
            return None
        if any(k in lab for k in ("trigger", "ext", "volume", "scanner")):
            return "trigger"
        if "resp" in lab or "breath" in lab:
            return "respiratory"
        if "ecg" in lab:
            return "ecg"
        if any(k in lab for k in ("cardiac", "pulse", "puls", "ppg", "heart")):
            return "cardiac"
        return None

    channel = from_label(label)

    # 2) recording entity
    if channel is None and recording in CHANNEL_FROM_RECORDING:
        channel = CHANNEL_FROM_RECORDING[recording]

    # 3) SiemensChannel
    if channel is None and siemens in CHANNEL_FROM_SIEMENS:
        channel = CHANNEL_FROM_SIEMENS[siemens]

    # 4) filename / remaining blob
    if channel is None:
        channel = from_label(fname_blob) or "unknown"

    if recording in RECORDING_TYPES:
        recording_type = recording
    elif channel == "cardiac":
        recording_type = "pulse"
    elif channel in RECORDING_TYPES:
        recording_type = channel
    elif len(columns) > 1:
        recording_type = "multi"
    else:
        recording_type = "unknown"

    return recording_type, channel


def extract_sampling_frequency(meta: dict[str, Any]) -> float | None:
    fs = meta.get("SamplingFrequency")
    if fs is not None:
        try:
            val = float(fs)
            if np.isfinite(val) and val > 0:
                return val
        except (TypeError, ValueError):
            pass
    sample_ms = meta.get("SampleTime_ms")
    if sample_ms is not None:
        try:
            ms = float(sample_ms)
            if np.isfinite(ms) and ms > 0:
                return 1000.0 / ms
        except (TypeError, ValueError):
            pass
    return None


def load_physio_records(
    path: Path,
    bids_dir: Path,
    compute_hash: bool = False,
) -> list[PhysioRecord]:
    """Load one physio file into one or more PhysioRecord objects."""
    entities = parse_bids_entities(path)
    rel = relative_to_bids(path, bids_dir)
    meta = load_json(sidecar_path(path))
    meta["_filename"] = path.name
    if compute_hash:
        meta["_sha256"] = optional_file_hash(path, True)

    fs = extract_sampling_frequency(meta)
    start_raw = meta.get("StartTime")
    try:
        start_time = float(start_raw) if start_raw is not None else None
    except (TypeError, ValueError):
        start_time = None
        LOGGER.warning("Invalid StartTime for %s", rel)

    try:
        df = read_physio_tsv(path)
    except OSError as exc:
        LOGGER.error("Corrupt/unreadable physio file %s: %s", rel, exc)
        return [
            PhysioRecord(
                participant_id=entities["participant_id"],
                session_id=entities["session_id"],
                task=entities["task"],
                run=entities["run"],
                recording_type=entities.get("recording") or "unknown",
                channel="unknown",
                file_path_relative=rel,
                signal=np.array([], dtype=np.float64),
                sampling_frequency=fs,
                start_time=start_time,
                metadata=meta,
                error=f"read_error: {exc}",
            )
        ]

    if df.empty:
        LOGGER.warning("Empty physio table: %s", rel)
        rec_type, channel = infer_channel(meta, entities, [])
        return [
            PhysioRecord(
                participant_id=entities["participant_id"],
                session_id=entities["session_id"],
                task=entities["task"],
                run=entities["run"],
                recording_type=rec_type,
                channel=channel,
                file_path_relative=rel,
                signal=np.array([], dtype=np.float64),
                sampling_frequency=fs,
                start_time=start_time,
                metadata=meta,
                error="empty_table",
            )
        ]

    records: list[PhysioRecord] = []
    columns = [str(c) for c in df.columns]

    # recording-* entity ⇒ treat as one primary channel (first/only column).
    # Combined multi-column physio ⇒ one PhysioRecord per column.
    recording_entity = entities.get("recording")
    col_indices = list(range(len(columns)))
    if recording_entity and len(columns) >= 1:
        if len(columns) > 1:
            LOGGER.warning(
                "recording-%s file has %d columns; using primary column %r (%s)",
                recording_entity,
                len(columns),
                columns[0],
                rel,
            )
        col_indices = [0]

    for i in col_indices:
        col = columns[i]
        rec_type, channel = infer_channel(meta, entities, columns, col_index=i)
        if recording_entity in RECORDING_TYPES:
            rec_type = recording_entity
            channel = CHANNEL_FROM_RECORDING.get(recording_entity, channel)
        elif len(columns) > 1:
            if channel in ("respiratory", "trigger", "ecg"):
                rec_type = channel
            elif channel == "cardiac":
                rec_type = "pulse"
            else:
                rec_type = "multi"

        series = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)
        records.append(
            PhysioRecord(
                participant_id=entities["participant_id"],
                session_id=entities["session_id"],
                task=entities["task"],
                run=entities["run"],
                recording_type=rec_type,
                channel=channel,
                file_path_relative=rel if len(col_indices) == 1 else f"{rel}#{col}",
                signal=series,
                sampling_frequency=fs,
                start_time=start_time,
                metadata={
                    **meta,
                    "column_name": col,
                    "StartTimeConfidence": meta.get("StartTimeConfidence"),
                    "SiemensChannel": meta.get("SiemensChannel"),
                },
            )
        )
    return records


# ---------------------------------------------------------------------------
# Signal QC
# ---------------------------------------------------------------------------


def longest_nan_gap_seconds(x: np.ndarray, fs: float | None) -> float:
    if x.size == 0 or fs is None or not np.isfinite(fs) or fs <= 0:
        return float("nan")
    is_nan = ~np.isfinite(x)
    if not is_nan.any():
        return 0.0
    padded = np.concatenate([[False], is_nan, [False]])
    d = np.diff(padded.astype(np.int8))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    if starts.size == 0:
        return 0.0
    return float((ends - starts).max() / fs)


def compute_signal_qc(rec: PhysioRecord) -> SignalQC:
    x = rec.signal
    fs = rec.sampling_frequency
    n = int(x.size)
    duration = (n / fs) if fs and fs > 0 else None
    flags: list[str] = []

    if rec.error:
        flags.append("READ_ERROR")

    if fs is None or not np.isfinite(fs) or fs <= 0:
        flags.append("BAD_SAMPLING")

    if n == 0:
        flags.append("EMPTY")
        return SignalQC(
            sample_count=0,
            duration_seconds=duration,
            n_missing=0,
            nan_fraction=1.0,
            min=None,
            max=None,
            mean=None,
            std=None,
            p01=None,
            p50=None,
            p99=None,
            flags=flags,
            longest_gap_seconds=float("nan"),
        )

    finite = x[np.isfinite(x)]
    n_missing = int(n - finite.size)
    nan_frac = float(n_missing / n)
    gap_s = longest_nan_gap_seconds(x, fs)

    if finite.size == 0:
        flags.append("ALL_NAN")
        return SignalQC(
            sample_count=n,
            duration_seconds=duration,
            n_missing=n_missing,
            nan_fraction=nan_frac,
            min=None,
            max=None,
            mean=None,
            std=None,
            p01=None,
            p50=None,
            p99=None,
            flags=flags,
            longest_gap_seconds=gap_s,
        )

    std = float(np.std(finite, ddof=1)) if finite.size > 1 else 0.0
    if std < FLAT_STD_THRESHOLD:
        flags.append("FLAT_SIGNAL")

    # Saturation: >99% identical values among finite samples.
    vals, counts = np.unique(np.round(finite, 6), return_counts=True)
    if counts.max() / finite.size > SATURATION_FRAC:
        flags.append("SATURATION")

    if np.isfinite(gap_s) and gap_s > LARGE_GAP_SECONDS:
        flags.append("LARGE_GAPS")

    return SignalQC(
        sample_count=n,
        duration_seconds=duration,
        n_missing=n_missing,
        nan_fraction=nan_frac,
        min=float(np.min(finite)),
        max=float(np.max(finite)),
        mean=float(np.mean(finite)),
        std=std,
        p01=float(np.percentile(finite, 1)),
        p50=float(np.percentile(finite, 50)),
        p99=float(np.percentile(finite, 99)),
        flags=flags,
        longest_gap_seconds=gap_s,
    )


# ---------------------------------------------------------------------------
# Trigger QC
# ---------------------------------------------------------------------------


def _find_peaks_numpy(y: np.ndarray, height: float, distance: int) -> np.ndarray:
    if y.size < 3:
        return np.array([], dtype=int)
    cand = (
        np.where((y[1:-1] > y[:-2]) & (y[1:-1] >= y[2:]) & (y[1:-1] >= height))[0] + 1
    )
    if cand.size == 0:
        return cand.astype(int)
    order = cand[np.argsort(y[cand])[::-1]]
    keep: list[int] = []
    taken = np.zeros(y.size, dtype=bool)
    for idx in order:
        lo = max(idx - distance, 0)
        hi = min(idx + distance + 1, y.size)
        if taken[lo:hi].any():
            continue
        keep.append(int(idx))
        taken[lo:hi] = True
    return np.array(sorted(keep), dtype=int)


def detect_trigger_indices(signal: np.ndarray, fs: float | None) -> np.ndarray:
    """Detect volume-onset events with an automatic threshold / rising edges."""
    if signal.size == 0 or not np.isfinite(signal).any():
        return np.array([], dtype=int)
    y = signal.astype(np.float64).copy()
    finite = np.isfinite(y)
    y[~finite] = float(np.nanmedian(y[finite]))

    uniq = np.unique(np.round(y[finite], 6))
    looks_binary = uniq.size <= 4
    if looks_binary:
        lo, hi = float(np.nanmin(y)), float(np.nanmax(y))
        if hi == lo:
            return np.array([], dtype=int)
        thr = lo + 0.5 * (hi - lo)
        binary = (y > thr).astype(np.int8)
        return np.where(np.diff(binary, prepend=0) == 1)[0].astype(int)

    y_z = y - np.nanmedian(y)
    height = max(0.5 * float(np.nanstd(y_z)), 1e-6)
    distance = max(int(0.1 * (fs or 100.0)), 1)
    if sp_signal is not None:
        peaks, _ = sp_signal.find_peaks(y_z, height=height, distance=distance)
        return peaks.astype(int)
    return _find_peaks_numpy(y_z, height=height, distance=distance)


def bold_tr_and_volumes(bold_nii: Path) -> tuple[float | None, int | None]:
    """Read RepetitionTime from sidecar and volume count from NIfTI header."""
    js = load_json(Path(str(bold_nii).removesuffix(".nii.gz") + ".json"))
    tr = None
    if "RepetitionTime" in js:
        try:
            tr = float(js["RepetitionTime"])
        except (TypeError, ValueError):
            tr = None
    nvol = None
    if nib is not None:
        try:
            img = nib.load(str(bold_nii))
            shape = img.shape
            if len(shape) >= 4:
                nvol = int(shape[3])
            else:
                nvol = 1
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not read NIfTI header %s: %s", bold_nii.name, exc)
    return tr, nvol


def compute_trigger_qc(
    rec: PhysioRecord,
    bold_tr: float | None = None,
    n_bold_volumes: int | None = None,
) -> TriggerQC:
    fs = rec.sampling_frequency
    idx = detect_trigger_indices(rec.signal, fs)
    n = int(idx.size)
    if n < 2 or fs is None or fs <= 0:
        status = "FAIL" if n == 0 else ("REVIEW" if n < MIN_TRIGGERS_OK else "PASS")
        return TriggerQC(
            trigger_count=n,
            median_interval=None,
            mean_interval=None,
            std_interval=None,
            estimated_TR=None,
            bold_TR=bold_tr,
            n_bold_volumes=n_bold_volumes,
            TR_difference=None,
            TR_relative_diff=None,
            trigger_status="FAIL" if n == 0 else "REVIEW",
            trigger_indices=idx,
        )

    intervals = np.diff(idx.astype(np.float64)) / fs
    est_tr = float(np.median(intervals))
    mean_i = float(np.mean(intervals))
    std_i = float(np.std(intervals, ddof=1)) if intervals.size > 1 else 0.0
    med_i = float(np.median(intervals))

    tr_diff = None
    tr_rel = None
    status = "PASS"
    if n < MIN_TRIGGERS_OK:
        status = "REVIEW"
    if bold_tr is not None and bold_tr > 0 and np.isfinite(est_tr):
        tr_diff = float(est_tr - bold_tr)
        tr_rel = float(abs(tr_diff) / bold_tr)
        if tr_rel >= TR_MATCH_TOLERANCE:
            status = "REVIEW"
    elif bold_tr is None:
        # No BOLD TR available for comparison — keep interval QC only.
        if status == "PASS" and n >= MIN_TRIGGERS_OK:
            status = "PASS"

    return TriggerQC(
        trigger_count=n,
        median_interval=med_i,
        mean_interval=mean_i,
        std_interval=std_i,
        estimated_TR=est_tr,
        bold_TR=bold_tr,
        n_bold_volumes=n_bold_volumes,
        TR_difference=tr_diff,
        TR_relative_diff=tr_rel,
        trigger_status=status,
        trigger_indices=idx,
    )


# ---------------------------------------------------------------------------
# Quality score
# ---------------------------------------------------------------------------


def physio_quality_score(
    rec: PhysioRecord,
    sqc: SignalQC,
    tqc: TriggerQC | None,
    run_has_trigger_pass: bool,
) -> tuple[int, str]:
    """Score 0–100 for physiological modeling readiness."""
    score = 0
    # +30 signal present (non-empty finite samples)
    if sqc.sample_count > 0 and sqc.nan_fraction < 1.0 and "FLAT_SIGNAL" not in sqc.flags:
        score += 30
    # +20 sampling valid
    if rec.sampling_frequency and rec.sampling_frequency > 0 and "BAD_SAMPLING" not in sqc.flags:
        score += 20
    # +20 timing valid (StartTime present; prefer pre-scan negative)
    if rec.start_time is not None and np.isfinite(rec.start_time):
        score += 15
        if rec.start_time < 0:
            score += 5
    # +20 trigger valid (this file or sibling in run)
    if rec.channel == "trigger" and tqc is not None and tqc.trigger_status == "PASS":
        score += 20
    elif rec.channel != "trigger" and run_has_trigger_pass:
        score += 20
    # +10 absence of large gaps
    if "LARGE_GAPS" not in sqc.flags and "ALL_NAN" not in sqc.flags:
        score += 10

    score = int(max(0, min(100, score)))
    if score >= 80:
        cat = "GOOD"
    elif score >= 50:
        cat = "ACCEPTABLE"
    else:
        cat = "POOR"
    return score, cat


def file_qc_status(sqc: SignalQC, tqc: TriggerQC | None, channel: str) -> str:
    hard = {"READ_ERROR", "EMPTY", "ALL_NAN", "BAD_SAMPLING", "FLAT_SIGNAL", "SATURATION"}
    if hard.intersection(sqc.flags):
        return "FAIL"
    if channel == "trigger":
        if tqc is None or tqc.trigger_status == "FAIL":
            return "FAIL"
        if tqc.trigger_status == "REVIEW" or "LARGE_GAPS" in sqc.flags:
            return "REVIEW"
        return "PASS"
    if "LARGE_GAPS" in sqc.flags:
        return "REVIEW"
    if sqc.duration_seconds is not None and sqc.duration_seconds < MIN_DURATION_SECONDS:
        return "REVIEW"
    return "PASS"


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------


def build_bold_index(
    bold_files: Sequence[Path],
    bids_dir: Path,
) -> dict[tuple, dict[str, Any]]:
    """Map (participant, session, task, run) → BOLD metadata."""
    index: dict[tuple, dict[str, Any]] = {}
    for path in bold_files:
        ent = parse_bids_entities(path)
        key = (ent["participant_id"], ent["session_id"], ent["task"], ent["run"])
        if key in index:
            continue  # first magnitude match wins
        tr, nvol = bold_tr_and_volumes(path)
        duration = (tr * nvol) if (tr and nvol) else None
        index[key] = {
            "bold_path_relative": relative_to_bids(path, bids_dir),
            "bold_TR": tr,
            "n_volumes": nvol,
            "bold_duration": duration,
        }
    return index


def align_physio_bold(
    records: Sequence[PhysioRecord],
    signal_qcs: dict[str, SignalQC],
    bold_index: dict[tuple, dict[str, Any]],
    trigger_by_run: dict[tuple, TriggerQC],
) -> list[dict[str, Any]]:
    """Align physiology to BOLD by participant+session+task+run only."""
    physio_runs: dict[tuple, list[PhysioRecord]] = defaultdict(list)
    for rec in records:
        physio_runs[rec.run_key].append(rec)

    # Session-level physio presence (for SESSION_ONLY detection)
    session_physio: set[tuple[str | None, str | None]] = {
        (r.participant_id, r.session_id) for r in records
    }

    rows: list[dict[str, Any]] = []
    all_keys = set(bold_index) | set(physio_runs)

    for key in sorted(all_keys, key=lambda k: tuple(str(x) for x in k)):
        participant, session, task, run = key
        bold = bold_index.get(key)
        precs = physio_runs.get(key, [])

        if bold and precs:
            # Max physio duration among channels for this run
            durations = []
            for r in precs:
                sqc = signal_qcs.get(r.file_path_relative)
                if sqc and sqc.duration_seconds is not None:
                    durations.append(sqc.duration_seconds)
            physio_duration = max(durations) if durations else None
            bold_duration = bold.get("bold_duration")
            dur_diff = (
                float(physio_duration - bold_duration)
                if (physio_duration is not None and bold_duration is not None)
                else None
            )
            tqc = trigger_by_run.get(key)
            tr_match = None
            if tqc and tqc.TR_relative_diff is not None:
                tr_match = bool(tqc.TR_relative_diff < TR_MATCH_TOLERANCE)
            elif tqc and tqc.estimated_TR is not None and bold.get("bold_TR"):
                rel = abs(tqc.estimated_TR - bold["bold_TR"]) / bold["bold_TR"]
                tr_match = bool(rel < TR_MATCH_TOLERANCE)

            start_times = [r.start_time for r in precs if r.start_time is not None]
            start_time = start_times[0] if start_times else None

            status = "PASS"
            if tr_match is False:
                status = "WARNING"
            if dur_diff is not None and bold_duration and abs(dur_diff) > max(10.0, 0.2 * bold_duration):
                status = "WARNING"

            rows.append(
                {
                    "participant": participant,
                    "session": session,
                    "task": task,
                    "run": run,
                    "bold_duration": bold_duration,
                    "physio_duration": physio_duration,
                    "duration_difference": dur_diff,
                    "StartTime": start_time,
                    "TR_match": tr_match,
                    "alignment_status": status,
                }
            )
        elif bold and not precs:
            # Physio elsewhere in session?
            if (participant, session) in session_physio:
                status = "SESSION_ONLY"
            else:
                status = "NO_MATCH"
            rows.append(
                {
                    "participant": participant,
                    "session": session,
                    "task": task,
                    "run": run,
                    "bold_duration": bold.get("bold_duration") if bold else None,
                    "physio_duration": None,
                    "duration_difference": None,
                    "StartTime": None,
                    "TR_match": None,
                    "alignment_status": status,
                }
            )
        else:
            # Physio without matched BOLD
            durations = []
            for r in precs:
                sqc = signal_qcs.get(r.file_path_relative)
                if sqc and sqc.duration_seconds is not None:
                    durations.append(sqc.duration_seconds)
            start_times = [r.start_time for r in precs if r.start_time is not None]
            rows.append(
                {
                    "participant": participant,
                    "session": session,
                    "task": task,
                    "run": run,
                    "bold_duration": None,
                    "physio_duration": max(durations) if durations else None,
                    "duration_difference": None,
                    "StartTime": start_times[0] if start_times else None,
                    "TR_match": None,
                    "alignment_status": "NO_MATCH",
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def _run_figure_stem(participant: str, session: str | None, task: str | None, run: str | None) -> str:
    parts = [f"sub-{participant}"]
    if session:
        parts.append(f"ses-{session}")
    if task:
        parts.append(f"task-{task}")
    if run:
        parts.append(f"run-{run}")
    parts.append("physio_qc.png")
    return "_".join(parts)


def make_run_figure(
    run_records: Sequence[PhysioRecord],
    signal_qcs: dict[str, SignalQC],
    trigger_qc: TriggerQC | None,
    score: int,
    out_path: Path,
) -> None:
    """Four-panel QC figure for one BIDS run."""
    # Prefer cardiac/pulse, else resp, else first
    primary = None
    for pref in ("cardiac", "ecg", "respiratory", "trigger"):
        for r in run_records:
            if r.channel == pref and r.signal.size:
                primary = r
                break
        if primary is not None:
            break
    if primary is None and run_records:
        primary = run_records[0]
    if primary is None:
        return

    fs = primary.sampling_frequency or float("nan")
    n = primary.signal.size
    time_s = np.arange(n) / fs if fs and fs > 0 else np.arange(n)

    trig_rec = next((r for r in run_records if r.channel == "trigger"), None)
    sqc = signal_qcs.get(primary.file_path_relative)

    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)

    # Panel 1 — raw signal
    ax = axes[0, 0]
    ax.plot(time_s, primary.signal, lw=0.5, color="#1f4e79")
    ax.set_title(f"Raw signal ({primary.channel})")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude (a.u.)")

    # Panel 2 — amplitude distribution
    ax = axes[0, 1]
    finite = primary.signal[np.isfinite(primary.signal)]
    if finite.size:
        ax.hist(finite, bins=60, color="#4c78a8", edgecolor="none")
    ax.set_title("Amplitude distribution")
    ax.set_xlabel("Amplitude")
    ax.set_ylabel("Count")

    # Panel 3 — trigger train
    ax = axes[1, 0]
    if trig_rec is not None and trig_rec.signal.size:
        tfs = trig_rec.sampling_frequency or fs
        tt = np.arange(trig_rec.signal.size) / tfs if tfs and tfs > 0 else np.arange(trig_rec.signal.size)
        ax.plot(tt, trig_rec.signal, lw=0.4, color="#666666")
        if trigger_qc is not None and trigger_qc.trigger_indices.size:
            idx = trigger_qc.trigger_indices
            idx = idx[idx < trig_rec.signal.size]
            ax.vlines(tt[idx], ymin=np.nanmin(trig_rec.signal), ymax=np.nanmax(trig_rec.signal),
                      colors="#c44e52", lw=0.6, alpha=0.7)
        ax.set_title("Trigger train")
    else:
        ax.text(0.5, 0.5, "No trigger channel", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Trigger train")
    ax.set_xlabel("Time (s)")

    # Panel 4 — text summary
    ax = axes[1, 1]
    ax.axis("off")
    est_tr = trigger_qc.estimated_TR if trigger_qc else None
    bold_tr = trigger_qc.bold_TR if trigger_qc else None
    lines = [
        f"sub-{primary.participant_id}  ses-{primary.session_id or 'n/a'}",
        f"task-{primary.task or 'n/a'}  run-{primary.run or 'n/a'}",
        "",
        f"SamplingFrequency : {fs:g} Hz" if fs and np.isfinite(fs) else "SamplingFrequency : n/a",
        f"Duration          : {sqc.duration_seconds:.2f} s" if sqc and sqc.duration_seconds else "Duration          : n/a",
        f"StartTime         : {primary.start_time:.4f} s" if primary.start_time is not None else "StartTime         : n/a",
        f"TR (physio)       : {est_tr:.4f} s" if est_tr is not None else "TR (physio)       : n/a",
        f"TR (BOLD)         : {bold_tr:.4f} s" if bold_tr is not None else "TR (BOLD)         : n/a",
        f"Quality score     : {score}/100",
        f"Flags             : {', '.join(sqc.flags) if sqc and sqc.flags else 'none'}",
    ]
    ax.text(0.0, 1.0, "\n".join(lines), va="top", ha="left", family="monospace", fontsize=9)

    fig.suptitle("Physiology QC", fontsize=12)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def make_dataset_summary_figure(
    summary_df: pd.DataFrame,
    trigger_df: pd.DataFrame,
    out_path: Path,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)

    # 1. Files per channel
    ax = axes[0, 0]
    if not summary_df.empty and "channel" in summary_df.columns:
        counts = summary_df["channel"].value_counts()
        ax.bar(counts.index.astype(str), counts.values, color="#4c78a8")
    ax.set_title("Files per channel")
    ax.tick_params(axis="x", rotation=30)
    ax.set_ylabel("Count")

    # 2. PASS / REVIEW / FAIL
    ax = axes[0, 1]
    if not summary_df.empty and "qc_status" in summary_df.columns:
        counts = summary_df["qc_status"].value_counts().reindex(
            ["PASS", "REVIEW", "FAIL"], fill_value=0
        )
        colors = {"PASS": "#59a14f", "REVIEW": "#f28e2b", "FAIL": "#e15759"}
        ax.bar(counts.index, counts.values, color=[colors[k] for k in counts.index])
    ax.set_title("QC status")
    ax.set_ylabel("Count")

    # 3. Quality by task
    ax = axes[1, 0]
    if not summary_df.empty and "task" in summary_df.columns:
        tasks = [t for t in SUPPORTED_TASKS if t in set(summary_df["task"].dropna().astype(str))]
        if not tasks:
            tasks = sorted(summary_df["task"].dropna().astype(str).unique())
        cats = ["GOOD", "ACCEPTABLE", "POOR"]
        x = np.arange(len(tasks))
        width = 0.25
        for i, cat in enumerate(cats):
            vals = []
            for t in tasks:
                sub = summary_df[summary_df["task"].astype(str) == t]
                vals.append(int((sub["PhysioQualityCategory"] == cat).sum()))
            ax.bar(x + i * width, vals, width, label=cat)
        ax.set_xticks(x + width)
        ax.set_xticklabels(tasks)
        ax.legend(fontsize=8, frameon=False)
    ax.set_title("Quality by task")
    ax.set_ylabel("Count")

    # 4. Estimated TR histogram
    ax = axes[1, 1]
    if not trigger_df.empty and "estimated_TR" in trigger_df.columns:
        trs = pd.to_numeric(trigger_df["estimated_TR"], errors="coerce").dropna()
        if len(trs):
            ax.hist(trs, bins=30, color="#76b7b2", edgecolor="none")
    ax.set_title("Estimated TR (physio triggers)")
    ax.set_xlabel("TR (s)")
    ax.set_ylabel("Count")

    fig.suptitle("Dataset physiology QC summary", fontsize=13)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def write_markdown_report(
    out_path: Path,
    bids_dir: Path,
    summary_df: pd.DataFrame,
    align_df: pd.DataFrame,
    trigger_df: pd.DataFrame,
    start_df: pd.DataFrame,
    n_bold: int,
) -> None:
    n_files = len(summary_df)
    n_sub = summary_df["participant_id"].nunique() if n_files else 0
    n_ses = (
        summary_df[["participant_id", "session_id"]].drop_duplicates().shape[0]
        if n_files
        else 0
    )
    covered = 0
    if not align_df.empty:
        covered = int(
            ((align_df["alignment_status"] == "PASS") | (align_df["alignment_status"] == "WARNING")).sum()
        )

    def channel_pass(ch_names: Sequence[str]) -> tuple[int, int, int]:
        sub = summary_df[summary_df["channel"].isin(ch_names)]
        return (
            int((sub["qc_status"] == "PASS").sum()),
            int((sub["qc_status"] == "REVIEW").sum()),
            int((sub["qc_status"] == "FAIL").sum()),
        )

    pulse_p, pulse_r, pulse_f = channel_pass(["cardiac"])
    resp_p, resp_r, resp_f = channel_pass(["respiratory"])
    trig_p, trig_r, trig_f = channel_pass(["trigger"])

    # Automatic limitation flags
    limitations: list[str] = []
    if not summary_df.empty:
        # EXT-only: runs where only trigger exists (Siemens EXT) without pulse/resp
        by_run = summary_df.groupby(
            ["participant_id", "session_id", "task", "run"], dropna=False
        )["channel"].apply(set)
        ext_only = sum(
            1 for chs in by_run if chs == {"trigger"} or chs == {"trigger", "unknown"}
        )
        if ext_only:
            limitations.append(
                f"EXT-only / trigger-only runs (no pulse or respiratory): {ext_only}"
            )
        n_missing_st = int(summary_df["StartTime"].isna().sum())
        if n_missing_st:
            limitations.append(f"Missing StartTime on {n_missing_st} physio file(s)")
        for ch in ("cardiac", "respiratory", "trigger"):
            if ch not in set(summary_df["channel"].dropna()):
                limitations.append(f"Missing channel entirely in inventory: {ch}")
        siemens = summary_df.get("SiemensChannel")
        if siemens is not None and (siemens.astype(str).str.upper() == "EXT").any():
            limitations.append(
                "Siemens EXT trigger channels present; cardiac/respiratory must be "
                "assessed separately for RETROICOR eligibility"
            )
    limitations.append(
        "Peripheral PMU session-wide vendor logs (`.ecg/.resp/.puls`) are excluded "
        "from BIDS conversion under the project fail-closed policy and are not "
        "inventoried here"
    )
    if not align_df.empty:
        n_session_only = int((align_df["alignment_status"] == "SESSION_ONLY").sum())
        if n_session_only:
            limitations.append(
                f"SESSION_ONLY alignments (physio in session but not matched by "
                f"task+run): {n_session_only} — never use session-only pairing"
            )

    conf_lines = ""
    if not start_df.empty:
        for _, row in start_df.iterrows():
            conf_lines += f"| {row['confidence']} | {row['n_files']} |\n"

    text = f"""# Physiology QC Report

Read-only QC of BIDS physiological recordings. All paths below are relative to
the dataset root. Absolute filesystem locations are intentionally omitted (PHI-safe).

## Dataset size

| Metric | Value |
| --- | ---: |
| BIDS root (relative) | `{bids_dir.name}` |
| Subjects with physio | {n_sub} |
| Subject–session pairs | {n_ses} |
| Physio files (channels) | {n_files} |
| Magnitude BOLD runs scanned | {n_bold} |
| BOLD runs with physio alignment (PASS/WARNING) | {covered} |

## Channel QC summary

| Channel | PASS | REVIEW | FAIL |
| --- | ---: | ---: | ---: |
| Pulse / cardiac | {pulse_p} | {pulse_r} | {pulse_f} |
| Respiratory | {resp_p} | {resp_r} | {resp_f} |
| Trigger | {trig_p} | {trig_r} | {trig_f} |

Pulse: **{pulse_p} PASS**  
Resp: **{resp_p} PASS**  
Trigger: **{trig_p} PASS**

## StartTime confidence

| Confidence | n_files |
| --- | ---: |
{conf_lines if conf_lines else "| (none) | 0 |"}

## Outputs

- `physiology_inventory.tsv`
- `physiology_qc_summary.tsv` / `.json`
- `physio_bold_alignment.tsv`
- `trigger_qc.tsv`
- `starttime_summary.tsv`
- `figures/` (per-run QC PNGs)
- `dataset_physio_summary.png`

## Limitations

"""
    for item in limitations:
        text += f"- {item}\n"

    text += """
## Methods notes

Physiological QC is performed because cardiac/respiratory nuisance models
(RETROICOR and related) require continuous, correctly timed waveforms. Volume
triggers (or a validated negative `StartTime`) synchronize physiology to BOLD;
without them, phase regressors are misaligned. Large missing segments break
within-run phase estimation and should not be used for modeling without review.
"""
    out_path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def write_tsv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, sep="\t", index=False, na_rep="n/a")


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        return None if not np.isfinite(obj) else obj
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if not np.isfinite(v) else v
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    bids_dir: Path,
    output_dir: Path,
    tasks: Sequence[str] | None = None,
    overwrite: bool = False,
    compute_hash: bool = False,
    max_figures: int | None = None,
) -> dict[str, Any]:
    """Execute the full physiology QC pipeline (read-only on BIDS)."""
    bids_dir = bids_dir.resolve()
    output_dir = output_dir.resolve()

    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        LOGGER.warning(
            "Output directory is not empty; writing alongside existing files "
            "(use --overwrite to replace figures aggressively)."
        )
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    if sp_signal is None:
        LOGGER.warning("SciPy unavailable; NumPy peak detection will be used for analog triggers")
    if nib is None:
        LOGGER.warning("nibabel unavailable; BOLD volume counts / durations will be limited")

    physio_paths = discover_physio_files(bids_dir, tasks)
    bold_paths = discover_bold_files(bids_dir, tasks)
    LOGGER.info("Discovered %d physio file(s), %d magnitude BOLD run(s)", len(physio_paths), len(bold_paths))

    # --- Load records -------------------------------------------------------
    records: list[PhysioRecord] = []
    for i, path in enumerate(physio_paths, 1):
        if i % 200 == 0 or i == 1:
            LOGGER.info("Loading physio [%d/%d]", i, len(physio_paths))
        records.extend(load_physio_records(path, bids_dir, compute_hash=compute_hash))

    # --- Inventory ----------------------------------------------------------
    inv_rows = []
    for rec in records:
        inv_rows.append(
            {
                "participant_id": rec.participant_id,
                "session_id": rec.session_id,
                "task": rec.task,
                "run": rec.run,
                "recording_type": rec.recording_type,
                "channel": rec.channel,
                "file_path_relative": rec.file_path_relative.split("#", 1)[0],
                "sampling_frequency": rec.sampling_frequency,
                "sample_count": int(rec.signal.size),
                "duration_seconds": (
                    (len(rec.signal) / rec.sampling_frequency)
                    if rec.sampling_frequency and rec.sampling_frequency > 0
                    else None
                ),
                "StartTime": rec.start_time,
                "StartTimeConfidence": rec.metadata.get("StartTimeConfidence"),
                "SiemensChannel": rec.metadata.get("SiemensChannel"),
            }
        )
    inventory_df = pd.DataFrame(inv_rows)
    write_tsv(inventory_df, output_dir / "physiology_inventory.tsv")

    # --- Bold index ---------------------------------------------------------
    LOGGER.info("Indexing BOLD runs for TR / duration")
    bold_index = build_bold_index(bold_paths, bids_dir)

    # --- Per-file signal QC + triggers --------------------------------------
    signal_qcs: dict[str, SignalQC] = {}
    trigger_by_run: dict[tuple, TriggerQC] = {}
    trigger_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    # Precompute which runs have triggers for scoring pass-2
    triggers_tmp: dict[tuple, PhysioRecord] = {}
    for rec in records:
        if rec.channel == "trigger":
            triggers_tmp[rec.run_key] = rec

    for key, trec in triggers_tmp.items():
        bold_meta = bold_index.get(key, {})
        tqc = compute_trigger_qc(
            trec,
            bold_tr=bold_meta.get("bold_TR"),
            n_bold_volumes=bold_meta.get("n_volumes"),
        )
        trigger_by_run[key] = tqc
        trigger_rows.append(
            {
                "participant_id": trec.participant_id,
                "session_id": trec.session_id,
                "task": trec.task,
                "run": trec.run,
                "file_path_relative": trec.file_path_relative.split("#", 1)[0],
                "trigger_count": tqc.trigger_count,
                "median_interval": tqc.median_interval,
                "mean_interval": tqc.mean_interval,
                "std_interval": tqc.std_interval,
                "estimated_TR": tqc.estimated_TR,
                "bold_TR": tqc.bold_TR,
                "n_bold_volumes": tqc.n_bold_volumes,
                "TR_difference": tqc.TR_difference,
                "TR_relative_diff": tqc.TR_relative_diff,
                "trigger_status": tqc.trigger_status,
            }
        )

    run_trigger_pass = {
        k: (v.trigger_status == "PASS") for k, v in trigger_by_run.items()
    }

    for rec in records:
        sqc = compute_signal_qc(rec)
        signal_qcs[rec.file_path_relative] = sqc
        tqc = trigger_by_run.get(rec.run_key) if rec.channel == "trigger" else None
        # For trigger channel use its own QC; for others use sibling pass flag
        score, category = physio_quality_score(
            rec,
            sqc,
            trigger_by_run.get(rec.run_key),
            run_has_trigger_pass=run_trigger_pass.get(rec.run_key, False),
        )
        status = file_qc_status(sqc, trigger_by_run.get(rec.run_key) if rec.channel == "trigger" else None, rec.channel)
        # Non-trigger files: incorporate sibling trigger into status lightly
        if rec.channel != "trigger" and status == "PASS":
            sibling = trigger_by_run.get(rec.run_key)
            if sibling is None:
                status = "REVIEW"  # modeling without triggers needs StartTime review
            elif sibling.trigger_status == "FAIL":
                status = "REVIEW"

        summary_rows.append(
            {
                "participant_id": rec.participant_id,
                "session_id": rec.session_id,
                "task": rec.task,
                "run": rec.run,
                "recording_type": rec.recording_type,
                "channel": rec.channel,
                "file_path_relative": rec.file_path_relative.split("#", 1)[0],
                "sampling_frequency": rec.sampling_frequency,
                "sample_count": sqc.sample_count,
                "duration_seconds": sqc.duration_seconds,
                "StartTime": rec.start_time,
                "StartTimeConfidence": rec.metadata.get("StartTimeConfidence"),
                "SiemensChannel": rec.metadata.get("SiemensChannel"),
                "nan_fraction": sqc.nan_fraction,
                "min": sqc.min,
                "max": sqc.max,
                "mean": sqc.mean,
                "std": sqc.std,
                "p01": sqc.p01,
                "p50": sqc.p50,
                "p99": sqc.p99,
                "flags": "|".join(sqc.flags) if sqc.flags else "",
                "PhysioQualityScore": score,
                "PhysioQualityCategory": category,
                "qc_status": status,
                "longest_gap_seconds": sqc.longest_gap_seconds,
                "error": rec.error,
                "sha256": rec.metadata.get("_sha256"),
            }
        )

    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        # Public TSV without internal hash column
        public_cols = [c for c in SUMMARY_COLUMNS if c in summary_df.columns]
        write_tsv(summary_df[public_cols], output_dir / "physiology_qc_summary.tsv")
    else:
        write_tsv(pd.DataFrame(columns=SUMMARY_COLUMNS), output_dir / "physiology_qc_summary.tsv")

    trigger_df = pd.DataFrame(trigger_rows)
    write_tsv(trigger_df, output_dir / "trigger_qc.tsv")

    # --- Alignment ----------------------------------------------------------
    align_rows = align_physio_bold(records, signal_qcs, bold_index, trigger_by_run)
    align_df = pd.DataFrame(align_rows)
    write_tsv(align_df, output_dir / "physio_bold_alignment.tsv")

    # --- StartTime summary --------------------------------------------------
    conf_counter: Counter[str] = Counter()
    for rec in records:
        conf = rec.metadata.get("StartTimeConfidence")
        if rec.start_time is None:
            conf_counter["MISSING"] += 1
        elif conf in ("HIGH", "MEDIUM", "LOW"):
            conf_counter[str(conf)] += 1
        elif conf:
            conf_counter[str(conf).upper()] += 1
        else:
            conf_counter["MISSING"] += 1
    start_df = pd.DataFrame(
        [{"confidence": k, "n_files": conf_counter[k]} for k in ("HIGH", "MEDIUM", "LOW", "MISSING")]
    )
    write_tsv(start_df, output_dir / "starttime_summary.tsv")

    # --- Figures per run ----------------------------------------------------
    by_run: dict[tuple, list[PhysioRecord]] = defaultdict(list)
    for rec in records:
        by_run[rec.run_key].append(rec)

    # Run-level score = max channel score
    score_by_run: dict[tuple, int] = {}
    if not summary_df.empty:
        for key, grp in summary_df.groupby(
            ["participant_id", "session_id", "task", "run"], dropna=False
        ):
            score_by_run[tuple(key)] = int(grp["PhysioQualityScore"].max())

    n_fig = 0
    for key, run_recs in sorted(by_run.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        if max_figures is not None and n_fig >= max_figures:
            LOGGER.info("Reached max_figures=%d; stopping figure generation", max_figures)
            break
        participant, session, task, run = key
        if participant is None:
            continue
        # Skip fully failed empty runs
        if not any(r.signal.size for r in run_recs):
            continue
        stem = _run_figure_stem(participant, session, task, run)
        fig_path = figures_dir / stem
        if fig_path.exists() and not overwrite:
            n_fig += 1
            continue
        try:
            make_run_figure(
                run_recs,
                signal_qcs,
                trigger_by_run.get(key),
                score_by_run.get(key, 0),
                fig_path,
            )
            n_fig += 1
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Figure failed for %s: %s", stem, exc)

    LOGGER.info("Wrote %d run QC figure(s)", n_fig)

    # --- Dataset summary figure --------------------------------------------
    make_dataset_summary_figure(
        summary_df, trigger_df, output_dir / "dataset_physio_summary.png"
    )

    # --- JSON summary (may include optional hashes) ------------------------
    json_payload = {
        "description": (
            "Physiology QC summary for BIDS recordings. Paths are relative to "
            "the BIDS dataset root. Optional sha256 fields are for internal "
            "traceability only."
        ),
        "bids_dir_name": bids_dir.name,
        "n_physio_files": len(physio_paths),
        "n_physio_channels": len(records),
        "n_bold_runs": len(bold_index),
        "n_figures": n_fig,
        "qc_status_counts": summary_df["qc_status"].value_counts().to_dict()
        if not summary_df.empty
        else {},
        "records": _json_safe(summary_rows),
    }
    with open(output_dir / "physiology_qc_summary.json", "w", encoding="utf-8") as handle:
        json.dump(json_payload, handle, indent=2, allow_nan=False)

    write_markdown_report(
        output_dir / "PHYSIOLOGY_QC_REPORT.md",
        bids_dir,
        summary_df,
        align_df,
        trigger_df,
        start_df,
        n_bold=len(bold_index),
    )

    n_pass = int((summary_df["qc_status"] == "PASS").sum()) if not summary_df.empty else 0
    n_review = int((summary_df["qc_status"] == "REVIEW").sum()) if not summary_df.empty else 0
    n_fail = int((summary_df["qc_status"] == "FAIL").sum()) if not summary_df.empty else 0

    stats = {
        "n_files_analyzed": len(records),
        "n_pass": n_pass,
        "n_review": n_review,
        "n_fail": n_fail,
        "n_excluded": int(summary_df["error"].notna().sum()) if not summary_df.empty and "error" in summary_df else 0,
        "n_figures": n_fig,
        "output_dir": str(output_dir),
    }
    return stats


# ---------------------------------------------------------------------------
# Smoke test / synthetic fixtures
# ---------------------------------------------------------------------------


def write_synthetic_bids(root: Path) -> Path:
    """Create a minimal BIDS tree with pulse/resp/trigger and matching BOLD."""
    bids = root / "bids"
    func = bids / "sub-001" / "ses-01" / "func"
    func.mkdir(parents=True, exist_ok=True)

    fs = 50.0
    tr = 2.0
    n_vol = 30
    dur = n_vol * tr
    n = int(fs * dur)
    t = np.arange(n) / fs
    rng = np.random.default_rng(0)

    pulse = np.sin(2 * np.pi * 1.2 * t) + 0.05 * rng.normal(size=n)
    resp = np.sin(2 * np.pi * 0.25 * t) + 0.02 * rng.normal(size=n)
    trig = np.zeros(n)
    onsets = (np.arange(n_vol) * tr * fs).astype(int)
    onsets = onsets[onsets < n]
    trig[onsets] = 1

    def write_channel(recording: str, column: str, siemens: str, data: np.ndarray, sfreq: float) -> None:
        stem = f"sub-001_ses-01_task-rest_run-01_recording-{recording}_physio"
        with gzip.open(func / f"{stem}.tsv.gz", "wt") as handle:
            handle.write(f"{column}\n")
            for v in data:
                handle.write(f"{v:.6f}\n")
        meta = {
            "SamplingFrequency": sfreq,
            "SampleTime_ms": 1000.0 / sfreq,
            "StartTime": -4.0,
            "StartTimeConfidence": "HIGH",
            "Columns": [column],
            "SiemensChannel": siemens,
        }
        (func / f"{stem}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    write_channel("pulse", "cardiac", "PULS", pulse, fs)
    write_channel("respiratory", "respiratory", "RESP", resp, fs)
    write_channel("trigger", "trigger", "EXT", trig, fs)

    # Minimal BOLD NIfTI + JSON
    if nib is None:
        raise RuntimeError("nibabel is required for --smoke-test")
    bold_shape = (4, 4, 4, n_vol)
    bold_data = rng.normal(size=bold_shape).astype(np.float32)
    bold_path = func / "sub-001_ses-01_task-rest_run-01_bold.nii.gz"
    nib.save(nib.Nifti1Image(bold_data, np.eye(4)), str(bold_path))
    (func / "sub-001_ses-01_task-rest_run-01_bold.json").write_text(
        json.dumps({"RepetitionTime": tr, "TaskName": "rest"}, indent=2),
        encoding="utf-8",
    )
    (bids / "dataset_description.json").write_text(
        json.dumps({"Name": "physio-qc-smoke", "BIDSVersion": "1.8.0"}, indent=2),
        encoding="utf-8",
    )
    return bids


def run_smoke_test() -> int:
    """Generate synthetic physio (30 triggers, TR=2 s) and assert PASS."""
    with tempfile.TemporaryDirectory(prefix="physio_qc_smoke_") as tmp:
        root = Path(tmp)
        bids = write_synthetic_bids(root)
        out = root / "derivatives" / "physiology_qc"
        stats = run_pipeline(bids, out, tasks=["rest"], overwrite=True)
        summary = pd.read_csv(out / "physiology_qc_summary.tsv", sep="\t")
        trigger = pd.read_csv(out / "trigger_qc.tsv", sep="\t")

        assert len(summary) >= 3, summary
        assert (summary["qc_status"] == "PASS").any(), summary["qc_status"].tolist()
        assert int(trigger.iloc[0]["trigger_count"]) == 30, trigger.iloc[0].to_dict()
        est = float(trigger.iloc[0]["estimated_TR"])
        assert abs(est - 2.0) < 0.05, est
        assert trigger.iloc[0]["trigger_status"] == "PASS", trigger.iloc[0].to_dict()
        assert (out / "PHYSIOLOGY_QC_REPORT.md").is_file()
        assert (out / "dataset_physio_summary.png").is_file()
        print("SMOKE TEST PASS")
        print(f"  files analyzed : {stats['n_files_analyzed']}")
        print(f"  PASS           : {stats['n_pass']}")
        print(f"  trigger_count  : {int(trigger.iloc[0]['trigger_count'])}")
        print(f"  estimated_TR   : {est}")
        return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read-only BIDS physiology QC pipeline (Scientific Data ready).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--bids_dir", type=Path, help="BIDS dataset root (read-only).")
    p.add_argument(
        "--output_dir",
        type=Path,
        default=Path("derivatives/physiology_qc"),
        help="Derivative output directory.",
    )
    p.add_argument(
        "--task",
        action="append",
        dest="tasks",
        choices=list(SUPPORTED_TASKS),
        help="Restrict to task (repeatable): rest, fmri, movie.",
    )
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing figures.")
    p.add_argument("--verbose", action="store_true", help="DEBUG logging.")
    p.add_argument(
        "--hash",
        action="store_true",
        dest="compute_hash",
        help="Compute optional SHA-256 hashes for internal JSON traceability.",
    )
    p.add_argument(
        "--max-figures",
        type=int,
        default=None,
        help="Optional cap on per-run QC figures (useful on large datasets).",
    )
    p.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run synthetic self-test (30 triggers, TR=2s) and exit.",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")

    if args.smoke_test:
        return run_smoke_test()

    if args.bids_dir is None:
        parser.error("--bids_dir is required unless --smoke-test is set")

    bids_dir = args.bids_dir
    if not bids_dir.is_dir():
        LOGGER.error("BIDS directory not found: %s", bids_dir)
        return 1

    # Refuse to write into the BIDS input tree.
    out = args.output_dir
    try:
        out_res = out.resolve()
        bids_res = bids_dir.resolve()
        if out_res == bids_res or bids_res in out_res.parents and "derivatives" not in out_res.parts:
            # Allow output_dir == bids/derivatives/... ; block writing over raw bids data dirs.
            pass
        if any(out_res.parts[i:i + 1] == ("raw_original",) for i in range(len(out_res.parts))):
            LOGGER.error("Refusing to write under raw_original/")
            return 1
    except OSError:
        pass

    stats = run_pipeline(
        bids_dir=bids_dir,
        output_dir=out,
        tasks=args.tasks,
        overwrite=args.overwrite,
        compute_hash=args.compute_hash,
        max_figures=args.max_figures,
    )

    print()
    print("=" * 60)
    print("Physiology QC complete (read-only on BIDS)")
    print("=" * 60)
    print(f"Number of files analyzed : {stats['n_files_analyzed']}")
    print(f"Number PASS              : {stats['n_pass']}")
    print(f"Number REVIEW            : {stats['n_review']}")
    print(f"Number FAIL              : {stats['n_fail']}")
    print(f"Number excluded          : {stats['n_excluded']}")
    print(f"Figures written          : {stats['n_figures']}")
    print(f"Output directory         : {out}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
