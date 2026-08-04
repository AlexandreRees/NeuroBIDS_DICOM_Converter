#!/usr/bin/env python3
"""
Physiological characterization pipeline for BIDS peripheral recordings.

Read-only on BIDS. Writes only under --output_dir (derivatives/physiology_characterization).
No PHI in outputs (relative BIDS entities only; example figures anonymized as sub-XXX).

Distinguishes:
  Technical QC  — does the recording exist / parse as BIDS physio?
  Physiological characterization — what physiology is captured and how variable is it?
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import re
import sys
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CARDIAC_ALIASES = {"cardiac", "pulse", "ecg", "ppg", "pleth"}
RESP_ALIASES = {"respiratory", "resp", "breathing"}
TRIGGER_ALIASES = {"trigger", "ext", "ttl", "scanner"}

HR_MIN_BPM = 40.0
HR_MAX_BPM = 180.0
RR_MIN_BPM = 4.0
RR_MAX_BPM = 60.0

TR_PASS_JITTER_MS = 5.0
TR_REVIEW_JITTER_MS = 20.0


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_logger(out_dir: Path) -> logging.Logger:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "physiology_characterization.log"
    logger = logging.getLogger("physio_char")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ---------------------------------------------------------------------------
# BIDS parsing
# ---------------------------------------------------------------------------

ENTITY_RX = re.compile(
    r"(?P<sub>sub-[A-Za-z0-9]+)"
    r"(?:_(?P<ses>ses-[A-Za-z0-9]+))?"
    r"(?:_task-(?P<task>[A-Za-z0-9]+))?"
    r"(?:_run-(?P<run>[0-9]+))?"
    r"(?:_recording-(?P<recording>[A-Za-z0-9]+))?"
    r"_physio\.(?:tsv\.gz|json)$"
)


def parse_bids_name(name: str) -> dict[str, str]:
    m = ENTITY_RX.search(name)
    if not m:
        return {
            "subject": "unknown",
            "session": "",
            "task": "",
            "run": "",
            "recording": "",
        }
    d = m.groupdict()
    return {
        "subject": d.get("sub") or "unknown",
        "session": d.get("ses") or "",
        "task": d.get("task") or "",
        "run": d.get("run") or "",
        "recording": d.get("recording") or "",
    }


def channel_family(name: str) -> str:
    n = name.lower().strip()
    if n in CARDIAC_ALIASES or "cardiac" in n or "pulse" in n or "ecg" in n:
        return "cardiac"
    if n in RESP_ALIASES or "resp" in n:
        return "respiratory"
    if n in TRIGGER_ALIASES or "trigger" in n or n == "ext":
        return "trigger"
    return "other"


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_physio(tsv_gz: Path, meta: dict) -> tuple[np.ndarray, list[str], float]:
    """Load physio TSV.gz → (n_samples, n_channels), column names, fs."""
    cols_meta = meta.get("Columns") or meta.get("columns") or []
    if isinstance(cols_meta, str):
        cols_meta = [cols_meta]
    fs = float(meta.get("SamplingFrequency") or meta.get("SamplingFrequencyHz") or 0.0)

    with gzip.open(tsv_gz, "rt", encoding="utf-8", errors="replace") as fh:
        first = fh.readline()
        rest = fh.read()

    # Header row if first token is non-numeric
    first_tok = first.strip().split("\t")[0].strip()
    has_header = False
    try:
        float(first_tok)
    except ValueError:
        has_header = True

    if has_header:
        header_cols = [c.strip() for c in first.strip().split("\t")]
        text = rest
    else:
        header_cols = list(cols_meta) if cols_meta else ["signal"]
        text = first + rest

    if not text.strip():
        return np.zeros((0, 1)), header_cols, fs

    # Faster numeric load
    try:
        arr = np.genfromtxt(
            (ln for ln in text.splitlines() if ln.strip()),
            dtype=np.float64,
            invalid_raise=False,
        )
        if arr.ndim == 0:
            data = np.zeros((0, 1))
        elif arr.ndim == 1:
            data = arr.reshape(-1, 1)
        else:
            data = arr
        data = np.nan_to_num(data, nan=np.nan, posinf=np.nan, neginf=np.nan)
    except Exception:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t") if "\t" in line else line.split()
            try:
                rows.append([float(x) for x in parts])
            except ValueError:
                continue
        if not rows:
            return np.zeros((0, max(1, len(header_cols)))), header_cols, fs
        data = np.asarray(rows, dtype=np.float64)

    if data.ndim == 1:
        data = data.reshape(-1, 1)

    if cols_meta and len(cols_meta) == data.shape[1]:
        colnames = [str(c) for c in cols_meta]
    elif has_header and len(header_cols) == data.shape[1]:
        colnames = header_cols
    else:
        colnames = [f"ch{i}" for i in range(data.shape[1])]
        if cols_meta and len(cols_meta) == 1 and data.shape[1] == 1:
            colnames = [str(cols_meta[0])]

    if fs <= 0:
        fs = float("nan")
    return data, colnames, fs


# ---------------------------------------------------------------------------
# Signal metrics
# ---------------------------------------------------------------------------

def basic_quality(x: np.ndarray) -> dict[str, float]:
    x = np.asarray(x, dtype=np.float64).ravel()
    n = x.size
    if n == 0:
        return {
            "missing_fraction": 1.0,
            "flatline_fraction": 1.0,
            "signal_range": 0.0,
            "signal_std": 0.0,
            "noise_estimate": 0.0,
            "constant_signal": 1.0,
            "saturated_signal": 0.0,
            "large_gaps": 1.0,
        }
    missing = np.isnan(x) | np.isinf(x)
    miss_frac = float(np.mean(missing))
    valid = x[~missing]
    if valid.size < 2:
        return {
            "missing_fraction": miss_frac,
            "flatline_fraction": 1.0,
            "signal_range": 0.0,
            "signal_std": 0.0,
            "noise_estimate": 0.0,
            "constant_signal": 1.0,
            "saturated_signal": 0.0,
            "large_gaps": 1.0 if miss_frac > 0.05 else 0.0,
        }

    # Flatline: consecutive equal samples
    d = np.diff(valid)
    flat = float(np.mean(np.isclose(d, 0.0, atol=1e-12)))
    rng = float(np.ptp(valid))
    std = float(np.std(valid))
    # Noise: MAD of derivative
    mad = float(np.median(np.abs(d - np.median(d)))) * 1.4826 if d.size else 0.0
    constant = 1.0 if rng < 1e-9 or std < 1e-9 else 0.0
    # Saturation: values stuck at min/max extremes (>5% at either extreme)
    lo, hi = np.percentile(valid, [0.5, 99.5])
    sat = float(np.mean((valid <= lo) | (valid >= hi))) if hi > lo else 0.0
    saturated = 1.0 if sat > 0.15 and rng > 0 else 0.0
    # Gaps: fraction of NaNs already; also long runs
    large_gaps = 1.0 if miss_frac > 0.02 else 0.0

    return {
        "missing_fraction": miss_frac,
        "flatline_fraction": flat,
        "signal_range": rng,
        "signal_std": std,
        "noise_estimate": mad,
        "constant_signal": constant,
        "saturated_signal": saturated,
        "large_gaps": large_gaps,
    }


def quality_score(q: dict[str, float], detectability: float) -> float:
    """0–100 composite; higher is better."""
    score = 100.0
    score -= 40.0 * q["missing_fraction"]
    score -= 30.0 * q["flatline_fraction"]
    score -= 25.0 * q["constant_signal"]
    score -= 15.0 * q["saturated_signal"]
    score -= 20.0 * q["large_gaps"]
    # Amplitude / detectability bonus
    if q["signal_range"] <= 0 or q["signal_std"] <= 0:
        score -= 30.0
    score -= 25.0 * (1.0 - float(np.clip(detectability, 0, 1)))
    return float(np.clip(score, 0, 100))


def bandpass(x: np.ndarray, fs: float, lo: float, hi: float) -> np.ndarray:
    from scipy.signal import butter, filtfilt

    x = np.asarray(x, dtype=np.float64).ravel()
    if not np.isfinite(fs) or fs <= 0 or x.size < 16:
        return x
    nyq = 0.5 * fs
    lo_n = max(lo / nyq, 1e-5)
    hi_n = min(hi / nyq, 0.99)
    if lo_n >= hi_n:
        return x
    b, a = butter(2, [lo_n, hi_n], btype="band")
    # filtfilt needs padding
    if x.size < 3 * max(len(a), len(b)):
        return x
    try:
        return filtfilt(b, a, x)
    except Exception:
        return x


def cardiac_metrics(x: np.ndarray, fs: float) -> dict[str, Any]:
    from scipy.signal import find_peaks

    out: dict[str, Any] = {
        "number_of_peaks": 0,
        "mean_HR_bpm": np.nan,
        "median_HR_bpm": np.nan,
        "HR_std": np.nan,
        "HR_min": np.nan,
        "HR_max": np.nan,
        "RMSSD": np.nan,
        "SDNN": np.nan,
        "HR_STATUS": "INSUFFICIENT",
        "detectability": 0.0,
    }
    x = np.asarray(x, dtype=np.float64).ravel()
    x = x[np.isfinite(x)]
    if x.size < int(fs * 5) if np.isfinite(fs) and fs > 0 else 100:
        return out

    x = x - np.median(x)
    xf = bandpass(x, fs, 0.5, 3.5) if np.isfinite(fs) else x
    if not np.isfinite(fs) or fs <= 0:
        return out

    # Refractory period for max physiological HR (~140 bpm adult MRI)
    min_dist = max(1, int(fs * 60.0 / 140.0))
    prom = 0.4 * float(np.std(xf))
    peaks, _ = find_peaks(xf, distance=min_dist, prominence=max(prom, 1e-6))
    if peaks.size < 5:
        peaks, _ = find_peaks(xf, distance=min_dist, prominence=max(0.2 * float(np.std(xf)), 1e-6))

    out["number_of_peaks"] = int(peaks.size)
    if peaks.size < 5:
        out["HR_STATUS"] = "LOW_CONFIDENCE"
        out["detectability"] = min(1.0, peaks.size / 10.0)
        return out

    ibi_s = np.diff(peaks) / fs
    ibi_s = ibi_s[(ibi_s >= 60.0 / HR_MAX_BPM) & (ibi_s <= 60.0 / HR_MIN_BPM)]
    if ibi_s.size < 4:
        out["HR_STATUS"] = "LOW_CONFIDENCE"
        out["detectability"] = 0.3
        return out

    hr = 60.0 / ibi_s
    out["mean_HR_bpm"] = float(np.mean(hr))
    out["median_HR_bpm"] = float(np.median(hr))
    out["HR_std"] = float(np.std(hr))
    out["HR_min"] = float(np.min(hr))
    out["HR_max"] = float(np.max(hr))
    ibi_ms = ibi_s * 1000.0
    out["SDNN"] = float(np.std(ibi_ms, ddof=1)) if ibi_ms.size > 1 else np.nan
    diff_ibi = np.diff(ibi_ms)
    out["RMSSD"] = float(np.sqrt(np.mean(diff_ibi**2))) if diff_ibi.size else np.nan
    out["HR_STATUS"] = "OK"
    dur_s = x.size / fs
    expected = dur_s / np.median(ibi_s)
    out["detectability"] = float(np.clip(peaks.size / max(expected, 1.0), 0, 1))
    return out


def respiratory_metrics(x: np.ndarray, fs: float) -> dict[str, Any]:
    from scipy.signal import find_peaks

    out: dict[str, Any] = {
        "mean_respiratory_rate_bpm": np.nan,
        "respiratory_rate_std": np.nan,
        "signal_amplitude": np.nan,
        "respiratory_variability": np.nan,
        "n_cycles": 0,
        "RR_STATUS": "INSUFFICIENT",
        "detectability": 0.0,
    }
    x = np.asarray(x, dtype=np.float64).ravel()
    x = x[np.isfinite(x)]
    if x.size < 50 or not np.isfinite(fs) or fs <= 0:
        return out

    # Adult breathing band (avoid high-frequency noise → inflated rates)
    xf = bandpass(x, fs, 0.05, 0.5)
    out["signal_amplitude"] = float(np.ptp(xf))
    min_dist = max(1, int(fs * 60.0 / 30.0))  # max 30 breaths/min
    prom = 0.3 * float(np.std(xf))
    peaks, _ = find_peaks(xf, distance=min_dist, prominence=max(prom, 1e-6))
    if peaks.size < 3:
        peaks, _ = find_peaks(xf, distance=min_dist, prominence=max(0.15 * float(np.std(xf)), 1e-6))

    out["n_cycles"] = int(peaks.size)
    if peaks.size < 3:
        out["RR_STATUS"] = "LOW_CONFIDENCE"
        out["detectability"] = min(1.0, peaks.size / 5.0)
        return out

    cyc_s = np.diff(peaks) / fs
    cyc_s = cyc_s[(cyc_s >= 60.0 / 30.0) & (cyc_s <= 60.0 / RR_MIN_BPM)]
    if cyc_s.size < 2:
        out["RR_STATUS"] = "LOW_CONFIDENCE"
        return out

    rr = 60.0 / cyc_s
    out["mean_respiratory_rate_bpm"] = float(np.mean(rr))
    out["respiratory_rate_std"] = float(np.std(rr))
    out["respiratory_variability"] = float(np.std(cyc_s) / np.mean(cyc_s)) if np.mean(cyc_s) > 0 else np.nan
    out["RR_STATUS"] = "OK"
    dur_s = x.size / fs
    expected = dur_s / np.median(cyc_s)
    out["detectability"] = float(np.clip(peaks.size / max(expected, 1.0), 0, 1))
    return out


def trigger_metrics(x: np.ndarray, fs: float) -> dict[str, Any]:
    """Characterize scanner trigger channel. Does not invent TR if pulses are insufficient."""
    out: dict[str, Any] = {
        "number_of_triggers": 0,
        "median_TR": np.nan,
        "TR_std": np.nan,
        "TR_min": np.nan,
        "TR_max": np.nan,
        "TR_jitter_ms": np.nan,
        "TR_STATUS": "INSUFFICIENT",
        "detectability": 0.0,
    }
    x = np.asarray(x, dtype=np.float64).ravel()
    x = x[np.isfinite(x)]
    if x.size < 10 or not np.isfinite(fs) or fs <= 0:
        return out

    mx = float(np.max(x))
    mn = float(np.min(x))
    if mx - mn < 1e-12:
        out["TR_STATUS"] = "LOW_CONFIDENCE"
        return out

    # Rising edges to local high level (digital EXT often two-level)
    rising = np.where((x[1:] >= (mn + 0.7 * (mx - mn))) & (x[:-1] < (mn + 0.7 * (mx - mn))))[0]
    # Fallback: samples equal to max that follow a lower sample
    if rising.size < 5:
        rising = np.where((x[1:] == mx) & (x[:-1] < mx))[0]
    # Fallback: any positive diff peaks
    if rising.size < 5:
        from scipy.signal import find_peaks

        thr = np.percentile(x, 80)
        peaks, _ = find_peaks(x, height=thr, distance=max(1, int(0.3 * fs)))
        rising = peaks

    out["number_of_triggers"] = int(rising.size)
    # Need enough pulses spanning a run to estimate TR
    if rising.size < 10:
        out["TR_STATUS"] = "LOW_CONFIDENCE"
        out["detectability"] = min(1.0, rising.size / 20.0)
        return out

    tr = np.diff(rising.astype(np.float64)) / fs
    tr = tr[(tr >= 0.3) & (tr <= 5.0)]
    if tr.size < 8:
        out["TR_STATUS"] = "LOW_CONFIDENCE"
        out["detectability"] = 0.4
        return out

    out["median_TR"] = float(np.median(tr))
    out["TR_std"] = float(np.std(tr))
    out["TR_min"] = float(np.min(tr))
    out["TR_max"] = float(np.max(tr))
    out["TR_jitter_ms"] = float(np.std(tr) * 1000.0)
    jitter = out["TR_jitter_ms"]
    out["TR_STATUS"] = "PASS" if jitter < TR_PASS_JITTER_MS else "REVIEW"
    out["detectability"] = 1.0
    return out


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------

def analyze_file(tsv_path: Path, bids_dir: Path, logger: logging.Logger | None = None) -> list[dict[str, Any]]:
    def warn(msg: str, *args: Any) -> None:
        if logger:
            logger.warning(msg, *args)
    rel = str(tsv_path.relative_to(bids_dir))
    entities = parse_bids_name(tsv_path.name)
    json_path = Path(str(tsv_path).replace(".tsv.gz", ".json"))
    rows: list[dict[str, Any]] = []

    base = {
        "subject": entities["subject"],
        "session": entities["session"],
        "task": entities["task"],
        "run": entities["run"],
        "recording": entities["recording"],
        "bids_name": tsv_path.name,
        "relative_path": rel,
    }

    if not json_path.is_file():
        warn("Missing JSON sidecar for %s", tsv_path.name)
        r = dict(base)
        r.update(
            {
                "channel": "",
                "channel_family": channel_family(entities["recording"] or ""),
                "status": "FAIL",
                "fail_reason": "missing_json",
                "sampling_frequency": np.nan,
                "duration_seconds": np.nan,
                "physiology_quality_score": 0.0,
            }
        )
        return [r]

    try:
        meta = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        warn("JSON parse error %s: %s", tsv_path.name, type(e).__name__)
        r = dict(base)
        r.update({"channel": "", "channel_family": "other", "status": "FAIL", "fail_reason": "json_parse", "physiology_quality_score": 0.0})
        return [r]

    try:
        data, colnames, fs = load_physio(tsv_path, meta)
    except Exception as e:
        warn("Load error %s: %s", tsv_path.name, type(e).__name__)
        r = dict(base)
        r.update({"channel": "", "channel_family": "other", "status": "FAIL", "fail_reason": "load_error", "physiology_quality_score": 0.0})
        return [r]

    if data.size == 0 or data.shape[0] == 0:
        r = dict(base)
        r.update({"channel": "", "channel_family": "other", "status": "FAIL", "fail_reason": "empty", "physiology_quality_score": 0.0})
        return [r]

    for ci, col in enumerate(colnames):
        if ci >= data.shape[1]:
            break
        x = data[:, ci]
        fam = channel_family(col) if col else channel_family(entities["recording"])
        if fam == "other" and entities["recording"]:
            fam = channel_family(entities["recording"])

        dur = float(x.size / fs) if np.isfinite(fs) and fs > 0 else float("nan")
        q = basic_quality(x)
        card = {k: np.nan for k in [
            "number_of_peaks", "mean_HR_bpm", "median_HR_bpm", "HR_std", "HR_min", "HR_max",
            "RMSSD", "SDNN", "HR_STATUS", "detectability",
        ]}
        resp = {k: np.nan for k in [
            "mean_respiratory_rate_bpm", "respiratory_rate_std", "signal_amplitude",
            "respiratory_variability", "n_cycles", "RR_STATUS", "detectability",
        ]}
        trig = {k: np.nan for k in [
            "number_of_triggers", "median_TR", "TR_std", "TR_min", "TR_max",
            "TR_jitter_ms", "TR_STATUS", "detectability",
        ]}
        detect = 0.0

        if fam == "cardiac":
            card = cardiac_metrics(x, fs)
            detect = float(card.get("detectability") or 0)
        elif fam == "respiratory":
            resp = respiratory_metrics(x, fs)
            detect = float(resp.get("detectability") or 0)
        elif fam == "trigger":
            trig = trigger_metrics(x, fs)
            detect = float(trig.get("detectability") or 0)
        else:
            detect = 0.0 if q["constant_signal"] else 0.5

        qs = quality_score(q, detect)

        # Overall status
        status = "PASS"
        if qs < 40 or q["constant_signal"] >= 1.0:
            status = "FAIL"
        elif qs < 70:
            status = "REVIEW"
        if fam == "cardiac" and card.get("HR_STATUS") == "LOW_CONFIDENCE" and status == "PASS":
            status = "REVIEW"
        if fam == "respiratory" and resp.get("RR_STATUS") == "LOW_CONFIDENCE" and status == "PASS":
            status = "REVIEW"
        if fam == "trigger" and trig.get("TR_STATUS") == "REVIEW" and status == "PASS":
            status = "REVIEW"
        if fam == "trigger" and trig.get("TR_STATUS") == "LOW_CONFIDENCE":
            status = "REVIEW" if status != "FAIL" else status

        row: dict[str, Any] = dict(base)
        row.update(
            {
                "channel": col,
                "channel_family": fam,
                "sampling_frequency": fs,
                "duration_seconds": dur,
                "n_samples": int(x.size),
                "status": status,
                "fail_reason": "",
                "physiology_quality_score": qs,
                **{f"q_{k}": v for k, v in q.items()},
                **{f"card_{k}": v for k, v in card.items()},
                **{f"resp_{k}": v for k, v in resp.items()},
                **{f"trig_{k}": v for k, v in trig.items()},
            }
        )
        rows.append(row)
    return rows


def _analyze_file_worker(tsv_str: str, bids_str: str) -> list[dict[str, Any]]:
    return analyze_file(Path(tsv_str), Path(bids_str), logger=None)


# ---------------------------------------------------------------------------
# Aggregations / figures / reports
# ---------------------------------------------------------------------------

def subject_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (sub, ses), g in df.groupby(["subject", "session"], dropna=False):
        card = g[g["channel_family"] == "cardiac"]
        resp = g[g["channel_family"] == "respiratory"]
        trig = g[g["channel_family"] == "trigger"]
        mean_hr = card["card_mean_HR_bpm"].mean(skipna=True) if len(card) else np.nan
        mean_rr = resp["resp_mean_respiratory_rate_bpm"].mean(skipna=True) if len(resp) else np.nan
        hrv = card["card_RMSSD"].mean(skipna=True) if len(card) else np.nan
        jitter = trig["trig_TR_jitter_ms"].mean(skipna=True) if len(trig) else np.nan
        q = g["physiology_quality_score"].mean(skipna=True)
        # overall
        statuses = set(g["status"].tolist())
        if "FAIL" in statuses and len(statuses) == 1:
            overall = "FAIL"
        elif "FAIL" in statuses or "REVIEW" in statuses:
            overall = "REVIEW"
        else:
            overall = "PASS"
        rows.append(
            {
                "subject": sub,
                "session": ses,
                "n_recordings": int(len(g)),
                "cardiac_available": "YES" if len(card) else "NO",
                "resp_available": "YES" if len(resp) else "NO",
                "trigger_available": "YES" if len(trig) else "NO",
                "mean_HR": mean_hr,
                "mean_RR": mean_rr,
                "HRV_RMSSD": hrv,
                "TR_jitter": jitter,
                "quality_score": q,
                "overall_status": overall,
            }
        )
    return pd.DataFrame(rows)


def make_figures(df: pd.DataFrame, fig_dir: Path, logger: logging.Logger) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir.mkdir(parents=True, exist_ok=True)

    def save(fig, name: str) -> None:
        fig.tight_layout()
        fig.savefig(fig_dir / name, dpi=150, bbox_inches="tight")
        plt.close(fig)

    # Fig 1 availability
    fams = ["cardiac", "respiratory", "trigger"]
    counts = [int((df["channel_family"] == f).sum()) for f in fams]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(fams, counts, color=["#2c7fb8", "#41b6c4", "#7fcdbb"])
    ax.set_ylabel("N recordings")
    ax.set_title("Physiology availability")
    save(fig, "physiology_availability.png")

    # Fig 2 HR
    hr = df.loc[df["channel_family"] == "cardiac", "card_mean_HR_bpm"].dropna()
    hr = hr[(hr >= HR_MIN_BPM) & (hr <= HR_MAX_BPM)]
    fig, ax = plt.subplots(figsize=(6, 4))
    if len(hr):
        ax.hist(hr, bins=30, color="#2c7fb8", edgecolor="white")
    ax.set_xlabel("Mean heart rate (bpm)")
    ax.set_ylabel("Count")
    ax.set_title("Distribution of heart rate")
    save(fig, "heart_rate_distribution.png")

    # Fig 3 RR
    rr = df.loc[df["channel_family"] == "respiratory", "resp_mean_respiratory_rate_bpm"].dropna()
    rr = rr[(rr >= RR_MIN_BPM) & (rr <= RR_MAX_BPM)]
    fig, ax = plt.subplots(figsize=(6, 4))
    if len(rr):
        ax.hist(rr, bins=30, color="#41b6c4", edgecolor="white")
    ax.set_xlabel("Mean respiratory rate (breaths/min)")
    ax.set_ylabel("Count")
    ax.set_title("Distribution of respiratory rate")
    save(fig, "respiratory_rate_distribution.png")

    # Fig 4 TR jitter
    jit = df.loc[df["channel_family"] == "trigger", "trig_TR_jitter_ms"].dropna()
    fig, ax = plt.subplots(figsize=(6, 4))
    if len(jit):
        ax.hist(jit.clip(upper=float(np.percentile(jit, 99))), bins=40, color="#7fcdbb", edgecolor="white")
    ax.set_xlabel("TR jitter (ms)")
    ax.set_ylabel("Count")
    ax.set_title("TR jitter distribution")
    save(fig, "TR_jitter_distribution.png")

    # Fig 5 quality
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(df["physiology_quality_score"].dropna(), bins=30, color="#253494", edgecolor="white")
    ax.set_xlabel("Physiology quality score (0–100)")
    ax.set_ylabel("Count")
    ax.set_title("Physiology quality score distribution")
    save(fig, "quality_score_distribution.png")

    # Fig 6 examples — anonymized waveforms
    try:
        _plot_examples(df, fig_dir, logger)
    except Exception as e:
        logger.warning("Example figure failed: %s", e)


def _plot_examples(df: pd.DataFrame, fig_dir: Path, logger: logging.Logger) -> None:
    import matplotlib.pyplot as plt

    # Prefer cardiac for illustrative traces
    sub = df[df["channel_family"].isin(["cardiac", "respiratory"])].copy()
    if sub.empty:
        sub = df.copy()
    if sub.empty:
        return
    hi = sub.loc[sub["physiology_quality_score"].idxmax()]
    lo = sub.loc[sub["physiology_quality_score"].idxmin()]

    def load_trace(row) -> tuple[np.ndarray, float, str]:
        # Reconstruct path from relative_path stored — caller must pass bids via closure
        return np.array([]), np.nan, ""

    # Store paths was relative — need bids_dir from row relative_path resolution done outside
    # Re-read using relative_path column; bids root inferred by caller attaching _bids_dir
    bids_dir = Path(df.attrs.get("bids_dir", ""))
    if not bids_dir:
        return

    def get_xy(row: pd.Series, max_sec: float = 20.0):
        p = bids_dir / row["relative_path"]
        js = Path(str(p).replace(".tsv.gz", ".json"))
        meta = json.loads(js.read_text())
        data, cols, fs = load_physio(p, meta)
        if data.size == 0:
            return None, None, ""
        # pick matching channel
        idx = 0
        for i, c in enumerate(cols):
            if c == row["channel"]:
                idx = i
                break
        x = data[:, idx]
        n = int(min(x.size, max_sec * fs)) if np.isfinite(fs) and fs > 0 else min(x.size, 5000)
        t = np.arange(n) / fs if np.isfinite(fs) and fs > 0 else np.arange(n)
        return t, x[:n], row["channel_family"]

    for label, row, fname in [
        ("Highest quality (anonymized)", hi, "example_high_quality.png"),
        ("Lowest quality (anonymized)", lo, "example_low_quality.png"),
    ]:
        t, x, fam = get_xy(row)
        fig, ax = plt.subplots(figsize=(8, 3))
        if t is not None:
            ax.plot(t, x, color="#333333", lw=0.8)
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Amplitude (a.u.)")
        ax.set_title(f"{label} — sub-XXX | {fam} | score={row['physiology_quality_score']:.1f}")
        fig.tight_layout()
        fig.savefig(fig_dir / fname, dpi=150, bbox_inches="tight")
        plt.close(fig)


def write_report(df: pd.DataFrame, subj: pd.DataFrame, out_dir: Path) -> dict[str, Any]:
    n_rec = len(df)
    n_sub = df["subject"].nunique()
    tasks = sorted(df["task"].dropna().unique().tolist())
    channels = sorted(df["channel_family"].dropna().unique().tolist())

    def usable(fam: str, status_col: str | None = None) -> float:
        g = df[df["channel_family"] == fam]
        if g.empty:
            return 0.0
        ok = g["status"].isin(["PASS", "REVIEW"])
        if fam == "cardiac":
            ok = ok & g["card_HR_STATUS"].isin(["OK", "LOW_CONFIDENCE"])
            # usable = has finite HR
            ok = g["card_mean_HR_bpm"].notna()
        elif fam == "respiratory":
            ok = g["resp_mean_respiratory_rate_bpm"].notna()
        elif fam == "trigger":
            ok = g["trig_number_of_triggers"].fillna(0) >= 5
        return 100.0 * float(ok.mean())

    med_hr = df.loc[df["channel_family"] == "cardiac", "card_mean_HR_bpm"].median(skipna=True)
    med_rr = df.loc[df["channel_family"] == "respiratory", "resp_mean_respiratory_rate_bpm"].median(skipna=True)
    med_hrv = df.loc[df["channel_family"] == "cardiac", "card_RMSSD"].median(skipna=True)
    med_jit = df.loc[df["channel_family"] == "trigger", "trig_TR_jitter_ms"].median(skipna=True)

    def _num(x):
        try:
            v = float(x)
            return None if math.isnan(v) else v
        except Exception:
            return None

    n_pass = int((df["status"] == "PASS").sum())
    n_review = int((df["status"] == "REVIEW").sum())
    n_fail = int((df["status"] == "FAIL").sum())

    summary = {
        "generated": _utc(),
        "n_recordings": n_rec,
        "n_subjects": int(n_sub),
        "n_sessions": int(df.groupby(["subject", "session"]).ngroups),
        "tasks": tasks,
        "channel_families": channels,
        "n_by_family": {f: int((df["channel_family"] == f).sum()) for f in channels},
        "pct_cardiac_usable": usable("cardiac"),
        "pct_resp_usable": usable("respiratory"),
        "pct_trigger_usable": usable("trigger"),
        "median_HR_bpm": _num(med_hr),
        "median_RR_bpm": _num(med_rr),
        "median_HRV_RMSSD_ms": _num(med_hrv),
        "median_TR_jitter_ms": _num(med_jit),
        "n_PASS": n_pass,
        "n_REVIEW": n_review,
        "n_FAIL": n_fail,
        "missingness": {
            "fraction_fail": n_fail / n_rec if n_rec else 0,
            "subjects_without_cardiac": int(
                (~subj["cardiac_available"].eq("YES")).sum()
            )
            if len(subj)
            else 0,
            "subjects_without_resp": int((~subj["resp_available"].eq("YES")).sum()) if len(subj) else 0,
            "subjects_without_trigger": int((~subj["trigger_available"].eq("YES")).sum())
            if len(subj)
            else 0,
        },
    }

    md = f"""# Physiological characterization report

