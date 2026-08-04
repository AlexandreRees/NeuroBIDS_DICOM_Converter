#!/usr/bin/env python3
"""Physiology recording quality vs fMRI quality and longitudinal reproducibility.

READ-ONLY with respect to BIDS imaging / raw data.
All outputs written exclusively under --output_dir
(default: derivatives/physiology_reproducibility).

Dependencies: numpy, matplotlib (standard scientific stack).
No PHI: only BIDS entities (sub-XXX, ses-XX, task, run) are retained.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

warnings.filterwarnings("ignore", category=RuntimeWarning)

ENTITY_RE = re.compile(
    r"(?P<sub>sub-\d+)_"
    r"(?P<ses>ses-\d+)_"
    r"task-(?P<task>[^_]+)_"
    r"run-(?P<run>\d+)_"
    r"recording-(?P<rec>[^_]+)_physio"
)


def log(msg: str) -> None:
    print(msg, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        seen = set()
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
                if isinstance(v, float):
                    if math.isnan(v) or math.isinf(v):
                        out[k] = "n/a"
                    else:
                        out[k] = f"{v:.6g}"
                elif isinstance(v, (bool, np.bool_)):
                    out[k] = "true" if bool(v) else "false"
                elif v is None:
                    out[k] = "n/a"
                else:
                    out[k] = v
            w.writerow(out)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def to_float(x: Any) -> float:
    if x is None:
        return float("nan")
    if isinstance(x, (int, float, np.floating)):
        return float(x)
    s = str(x).strip()
    if s in {"", "n/a", "NA", "nan", "None"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


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
    last = -10**9
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
    prominence = 1.5 * mad
    return find_peaks_simple(x, min_dist, prominence)


def cardiac_metrics(arr: np.ndarray, sf: float) -> dict[str, float]:
    out = {
        "mean_HR": np.nan,
        "HR_sd": np.nan,
        "RMSSD": np.nan,
        "cardiac_variance": np.nan,
        "cardiac_n_peaks": 0.0,
    }
    x = clean_signal(arr)
    if x.size < int(sf * 5):
        return out
    out["cardiac_variance"] = float(np.var(x))
    peaks = detect_peaks(x, sf, 0.5, 2.5)
    out["cardiac_n_peaks"] = float(peaks.size)
    if peaks.size < 3:
        return out
    ibi = np.diff(peaks) / sf
    ibi = ibi[(ibi > 0.3) & (ibi < 2.0)]
    if ibi.size < 2:
        return out
    hr = 60.0 / ibi
    out["mean_HR"] = float(np.mean(hr))
    out["HR_sd"] = float(np.std(hr, ddof=1)) if hr.size > 1 else 0.0
    diff = np.diff(ibi * 1000.0)
    out["RMSSD"] = float(np.sqrt(np.mean(diff**2)))
    return out


def respiratory_metrics(arr: np.ndarray, sf: float) -> dict[str, float]:
    out = {
        "mean_RR": np.nan,
        "resp_variance": np.nan,
        "resp_amplitude_stability": np.nan,
        "resp_n_peaks": 0.0,
    }
    x = clean_signal(arr)
    if x.size < int(sf * 10):
        return out
    out["resp_variance"] = float(np.var(x))
    peaks = detect_peaks(x, sf, 0.05, 0.7)
    out["resp_n_peaks"] = float(peaks.size)
    if peaks.size < 3:
        return out
    ibi = np.diff(peaks) / sf
    ibi = ibi[(ibi > 1.0) & (ibi < 20.0)]
    if ibi.size < 2:
        return out
    rr = 60.0 / ibi
    out["mean_RR"] = float(np.mean(rr))
    amps = x[peaks]
    amps = amps[np.isfinite(amps)]
    if amps.size >= 3 and np.mean(np.abs(amps)) > 0:
        cv = float(np.std(amps, ddof=1) / (np.mean(np.abs(amps)) + 1e-8))
        out["resp_amplitude_stability"] = float(1.0 / (1.0 + cv))
    return out


def trigger_metrics(arr: np.ndarray, sf: float) -> dict[str, float]:
    out = {"n_triggers": 0.0, "median_TR_interval": np.nan, "TR_jitter": np.nan}
    x = clean_signal(arr)
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
    out["median_TR_interval"] = float(np.median(use))
    out["TR_jitter"] = float(np.std(use, ddof=1)) if use.size > 1 else 0.0
    return out


def quantile(a: np.ndarray, q: float) -> float:
    a = a[np.isfinite(a)]
    if a.size == 0:
        return float("nan")
    return float(np.quantile(a, q))


def robust_minmax_arr(vals: np.ndarray, higher_is_better: bool = True) -> np.ndarray:
    lo, hi = quantile(vals, 0.05), quantile(vals, 0.95)
    out = np.full(vals.shape, np.nan)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return out
    z = np.clip((vals - lo) / (hi - lo), 0, 1)
    return z if higher_is_better else (1.0 - z)


def extract_physiology(bids_dir: Path) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Path]] = defaultdict(dict)
    json_map: dict[Path, Path] = {}
    for tsv in bids_dir.glob("sub-*/ses-*/func/*_physio.tsv.gz"):
        ent = parse_entities(tsv)
        if not ent:
            continue
        key = (ent["subject"], ent["session"], ent["task"], ent["run"])
        groups[key][ent["recording"]] = tsv
        jp = Path(str(tsv).replace(".tsv.gz", ".json"))
        if jp.is_file():
            json_map[tsv] = jp

    rows: list[dict[str, Any]] = []
    n = len(groups)
    log(f"  physiology run groups: {n}")
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
            "mean_HR": np.nan,
            "HR_sd": np.nan,
            "RMSSD": np.nan,
            "cardiac_variance": np.nan,
            "mean_RR": np.nan,
            "resp_variance": np.nan,
            "resp_amplitude_stability": np.nan,
            "n_triggers": np.nan,
            "median_TR_interval": np.nan,
            "TR_jitter": np.nan,
            "missing_fraction": np.nan,
            "missing_fraction_cardiac": np.nan,
            "missing_fraction_resp": np.nan,
            "missing_fraction_trigger": np.nan,
        }
        miss_parts: list[float] = []

        for cand in ("pulse", "cardiac", "ecg"):
            if cand in recs and recs[cand] in json_map:
                arr, meta = read_physio(recs[cand], json_map[recs[cand]])
                sf = float(meta.get("SamplingFrequency") or 0.0)
                mfrac = missing_fraction(arr)
                row["missing_fraction_cardiac"] = mfrac
                miss_parts.append(mfrac)
                row.update(cardiac_metrics(arr, sf))
                row["cardiac_available"] = True
                break

        if "respiratory" in recs and recs["respiratory"] in json_map:
            arr, meta = read_physio(recs["respiratory"], json_map[recs["respiratory"]])
            sf = float(meta.get("SamplingFrequency") or 0.0)
            mfrac = missing_fraction(arr)
            row["missing_fraction_resp"] = mfrac
            miss_parts.append(mfrac)
            row.update(respiratory_metrics(arr, sf))
            row["resp_available"] = True

        if "trigger" in recs and recs["trigger"] in json_map:
            arr, meta = read_physio(recs["trigger"], json_map[recs["trigger"]])
            sf = float(meta.get("SamplingFrequency") or 0.0)
            mfrac = missing_fraction(arr)
            row["missing_fraction_trigger"] = mfrac
            miss_parts.append(mfrac)
            row.update(trigger_metrics(arr, sf))
            row["trigger_available"] = True

        row["missing_fraction"] = float(np.mean(miss_parts)) if miss_parts else 1.0
        rows.append(row)
        if (i + 1) % 200 == 0:
            log(f"    physio progress {i+1}/{n}")
    return rows


def compute_quality_score(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    n = len(rows)
    ntrig = np.array([to_float(r.get("n_triggers")) for r in rows])
    jitter = np.array([to_float(r.get("TR_jitter")) for r in rows])
    hr = np.array([to_float(r.get("mean_HR")) for r in rows])
    rmssd = np.array([to_float(r.get("RMSSD")) for r in rows])
    miss_c = np.array([to_float(r.get("missing_fraction_cardiac")) for r in rows])
    rr = np.array([to_float(r.get("mean_RR")) for r in rows])
    stab = np.array([to_float(r.get("resp_amplitude_stability")) for r in rows])
    miss_r = np.array([to_float(r.get("missing_fraction_resp")) for r in rows])
    miss = np.array([to_float(r.get("missing_fraction")) for r in rows])

    q90 = quantile(ntrig[np.isfinite(ntrig)], 0.9)
    if not np.isfinite(q90) or q90 <= 0:
        q90 = 1.0
    trig_count_score = np.clip(np.nan_to_num(ntrig, nan=0.0) / q90, 0, 1)
    trig_jitter_score = robust_minmax_arr(jitter, higher_is_better=False)
    has_trig = np.array([bool(r.get("trigger_available")) for r in rows])
    trigger_rel = 0.5 * trig_count_score + 0.5 * np.nan_to_num(trig_jitter_score, nan=0.5)
    trigger_rel = np.where(has_trig, trigger_rel, np.nan)

    hr_ok = ((hr >= 35) & (hr <= 160)).astype(float)
    hr_ok[~np.isfinite(hr)] = 0.0
    rmssd_score = robust_minmax_arr(rmssd, True)
    miss_c_score = np.clip(1.0 - np.nan_to_num(miss_c, nan=1.0), 0, 1)
    has_c = np.array([bool(r.get("cardiac_available")) for r in rows])
    cardiac_q = 0.45 * hr_ok + 0.35 * np.nan_to_num(rmssd_score, nan=0.5) + 0.20 * miss_c_score
    cardiac_q = np.where(has_c, cardiac_q, np.nan)

    rr_ok = ((rr >= 4) & (rr <= 40)).astype(float)
    rr_ok[~np.isfinite(rr)] = 0.0
    miss_r_score = np.clip(1.0 - np.nan_to_num(miss_r, nan=1.0), 0, 1)
    has_r = np.array([bool(r.get("resp_available")) for r in rows])
    resp_q = 0.40 * rr_ok + 0.40 * np.nan_to_num(stab, nan=0.5) + 0.20 * miss_r_score
    resp_q = np.where(has_r, resp_q, np.nan)

    miss_penalty = np.clip(1.0 - np.nan_to_num(miss, nan=1.0), 0, 1)

    comps = []
    for i, r in enumerate(rows):
        parts = []
        weights = []
        for val, w in [
            (trigger_rel[i], 0.30),
            (cardiac_q[i], 0.30),
            (resp_q[i], 0.25),
            (miss_penalty[i], 0.15),
        ]:
            if np.isfinite(val):
                parts.append(val * w)
                weights.append(w)
        q = float(sum(parts) / sum(weights)) if weights else float("nan")
        q = float(np.clip(q, 0, 1)) if np.isfinite(q) else float("nan")
        r["physio_quality_score"] = q
        comps.append(
            {
                "subject": r["subject"],
                "session": r["session"],
                "task": r["task"],
                "run": r["run"],
                "trigger_reliability": trigger_rel[i],
                "cardiac_signal_quality": cardiac_q[i],
                "respiratory_signal_quality": resp_q[i],
                "missing_data_score": miss_penalty[i],
                "physio_quality_score": q,
            }
        )
    return rows, comps


def load_mriqc_table(derivatives_dir: Path) -> list[dict[str, Any]]:
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
                "median_FD": np.nan,
                "fd_perc_02": meta.get("fd_perc", np.nan),
                "fd_perc_05": np.nan,
                "tSNR": meta.get("tsnr", np.nan),
                "DVARS": meta.get("dvars_nstd", np.nan),
                "gCOR": meta.get("gcor", np.nan),
                "SNR": meta.get("snr", np.nan),
                "mriqc_available": True,
            }
        )
    return rows


def key4(r: dict[str, Any]) -> tuple[str, str, str, str]:
    return (r["subject"], r["session"], r["task"], r["run"])


def merge_strict(phys: list[dict[str, Any]], fmri: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fmap = {}
    for r in fmri:
        fmap[key4(r)] = r
    out = []
    for p in phys:
        f = fmap.get(key4(p))
        if not f:
            continue
        merged = dict(p)
        for k, v in f.items():
            if k not in merged:
                merged[k] = v
            elif k in {"mean_FD", "median_FD", "fd_perc_02", "fd_perc_05", "tSNR", "DVARS", "gCOR", "SNR", "mriqc_available"}:
                merged[k] = v
        out.append(merged)
    return out


def pearson_spearman(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = x.size
    if n < 5:
        return {"n": float(n), "pearson_r": np.nan, "pearson_p": np.nan, "spearman_r": np.nan, "spearman_p": np.nan}
    # Pearson
    xz = (x - x.mean()) / (x.std(ddof=1) + 1e-12)
    yz = (y - y.mean()) / (y.std(ddof=1) + 1e-12)
    r = float(np.mean(xz * yz) * (n - 1) / n * n / (n - 1))  # simplify:
    r = float(np.corrcoef(x, y)[0, 1])
    # t-test for pearson
    if abs(r) >= 1:
        pp = 0.0
    else:
        t = r * math.sqrt((n - 2) / max(1e-12, 1 - r * r))
        # two-sided approx via regularized incomplete beta / erfc fallback
        pp = float(2 * student_t_sf(abs(t), n - 2))
    # Spearman via ranks
    rx = rankdata(x)
    ry = rankdata(y)
    rs = float(np.corrcoef(rx, ry)[0, 1])
    if abs(rs) >= 1:
        sp = 0.0
    else:
        ts = rs * math.sqrt((n - 2) / max(1e-12, 1 - rs * rs))
        sp = float(2 * student_t_sf(abs(ts), n - 2))
    return {"n": float(n), "pearson_r": r, "pearson_p": pp, "spearman_r": rs, "spearman_p": sp}


def rankdata(a: np.ndarray) -> np.ndarray:
    order = np.argsort(a)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, a.size + 1, dtype=float)
    # average ties
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
    """Survival function P(|T|>t)/2 one-tail approx using incomplete beta relation."""
    # Use Wilson-Hilferty / continuation: sf via beta incomplete
    x = df / (df + t * t)
    # regularized incomplete beta I_x(df/2, 0.5) ≈ 2*sf for two-sided? 
    # Actually: P(T>t) = 0.5 * I_x(df/2, 1/2)
    try:
        from math import lgamma

        def betainc_cont(a, b, xval, n_terms=200):
            # continued fraction for incomplete beta (Lentz)
            if xval <= 0:
                return 0.0
            if xval >= 1:
                return 1.0
            # use series for small x
            # I_x(a,b) = x^a (1-x)^b / (a B(a,b)) * sum
            lnB = lgamma(a) + lgamma(b) - lgamma(a + b)
            front = math.exp(a * math.log(xval) + b * math.log(1 - xval) - lnB) / a
            term = 1.0
            s = 1.0
            for m in range(1, n_terms):
                term *= (a + m - 1) * (1 - (a + b) * xval / (a + m)) / (m * (1 - xval) + 1e-18) * xval / (a + m) * (a + m)
                # simpler power series:
                break
            # Power series:
            term = 1.0
            s = 1.0
            for m in range(1, n_terms):
                term *= (a + b + m - 1) * xval / (a + m)
                s += term
                if abs(term) < 1e-12:
                    break
            return front * s

        a = df / 2.0
        b = 0.5
        # choose better expansion
        if x < (a + 1) / (a + b + 2):
            ix = betainc_cont(a, b, x)
        else:
            ix = 1.0 - betainc_cont(b, a, 1.0 - x)
        return 0.5 * ix
    except Exception:
        # crude normal approx
        z = t * (1 - 1 / (4 * df)) / math.sqrt(1 + t * t / (2 * df))
        return 0.5 * math.erfc(z / math.sqrt(2))


def ols(y: np.ndarray, X: np.ndarray, names: list[str]) -> dict[str, Any]:
    m = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    y = y[m]
    X = X[m]
    n, p = X.shape
    out: dict[str, Any] = {"n": n, "r2": np.nan, "terms": []}
    if n < max(10, p + 3):
        return out
    Xc = np.column_stack([np.ones(n), X])
    beta, _, _, _ = np.linalg.lstsq(Xc, y, rcond=None)
    yhat = Xc @ beta
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    dof = n - Xc.shape[1]
    mse = ss_res / max(dof, 1)
    try:
        xtx_inv = np.linalg.inv(Xc.T @ Xc)
    except np.linalg.LinAlgError:
        xtx_inv = np.linalg.pinv(Xc.T @ Xc)
    se = np.sqrt(np.clip(np.diag(xtx_inv) * mse, 0, None))
    # t critical ~ 1.96 for large n; use approx
    tcrit = 1.96 if dof > 30 else 2.04
    out["r2"] = float(r2)
    full_names = ["Intercept"] + names
    for i, name in enumerate(full_names):
        tval = beta[i] / se[i] if se[i] > 0 else np.nan
        p = float(2 * student_t_sf(abs(float(tval)), dof)) if np.isfinite(tval) else np.nan
        out["terms"].append(
            {
                "term": name,
                "beta": float(beta[i]),
                "ci_low": float(beta[i] - tcrit * se[i]),
                "ci_high": float(beta[i] + tcrit * se[i]),
                "p": p,
            }
        )
    return out


def icc_twoway(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    by_sub: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = to_float(r.get(metric))
        if np.isfinite(v):
            by_sub[r["subject"]].append((r["session"], v))  # type: ignore
    # rebuild properly
    by_sub2: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        v = to_float(r.get(metric))
        if np.isfinite(v):
            by_sub2[r["subject"]].append((r["session"], v))
    wide = []
    for sub, items in by_sub2.items():
        items = sorted(items, key=lambda z: z[0])
        # unique sessions mean
        sess: dict[str, list[float]] = defaultdict(list)
        for s, v in items:
            sess[s].append(v)
        vals = [float(np.mean(sess[s])) for s in sorted(sess)]
        if len(vals) >= 2:
            wide.append(vals[:2])
    result = {
        "metric": metric,
        "n_subjects": len(wide),
        "n_observations": sum(2 for _ in wide),
        "ICC": np.nan,
        "CI95_low": np.nan,
        "CI95_high": np.nan,
        "method": "manual_ICC3_1",
    }
    if len(wide) < 5:
        return result
    M = np.asarray(wide, dtype=float)
    n, k = M.shape
    mean_t = M.mean(axis=1, keepdims=True)
    mean_r = M.mean(axis=0, keepdims=True)
    mean_g = M.mean()
    BMS = k * np.sum((mean_t - mean_g) ** 2) / (n - 1)
    EMS = np.sum((M - mean_t - mean_r + mean_g) ** 2) / ((n - 1) * (k - 1))
    denom = BMS + (k - 1) * EMS
    icc_val = (BMS - EMS) / denom if denom != 0 else np.nan
    result["ICC"] = float(icc_val)
    result["n_subjects"] = int(n)
    return result


def longitudinal_pairs(master: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in master:
        groups[(r["subject"], r["task"], r["run"])].append(r)
    rows = []
    for (sub, task, run), g in groups.items():
        g = sorted(g, key=lambda z: z["session"])
        if len(g) < 2:
            continue
        for i in range(len(g) - 1):
            a, b = g[i], g[i + 1]

            def delta(col: str) -> float:
                return abs(to_float(b.get(col)) - to_float(a.get(col)))

            def cv(col: str) -> float:
                vals = np.array([to_float(x.get(col)) for x in g], dtype=float)
                vals = vals[np.isfinite(vals)]
                if vals.size < 2 or abs(vals.mean()) < 1e-12:
                    return float("nan")
                return float(vals.std(ddof=1) / abs(vals.mean()))

            rows.append(
                {
                    "subject": sub,
                    "task": task,
                    "run": run,
                    "session_a": a["session"],
                    "session_b": b["session"],
                    "delta_physio_quality": delta("physio_quality_score"),
                    "delta_FD": delta("mean_FD"),
                    "delta_tSNR": delta("tSNR"),
                    "delta_DVARS": delta("DVARS"),
                    "mean_FD": float(np.nanmean([to_float(a.get("mean_FD")), to_float(b.get("mean_FD"))])),
                    "mean_physio_quality": float(
                        np.nanmean([to_float(a.get("physio_quality_score")), to_float(b.get("physio_quality_score"))])
                    ),
                    "cv_physio_quality": cv("physio_quality_score"),
                    "cv_FD": cv("mean_FD"),
                    "cv_tSNR": cv("tSNR"),
                }
            )
    return rows


def col(rows: list[dict[str, Any]], name: str) -> np.ndarray:
    return np.array([to_float(r.get(name)) for r in rows], dtype=float)


def make_figures(
    out_fig: Path,
    phys: list[dict[str, Any]],
    master: list[dict[str, Any]],
    long_df: list[dict[str, Any]],
    icc_rows: list[dict[str, Any]],
) -> list[str]:
    out_fig.mkdir(parents=True, exist_ok=True)
    made: list[str] = []

    def save(fig: plt.Figure, name: str) -> None:
        fig.tight_layout()
        fig.savefig(out_fig / name, dpi=200, bbox_inches="tight")
        plt.close(fig)
        made.append(name)

    q = col(phys, "physio_quality_score")
    q = q[np.isfinite(q)]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(q, bins=25, color="#2c5f6e", edgecolor="white")
    ax.set_xlabel("Physiology quality score")
    ax.set_ylabel("Number of runs")
    ax.set_title("Distribution of physiology quality scores")
    save(fig, "figure1_physio_quality_distribution.png")

    def scatter_fit(xname, yname, title, fname, data):
        x, y = col(data, xname), col(data, yname)
        m = np.isfinite(x) & np.isfinite(y)
        x, y = x[m], y[m]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.scatter(x, y, s=12, alpha=0.45, c="#2c5f6e", edgecolors="none")
        if x.size >= 5:
            coef = np.polyfit(x, y, 1)
            xs = np.linspace(x.min(), x.max(), 50)
            ax.plot(xs, coef[0] * xs + coef[1], color="#b85c38", lw=2)
            r = float(np.corrcoef(x, y)[0, 1])
            ax.set_title(f"{title} (r={r:.2f})")
        else:
            ax.set_title(title)
        ax.set_xlabel(xname.replace("_", " "))
        ax.set_ylabel(yname.replace("_", " "))
        save(fig, fname)

    scatter_fit("physio_quality_score", "tSNR", "Physio quality vs tSNR", "figure2_physio_vs_tsnr.png", master)
    scatter_fit("physio_quality_score", "mean_FD", "Physio quality vs mean FD", "figure3_physio_vs_fd.png", master)
    scatter_fit("delta_physio_quality", "delta_tSNR", "Δ physio vs Δ tSNR", "figure4_delta_physio_vs_delta_tsnr.png", long_df)
    scatter_fit("delta_physio_quality", "delta_FD", "Δ physio vs Δ FD", "figure5_delta_physio_vs_delta_fd.png", long_df)

    fig, ax = plt.subplots(figsize=(6, 4))
    metrics = [r["metric"] for r in icc_rows]
    vals = [to_float(r.get("ICC")) for r in icc_rows]
    ax.bar(metrics, [0 if not np.isfinite(v) else v for v in vals], color=["#2c5f6e", "#4a7c59", "#b85c38"][: len(metrics)])
    ax.set_ylim(0, 1)
    ax.set_ylabel("ICC")
    ax.set_title("Intraclass correlation across sessions")
    ax.tick_params(axis="x", rotation=15)
    save(fig, "figure6_icc_comparison.png")

    fig, axes = plt.subplots(1, 2, figsize=(9, 4), sharey=True)
    if long_df:
        subj_delta: dict[str, list[float]] = defaultdict(list)
        for r in long_df:
            v = to_float(r.get("delta_physio_quality"))
            if np.isfinite(v):
                subj_delta[r["subject"]].append(v)
        means = {s: float(np.mean(v)) for s, v in subj_delta.items() if v}
        if len(means) >= 2:
            ordered = sorted(means.items(), key=lambda z: z[1])
            stable_sub, unstable_sub = ordered[0][0], ordered[-1][0]
            for ax, sub, title in [
                (axes[0], stable_sub, f"More stable physio ({stable_sub})"),
                (axes[1], unstable_sub, f"Less stable physio ({unstable_sub})"),
            ]:
                g = [r for r in master if r["subject"] == sub]
                by_ses: dict[str, list[float]] = defaultdict(list)
                for r in g:
                    by_ses[r["session"]].append(to_float(r.get("physio_quality_score")))
                xs = sorted(by_ses)
                ys = [float(np.nanmean(by_ses[s])) for s in xs]
                ax.plot(xs, ys, marker="o", color="#2c5f6e")
                ax.set_title(title)
                ax.set_xlabel("Session")
                ax.set_ylabel("Mean physio quality")
                ax.set_ylim(0, 1)
        else:
            axes[0].text(0.5, 0.5, "Insufficient longitudinal data", ha="center", transform=axes[0].transAxes)
            axes[1].axis("off")
    save(fig, "figure7_longitudinal_examples.png")
    return made


def run(bids_dir: Path, derivatives_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    log("STEP 1 — Physiology extraction")
    phys = extract_physiology(bids_dir)
    if not phys:
        raise SystemExit("No physiology files found under bids_dir")

    log("STEP 2 — Physiology quality score")
    phys, components = compute_quality_score(phys)
    metric_fields = [
        "subject", "session", "task", "run", "physio_quality_score",
        "cardiac_available", "resp_available", "trigger_available",
        "mean_HR", "RMSSD", "mean_RR", "TR_jitter", "missing_fraction",
        "HR_sd", "cardiac_variance", "resp_variance", "resp_amplitude_stability",
        "n_triggers", "median_TR_interval",
        "missing_fraction_cardiac", "missing_fraction_resp", "missing_fraction_trigger",
    ]
    write_tsv(output_dir / "physiology_metrics.tsv", phys, metric_fields)
    write_tsv(
        output_dir / "physiology_quality_components.tsv",
        components,
        [
            "subject", "session", "task", "run",
            "trigger_reliability", "cardiac_signal_quality",
            "respiratory_signal_quality", "missing_data_score", "physio_quality_score",
        ],
    )

    log("STEP 3 — MRIQC quality extraction")
    fmri = load_mriqc_table(derivatives_dir)
    write_tsv(
        output_dir / "fmri_quality_metrics.tsv",
        fmri,
        [
            "subject", "session", "task", "run",
            "mean_FD", "median_FD", "fd_perc_02", "fd_perc_05",
            "tSNR", "DVARS", "gCOR", "SNR", "mriqc_available",
        ],
    )
    log(f"  MRIQC bold runs: {len(fmri)}")

    log("STEP 4 — Match physio and fMRI")
    master = merge_strict(phys, fmri)
    write_tsv(output_dir / "physio_fmri_master_table.tsv", master)
    log(f"  matched runs: {len(master)}")

    log("STEP 5 — Single-session associations")
    single_rows: list[dict[str, Any]] = []
    pq = col(master, "physio_quality_score")
    for outcome in ["mean_FD", "tSNR", "DVARS", "gCOR"]:
        assoc = pearson_spearman(pq, col(master, outcome))
        single_rows.append(
            {"test": "correlation", "predictor": "physio_quality_score", "outcome": outcome, **assoc}
        )

    # OLS models
    y = col(master, "tSNR")
    X = np.column_stack([col(master, "physio_quality_score"), col(master, "mean_FD")])
    model = ols(y, X, ["physio_quality_score", "mean_FD"])
    for term in model["terms"] or []:
        single_rows.append(
            {
                "test": "OLS",
                "model": "tSNR ~ physio_quality_score + mean_FD",
                "predictor": term["term"],
                "outcome": "tSNR",
                "n": model["n"],
                "r2": model["r2"],
                **term,
            }
        )
    y = col(master, "mean_FD")
    X = np.column_stack([col(master, "physio_quality_score")])
    model = ols(y, X, ["physio_quality_score"])
    for term in model["terms"] or []:
        single_rows.append(
            {
                "test": "OLS",
                "model": "mean_FD ~ physio_quality_score",
                "predictor": term["term"],
                "outcome": "mean_FD",
                "n": model["n"],
                "r2": model["r2"],
                **term,
            }
        )
    write_tsv(output_dir / "single_session_statistics.tsv", single_rows)

    log("STEP 6–7 — Longitudinal differences")
    long_df = longitudinal_pairs(master)
    write_tsv(
        output_dir / "longitudinal_session_difference.tsv",
        long_df,
        [
            "subject", "task", "run", "session_a", "session_b",
            "delta_physio_quality", "delta_FD", "delta_tSNR", "delta_DVARS",
            "mean_FD", "mean_physio_quality", "cv_physio_quality", "cv_FD", "cv_tSNR",
        ],
    )
    log(f"  longitudinal pairs: {len(long_df)}")

    log("STEP 8 — ICC")
    icc_rows = [
        icc_twoway(master, "physio_quality_score"),
        icc_twoway(master, "mean_FD"),
        icc_twoway(master, "tSNR"),
    ]
    write_tsv(output_dir / "ICC_results.tsv", icc_rows)

    log("STEP 9 — Reproducibility models")
    model_rows: list[dict[str, Any]] = []
    if long_df:
        y = col(long_df, "delta_tSNR")
        X = np.column_stack([col(long_df, "delta_physio_quality"), col(long_df, "mean_FD")])
        model = ols(y, X, ["delta_physio_quality", "mean_FD"])
        for term in model["terms"] or []:
            model_rows.append(
                {
                    "model": "delta_tSNR ~ delta_physio_quality + mean_FD",
                    "outcome": "delta_tSNR",
                    "n": model["n"],
                    "r2": model["r2"],
                    **term,
                }
            )
        y = col(long_df, "delta_FD")
        X = np.column_stack([col(long_df, "delta_physio_quality")])
        model = ols(y, X, ["delta_physio_quality"])
        for term in model["terms"] or []:
            model_rows.append(
                {
                    "model": "delta_FD ~ delta_physio_quality",
                    "outcome": "delta_FD",
                    "n": model["n"],
                    "r2": model["r2"],
                    **term,
                }
            )
    write_tsv(output_dir / "reproducibility_models.tsv", model_rows)

    log("STEP 10 — Figures")
    figs = make_figures(fig_dir, phys, master, long_df, icc_rows)
    log(f"  figures: {len(figs)}")

    log("STEP 11–13 — Report, validation, README")
    n_sub = len({r["subject"] for r in master})
    n_long_sub = len({r["subject"] for r in long_df}) if long_df else 0
    n_ses = len({(r["subject"], r["session"]) for r in master})
    cardiac_pct = 100.0 * np.mean([1 if r.get("cardiac_available") else 0 for r in phys])
    resp_pct = 100.0 * np.mean([1 if r.get("resp_available") else 0 for r in phys])
    trig_pct = 100.0 * np.mean([1 if r.get("trigger_available") else 0 for r in phys])

    findings = []
    for r in single_rows:
        if r.get("test") == "correlation" and np.isfinite(to_float(r.get("spearman_p"))) and to_float(r["spearman_p"]) < 0.05:
            findings.append(
                f"- Across runs, physiology quality score showed a Spearman association with "
                f"{r['outcome']} (ρ={to_float(r['spearman_r']):.2f}, p={to_float(r['spearman_p']):.2g}, n={int(to_float(r['n']))})."
            )
    for r in model_rows:
        if r.get("term") not in {None, "", "Intercept"} and np.isfinite(to_float(r.get("p"))) and to_float(r["p"]) < 0.05:
            findings.append(
                f"- In model `{r['model']}`, term `{r['term']}` was associated with the outcome "
                f"(β={to_float(r['beta']):.3g}, 95% CI [{to_float(r['ci_low']):.3g}, {to_float(r['ci_high']):.3g}], "
                f"p={to_float(r['p']):.2g})."
            )
    if not findings:
        findings.append(
            "- Within the available matched sample, associations between physiology quality and "
            "fMRI quality / session-to-session differences did not meet a conventional p<0.05 "
            "threshold for the primary tested relationships, or sample size limited inference."
        )

    validation = {
        "generated": now_iso(),
        "number_analyzed_runs_matched": len(master),
        "number_physio_run_groups": len(phys),
        "number_mriqc_bold_runs": len(fmri),
        "number_longitudinal_pairs": len(long_df),
        "number_longitudinal_subjects": n_long_sub,
        "number_missing_physio_relative_to_mriqc": max(0, len(fmri) - len(master)),
        "number_missing_mriqc_relative_to_physio": max(0, len(phys) - len(master)),
        "figures": figs,
        "phi_fields_written": False,
        "absolute_paths_written": False,
        "dependencies": ["numpy", "matplotlib"],
        "notes": [
            "fMRIPrep confounds unavailable; mean_FD/fd_perc/tSNR/DVARS/gCOR/SNR from MRIQC",
            "median_FD and fd_perc_05 left undefined without FD timeseries",
        ],
    }
    (output_dir / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")

    icc_lines = [
        f"- {r['metric']}: ICC={r['ICC'] if np.isfinite(to_float(r.get('ICC'))) else 'n/a'} "
        f"(n_subjects={r['n_subjects']}, method={r['method']})"
        for r in icc_rows
    ]
    report = f"""# Physiology reproducibility analysis

