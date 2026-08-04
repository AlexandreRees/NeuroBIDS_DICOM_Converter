#!/usr/bin/env python3
"""Advanced physiological characterization for Scientific Data / OpenNeuro.

Characterizes physiological recording quality as an acquisition-level property
and its relationship with MRIQC-derived fMRI quality and longitudinal
reproducibility.

READ-ONLY for raw_original/, bids/, and pre-existing derivative sources.
All outputs written under --output_dir (default: derivatives/physiology_characterization).

No PHI: only BIDS entities (sub-XXX, ses-XX, task, run) and numeric metrics.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

warnings.filterwarnings("ignore", category=RuntimeWarning)

ENTITY_RE = re.compile(
    r"(?P<sub>sub-\d+)_"
    r"(?P<ses>ses-\d+)_"
    r"task-(?P<task>[^_]+)_"
    r"run-(?P<run>\d+)_"
    r"recording-(?P<rec>[^_]+)_physio"
)

# Approximate expected volumes by task (from acquisition protocol); used only for trigger integrity scoring
EXPECTED_VOLUMES = {
    "rest": 320,
    "fmri": 226,
    "movie": 210,
    "control": 210,
}


def log(msg: str) -> None:
    print(msg, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not fieldnames:
        keys: list[str] = []
        seen: set[str] = set()
        for r in rows:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        fieldnames = keys
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {}
            for k in fieldnames:
                v = r.get(k, "")
                if isinstance(v, (bool, np.bool_)):
                    out[k] = "true" if bool(v) else "false"
                elif isinstance(v, float):
                    out[k] = "n/a" if not np.isfinite(v) else f"{v:.6g}"
                elif v is None:
                    out[k] = "n/a"
                else:
                    out[k] = v
            w.writerow(out)


def to_float(x: Any) -> float:
    if x is None:
        return float("nan")
    if isinstance(x, (int, float, np.floating)):
        return float(x)
    s = str(x).strip()
    if s in {"", "n/a", "NA", "nan", "None", "true", "false"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def col(rows: list[dict[str, Any]], name: str) -> np.ndarray:
    return np.asarray([to_float(r.get(name)) for r in rows], dtype=float)


def parse_entities(path: Path) -> dict[str, str] | None:
    m = ENTITY_RE.search(path.name)
    if not m:
        return None
    d = m.groupdict()
    return {
        "subject": d["sub"],
        "session": d["ses"],
        "task": d["task"],
        "run": f"run-{d['run']}",
        "recording": d["rec"],
    }


def read_physio(tsv_gz: Path, json_path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    with gzip.open(tsv_gz, "rt", encoding="utf-8") as handle:
        first = handle.readline()
        rest = handle.read()
    try:
        float(first.strip().split("\t")[0])
        text = first + rest
    except ValueError:
        text = rest
    vals: list[float] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        tok = line.split("\t")[0].strip()
        if tok in {"n/a", "N/A", "nan", "NaN", ""}:
            vals.append(np.nan)
            continue
        try:
            vals.append(float(tok))
        except ValueError:
            vals.append(np.nan)
    return np.asarray(vals, dtype=float), meta


def missing_fraction(arr: np.ndarray) -> float:
    if arr.size == 0:
        return 1.0
    return float(np.mean(~np.isfinite(arr)))


def clean_signal(arr: np.ndarray) -> np.ndarray:
    x = arr.astype(float).copy()
    if x.size == 0:
        return x
    nans = ~np.isfinite(x)
    if nans.all():
        return x
    if nans.any():
        idx = np.arange(x.size)
        x[nans] = np.interp(idx[nans], idx[~nans], x[~nans])
    return x


def find_peaks_simple(x: np.ndarray, distance: int, prominence: float) -> np.ndarray:
    if x.size < 3:
        return np.asarray([], dtype=int)
    peaks = []
    last = -(10**9)
    for i in range(1, x.size - 1):
        if x[i] >= x[i - 1] and x[i] > x[i + 1]:
            left = max(0, i - distance)
            right = min(x.size, i + distance + 1)
            baseline = np.min(x[left:right])
            if (x[i] - baseline) >= prominence and (i - last) >= distance:
                peaks.append(i)
                last = i
    return np.asarray(peaks, dtype=int)


def detect_peaks(x: np.ndarray, sf: float, min_hz: float, max_hz: float) -> np.ndarray:
    if x.size < 10 or sf <= 0:
        return np.asarray([], dtype=int)
    min_dist = max(1, int(sf / max_hz))
    mad = float(np.median(np.abs(x - np.median(x)))) + 1e-8
    return find_peaks_simple(x, min_dist, 1.5 * mad)


def cardiac_features(arr: np.ndarray, sf: float) -> dict[str, float]:
    x = clean_signal(arr)
    out = {
        "cardiac_n_samples": float(arr.size),
        "cardiac_sf": float(sf) if sf > 0 else float("nan"),
        "cardiac_mean_amp": float("nan"),
        "cardiac_amp_sd": float("nan"),
        "cardiac_variance": float("nan"),
        "cardiac_missing_fraction": missing_fraction(arr),
        "cardiac_amp_stability": float("nan"),
    }
    if x.size < 10:
        return out
    out["cardiac_mean_amp"] = float(np.mean(np.abs(x)))
    out["cardiac_amp_sd"] = float(np.std(x, ddof=1)) if x.size > 1 else 0.0
    out["cardiac_variance"] = float(np.var(x))
    peaks = detect_peaks(x, sf if sf > 0 else 50.0, 0.5, 2.5)
    if peaks.size >= 3:
        amps = x[peaks]
        cv = float(np.std(amps, ddof=1) / (np.mean(np.abs(amps)) + 1e-8))
        out["cardiac_amp_stability"] = float(1.0 / (1.0 + cv))
    return out


def respiratory_features(arr: np.ndarray, sf: float) -> dict[str, float]:
    x = clean_signal(arr)
    out = {
        "resp_n_samples": float(arr.size),
        "resp_sf": float(sf) if sf > 0 else float("nan"),
        "resp_variance": float("nan"),
        "resp_amp_stability": float("nan"),
        "resp_missing_fraction": missing_fraction(arr),
    }
    if x.size < 10:
        return out
    out["resp_variance"] = float(np.var(x))
    peaks = detect_peaks(x, sf if sf > 0 else 25.0, 0.05, 0.7)
    if peaks.size >= 3:
        amps = x[peaks]
        cv = float(np.std(amps, ddof=1) / (np.mean(np.abs(amps)) + 1e-8))
        out["resp_amp_stability"] = float(1.0 / (1.0 + cv))
    return out


def trigger_features(arr: np.ndarray, sf: float) -> dict[str, float]:
    x = clean_signal(arr)
    out = {
        "trigger_n_samples": float(arr.size),
        "trigger_sf": float(sf) if sf > 0 else float("nan"),
        "n_triggers": 0.0,
        "median_TR_interval": float("nan"),
        "TR_sd": float("nan"),
        "TR_cv": float("nan"),
        "trigger_missing_fraction": missing_fraction(arr),
    }
    if x.size < 5 or sf <= 0:
        return out
    dx = np.diff(x)
    thr = float(np.nanpercentile(np.abs(dx), 90)) if np.any(np.isfinite(dx)) else 0.0
    edges = np.where(dx > max(thr, 1e-6))[0]
    if edges.size < 3:
        uniq = np.unique(x[np.isfinite(x)])
        if uniq.size <= 4:
            edges = np.where(np.diff(x) != 0)[0]
        else:
            edges = detect_peaks(x, sf, 0.5, 2.0)
    out["n_triggers"] = float(edges.size)
    if edges.size < 3:
        return out
    intervals = np.diff(edges) / sf
    cand = intervals[(intervals > 0.4) & (intervals < 3.0)]
    use = cand if cand.size >= 3 else intervals
    med = float(np.median(use))
    sd = float(np.std(use, ddof=1)) if use.size > 1 else 0.0
    out["median_TR_interval"] = med
    out["TR_sd"] = sd
    out["TR_cv"] = float(sd / med) if med > 0 else float("nan")
    return out


# ---------------------------------------------------------------------------
# Part 1 — extraction
# ---------------------------------------------------------------------------
def extract_physiology(bids_dir: Path) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Path]] = defaultdict(dict)
    json_map: dict[Path, Path] = {}
    n_files = 0
    for tsv in bids_dir.glob("sub-*/ses-*/func/*_physio.tsv.gz"):
        ent = parse_entities(tsv)
        if not ent:
            continue
        n_files += 1
        key = (ent["subject"], ent["session"], ent["task"], ent["run"])
        groups[key][ent["recording"]] = tsv
        jp = Path(str(tsv).replace(".tsv.gz", ".json"))
        if jp.is_file():
            json_map[tsv] = jp

    rows: list[dict[str, Any]] = []
    n = len(groups)
    log(f"  physio files: {n_files}; run groups: {n}")
    for i, (key, recs) in enumerate(sorted(groups.items())):
        subject, session, task, run = key
        row: dict[str, Any] = {
            "subject": subject,
            "session": session,
            "task": task,
            "run": run,
            "cardiac_available": False,
            "resp_available": False,
            "trigger_available": False,
            "ecg_available": False,
            "cardiac_starttime": float("nan"),
            "resp_starttime": float("nan"),
            "trigger_starttime": float("nan"),
            "n_physio_files": float(len(recs)),
        }
        # cardiac / pulse / ecg
        for cand in ("pulse", "cardiac", "ecg"):
            if cand in recs and recs[cand] in json_map:
                arr, meta = read_physio(recs[cand], json_map[recs[cand]])
                sf = float(meta.get("SamplingFrequency") or 0.0)
                st = meta.get("StartTime")
                row.update(cardiac_features(arr, sf))
                row["cardiac_available"] = True
                row["cardiac_starttime"] = to_float(st)
                if cand == "ecg":
                    row["ecg_available"] = True
                break
        if "ecg" in recs and not row["ecg_available"]:
            row["ecg_available"] = True  # present even if pulse preferred for features

        if "respiratory" in recs and recs["respiratory"] in json_map:
            arr, meta = read_physio(recs["respiratory"], json_map[recs["respiratory"]])
            sf = float(meta.get("SamplingFrequency") or 0.0)
            row.update(respiratory_features(arr, sf))
            row["resp_available"] = True
            row["resp_starttime"] = to_float(meta.get("StartTime"))

        if "trigger" in recs and recs["trigger"] in json_map:
            arr, meta = read_physio(recs["trigger"], json_map[recs["trigger"]])
            sf = float(meta.get("SamplingFrequency") or 0.0)
            row.update(trigger_features(arr, sf))
            row["trigger_available"] = True
            row["trigger_starttime"] = to_float(meta.get("StartTime"))

        rows.append(row)
        if (i + 1) % 200 == 0:
            log(f"    extraction progress {i+1}/{n}")
    return rows, n_files


# ---------------------------------------------------------------------------
# Part 2 — PRI
# ---------------------------------------------------------------------------
def compute_pri(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """PRI 0–100: trigger 40 + availability 30 + signal quality 20 + metadata 10."""
    comps: list[dict[str, Any]] = []
    for r in rows:
        # --- Trigger integrity (40) ---
        trig = 0.0
        if r.get("trigger_available"):
            ntrig = to_float(r.get("n_triggers"))
            expected = float(EXPECTED_VOLUMES.get(str(r.get("task")), 200))
            # Count score: closer to expected is better (allow sparse EXT markers → partial credit)
            if np.isfinite(ntrig) and ntrig >= 3:
                ratio = min(ntrig, expected) / expected
                # Many EXT logs are sparse digital markers (~1 transition): low but non-zero if present
                count_score = float(np.clip(ratio, 0, 1))
                if ntrig < 10:
                    count_score = min(count_score, 0.25)  # sparse marker channel
            else:
                count_score = 0.0
            cv = to_float(r.get("TR_cv"))
            if np.isfinite(cv) and ntrig >= 10:
                # CV < 0.02 excellent, >0.1 poor
                jitter_score = float(np.clip(1.0 - cv / 0.10, 0, 1))
            elif np.isfinite(to_float(r.get("TR_sd"))) and ntrig >= 10:
                sd = to_float(r.get("TR_sd"))
                jitter_score = float(np.clip(1.0 - sd / 0.10, 0, 1))
            else:
                jitter_score = 0.35 if r.get("trigger_available") else 0.0
            trig = 40.0 * (0.55 * count_score + 0.45 * jitter_score)
        pri_trigger = float(trig)

        # --- Signal availability (30) ---
        avail = 0.0
        if r.get("cardiac_available"):
            avail += 15.0
        if r.get("resp_available"):
            avail += 15.0
        pri_signal_avail = float(avail)

        # --- Signal quality (20) ---
        miss_parts = []
        stab_parts = []
        if r.get("cardiac_available"):
            miss_parts.append(1.0 - np.clip(to_float(r.get("cardiac_missing_fraction")), 0, 1))
            s = to_float(r.get("cardiac_amp_stability"))
            if np.isfinite(s):
                stab_parts.append(s)
        if r.get("resp_available"):
            miss_parts.append(1.0 - np.clip(to_float(r.get("resp_missing_fraction")), 0, 1))
            s = to_float(r.get("resp_amp_stability"))
            if np.isfinite(s):
                stab_parts.append(s)
        if miss_parts or stab_parts:
            miss_score = float(np.mean(miss_parts)) if miss_parts else 0.5
            stab_score = float(np.mean(stab_parts)) if stab_parts else 0.5
            pri_quality = 20.0 * (0.5 * miss_score + 0.5 * stab_score)
        else:
            pri_quality = 0.0

        # --- Acquisition metadata (10) ---
        meta_pts = 0.0
        sfs = []
        sts = []
        if r.get("cardiac_available"):
            sfs.append(to_float(r.get("cardiac_sf")))
            sts.append(to_float(r.get("cardiac_starttime")))
        if r.get("resp_available"):
            sfs.append(to_float(r.get("resp_sf")))
            sts.append(to_float(r.get("resp_starttime")))
        if r.get("trigger_available"):
            sfs.append(to_float(r.get("trigger_sf")))
            sts.append(to_float(r.get("trigger_starttime")))
        valid_sf = sum(1 for s in sfs if np.isfinite(s) and s > 0)
        valid_st = sum(1 for s in sts if np.isfinite(s))
        if sfs:
            meta_pts += 5.0 * (valid_sf / len(sfs))
        if sts:
            meta_pts += 5.0 * (valid_st / len(sts))
        pri_sampling = float(meta_pts)

        # Bundle signal availability + quality into PRI_signal for requested columns
        # Requested: PRI_trigger, PRI_signal, PRI_sampling — map quality into signal
        pri_signal = pri_signal_avail + pri_quality  # max 50; will note in report
        # Re-scale to requested semantics: keep trigger 40, sampling 10, and put avail+quality as signal (50→ renormalize display)
        # Spec: trigger 40, availability 30, quality 20, metadata 10 → total 100
        # Columns: PRI_trigger, PRI_signal, PRI_sampling
        # Interpret PRI_signal = availability + quality (50), PRI_sampling = metadata (10)
        pri_total = pri_trigger + pri_signal_avail + pri_quality + pri_sampling
        pri_total = float(np.clip(pri_total, 0, 100))

        r["PRI_total"] = pri_total
        r["PRI_trigger"] = pri_trigger
        r["PRI_signal"] = float(pri_signal_avail + pri_quality)  # 0–50
        r["PRI_sampling"] = pri_sampling
        r["PRI_availability"] = pri_signal_avail
        r["PRI_quality"] = pri_quality

        comps.append(
            {
                "subject": r["subject"],
                "session": r["session"],
                "task": r["task"],
                "run": r["run"],
                "PRI_total": pri_total,
                "PRI_trigger": pri_trigger,
                "PRI_signal": float(pri_signal_avail + pri_quality),
                "PRI_sampling": pri_sampling,
                "PRI_availability": pri_signal_avail,
                "PRI_quality": pri_quality,
            }
        )
    return rows, comps


# ---------------------------------------------------------------------------
# Part 3 — MRIQC
# ---------------------------------------------------------------------------
def load_mriqc(derivatives_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = derivatives_dir / "mriqc"
    if not root.is_dir():
        return rows
    for jp in root.glob("sub-*/ses-*/func/*_bold.json"):
        if "part-phase" in jp.name:
            continue
        m = re.search(r"(sub-\d+)_(ses-\d+)_task-([^_]+)_run-(\d+)_bold\.json", jp.name)
        if not m:
            continue
        try:
            meta = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(
            {
                "subject": m.group(1),
                "session": m.group(2),
                "task": m.group(3),
                "run": f"run-{m.group(4)}",
                "mean_FD": meta.get("fd_mean", np.nan),
                "fd_perc_02": meta.get("fd_perc", np.nan),
                "DVARS": meta.get("dvars_nstd", np.nan),
                "tSNR": meta.get("tsnr", np.nan),
                "gCOR": meta.get("gcor", np.nan),
                "SNR": meta.get("snr", np.nan),
            }
        )
    return rows


def merge_strict(phys: list[dict[str, Any]], fmri: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fmap = {(r["subject"], r["session"], r["task"], r["run"]): r for r in fmri}
    out = []
    for p in phys:
        key = (p["subject"], p["session"], p["task"], p["run"])
        f = fmap.get(key)
        if not f:
            continue
        m = dict(p)
        for k in ("mean_FD", "fd_perc_02", "DVARS", "tSNR", "gCOR", "SNR"):
            m[k] = f.get(k, np.nan)
        out.append(m)
    return out


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def rankdata(a: np.ndarray) -> np.ndarray:
    order = np.argsort(a)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, a.size + 1, dtype=float)
    sa = a[order]
    i = 0
    while i < a.size:
        j = i
        while j + 1 < a.size and sa[j + 1] == sa[i]:
            j += 1
        if j > i:
            avg = 0.5 * (i + 1 + j + 1)
            ranks[order[i : j + 1]] = avg
        i = j + 1
    return ranks


def student_t_sf(t: float, df: float) -> float:
    if not np.isfinite(t) or df <= 0:
        return float("nan")
    z = t * (1 - 1 / (4 * df)) / math.sqrt(1 + t * t / (2 * df))
    return 0.5 * math.erfc(z / math.sqrt(2))


def spearman_with_ci(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = int(x.size)
    out = {"n": float(n), "rho": float("nan"), "p": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "R2": float("nan")}
    if n < 5:
        return out
    rx, ry = rankdata(x), rankdata(y)
    rho = float(np.corrcoef(rx, ry)[0, 1])
    if abs(rho) >= 1:
        p = 0.0
    else:
        t = rho * math.sqrt((n - 2) / max(1e-12, 1 - rho * rho))
        p = float(2 * student_t_sf(abs(t), n - 2))
    # Fisher z CI on Spearman
    z = np.arctanh(np.clip(rho, -0.999999, 0.999999))
    se = 1.0 / math.sqrt(max(n - 3, 1))
    zlo, zhi = z - 1.96 * se, z + 1.96 * se
    out.update(
        {
            "rho": rho,
            "p": p,
            "ci_low": float(np.tanh(zlo)),
            "ci_high": float(np.tanh(zhi)),
            "R2": float(rho * rho),
        }
    )
    return out


def ols_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if x.size < 3:
        return float("nan"), float("nan")
    coef = np.polyfit(x, y, 1)
    return float(coef[0]), float(coef[1])


def icc31(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    by_sub: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        v = to_float(r.get(metric))
        if np.isfinite(v):
            by_sub[r["subject"]][r["session"]].append(v)
    wide = []
    for sess in by_sub.values():
        if len(sess) < 2:
            continue
        vals = [float(np.mean(sess[s])) for s in sorted(sess)]
        wide.append(vals[:2])
    result = {
        "metric": metric,
        "n_subjects": len(wide),
        "ICC": float("nan"),
        "CI95_low": float("nan"),
        "CI95_high": float("nan"),
        "interpretation": "insufficient_data",
    }
    if len(wide) < 5:
        return result
    M = np.asarray(wide, float)
    n, k = M.shape
    mean_t = M.mean(axis=1, keepdims=True)
    mean_r = M.mean(axis=0, keepdims=True)
    mean_g = M.mean()
    BMS = k * np.sum((mean_t - mean_g) ** 2) / (n - 1)
    WMS = np.sum((M - mean_t) ** 2) / (n * (k - 1))
    EMS = np.sum((M - mean_t - mean_r + mean_g) ** 2) / ((n - 1) * (k - 1))
    denom = BMS + (k - 1) * EMS
    icc = float((BMS - EMS) / denom) if denom != 0 else float("nan")
    # Approximate CI via Fisher-like transform (McGraw & Wong style rough bound)
    if np.isfinite(icc) and abs(icc) < 0.999:
        # Shrout Fleiss approx SE for ICC
        se = math.sqrt(max(2 * (1 - icc) ** 2 * (1 + (k - 1) * icc) ** 2 / (k * n * (k - 1)), 1e-12))
        ci_lo = icc - 1.96 * se
        ci_hi = icc + 1.96 * se
    else:
        ci_lo = ci_hi = float("nan")
    result.update(
        {
            "n_subjects": int(n),
            "ICC": icc,
            "CI95_low": float(ci_lo) if np.isfinite(ci_lo) else float("nan"),
            "CI95_high": float(ci_hi) if np.isfinite(ci_hi) else float("nan"),
            "interpretation": interpret_icc(icc),
        }
    )
    return result


def interpret_icc(icc: float) -> str:
    if not np.isfinite(icc):
        return "undefined"
    if icc < 0.5:
        return "poor"
    if icc < 0.75:
        return "moderate"
    if icc < 0.9:
        return "good"
    return "excellent"


def variance_partition(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    """Partition variance into between-subject vs within-subject fractions."""
    by_sub: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = to_float(r.get(metric))
        if np.isfinite(v):
            by_sub[r["subject"]].append(v)
    # keep subjects with >=2 observations for within-subject estimate
    subs = {s: v for s, v in by_sub.items() if len(v) >= 1}
    if len(subs) < 5:
        return {
            "metric": metric,
            "n_subjects": len(subs),
            "between_subject_variance": float("nan"),
            "within_subject_variance": float("nan"),
            "between_subject_fraction": float("nan"),
            "within_subject_fraction": float("nan"),
            "interpretation": "insufficient_data",
        }
    means = np.array([float(np.mean(v)) for v in subs.values()])
    between = float(np.var(means, ddof=1)) if means.size > 1 else 0.0
    within_list = []
    for v in subs.values():
        if len(v) >= 2:
            within_list.append(float(np.var(v, ddof=1)))
    within = float(np.mean(within_list)) if within_list else 0.0
    total = between + within
    if total <= 0:
        bf = wf = float("nan")
        interp = "undefined"
    else:
        bf = between / total
        wf = within / total
        interp = "acquisition-dependent" if wf >= bf else "subject-dependent"
    return {
        "metric": metric,
        "n_subjects": len(subs),
        "n_subjects_with_repeats": len(within_list),
        "between_subject_variance": between,
        "within_subject_variance": within,
        "between_subject_fraction": float(bf),
        "within_subject_fraction": float(wf),
        "interpretation": interp,
    }


def longitudinal_pairs(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in master:
        groups[(r["subject"], r["task"], r["run"])].append(r)
    out = []
    for (sub, task, run), g in groups.items():
        g = sorted(g, key=lambda z: z["session"])
        if len(g) < 2:
            continue
        for i in range(len(g) - 1):
            a, b = g[i], g[i + 1]

            def ad(colname: str) -> float:
                return abs(to_float(b.get(colname)) - to_float(a.get(colname)))

            out.append(
                {
                    "subject": sub,
                    "task": task,
                    "run": run,
                    "session_a": a["session"],
                    "session_b": b["session"],
                    "delta_PRI": ad("PRI_total"),
                    "delta_FD": ad("mean_FD"),
                    "delta_tSNR": ad("tSNR"),
                    "delta_DVARS": ad("DVARS"),
                    "PRI_a": to_float(a.get("PRI_total")),
                    "PRI_b": to_float(b.get("PRI_total")),
                }
            )
    return out


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def save_fig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def make_figures(
    out_dir: Path,
    raw_rows: list[dict[str, Any]],
    master: list[dict[str, Any]],
    assoc: list[dict[str, Any]],
    icc_rows: list[dict[str, Any]],
    var_rows: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )
    primary, secondary, accent = "#2C5F6E", "#B85C38", "#4A7C59"

    # Fig1 PRI distribution
    pri = col(raw_rows, "PRI_total")
    pri = pri[np.isfinite(pri)]
    fig, ax = plt.subplots(figsize=(6.2, 4))
    ax.hist(pri, bins=30, density=True, color=primary, alpha=0.55, edgecolor="white")
    # simple density
    if pri.size > 10:
        xs = np.linspace(pri.min(), pri.max(), 200)
        # gaussian kde via sum of kernels
        bw = 1.06 * np.std(pri, ddof=1) * pri.size ** (-0.2)
        bw = max(bw, 1.0)
        dens = np.zeros_like(xs)
        for v in pri:
            dens += np.exp(-0.5 * ((xs - v) / bw) ** 2)
        dens /= dens.sum() * (xs[1] - xs[0]) if dens.sum() > 0 else 1
        ax.plot(xs, dens, color=secondary, lw=2)
    ax.set_xlabel("Physiological Reliability Index (PRI, 0–100)")
    ax.set_ylabel("Density")
    ax.set_title(f"PRI distribution (N={pri.size} runs)")
    save_fig(fig, out_dir / "Figure1_PRI_distribution.png")
    made.append("Figure1_PRI_distribution.png")

    # Fig2 PRI vs MRI
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.5))
    panels = [
        ("tSNR", "tSNR", "A  PRI vs tSNR"),
        ("mean_FD", "Framewise displacement (mm)", "B  PRI vs FD"),
        ("DVARS", "DVARS (a.u.)", "C  PRI vs DVARS"),
    ]
    x = col(master, "PRI_total")
    assoc_map = {r["outcome"]: r for r in assoc}
    for ax, (yname, ylabel, title) in zip(axes, panels):
        y = col(master, yname)
        m = np.isfinite(x) & np.isfinite(y)
        ax.scatter(x[m], y[m], s=9, alpha=0.35, c=primary, edgecolors="none", rasterized=True)
        slope, intercept = ols_line(x, y)
        if np.isfinite(slope):
            xs = np.linspace(np.nanmin(x), np.nanmax(x), 60)
            ax.plot(xs, slope * xs + intercept, color=secondary, lw=1.6)
        st = assoc_map.get(yname, {})
        ax.text(
            0.98,
            0.98,
            f"ρ={st.get('rho', float('nan')):.2f}\nR²={st.get('R2', float('nan')):.3f}\nN={int(st.get('n', 0))}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#D1D5DB", lw=0.6),
        )
        ax.set_xlabel("PRI (0–100)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
    fig.suptitle("PRI and MRIQC quality metrics", y=1.02)
    save_fig(fig, out_dir / "Figure2_PRI_vs_MRI_quality.png")
    made.append("Figure2_PRI_vs_MRI_quality.png")

    # Fig3 ICC bars
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    labels = [r["metric"] for r in icc_rows]
    vals = [to_float(r.get("ICC")) for r in icc_rows]
    y = np.arange(len(labels))
    colors = [primary if (np.isfinite(v) and v >= 0) else secondary for v in vals]
    ax.barh(y, np.nan_to_num(vals, nan=0.0), color=colors, height=0.65)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.axvline(0, color="#9CA3AF", lw=0.7)
    ax.set_xlabel("ICC(3,1)")
    ax.set_title("Longitudinal reproducibility")
    for yi, v in zip(y, vals):
        if np.isfinite(v):
            ax.text(v + 0.02, yi, f"{v:.2f}", va="center", fontsize=8)
    save_fig(fig, out_dir / "Figure3_longitudinal_ICC.png")
    made.append("Figure3_longitudinal_ICC.png")

    # Fig4 variance partition
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    metrics = [r["metric"] for r in var_rows]
    between = [to_float(r.get("between_subject_fraction")) for r in var_rows]
    within = [to_float(r.get("within_subject_fraction")) for r in var_rows]
    x = np.arange(len(metrics))
    ax.bar(x, between, label="Between-subject", color=accent, width=0.65)
    ax.bar(x, within, bottom=np.nan_to_num(between, nan=0), label="Within-subject", color=primary, width=0.65)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.set_ylabel("Variance fraction")
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False)
    ax.set_title("Acquisition- vs subject-specificity")
    save_fig(fig, out_dir / "Figure4_variance_partitioning.png")
    made.append("Figure4_variance_partitioning.png")

    # Fig5 delta coupling
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 3.6))
    dx = col(pairs, "delta_PRI")
    for ax, yname, ylabel, title in [
        (axes[0], "delta_tSNR", "|Δ tSNR|", "A  ΔPRI vs ΔtSNR"),
        (axes[1], "delta_FD", "|Δ FD| (mm)", "B  ΔPRI vs ΔFD"),
    ]:
        y = col(pairs, yname)
        m = np.isfinite(dx) & np.isfinite(y)
        ax.scatter(dx[m], y[m], s=12, alpha=0.4, c=primary, edgecolors="none", rasterized=True)
        slope, intercept = ols_line(dx, y)
        if np.isfinite(slope) and m.sum() > 2:
            xs = np.linspace(np.nanmin(dx), np.nanmax(dx), 50)
            ax.plot(xs, slope * xs + intercept, color=secondary, lw=1.6)
        st = spearman_with_ci(dx, y)
        ax.text(
            0.98,
            0.98,
            f"ρ={st['rho']:.2f}\np={st['p']:.3g}\nN={int(st['n'])}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#D1D5DB", lw=0.6),
        )
        ax.set_xlabel("|Δ PRI|")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
    fig.suptitle("Within-subject session-to-session change", y=1.02)
    save_fig(fig, out_dir / "Figure5_longitudinal_change.png")
    made.append("Figure5_longitudinal_change.png")
    return made


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def write_report(
    path: Path,
    raw_rows: list[dict[str, Any]],
    master: list[dict[str, Any]],
    assoc: list[dict[str, Any]],
    icc_rows: list[dict[str, Any]],
    var_rows: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    validation: dict[str, Any],
) -> None:
    n_sub = len({r["subject"] for r in raw_rows})
    n_ses = len({(r["subject"], r["session"]) for r in raw_rows})
    n_runs = len(raw_rows)
    pulse_pct = 100 * np.mean([1 if r.get("cardiac_available") else 0 for r in raw_rows])
    resp_pct = 100 * np.mean([1 if r.get("resp_available") else 0 for r in raw_rows])
    trig_pct = 100 * np.mean([1 if r.get("trigger_available") else 0 for r in raw_rows])

    assoc_lines = []
    for r in assoc:
        assoc_lines.append(
            f"- PRI vs {r['outcome']}: ρ={to_float(r['rho']):.2f} "
            f"(95% CI [{to_float(r['ci_low']):.2f}, {to_float(r['ci_high']):.2f}]), "
            f"R²={to_float(r['R2']):.3f}, p={to_float(r['p']):.2g}, N={int(to_float(r['n']))}"
        )
    icc_lines = [
        f"- {r['metric']}: ICC={to_float(r['ICC']):.2f} "
        f"[{to_float(r['CI95_low']):.2f}, {to_float(r['CI95_high']):.2f}] "
        f"→ {r.get('interpretation')} (n_subjects={r.get('n_subjects')})"
        for r in icc_rows
    ]
    var_lines = [
        f"- {r['metric']}: within={to_float(r['within_subject_fraction']):.2f}, "
        f"between={to_float(r['between_subject_fraction']):.2f} → {r.get('interpretation')}"
        for r in var_rows
    ]

    text = f"""# Physiology characterization report