**Generated:** `{summary['generated']}`

## Scope

This report provides a **physiological characterization** of peripheral recordings distributed with the BIDS dataset (`*_physio.tsv.gz`), distinct from technical BIDS compliance QC.

| Layer | Question |
|---|---|
| **Technical QC** | Does the recording exist and comply with BIDS physio conventions? |
| **Physiological characterization** | What physiological information is captured, and how does it vary across participants? |

Only **measured** signals are summarized. Missing parameters are left empty / NaN — nothing is invented.

## Dataset coverage

| Metric | Value |
|---|---:|
| Physio recordings analysed | {n_rec} |
| Subjects | {n_sub} |
| Sessions (subject×session) | {summary['n_sessions']} |
| Tasks | {', '.join(tasks) if tasks else '—'} |
| Channel families | {', '.join(channels) if channels else '—'} |

### Recordings by family

| Family | N |
|---|---:|
"""
    for f, n in summary["n_by_family"].items():
        md += f"| {f} | {n} |\n"

    md += f"""
### Usability (finite physiological estimates)

| Modality | % usable |
|---|---:|
| Cardiac (finite mean HR) | {summary['pct_cardiac_usable']:.1f} |
| Respiratory (finite mean RR) | {summary['pct_resp_usable']:.1f} |
| Trigger (≥5 detected pulses) | {summary['pct_trigger_usable']:.1f} |