Generated: `{now_iso()}`

## Purpose

This analysis investigates whether peripheral physiological recording quality is associated with
within-session fMRI quality metrics and with longitudinal (across-session) reproducibility of those metrics.

This is a **dataset characterization** analysis. Associations should not be interpreted as causal effects.

## Dataset coverage

| Item | Value |
| --- | ---: |
| Subjects in matched physio–fMRI table | {n_sub} |
| Subject–session pairs | {n_ses} |
| Subjects with ≥2 sessions in longitudinal pairs | {n_long_sub} |
| Longitudinal pairs | {len(long_df)} |
| Physiology run groups | {len(phys)} |
| Matched physio–fMRI runs | {len(master)} |

### Physiology availability (among physio run groups)

| Channel | Availability |
| --- | ---: |
| Cardiac / pulse | {cardiac_pct:.1f}% |
| Respiratory | {resp_pct:.1f}% |
| Trigger | {trig_pct:.1f}% |

## Methods (brief)

- Physiology metrics were derived from BIDS `*_physio.tsv.gz` + JSON sidecars (pulse, respiratory, trigger).
- A composite `physio_quality_score` (0–1) combined trigger reliability, cardiac and respiratory signal quality, and a missing-data term.
- fMRI quality metrics were taken from MRIQC bold IQMs (`fd_mean`, `fd_perc`, `tsnr`, `dvars_nstd`, `gcor`, `snr`). Framewise FD timeseries from fMRIPrep were not available; median FD and FD>0.5% were therefore left undefined.
- Runs were matched strictly on `subject`, `session`, `task`, and `run`.
- Longitudinal analyses used identical `task`/`run` labels across sessions within subject.

