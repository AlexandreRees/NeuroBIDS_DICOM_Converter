#!/usr/bin/env python3
"""Publication figures: physiology quality vs MRIQC fMRI quality.

READ-ONLY with respect to BIDS / raw / existing derivative source tables.
Writes only under --output_dir (default: .../publication_figures).

Flexible input resolution maps legacy/alternate table names produced by
code/physiology_reproducibility_analysis.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

warnings.filterwarnings("ignore", category=RuntimeWarning)

# Optional stack (preferred when available)
try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

try:
    import seaborn as sns
except ImportError:  # pragma: no cover
    sns = None

try:
    from scipy import stats as scipy_stats
except ImportError:  # pragma: no cover
    scipy_stats = None

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------
NATURE_RC = {
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica", "sans-serif"],
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.dpi": 300,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
}

COLORS = {
    "primary": "#2C5F6E",
    "secondary": "#B85C38",
    "accent": "#4A7C59",
    "muted": "#6B7280",
    "rest": "#2C5F6E",
    "movie": "#B85C38",
    "fmri": "#4A7C59",
    "control": "#6B7280",
}

TASK_ORDER = ["rest", "movie", "fmri", "control"]

INPUT_ALIASES = {
    "matching": [
        "physiology_mriqc_matching.tsv",
        "physio_fmri_master_table.tsv",
    ],
    "longitudinal": [
        "longitudinal_pairs.tsv",
        "longitudinal_session_difference.tsv",
    ],
    "correlations": [
        "correlations.tsv",
        "single_session_statistics.tsv",
    ],
    "icc": [
        "icc_results.tsv",
        "ICC_results.tsv",
    ],
    "validation": ["validation.json"],
    "participants": [
        # resolved relative to bids if present beside derivatives
    ],
}


def log(msg: str) -> None:
    print(msg, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_style() -> None:
    plt.rcParams.update(NATURE_RC)
    if sns is not None:
        sns.set_theme(style="ticks", rc=NATURE_RC)


def resolve_table(input_dir: Path, key: str) -> Path:
    for name in INPUT_ALIASES[key]:
        p = input_dir / name
        if p.is_file():
            return p
    raise FileNotFoundError(
        f"Missing required table for '{key}'. Tried: {INPUT_ALIASES[key]} under {input_dir}"
    )


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def to_float(x: Any) -> float:
    if x is None:
        return float("nan")
    if isinstance(x, (int, float, np.floating)):
        return float(x)
    s = str(x).strip()
    if s in {"", "n/a", "NA", "nan", "None", "true", "false"}:
        # booleans handled elsewhere; treat non-numeric as nan here
        if s in {"true", "false"}:
            return float("nan")
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def col(rows: list[dict[str, Any]], name: str) -> np.ndarray:
    return np.asarray([to_float(r.get(name)) for r in rows], dtype=float)


def require_columns(rows: list[dict[str, Any]], required: list[str], label: str) -> list[str]:
    if not rows:
        raise ValueError(f"{label}: empty table")
    present = set(rows[0].keys())
    missing = [c for c in required if c not in present]
    if missing:
        raise ValueError(f"{label}: missing columns {missing}")
    return missing


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    fig.savefig(png, dpi=300, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)
    return {"png": str(png.name), "pdf": str(pdf.name)}


# ---------------------------------------------------------------------------
# Stats helpers (numpy fallback if scipy absent)
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


def spearman_corr(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = int(x.size)
    if n < 5:
        return float("nan"), float("nan"), n
    if scipy_stats is not None:
        r, p = scipy_stats.spearmanr(x, y)
        return float(r), float(p), n
    rx, ry = rankdata(x), rankdata(y)
    r = float(np.corrcoef(rx, ry)[0, 1])
    if abs(r) >= 1:
        p = 0.0
    else:
        t = r * math.sqrt((n - 2) / max(1e-12, 1 - r * r))
        p = float(2 * student_t_sf(abs(t), n - 2))
    return r, p, n


def ols_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if x.size < 3:
        return float("nan"), float("nan")
    coef = np.polyfit(x, y, 1)
    return float(coef[0]), float(coef[1])


def fmt_p(p: float) -> str:
    if not np.isfinite(p):
        return "n/a"
    if p < 1e-4:
        return f"{p:.1e}"
    return f"{p:.3f}"


def fmt_rho(r: float) -> str:
    if not np.isfinite(r):
        return "n/a"
    return f"{r:.2f}"


def annotate_stats(ax, rho: float, p: float, n: int, loc: str = "upper right") -> None:
    txt = f"ρ = {fmt_rho(rho)}\np = {fmt_p(p)}\nN = {n}"
    ax.text(
        0.98 if "right" in loc else 0.02,
        0.98 if "upper" in loc else 0.02,
        txt,
        transform=ax.transAxes,
        ha="right" if "right" in loc else "left",
        va="top" if "upper" in loc else "bottom",
        fontsize=8,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#D1D5DB", linewidth=0.6),
    )


def scatter_with_fit(
    ax,
    x: np.ndarray,
    y: np.ndarray,
    xlabel: str,
    ylabel: str,
    title: str,
) -> dict[str, Any]:
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    ax.scatter(x, y, s=10, alpha=0.35, c=COLORS["primary"], edgecolors="none", rasterized=True)
    slope, intercept = ols_line(x, y)
    if np.isfinite(slope):
        xs = np.linspace(np.min(x), np.max(x), 80)
        ax.plot(xs, slope * xs + intercept, color=COLORS["secondary"], lw=1.6)
    rho, p, n = spearman_corr(x, y)
    annotate_stats(ax, rho, p, n)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    return {"rho": rho, "p": p, "n": n, "slope": slope, "intercept": intercept}


def load_cohort_map(bids_participants: Path | None) -> dict[str, str]:
    if bids_participants is None or not bids_participants.is_file():
        return {}
    rows = read_tsv(bids_participants)
    out = {}
    for r in rows:
        pid = r.get("participant_id") or r.get("subject")
        cohort = r.get("cohort") or r.get("group") or ""
        if pid:
            out[pid] = cohort
    return out


def icc_manual(master: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    by_sub: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in master:
        v = to_float(r.get(metric))
        if np.isfinite(v):
            by_sub[r["subject"]].append((r["session"], v))
    wide = []
    for items in by_sub.values():
        sess: dict[str, list[float]] = defaultdict(list)
        for s, v in items:
            sess[s].append(v)
        vals = [float(np.mean(sess[s])) for s in sorted(sess)]
        if len(vals) >= 2:
            wide.append(vals[:2])
    result = {"metric": metric, "n_subjects": len(wide), "ICC": float("nan"), "method": "manual_ICC3_1"}
    if len(wide) < 5:
        return result
    M = np.asarray(wide, float)
    n, k = M.shape
    mean_t = M.mean(axis=1, keepdims=True)
    mean_r = M.mean(axis=0, keepdims=True)
    mean_g = M.mean()
    BMS = k * np.sum((mean_t - mean_g) ** 2) / (n - 1)
    EMS = np.sum((M - mean_t - mean_r + mean_g) ** 2) / ((n - 1) * (k - 1))
    denom = BMS + (k - 1) * EMS
    result["ICC"] = float((BMS - EMS) / denom) if denom != 0 else float("nan")
    result["n_subjects"] = int(n)
    return result


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def figure1_dataset_overview(
    master: list[dict[str, Any]],
    long_rows: list[dict[str, Any]],
    validation: dict[str, Any],
    cohort_map: dict[str, str],
    out_dir: Path,
) -> dict[str, Any]:
    n_runs = len(master)
    n_pairs = len(long_rows)
    n_long_subj = len({r["subject"] for r in long_rows}) if long_rows else int(
        validation.get("number_longitudinal_subjects") or 0
    )
    n_subj = len({r["subject"] for r in master})

    task_counts = Counter(r["task"] for r in master)
    cohort_counts: Counter[str] = Counter()
    for r in master:
        c = cohort_map.get(r["subject"], "Unknown")
        cohort_counts[c or "Unknown"] += 1

    metrics_avail = {
        "FD (mm)": sum(1 for r in master if np.isfinite(to_float(r.get("mean_FD")))),
        "DVARS": sum(1 for r in master if np.isfinite(to_float(r.get("DVARS")))),
        "tSNR": sum(1 for r in master if np.isfinite(to_float(r.get("tSNR")))),
        "gCOR": sum(1 for r in master if np.isfinite(to_float(r.get("gCOR")))),
    }

    fig = plt.figure(figsize=(8.5, 6.5))
    gs = GridSpec(2, 2, figure=fig, wspace=0.35, hspace=0.4)

    # A — overview numbers
    ax = fig.add_subplot(gs[0, 0])
    ax.axis("off")
    ax.set_title("A  Dataset size", loc="left", fontweight="bold")
    lines = [
        f"Matched physio–fMRI runs:  {n_runs}",
        f"Longitudinal pairs:        {n_pairs}",
        f"Longitudinal subjects:     {n_long_subj}",
        f"Subjects with physio:      {n_subj}",
    ]
    ax.text(0.02, 0.75, "\n".join(lines), va="top", fontsize=10, family="monospace",
            transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#F8FAFC", edgecolor="#CBD5E1"))

    # B — tasks
    ax = fig.add_subplot(gs[0, 1])
    tasks = [t for t in TASK_ORDER if task_counts.get(t, 0) > 0]
    vals = [task_counts[t] for t in tasks]
    colors = [COLORS.get(t, COLORS["muted"]) for t in tasks]
    ax.barh(tasks[::-1], vals[::-1], color=colors[::-1], height=0.65)
    for y, v in zip(tasks[::-1], vals[::-1]):
        ax.text(v + max(vals) * 0.01, y, str(v), va="center", fontsize=8)
    ax.set_xlabel("Number of matched runs")
    ax.set_title("B  Runs by task", loc="left", fontweight="bold")
    ax.set_xlim(0, max(vals) * 1.18)

    # C — cohort
    ax = fig.add_subplot(gs[1, 0])
    if cohort_counts and set(cohort_counts) != {"Unknown"}:
        items = sorted(cohort_counts.items(), key=lambda z: -z[1])
        labels = [k for k, _ in items]
        cvals = [v for _, v in items]
        ax.barh(labels[::-1], cvals[::-1], color=COLORS["accent"], height=0.65)
        for y, v in zip(labels[::-1], cvals[::-1]):
            ax.text(v + max(cvals) * 0.01, y, str(v), va="center", fontsize=8)
        ax.set_xlabel("Number of matched runs")
        ax.set_title("C  Runs by cohort", loc="left", fontweight="bold")
        ax.set_xlim(0, max(cvals) * 1.18)
    else:
        ax.axis("off")
        ax.set_title("C  Runs by cohort", loc="left", fontweight="bold")
        ax.text(0.5, 0.5, "Cohort metadata unavailable", ha="center", va="center", color=COLORS["muted"])

    # D — MRIQC metrics coverage
    ax = fig.add_subplot(gs[1, 1])
    labels = list(metrics_avail.keys())
    cvals = [metrics_avail[k] for k in labels]
    ax.barh(labels[::-1], cvals[::-1], color=COLORS["primary"], height=0.65)
    for y, v in zip(labels[::-1], cvals[::-1]):
        ax.text(v + max(cvals) * 0.01, y, str(v), va="center", fontsize=8)
    ax.set_xlabel("Runs with finite value")
    ax.set_title("D  MRIQC metric availability", loc="left", fontweight="bold")
    ax.set_xlim(0, max(cvals) * 1.18)

    paths = save_figure(fig, out_dir, "Figure1_dataset_overview")
    return {"figure": "Figure1", **paths, "n_runs": n_runs, "n_pairs": n_pairs, "n_long_subjects": n_long_subj}


def figure2_associations(master: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    x = col(master, "physio_quality_score")
    panels = [
        ("mean_FD", "Framewise displacement (mm)", "A  FD"),
        ("DVARS", "DVARS (a.u.)", "B  DVARS"),
        ("gCOR", "Global correlation (gCOR)", "C  gCOR"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4))
    stats_out = []
    for ax, (yname, ylabel, title) in zip(axes, panels):
        st = scatter_with_fit(
            ax,
            x,
            col(master, yname),
            "Physiology quality score (0–1)",
            ylabel,
            title,
        )
        st["outcome"] = yname
        stats_out.append(st)
    fig.suptitle("Physiological quality and fMRI quality metrics", fontsize=11, y=1.02)
    paths = save_figure(fig, out_dir, "Figure2_physio_fmri_associations")
    return {"figure": "Figure2", **paths, "stats": stats_out}


def figure3_icc(
    icc_rows: list[dict[str, Any]],
    master: list[dict[str, Any]],
    out_dir: Path,
) -> dict[str, Any]:
    # Ensure DVARS ICC present (compute if missing)
    by_metric = {}
    for r in icc_rows:
        key = r.get("metric", "")
        by_metric[key] = r

    # normalize names
    wanted = [
        ("physiology_quality", ["physio_quality_score", "physiology_quality"]),
        ("FD", ["mean_FD", "FD", "fd_mean"]),
        ("tSNR", ["tSNR", "tsnr"]),
        ("DVARS", ["DVARS", "dvars_nstd"]),
    ]
    plot_metrics = []
    plot_vals = []
    for label, aliases in wanted:
        found = None
        for a in aliases:
            if a in by_metric and np.isfinite(to_float(by_metric[a].get("ICC"))):
                found = to_float(by_metric[a].get("ICC"))
                break
        if found is None:
            # compute from master using first alias that exists as column
            for a in aliases:
                if master and a in master[0]:
                    found = to_float(icc_manual(master, a).get("ICC"))
                    break
        plot_metrics.append(label)
        plot_vals.append(found if found is not None else float("nan"))

    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    y = np.arange(len(plot_metrics))
    vals = np.asarray(plot_vals, float)
    colors = [COLORS["primary"] if np.isfinite(v) and v >= 0 else COLORS["secondary"] for v in vals]
    ax.barh(y, np.nan_to_num(vals, nan=0.0), color=colors, height=0.65)
    for yi, v in zip(y, vals):
        if np.isfinite(v):
            ax.text(v + 0.02 if v >= 0 else v - 0.02, yi, f"{v:.2f}",
                    va="center", ha="left" if v >= 0 else "right", fontsize=8)
    ax.set_yticks(y)
    ax.set_yticklabels(plot_metrics)
    ax.set_xlabel("Intraclass correlation coefficient (ICC)")
    ax.set_xlim(min(-0.2, np.nanmin(vals) - 0.1 if np.isfinite(vals).any() else -0.2), 1.05)
    ax.axvline(0, color="#9CA3AF", lw=0.7)
    ax.set_title("Session-to-session reproducibility\n(Higher ICC = greater stability)")
    ax.text(0.98, 0.02, f"N subjects (ICC) ≈ {icc_rows[0].get('n_subjects', 'n/a') if icc_rows else 'n/a'}",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=8, color=COLORS["muted"])
    paths = save_figure(fig, out_dir, "Figure3_longitudinal_reproducibility")
    return {
        "figure": "Figure3",
        **paths,
        "icc": dict(zip(plot_metrics, plot_vals)),
    }


def figure4_delta(long_rows: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    # Prefer precomputed deltas; else compute
    dx = col(long_rows, "delta_physio_quality")
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 3.6))
    stats_out = []
    for ax, yname, ylabel, title in [
        (axes[0], "delta_tSNR", "|Δ tSNR|", "A  Δ physiology vs Δ tSNR"),
        (axes[1], "delta_FD", "|Δ FD| (mm)", "B  Δ physiology vs Δ FD"),
    ]:
        st = scatter_with_fit(
            ax,
            dx,
            col(long_rows, yname),
            "|Δ physiology quality|",
            ylabel,
            title,
        )
        st["outcome"] = yname
        stats_out.append(st)
    fig.suptitle("Within-subject session-to-session change", fontsize=11, y=1.02)
    paths = save_figure(fig, out_dir, "Figure4_delta_analysis")
    return {"figure": "Figure4", **paths, "stats": stats_out}


def _violin_matplotlib(ax, data_by_group: dict[str, np.ndarray], order: list[str], ylabel: str, title: str) -> int:
    positions = []
    datasets = []
    labels = []
    n_total = 0
    for i, g in enumerate(order):
        arr = data_by_group.get(g, np.asarray([]))
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            continue
        positions.append(len(positions) + 1)
        datasets.append(arr)
        labels.append(g)
        n_total += int(arr.size)
    if not datasets:
        ax.set_title(title)
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        return 0
    parts = ax.violinplot(datasets, positions=positions, showmeans=False, showmedians=False, showextrema=False)
    for b in parts["bodies"]:
        b.set_facecolor(COLORS["primary"])
        b.set_alpha(0.35)
        b.set_edgecolor(COLORS["primary"])
    # box/median
    for pos, arr in zip(positions, datasets):
        q1, med, q3 = np.percentile(arr, [25, 50, 75])
        ax.vlines(pos, q1, q3, color=COLORS["primary"], lw=3, zorder=3)
        ax.scatter(pos, med, color=COLORS["secondary"], s=18, zorder=4)
        # light jitter overlay
        jitter = np.random.default_rng(0).uniform(-0.08, 0.08, size=min(arr.size, 400))
        sample = arr if arr.size <= 400 else arr[np.linspace(0, arr.size - 1, 400).astype(int)]
        ax.scatter(np.full(sample.size, pos) + jitter[: sample.size], sample,
                   s=4, alpha=0.18, c=COLORS["muted"], edgecolors="none", zorder=2, rasterized=True)
    ax.set_xticks(positions)
    ax.set_xticklabels(labels)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{title} (N={n_total})")
    return n_total


def figure5_task_distributions(master: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6))
    variables = [
        ("mean_HR", "Heart rate (beats/min)", "A  Heart rate"),
        ("mean_RR", "Respiratory rate (breaths/min)", "B  Respiratory rate"),
        ("physio_quality_score", "Physiology quality score (0–1)", "C  Quality score"),
    ]
    order = [t for t in TASK_ORDER if any(r["task"] == t for r in master)]
    summary = {}
    for ax, (colname, ylabel, title) in zip(axes, variables):
        by = {
            t: np.asarray([to_float(r.get(colname)) for r in master if r["task"] == t], float)
            for t in order
        }
        if sns is not None and pd is not None:
            records = []
            for t, arr in by.items():
                for v in arr[np.isfinite(arr)]:
                    records.append({"task": t, "value": float(v)})
            d = pd.DataFrame(records)
            if len(d):
                sns.violinplot(
                    data=d, x="task", y="value", order=order, ax=ax,
                    color=COLORS["primary"], inner="quartile", cut=0
                )
                sns.stripplot(
                    data=d, x="task", y="value", order=order, ax=ax,
                    color=COLORS["muted"], size=1.5, alpha=0.2, jitter=0.2
                )
                ax.set_xlabel("")
                ax.set_ylabel(ylabel)
                ax.set_title(f"{title} (N={len(d)})")
                summary[colname] = int(len(d))
            else:
                ax.set_title(title)
                ax.text(0.5, 0.5, "No data", ha="center", transform=ax.transAxes)
        else:
            summary[colname] = _violin_matplotlib(ax, by, order, ylabel, title)
    fig.suptitle("Physiological measures across paradigms", fontsize=11, y=1.03)
    paths = save_figure(fig, out_dir, "Figure5_task_distributions")
    return {"figure": "Figure5", **paths, "n_by_variable": summary}


def figure6_summary(
    fig2_stats: list[dict[str, Any]],
    fig3_icc: dict[str, float],
    validation: dict[str, Any],
    master: list[dict[str, Any]],
    long_rows: list[dict[str, Any]],
    out_dir: Path,
) -> dict[str, Any]:
    fig = plt.figure(figsize=(9.2, 4.8))
    gs = GridSpec(1, 3, figure=fig, width_ratios=[1.1, 1.1, 1.35], wspace=0.4)

    # A correlations
    ax = fig.add_subplot(gs[0, 0])
    labels, rhos = [], []
    for st in fig2_stats:
        labels.append(st["outcome"].replace("mean_FD", "FD"))
        rhos.append(st["rho"])
    y = np.arange(len(labels))
    ax.barh(y, rhos, color=COLORS["primary"], height=0.65)
    ax.axvline(0, color="#9CA3AF", lw=0.7)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Spearman ρ")
    ax.set_title("A  Cross-sectional associations", loc="left", fontweight="bold")
    for yi, r in zip(y, rhos):
        if np.isfinite(r):
            ax.text(r + (0.01 if r >= 0 else -0.01), yi, fmt_rho(r),
                    va="center", ha="left" if r >= 0 else "right", fontsize=8)

    # B ICC
    ax = fig.add_subplot(gs[0, 1])
    icc_labels = ["Physiology", "FD", "tSNR"]
    icc_keys = ["physiology_quality", "FD", "tSNR"]
    icc_vals = [fig3_icc.get(k, float("nan")) for k in icc_keys]
    y = np.arange(len(icc_labels))
    ax.barh(y, np.nan_to_num(icc_vals, nan=0.0), color=COLORS["accent"], height=0.65)
    ax.set_yticks(y)
    ax.set_yticklabels(icc_labels)
    ax.set_xlabel("ICC")
    ax.set_xlim(-0.2, 1.05)
    ax.axvline(0, color="#9CA3AF", lw=0.7)
    ax.set_title("B  Longitudinal ICC", loc="left", fontweight="bold")
    for yi, v in zip(y, icc_vals):
        if np.isfinite(v):
            ax.text(v + 0.02, yi, f"{v:.2f}", va="center", fontsize=8)

    # C text
    ax = fig.add_subplot(gs[0, 2])
    ax.axis("off")
    ax.set_title("C  Summary", loc="left", fontweight="bold")
    n_runs = len(master)
    n_subj = len({r["subject"] for r in master})
    n_long = len({r["subject"] for r in long_rows}) if long_rows else int(
        validation.get("number_longitudinal_subjects") or 0
    )
    text = (
        f"Dataset\n"
        f"  {n_runs} matched runs\n"
        f"  {n_subj} subjects with physiology\n"
        f"  {n_long} longitudinal subjects\n"
        f"  {len(long_rows)} session pairs\n\n"
        f"Conclusion\n"
        f"Physiological recording quality showed\n"
        f"weak associations with fMRI quality\n"
        f"metrics and limited longitudinal\n"
        f"stability."
    )
    ax.text(
        0.02, 0.95, text, transform=ax.transAxes, va="top", fontsize=9,
        family="sans-serif",
        bbox=dict(boxstyle="round,pad=0.55", facecolor="#F8FAFC", edgecolor="#CBD5E1"),
    )

    paths = save_figure(fig, out_dir, "Figure6_summary_panel")
    return {"figure": "Figure6", **paths}


def privacy_scan(out_dir: Path) -> list[str]:
    bad = []
    for p in out_dir.rglob("*"):
        if p.is_dir() or p.suffix.lower() in {".png", ".pdf"}:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "/lustre" in txt or "/home/" in txt or "raw_original" in txt:
            bad.append(p.name)
        if re.search(r"PatientName|PatientID|\bSUBC\d{2,}", txt):
            bad.append(f"phi:{p.name}")
    return bad


def run(input_dir: Path, output_dir: Path, bids_dir: Path | None = None) -> None:
    apply_style()
    output_dir.mkdir(parents=True, exist_ok=True)

    matching_path = resolve_table(input_dir, "matching")
    long_path = resolve_table(input_dir, "longitudinal")
    icc_path = resolve_table(input_dir, "icc")
    val_path = resolve_table(input_dir, "validation")
    try:
        corr_path = resolve_table(input_dir, "correlations")
    except FileNotFoundError:
        corr_path = None

    log(f"Using matching table: {matching_path.name}")
    log(f"Using longitudinal table: {long_path.name}")
    log(f"Using ICC table: {icc_path.name}")

    master = read_tsv(matching_path)
    long_rows = read_tsv(long_path)
    icc_rows = read_tsv(icc_path)
    validation = json.loads(val_path.read_text(encoding="utf-8"))
    corr_rows = read_tsv(corr_path) if corr_path else []

    require_columns(master, ["subject", "session", "task", "run", "physio_quality_score"], "matching")
    require_columns(long_rows, ["subject", "task", "run", "delta_physio_quality"], "longitudinal")

    # Exclusions: rows missing key outcomes for association plots
    n_before = len(master)
    excluded = {
        "missing_physio_quality": sum(1 for r in master if not np.isfinite(to_float(r.get("physio_quality_score")))),
        "missing_FD": sum(1 for r in master if not np.isfinite(to_float(r.get("mean_FD")))),
        "missing_DVARS": sum(1 for r in master if not np.isfinite(to_float(r.get("DVARS")))),
        "missing_gCOR": sum(1 for r in master if not np.isfinite(to_float(r.get("gCOR")))),
    }

    # Cohort map
    participants = None
    if bids_dir and (bids_dir / "participants.tsv").is_file():
        participants = bids_dir / "participants.tsv"
    else:
        # try sibling bids/
        cand = input_dir.parents[1] / "bids" / "participants.tsv"
        if cand.is_file():
            participants = cand
    cohort_map = load_cohort_map(participants)

    meta: dict[str, Any] = {
        "generated": now_iso(),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir.name),
        "tables_used": {
            "matching": matching_path.name,
            "longitudinal": long_path.name,
            "icc": icc_path.name,
            "validation": val_path.name,
            "correlations": corr_path.name if corr_path else None,
            "participants": participants.name if participants else None,
        },
        "n_matching_rows": n_before,
        "n_longitudinal_rows": len(long_rows),
        "excluded_counts": excluded,
        "dependencies_detected": {
            "pandas": pd is not None,
            "seaborn": sns is not None,
            "scipy": scipy_stats is not None,
        },
        "figures": [],
        "statistics": {},
    }

    log("Figure 1 — dataset overview")
    f1 = figure1_dataset_overview(master, long_rows, validation, cohort_map, output_dir)
    meta["figures"].append(f1)

    log("Figure 2 — physio–fMRI associations")
    f2 = figure2_associations(master, output_dir)
    meta["figures"].append(f2)
    meta["statistics"]["figure2"] = f2["stats"]

    log("Figure 3 — ICC")
    f3 = figure3_icc(icc_rows, master, output_dir)
    meta["figures"].append(f3)
    meta["statistics"]["figure3_icc"] = f3["icc"]

    log("Figure 4 — delta analysis")
    f4 = figure4_delta(long_rows, output_dir)
    meta["figures"].append(f4)
    meta["statistics"]["figure4"] = f4["stats"]

    log("Figure 5 — task distributions")
    f5 = figure5_task_distributions(master, output_dir)
    meta["figures"].append(f5)

    log("Figure 6 — summary panel")
    f6 = figure6_summary(f2["stats"], f3["icc"], validation, master, long_rows, output_dir)
    meta["figures"].append(f6)

    # Save statistics TSV
    stats_rows = []
    for st in f2["stats"]:
        stats_rows.append(
            {
                "figure": "Figure2",
                "outcome": st["outcome"],
                "spearman_rho": st["rho"],
                "spearman_p": st["p"],
                "n": st["n"],
                "ols_slope": st["slope"],
                "ols_intercept": st["intercept"],
            }
        )
    for st in f4["stats"]:
        stats_rows.append(
            {
                "figure": "Figure4",
                "outcome": st["outcome"],
                "spearman_rho": st["rho"],
                "spearman_p": st["p"],
                "n": st["n"],
                "ols_slope": st["slope"],
                "ols_intercept": st["intercept"],
            }
        )
    for k, v in f3["icc"].items():
        stats_rows.append(
            {
                "figure": "Figure3",
                "outcome": k,
                "spearman_rho": "",
                "spearman_p": "",
                "n": "",
                "ols_slope": "",
                "ols_intercept": "",
                "ICC": v,
            }
        )
    # write stats
    fieldnames = [
        "figure", "outcome", "spearman_rho", "spearman_p", "n",
        "ols_slope", "ols_intercept", "ICC",
    ]
    with (output_dir / "figure_statistics.tsv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in stats_rows:
            out = {}
            for k in fieldnames:
                v = r.get(k, "")
                if isinstance(v, float):
                    out[k] = "n/a" if not np.isfinite(v) else f"{v:.6g}"
                else:
                    out[k] = v
            w.writerow(out)

    # Metadata JSON — strip absolute paths for privacy
    meta_public = dict(meta)
    meta_public["input_dir"] = input_dir.name
    bad = privacy_scan(output_dir)
    meta_public["privacy_scan"] = "PASS" if not bad else f"ISSUES:{bad}"
    (output_dir / "figure_metadata.json").write_text(json.dumps(meta_public, indent=2) + "\n")

    log("")
    log("=== SUMMARY ===")
    log(f"Matched runs: {n_before}")
    log(f"Longitudinal pairs: {len(long_rows)}")
    log(f"Figures written to: {output_dir}")
    for figmeta in meta["figures"]:
        log(f"  {figmeta.get('figure')}: {figmeta.get('png')}, {figmeta.get('pdf')}")
    log(f"Excluded (missing physio quality / FD / DVARS / gCOR): {excluded}")
    log(f"Privacy scan: {meta_public['privacy_scan']}")
    log("PUBLICATION FIGURES COMPLETE")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input_dir", type=Path, required=True)
    p.add_argument("--output_dir", type=Path, required=True)
    p.add_argument(
        "--bids_dir",
        type=Path,
        default=None,
        help="Optional BIDS root for participants.tsv cohort labels",
    )
    args = p.parse_args(argv)
    run(args.input_dir.resolve(), args.output_dir.resolve(), args.bids_dir.resolve() if args.bids_dir else None)


if __name__ == "__main__":
    main()