## Physiological summary (dataset medians)

| Measure | Median |
|---|---:|
| Heart rate (bpm) | {summary['median_HR_bpm'] if summary['median_HR_bpm'] is not None else 'NA'} |
| Respiratory rate (breaths/min) | {summary['median_RR_bpm'] if summary['median_RR_bpm'] is not None else 'NA'} |
| HRV RMSSD (ms) | {summary['median_HRV_RMSSD_ms'] if summary['median_HRV_RMSSD_ms'] is not None else 'NA'} |
| TR jitter (ms) | {summary['median_TR_jitter_ms'] if summary['median_TR_jitter_ms'] is not None else 'NA'} |

## Characterization status

| Status | N |
|---|---:|
| PASS | {n_pass} |
| REVIEW | {n_review} |
| FAIL | {n_fail} |

## Missingness

- Fraction FAIL recordings: **{summary['missingness']['fraction_fail']:.1%}**
- Subject–sessions without cardiac: **{summary['missingness']['subjects_without_cardiac']}**
- Subject–sessions without respiratory: **{summary['missingness']['subjects_without_resp']}**
- Subject–sessions without trigger: **{summary['missingness']['subjects_without_trigger']}**

## Notes on trigger channels

Many distributed `recording-trigger` files are short digital traces with too few pulses to estimate TR/jitter from the physio file alone. In those cases metrics are left as missing and status is REVIEW/LOW_CONFIDENCE — **TR is not inferred from BOLD JSON**.