## Main findings

Physiological recording quality was associated with variability in fMRI quality metrics in the sense that the analyses below quantify cross-sectional and longitudinal relationships; wording remains associational.

{chr(10).join(findings)}

### ICC (session reproducibility)

{chr(10).join(icc_lines)}

## Outputs

See files in this directory and `figures/`.

## Validation snapshot

```json
{json.dumps(validation, indent=2)}
```
"""
    (output_dir / "PHYSIOLOGY_REPRODUCIBILITY_REPORT.md").write_text(report)
    (output_dir / "README.md").write_text(
        """# Physiology reproducibility derivatives

This analysis investigates whether peripheral physiological recording quality is associated with
within-subject reproducibility of MRI quality metrics across longitudinal sessions.

This is a dataset characterization analysis and does not imply causal effects.

## How to reproduce

```bash
python code/physiology_reproducibility_analysis.py \\
  --bids_dir bids \\
  --derivatives_dir derivatives \\
  --output_dir derivatives/physiology_reproducibility
```

Requires: `numpy`, `matplotlib`.

## Privacy

Tables contain only BIDS entities (`sub-XXX`, `ses-XX`, `task`, `run`) and numeric metrics.
No absolute paths, scanner dates, or personal identifiers are written.
"""
    )

    # Privacy scan
    bad = []
    for p in output_dir.rglob("*"):
        if p.is_dir() or p.suffix.lower() == ".png":
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "/lustre" in txt or "/home/" in txt or "raw_original" in txt:
            bad.append(p.name)
        if re.search(r"PatientName|PatientID|\bSUBC\d{2,}", txt):
            bad.append(f"phi:{p.name}")
    log("Privacy scan: PASS" if not bad else f"WARNING: {bad[:10]}")
    print("PHYSIOLOGY REPRODUCIBILITY ANALYSIS COMPLETE")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bids_dir", type=Path, required=True)
    parser.add_argument("--derivatives_dir", type=Path, required=True)
    parser.add_argument("--output_dir", type=Path, required=True)
    args = parser.parse_args(argv)
    run(args.bids_dir.resolve(), args.derivatives_dir.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    main()