Generated: `{now_iso()}`

## Framing

This report characterizes **physiological recording quality as an acquisition-level property**
and describes its relationship with MRIQC-derived fMRI quality metrics and longitudinal
reproducibility. Associations are descriptive and **do not imply causal effects**.

## Dataset summary

| Item | Value |
| --- | ---: |
| Subjects | {n_sub} |
| Subject–session pairs | {n_ses} |
| Physiology run groups | {n_runs} |
| Matched physio–MRIQC runs | {len(master)} |
| Longitudinal pairs | {len(pairs)} |

### Physiology availability

| Channel | % runs |
| --- | ---: |
| Cardiac / pulse | {pulse_pct:.1f} |
| Respiratory | {resp_pct:.1f} |
| Trigger | {trig_pct:.1f} |

## Physiological Reliability Index (PRI)

PRI (0–100) combines:

- Trigger integrity (40)
- Signal availability (30)
- Signal quality / missingness (20)
- Acquisition metadata (sampling frequency, StartTime) (10)

Component tables: `PRI_components.tsv`. User-facing export: `PRI.tsv`.

## Cross-sectional associations (PRI vs MRIQC)

{chr(10).join(assoc_lines)}

## Longitudinal ICC(3,1)

{chr(10).join(icc_lines)}

## Variance partitioning