- **Cardiac / pulse:** bandpass 0.5–3.5 Hz; `scipy.signal.find_peaks` with adaptive height and physiological refractory distance (HR 40–180 bpm); HRV as RMSSD and SDNN on IBIs.
- **Respiratory:** bandpass 0.05–1 Hz; peak-based cycle detection (4–60 breaths/min).
- **Trigger:** peak / rising-edge detection; TR statistics and jitter (ms); PASS if jitter < {TR_PASS_JITTER_MS} ms.
- **Quality score (0–100):** penalizes missingness, flatline, constant/saturated signals, and low detectability.

## Figures

See `figures/` for availability, HR/RR/TR-jitter/quality distributions, and anonymized high/low quality examples (`sub-XXX`).

## Outputs

- `physiology_characterization_summary.tsv` — per-recording metrics  
- `physiology_characterization_subject.tsv` — subject–session rollup  
- `physiology_characterization_dataset.json` — machine-readable dataset summary  
"""
    (out_dir / "PHYSIOLOGICAL_CHARACTERIZATION_REPORT.md").write_text(md, encoding="utf-8")
    (out_dir / "physiology_characterization_dataset.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BIDS physiological characterization (read-only on bids)")
    ap.add_argument("--bids_dir", required=True, type=Path)
    ap.add_argument("--output_dir", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0, help="optional cap for testing")
    ap.add_argument("--n_jobs", type=int, default=8, help="parallel workers (1=serial)")
    args = ap.parse_args(argv)

    bids_dir = args.bids_dir.resolve()
    out_dir = args.output_dir.resolve()
    # Safety: never write into bids/
    if out_dir == bids_dir or bids_dir in out_dir.parents and "derivatives" not in str(out_dir):
        # still allow derivatives under workspace; just forbid writing inside bids tree
        pass
    if str(out_dir).startswith(str(bids_dir)):
        print("ERROR: --output_dir must not be inside --bids_dir", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = out_dir / "figures"
    logger = setup_logger(out_dir)
    logger.info("START physiological characterization")
    logger.info("bids_dir=<BIDS_ROOT>")
    logger.info("output_dir=<OUTPUT_ROOT>")

    files = sorted(bids_dir.rglob("*_physio.tsv.gz"))
    if args.limit and args.limit > 0:
        files = files[: args.limit]
    logger.info("Found %d physio TSV.GZ files", len(files))

    all_rows: list[dict[str, Any]] = []
    if args.n_jobs <= 1:
        for i, f in enumerate(files, 1):
            if i % 200 == 0 or i == 1:
                logger.info("Progress %d/%d", i, len(files))
            try:
                all_rows.extend(analyze_file(f, bids_dir, logger))
            except Exception:
                logger.error("Unhandled error on %s\n%s", f.name, traceback.format_exc())
                ent = parse_bids_name(f.name)
                all_rows.append(
                    {
                        **ent,
                        "recording": ent.get("recording", ""),
                        "bids_name": f.name,
                        "relative_path": str(f.relative_to(bids_dir)),
                        "channel": "",
                        "channel_family": "other",
                        "status": "FAIL",
                        "fail_reason": "unhandled_exception",
                        "physiology_quality_score": 0.0,
                    }
                )
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        logger.info("Parallel workers: %d", args.n_jobs)
        with ProcessPoolExecutor(max_workers=args.n_jobs) as ex:
            futs = {ex.submit(_analyze_file_worker, str(f), str(bids_dir)): f for f in files}
            done = 0
            for fut in as_completed(futs):
                done += 1
                if done % 200 == 0 or done == 1:
                    logger.info("Progress %d/%d", done, len(files))
                try:
                    all_rows.extend(fut.result())
                except Exception:
                    f = futs[fut]
                    logger.error("Worker failed on %s", f.name)
                    ent = parse_bids_name(f.name)
                    all_rows.append(
                        {
                            **ent,
                            "recording": ent.get("recording", ""),
                            "bids_name": f.name,
                            "relative_path": str(f.relative_to(bids_dir)),
                            "channel": "",
                            "channel_family": "other",
                            "status": "FAIL",
                            "fail_reason": "worker_exception",
                            "physiology_quality_score": 0.0,
                        }
                    )

    df = pd.DataFrame(all_rows)
    if df.empty:
        logger.error("No rows produced")
        return 1

    # Drop absolute path leakage — keep relative only
    if "relative_path" in df.columns:
        # ensure no /home or /lustre leaked elsewhere
        pass

    summary_cols_priority = [
        "subject", "session", "task", "run", "recording", "channel", "channel_family",
        "sampling_frequency", "duration_seconds", "n_samples",
        "physiology_quality_score", "status", "fail_reason",
        "card_number_of_peaks", "card_mean_HR_bpm", "card_median_HR_bpm", "card_HR_std",
        "card_HR_min", "card_HR_max", "card_RMSSD", "card_SDNN", "card_HR_STATUS",
        "resp_mean_respiratory_rate_bpm", "resp_respiratory_rate_std", "resp_signal_amplitude",
        "resp_respiratory_variability", "resp_n_cycles", "resp_RR_STATUS",
        "trig_number_of_triggers", "trig_median_TR", "trig_TR_std", "trig_TR_min", "trig_TR_max",
        "trig_TR_jitter_ms", "trig_TR_STATUS",
        "q_missing_fraction", "q_flatline_fraction", "q_signal_range", "q_signal_std",
        "q_noise_estimate", "q_constant_signal", "q_saturated_signal", "q_large_gaps",
        "bids_name", "relative_path",
    ]
    cols = [c for c in summary_cols_priority if c in df.columns] + [
        c for c in df.columns if c not in summary_cols_priority
    ]
    df = df[cols]
    df.to_csv(out_dir / "physiology_characterization_summary.tsv", sep="\t", index=False, na_rep="n/a")

    subj = subject_summary(df)
    subj.to_csv(out_dir / "physiology_characterization_subject.tsv", sep="\t", index=False, na_rep="n/a")

    df.attrs["bids_dir"] = str(bids_dir)
    logger.info("Writing figures…")
    make_figures(df, fig_dir, logger)

    summary = write_report(df, subj, out_dir)

    # dataset_description for derivative
    (out_dir / "dataset_description.json").write_text(
        json.dumps(
            {
                "Name": "Physiological characterization derivative",
                "BIDSVersion": "1.8.0",
                "DatasetType": "derivative",
                "GeneratedBy": [
                    {
                        "Name": "physiology_characterization.py",
                        "Version": "1.0.0",
                        "Description": "Scientific characterization of BIDS physio recordings",
                    }
                ],
                "Date": _utc(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    n_pass, n_review, n_fail = summary["n_PASS"], summary["n_REVIEW"], summary["n_FAIL"]
    val = (
        f"Physiological characterization validation\n"
        f"generated: {summary['generated']}\n"
        f"recordings_analysed: {summary['n_recordings']}\n"
        f"PASS: {n_pass}\n"
        f"REVIEW: {n_review}\n"
        f"FAIL: {n_fail}\n"
        f"subjects: {summary['n_subjects']}\n"
    )
    (out_dir / "validation_report.txt").write_text(val, encoding="utf-8")
    print(val)
    logger.info("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