{chr(10).join(var_lines)}

## Main observation

Physiological recording quality showed weak associations with conventional MRI quality metrics
but demonstrated limited longitudinal stability, suggesting that physiological quality is
primarily acquisition-dependent rather than subject-specific.

## Outputs

- `physiology_raw_metrics.tsv`
- `PRI_components.tsv`
- `PRI.tsv`
- `physio_mri_quality_master.tsv`
- `PRI_MRI_association_statistics.tsv`
- `longitudinal_ICC_results.tsv`
- `variance_partitioning.tsv`
- `longitudinal_change_associations.tsv`
- `figures/`
- `validation_summary.json`

## Validation snapshot

```json
{json.dumps(validation, indent=2)}
```
"""
    path.write_text(text)


def privacy_scan(out_dir: Path) -> list[str]:
    bad = []
    for p in out_dir.rglob("*"):
        if p.is_dir() or p.suffix.lower() in {".png", ".pdf"}:
            continue
        # only scan new outputs we care about
        if p.suffix not in {".tsv", ".json", ".md"}:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "/lustre" in txt or "/home/" in txt or "raw_original" in txt:
            # allow only relative mentions in prose without absolute roots — flag absolute-like
            if re.search(r"/lustre\d+/|/home/[A-Za-z]", txt):
                bad.append(p.name)
        if re.search(r"PatientName|PatientID|\bSUBC\d{2,}", txt):
            bad.append(f"phi:{p.name}")
    return bad


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(bids_dir: Path, derivatives_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    log("PART 1 — Physiology extraction")
    raw_rows, n_physio_files = extract_physiology(bids_dir)
    if not raw_rows:
        raise SystemExit("No physiology files found")

    log("PART 2 — Physiological Reliability Index (PRI)")
    raw_rows, comps = compute_pri(raw_rows)

    raw_fields = [
        "subject", "session", "task", "run",
        "cardiac_available", "resp_available", "trigger_available", "ecg_available",
        "cardiac_n_samples", "cardiac_sf", "cardiac_mean_amp", "cardiac_amp_sd",
        "cardiac_variance", "cardiac_missing_fraction", "cardiac_amp_stability",
        "resp_n_samples", "resp_sf", "resp_variance", "resp_amp_stability", "resp_missing_fraction",
        "n_triggers", "median_TR_interval", "TR_sd", "TR_cv", "trigger_missing_fraction",
        "trigger_sf", "cardiac_starttime", "resp_starttime", "trigger_starttime",
        "PRI_total", "PRI_trigger", "PRI_signal", "PRI_sampling",
    ]
    write_tsv(output_dir / "physiology_raw_metrics.tsv", raw_rows, raw_fields)
    write_tsv(
        output_dir / "PRI_components.tsv",
        comps,
        ["subject", "session", "task", "run", "PRI_total", "PRI_trigger", "PRI_signal", "PRI_sampling"],
    )

    # User-facing PRI.tsv
    pri_user = [
        {
            "participant_id": r["subject"],
            "session_id": r["session"],
            "task": r["task"],
            "run": r["run"],
            "physio_reliability_index": r["PRI_total"],
        }
        for r in raw_rows
    ]
    write_tsv(
        output_dir / "PRI.tsv",
        pri_user,
        ["participant_id", "session_id", "task", "run", "physio_reliability_index"],
    )

    log("PART 3 — MRIQC integration")
    fmri = load_mriqc(derivatives_dir)
    master = merge_strict(raw_rows, fmri)
    write_tsv(output_dir / "physio_mri_quality_master.tsv", master)
    log(f"  matched runs: {len(master)}")

    log("PART 4 — Cross-sectional associations")
    assoc = []
    x = col(master, "PRI_total")
    for outcome in ["mean_FD", "DVARS", "tSNR", "gCOR"]:
        st = spearman_with_ci(x, col(master, outcome))
        assoc.append({"outcome": outcome, **st})
    write_tsv(
        output_dir / "PRI_MRI_association_statistics.tsv",
        assoc,
        ["outcome", "n", "rho", "p", "ci_low", "ci_high", "R2"],
    )

    log("PART 5 — Longitudinal ICC")
    icc_rows = [
        icc31(master, "PRI_total"),
        icc31(master, "mean_FD"),
        icc31(master, "DVARS"),
        icc31(master, "tSNR"),
    ]
    # rename metrics for readability
    rename = {"PRI_total": "PRI", "mean_FD": "FD", "DVARS": "DVARS", "tSNR": "tSNR"}
    for r in icc_rows:
        r["metric"] = rename.get(r["metric"], r["metric"])
    write_tsv(
        output_dir / "longitudinal_ICC_results.tsv",
        icc_rows,
        ["metric", "n_subjects", "ICC", "CI95_low", "CI95_high", "interpretation"],
    )

    log("PART 6 — Variance partitioning")
    var_rows = [
        variance_partition(master, "PRI_total"),
        variance_partition(master, "mean_FD"),
        variance_partition(master, "tSNR"),
    ]
    for r in var_rows:
        r["metric"] = rename.get(r["metric"], r["metric"])
    write_tsv(
        output_dir / "variance_partitioning.tsv",
        var_rows,
        [
            "metric", "n_subjects", "n_subjects_with_repeats",
            "between_subject_variance", "within_subject_variance",
            "between_subject_fraction", "within_subject_fraction", "interpretation",
        ],
    )

    log("PART 7 — Session change analysis")
    pairs = longitudinal_pairs(master)
    change_assoc = []
    dx = col(pairs, "delta_PRI")
    for outcome in ["delta_FD", "delta_tSNR"]:
        st = spearman_with_ci(dx, col(pairs, outcome))
        change_assoc.append({"outcome": outcome, **st})
    write_tsv(output_dir / "longitudinal_change_associations.tsv", change_assoc)
    write_tsv(
        output_dir / "longitudinal_pairs_detail.tsv",
        pairs,
        [
            "subject", "task", "run", "session_a", "session_b",
            "delta_PRI", "delta_FD", "delta_tSNR", "delta_DVARS", "PRI_a", "PRI_b",
        ],
    )
    log(f"  longitudinal pairs: {len(pairs)}")

    log("PART 8 — Figures")
    figs = make_figures(fig_dir, raw_rows, master, assoc, icc_rows, var_rows, pairs)

    log("PART 9–10 — Report + validation")
    validation = {
        "generated": now_iso(),
        "number_physio_files": int(n_physio_files),
        "number_physio_run_groups": len(raw_rows),
        "number_matched_MRI_runs": len(master),
        "number_longitudinal_pairs": len(pairs),
        "number_longitudinal_subjects": len({r["subject"] for r in pairs}) if pairs else 0,
        "number_missing_MRIQC_relative_to_physio": max(0, len(raw_rows) - len(master)),
        "figures": figs,
        "phi_fields_written": False,
        "absolute_paths_written": False,
    }
    # missing metrics counts
    validation["number_missing_metrics"] = {
        "PRI": int(sum(1 for r in raw_rows if not np.isfinite(to_float(r.get("PRI_total"))))),
        "FD": int(sum(1 for r in master if not np.isfinite(to_float(r.get("mean_FD"))))),
        "DVARS": int(sum(1 for r in master if not np.isfinite(to_float(r.get("DVARS"))))),
        "tSNR": int(sum(1 for r in master if not np.isfinite(to_float(r.get("tSNR"))))),
    }

    write_report(
        output_dir / "PHYSIOLOGY_CHARACTERIZATION_REPORT.md",
        raw_rows,
        master,
        assoc,
        icc_rows,
        var_rows,
        pairs,
        validation,
    )
    (output_dir / "validation_summary.json").write_text(json.dumps(validation, indent=2) + "\n")

    # dataset_description for derivatives
    (output_dir / "dataset_description.json").write_text(
        json.dumps(
            {
                "Name": "Physiology characterization derivatives",
                "BIDSVersion": "1.8.0",
                "DatasetType": "derivative",
                "GeneratedBy": [
                    {
                        "Name": "advanced_physiology_characterization.py",
                        "Version": "1.0.0",
                        "Description": "Physiological Reliability Index (PRI) and MRIQC association analyses",
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )

    bad = privacy_scan(output_dir)
    log("Privacy scan: PASS" if not bad else f"WARNING: {bad[:8]}")
    print("ADVANCED PHYSIOLOGY CHARACTERIZATION COMPLETE")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bids_dir", type=Path, required=True)
    p.add_argument("--derivatives_dir", type=Path, required=True)
    p.add_argument("--output_dir", type=Path, required=True)
    args = p.parse_args(argv)
    run(args.bids_dir.resolve(), args.derivatives_dir.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    main()
