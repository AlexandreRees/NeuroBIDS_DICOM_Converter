#!/usr/bin/env python3
"""Publication figures: physiological recording quality vs fMRI quality / reproducibility.

READ-ONLY with respect to bids/, raw_original/, and MRIQC derivatives.
Writes only under --output_dir.

Scientific question:
  Does physiological recording quality influence fMRI data quality and
  longitudinal reproducibility?

Default inputs:  derivatives/physiology_characterization/
Default output:  .../figures_publication/physiology_reproducibility/
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------
RC = {
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

C = {
    "ink": "#1F2937",
    "pri": "#2C5F6E",
    "mri": "#4A7C59",
    "accent": "#B85C38",
    "muted": "#9CA3AF",
    "between": "#2C5F6E",
    "within": "#B85C38",
    "line": "#1F2937",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_style() -> None:
    plt.rcParams.update(RC)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def to_float(x: Any) -> float:
    if x is None:
        return float("nan")
    if isinstance(x, (int, float, np.floating, np.integer)):
        return float(x)
    s = str(x).strip()
    if s in {"", "n/a", "NA", "nan", "None", "NaN"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def to_bool(x: Any) -> bool:
    return str(x).strip().lower() in {"true", "1", "yes", "t"}


def first_key(row: dict[str, Any], candidates: list[str], default: Any = None) -> Any:
    for k in candidates:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


def normalize_master_row(r: dict[str, str]) -> dict[str, Any]:
    """Map flexible column aliases to a canonical schema."""
    out: dict[str, Any] = {
        "subject": first_key(r, ["subject", "subject_id", "participant_id", "participant"]),
        "session": first_key(r, ["session", "session_id", "ses"]),
        "task": first_key(r, ["task", "task_id"]),
        "run": first_key(r, ["run", "run_id"]),
        "PRI": to_float(first_key(r, ["PRI_total", "PRI_score", "physio_reliability_index", "PRI"])),
        "FD": to_float(first_key(r, ["mean_FD", "FD", "fd_mean", "fd"])),
        "DVARS": to_float(first_key(r, ["DVARS", "dvars"])),
        "tSNR": to_float(first_key(r, ["tSNR", "tsnr", "tsnr_bold"])),
        "gCOR": to_float(first_key(r, ["gCOR", "gcor"])),
        "cardiac_available": to_bool(r.get("cardiac_available", False)),
        "resp_available": to_bool(r.get("resp_available", False)),
        "trigger_available": to_bool(r.get("trigger_available", False)),
        "ecg_available": to_bool(r.get("ecg_available", False)),
    }
    return out


def normalize_pair_row(r: dict[str, str]) -> dict[str, Any]:
    return {
        "subject": first_key(r, ["subject", "subject_id", "participant_id"]),
        "task": first_key(r, ["task", "task_id"]),
        "run": first_key(r, ["run", "run_id"]),
        "session_a": first_key(r, ["session_a", "session1"]),
        "session_b": first_key(r, ["session_b", "session2"]),
        "delta_PRI": to_float(first_key(r, ["delta_PRI", "abs_delta_PRI"])),
        "delta_FD": to_float(first_key(r, ["delta_FD", "abs_delta_FD"])),
        "delta_DVARS": to_float(first_key(r, ["delta_DVARS", "abs_delta_DVARS"])),
        "delta_tSNR": to_float(first_key(r, ["delta_tSNR", "abs_delta_tSNR"])),
    }


def normalize_icc_row(r: dict[str, str]) -> dict[str, Any]:
    return {
        "metric": str(first_key(r, ["metric", "Metric"], "")),
        "ICC": to_float(first_key(r, ["ICC", "icc", "ICC31"])),
        "CI_low": to_float(first_key(r, ["CI95_low", "lower_CI", "ci_low", "CI_low"])),
        "CI_high": to_float(first_key(r, ["CI95_high", "upper_CI", "ci_high", "CI_high"])),
        "n_subjects": to_float(first_key(r, ["n_subjects", "n", "N"])),
        "interpretation": first_key(r, ["interpretation"], ""),
    }


def normalize_var_row(r: dict[str, str]) -> dict[str, Any]:
    return {
        "metric": str(first_key(r, ["metric"], "")),
        "between_fraction": to_float(
            first_key(r, ["between_subject_fraction", "between_fraction", "between"])
        ),
        "within_fraction": to_float(
            first_key(r, ["within_subject_fraction", "within_fraction", "within"])
        ),
        "interpretation": first_key(r, ["interpretation"], ""),
    }


def resolve_input(input_dir: Path, names: list[str]) -> Path:
    for n in names:
        p = input_dir / n
        if p.is_file():
            return p
    raise FileNotFoundError(f"None of {names} found under {input_dir}")


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    fig.savefig(png, dpi=300, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)
    return {"png": png.name, "pdf": pdf.name}


# ---------------------------------------------------------------------------
# Statistics
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
    rx, ry = rankdata(x), rankdata(y)
    r = float(np.corrcoef(rx, ry)[0, 1])
    if abs(r) >= 1:
        p = 0.0
    else:
        t = r * math.sqrt((n - 2) / max(1e-12, 1 - r * r))
        p = float(2 * student_t_sf(abs(t), n - 2))
    return r, p, n


def theil_sen(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Robust Theil–Sen slope and intercept (median pairwise slopes)."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = int(x.size)
    if n < 3:
        return float("nan"), float("nan")
    # Cap pairwise count for large n (subsample for speed while remaining robust)
    if n > 800:
        rng = np.random.default_rng(42)
        idx = rng.choice(n, size=800, replace=False)
        x, y = x[idx], y[idx]
        n = int(x.size)
    slopes: list[float] = []
    for i in range(n - 1):
        dx = x[i + 1 :] - x[i]
        dy = y[i + 1 :] - y[i]
        ok = np.abs(dx) > 1e-12
        if np.any(ok):
            slopes.extend((dy[ok] / dx[ok]).tolist())
    if not slopes:
        return float("nan"), float("nan")
    slope = float(np.median(slopes))
    intercept = float(np.median(y - slope * x))
    return slope, intercept


def variance_partition_metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    by_sub: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = to_float(r.get(key))
        if np.isfinite(v) and r.get("subject"):
            by_sub[str(r["subject"])].append(v)
    means = np.array([float(np.mean(v)) for v in by_sub.values()]) if by_sub else np.array([])
    between = float(np.var(means, ddof=1)) if means.size > 1 else float("nan")
    within_vals = [float(np.var(v, ddof=1)) for v in by_sub.values() if len(v) >= 2]
    within = float(np.mean(within_vals)) if within_vals else float("nan")
    total = between + within if np.isfinite(between) and np.isfinite(within) else float("nan")
    if not np.isfinite(total) or total <= 0:
        bf = wf = float("nan")
        interp = "undefined"
    else:
        bf = between / total
        wf = within / total
        interp = "acquisition-dependent" if wf >= bf else "subject-dependent"
    return {
        "metric": key,
        "between_fraction": bf,
        "within_fraction": wf,
        "interpretation": interp,
        "n_subjects": len(by_sub),
    }


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
    txt = f"ρ = {fmt_rho(rho)}\np = {fmt_p(p)}\nn = {n}"
    ax.text(
        0.98 if "right" in loc else 0.02,
        0.98 if "upper" in loc else 0.02,
        txt,
        transform=ax.transAxes,
        ha="right" if "right" in loc else "left",
        va="top" if "upper" in loc else "bottom",
        fontsize=8,
        color=C["ink"],
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#D1D5DB", linewidth=0.6),
    )


# ---------------------------------------------------------------------------
# Inclusion / exclusion
# ---------------------------------------------------------------------------
def classify_recording(r: dict[str, Any]) -> str:
    card = bool(r.get("cardiac_available"))
    resp = bool(r.get("resp_available"))
    ecg = bool(r.get("ecg_available"))
    trig = bool(r.get("trigger_available"))
    if not card and not resp and not ecg:
        return "trigger_only" if trig else "no_physiology"
    if ecg and not card and not resp:
        return "ecg_only"
    if card or resp:
        return "biosignal"
    return "other"


def filter_runs(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply manuscript inclusion rules; return kept rows + exclusion log."""
    n_ecg_only = sum(1 for r in rows if classify_recording(r) == "ecg_only")
    exclude_ecg_only = n_ecg_only < 20

    kept: list[dict[str, Any]] = []
    exclusions: dict[str, int] = defaultdict(int)
    exclusion_detail: list[dict[str, str]] = []

    for r in rows:
        cls = classify_recording(r)
        reason = None
        if cls in {"trigger_only", "no_physiology"}:
            reason = "trigger_only_or_no_biosignal"
        elif cls == "ecg_only" and exclude_ecg_only:
            reason = f"ecg_only_n_lt_20 (n_ecg_only={n_ecg_only})"
        elif not all(np.isfinite(r[k]) for k in ("PRI", "FD", "DVARS", "tSNR")):
            reason = "missing_MRIQC_or_PRI"
        if reason:
            exclusions[reason] += 1
            exclusion_detail.append(
                {
                    "subject": str(r.get("subject", "")),
                    "session": str(r.get("session", "")),
                    "task": str(r.get("task", "")),
                    "run": str(r.get("run", "")),
                    "reason": reason,
                }
            )
            continue
        kept.append(r)

    log_info = {
        "n_input": len(rows),
        "n_included": len(kept),
        "n_excluded": len(rows) - len(kept),
        "n_ecg_only_total": n_ecg_only,
        "exclude_ecg_only": exclude_ecg_only,
        "exclusions_by_reason": dict(exclusions),
        "exclusion_detail": exclusion_detail,
    }
    return kept, log_info


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def figure1_pri_vs_mriqc(
    rows: list[dict[str, Any]], out_dir: Path, stats_out: list[dict[str, Any]]
) -> None:
    """Does better physiological recording quality correspond to better BOLD quality?"""
    panels = [
        ("A", "FD", "Framewise displacement (mm)", "upper right"),
        ("B", "DVARS", "DVARS", "upper right"),
        ("C", "tSNR", "temporal SNR", "upper left"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4))
    for ax, (lab, key, ylabel, loc) in zip(axes, panels):
        x = np.asarray([r["PRI"] for r in rows], float)
        y = np.asarray([r[key] for r in rows], float)
        m = np.isfinite(x) & np.isfinite(y)
        x, y = x[m], y[m]
        ax.scatter(x, y, s=9, alpha=0.28, c=C["pri"], edgecolors="none", rasterized=True)
        slope, intercept = theil_sen(x, y)
        if np.isfinite(slope):
            xs = np.linspace(np.nanmin(x), np.nanmax(x), 100)
            ax.plot(xs, slope * xs + intercept, color=C["accent"], lw=1.8, zorder=3)
        rho, p, n = spearman_corr(x, y)
        annotate_stats(ax, rho, p, n, loc=loc)
        ax.set_xlabel("Physiological Reliability Index (PRI)")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{lab}. PRI vs {key}", loc="left", fontweight="bold")
        stats_out.append(
            {
                "figure": "Figure1",
                "metric": f"PRI_vs_{key}",
                "n": n,
                "rho": rho,
                "p_value": p,
                "ICC": "",
                "CI_low": "",
                "CI_high": "",
                "note": "Spearman; Theil–Sen robust regression line",
            }
        )
    fig.suptitle(
        "Physiological recording quality and within-run fMRI quality",
        fontsize=11,
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    save_figure(fig, out_dir, "Figure1_PRI_vs_MRIQC")


def figure2_icc(
    icc_rows: list[dict[str, Any]], out_dir: Path, stats_out: list[dict[str, Any]]
) -> None:
    """Is physiological recording quality reproducible across sessions?"""
    order = ["FD", "DVARS", "tSNR", "PRI"]
    by = {r["metric"]: r for r in icc_rows}
    # Allow FD alias from mean_FD if needed
    if "FD" not in by and "mean_FD" in by:
        by["FD"] = dict(by["mean_FD"])
        by["FD"]["metric"] = "FD"

    metrics = [m for m in order if m in by]
    if len(metrics) < 2:
        raise RuntimeError(f"Insufficient ICC metrics: found {list(by)}")

    y = np.arange(len(metrics))
    iccs = [by[m]["ICC"] for m in metrics]
    lo = [by[m]["CI_low"] for m in metrics]
    hi = [by[m]["CI_high"] for m in metrics]
    colors = [C["pri"] if m == "PRI" else C["mri"] for m in metrics]

    fig, ax = plt.subplots(figsize=(5.8, 3.6))
    for i, m in enumerate(metrics):
        xerr = np.array([[iccs[i] - lo[i]], [hi[i] - iccs[i]]], dtype=float)
        ax.errorbar(
            iccs[i],
            y[i],
            xerr=xerr,
            fmt="o",
            color=colors[i],
            ecolor=colors[i],
            elinewidth=1.6,
            capsize=3.5,
            markersize=7,
            zorder=3,
        )
        stats_out.append(
            {
                "figure": "Figure2",
                "metric": m,
                "n": by[m].get("n_subjects", ""),
                "rho": "",
                "p_value": "",
                "ICC": iccs[i],
                "CI_low": lo[i],
                "CI_high": hi[i],
                "note": by[m].get("interpretation", "ICC(3,1)"),
            }
        )

    ax.axvline(0.5, color=C["muted"], ls="--", lw=0.9, zorder=1)
    ax.axvline(0.75, color=C["muted"], ls=":", lw=0.9, zorder=1)
    ax.axvline(0.9, color=C["muted"], ls=":", lw=0.9, zorder=1)
    ax.set_yticks(y)
    ax.set_yticklabels(metrics)
    ax.set_xlabel("ICC(3,1)  [95% CI]")
    ax.set_xlim(-0.6, 1.05)
    ax.set_title(
        "Longitudinal reproducibility of physiological vs MRI quality",
        loc="left",
        fontweight="bold",
    )
    # Highlight PRI difference
    if "PRI" in metrics:
        i = metrics.index("PRI")
        ax.annotate(
            "PRI less reproducible\nthan MRIQC metrics",
            xy=(iccs[i], y[i]),
            xytext=(0.35, y[i] + 0.85),
            fontsize=7.5,
            color=C["pri"],
            arrowprops=dict(arrowstyle="->", color=C["pri"], lw=0.9),
            ha="left",
        )
    ax.text(
        0.02,
        0.02,
        "Dashed: 0.50 (moderate) · 0.75 (good) · 0.90 (excellent)",
        transform=ax.transAxes,
        fontsize=7,
        color=C["muted"],
        va="bottom",
    )
    fig.tight_layout()
    save_figure(fig, out_dir, "Figure2_longitudinal_ICC")


def figure3_delta(
    pairs: list[dict[str, Any]], out_dir: Path, stats_out: list[dict[str, Any]]
) -> None:
    """When physiological quality changes, does fMRI quality change accordingly?"""
    dpri = np.abs(np.asarray([p["delta_PRI"] for p in pairs], float))
    dtsnr = np.abs(np.asarray([p["delta_tSNR"] for p in pairs], float))
    dfd = np.abs(np.asarray([p["delta_FD"] for p in pairs], float))

    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.5))
    specs = [
        (axes[0], "A", dtsnr, "|Δ tSNR|", "upper right", "delta_tSNR"),
        (axes[1], "B", dfd, "|Δ FD| (mm)", "upper right", "delta_FD"),
    ]
    for ax, lab, y, ylabel, loc, tag in specs:
        m = np.isfinite(dpri) & np.isfinite(y)
        x, yy = dpri[m], y[m]
        ax.scatter(x, yy, s=14, alpha=0.4, c=C["pri"], edgecolors="none", rasterized=True)
        slope, intercept = theil_sen(x, yy)
        if np.isfinite(slope):
            xs = np.linspace(np.nanmin(x), np.nanmax(x), 80)
            ax.plot(xs, slope * xs + intercept, color=C["accent"], lw=1.8)
        rho, p, n = spearman_corr(x, yy)
        annotate_stats(ax, rho, p, n, loc=loc)
        ax.set_xlabel("|Δ PRI|")
        ax.set_ylabel(ylabel)
        ax.set_title(f"{lab}. |Δ PRI| vs {ylabel}", loc="left", fontweight="bold")
        stats_out.append(
            {
                "figure": "Figure3",
                "metric": f"abs_delta_PRI_vs_{tag}",
                "n": n,
                "rho": rho,
                "p_value": p,
                "ICC": "",
                "CI_low": "",
                "CI_high": "",
                "note": "absolute session-to-session change; Spearman",
            }
        )
    fig.suptitle(
        "Longitudinal change coupling: physiological vs fMRI quality",
        fontsize=11,
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    save_figure(fig, out_dir, "Figure3_longitudinal_delta_analysis")


def figure4_variance(
    var_rows: list[dict[str, Any]], out_dir: Path, stats_out: list[dict[str, Any]]
) -> None:
    """Is variability driven mainly by subjects or acquisition?"""
    order = ["PRI", "FD", "DVARS", "tSNR"]
    by = {r["metric"]: r for r in var_rows}
    metrics = [m for m in order if m in by and np.isfinite(by[m]["between_fraction"])]
    if not metrics:
        raise RuntimeError("No variance partition rows available")

    between = [by[m]["between_fraction"] for m in metrics]
    within = [by[m]["within_fraction"] for m in metrics]
    x = np.arange(len(metrics))

    fig, ax = plt.subplots(figsize=(6.2, 3.8))
    ax.bar(x, between, width=0.62, color=C["between"], label="Between-subject")
    ax.bar(x, within, width=0.62, bottom=between, color=C["within"], label="Within-subject")
    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.set_ylabel("Variance fraction")
    ax.set_ylim(0, 1.08)
    ax.set_title(
        "Variance partitioning: subject- vs acquisition-dependent",
        loc="left",
        fontweight="bold",
    )
    ax.legend(frameon=False, loc="upper right")
    # Callouts
    if "FD" in metrics:
        i = metrics.index("FD")
        ax.text(i, 1.02, "subject-\ndependent", ha="center", va="bottom", fontsize=7, color=C["between"])
    if "PRI" in metrics:
        i = metrics.index("PRI")
        ax.text(i, 1.02, "acquisition-\ndependent", ha="center", va="bottom", fontsize=7, color=C["within"])

    for m in metrics:
        stats_out.append(
            {
                "figure": "Figure4",
                "metric": m,
                "n": by[m].get("n_subjects", ""),
                "rho": "",
                "p_value": "",
                "ICC": "",
                "CI_low": by[m]["between_fraction"],
                "CI_high": by[m]["within_fraction"],
                "note": f"CI_low=between_fraction; CI_high=within_fraction; {by[m].get('interpretation','')}",
            }
        )
    fig.tight_layout()
    save_figure(fig, out_dir, "Figure4_variance_partition")


def figure5_summary(
    rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    icc_rows: list[dict[str, Any]],
    assoc_stats: list[dict[str, Any]],
    out_dir: Path,
    stats_out: list[dict[str, Any]],
) -> None:
    """Manuscript summary communicating the full characterization story."""
    fig = plt.figure(figsize=(10.5, 7.2))
    gs = GridSpec(2, 2, figure=fig, hspace=0.38, wspace=0.32)

    # Panel A — PRI distribution (biosignal runs only; trigger-only already excluded)
    ax = fig.add_subplot(gs[0, 0])
    pri = np.asarray([r["PRI"] for r in rows], float)
    pri = pri[np.isfinite(pri)]
    ax.hist(pri, bins=30, density=True, color=C["pri"], alpha=0.55, edgecolor="white", lw=0.4)
    if pri.size > 10:
        # Gaussian KDE via numpy histogram smoothing fallback
        try:
            from numpy import histogram as _h  # noqa: F401

            xs = np.linspace(np.nanmin(pri), np.nanmax(pri), 200)
            # Silverman's rule bandwidth
            s = float(np.std(pri, ddof=1))
            bw = 1.06 * s * (pri.size ** (-0.2)) if s > 0 else 1.0
            dens = np.zeros_like(xs)
            for v in pri:
                dens += np.exp(-0.5 * ((xs - v) / bw) ** 2) / (bw * math.sqrt(2 * math.pi))
            dens /= pri.size
            ax.plot(xs, dens, color=C["accent"], lw=1.8)
        except Exception:
            pass
    ax.set_xlabel("PRI")
    ax.set_ylabel("Density")
    ax.set_title("A. PRI distribution", loc="left", fontweight="bold")
    stats_out.append(
        {
            "figure": "Figure5",
            "metric": "PRI_distribution",
            "n": int(pri.size),
            "rho": "",
            "p_value": "",
            "ICC": float(np.mean(pri)) if pri.size else "",
            "CI_low": float(np.percentile(pri, 2.5)) if pri.size else "",
            "CI_high": float(np.percentile(pri, 97.5)) if pri.size else "",
            "note": "ICC column stores mean PRI; CI stores 2.5–97.5 percentile",
        }
    )

    # Panel B — channel availability (Pulse, Respiratory; ECG only if n>=20). No trigger.
    ax = fig.add_subplot(gs[0, 1])
    n_all = max(len(all_rows), 1)
    n_pulse = sum(1 for r in all_rows if r.get("cardiac_available"))
    n_resp = sum(1 for r in all_rows if r.get("resp_available"))
    n_ecg = sum(1 for r in all_rows if r.get("ecg_available"))
    channels = [("Pulse", n_pulse), ("Respiratory", n_resp)]
    if n_ecg >= 20:
        channels.append(("ECG", n_ecg))
    labels = [c[0] for c in channels]
    pcts = [100.0 * c[1] / n_all for c in channels]
    palette = [C["pri"], C["mri"], C["accent"]][: len(labels)]
    bars = ax.barh(labels[::-1], pcts[::-1], color=palette[::-1])
    ax.set_xlim(0, 105)
    ax.set_xlabel("Availability (% runs)")
    ax.set_title("B. Channel quality (availability)", loc="left", fontweight="bold")
    for b, p in zip(bars, pcts[::-1]):
        ax.text(min(p + 1.5, 102), b.get_y() + b.get_height() / 2, f"{p:.1f}%", va="center", fontsize=8)
    ax.text(
        0.98,
        0.02,
        "Trigger excluded from panel",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=7,
        color=C["muted"],
    )
    for lab, nch, pct in zip(labels, [c[1] for c in channels], pcts):
        stats_out.append(
            {
                "figure": "Figure5",
                "metric": f"channel_{lab.replace(' / ', '_').replace(' ', '_')}",
                "n": nch,
                "rho": pct,
                "p_value": "",
                "ICC": "",
                "CI_low": "",
                "CI_high": "",
                "note": "rho column stores percent availability",
            }
        )

    # Panel C — relationship summary (rho)
    ax = fig.add_subplot(gs[1, 0])
    # Prefer freshly computed Figure1 stats
    rho_map = {}
    for s in assoc_stats:
        if s.get("figure") == "Figure1" and str(s.get("metric", "")).startswith("PRI_vs_"):
            m = str(s["metric"]).replace("PRI_vs_", "")
            rho_map[m] = to_float(s.get("rho"))
    order = ["FD", "DVARS", "tSNR"]
    rhos = [rho_map.get(m, float("nan")) for m in order]
    colors = [C["accent"] if (np.isfinite(r) and r < 0) else C["pri"] for r in rhos]
    y = np.arange(len(order))
    ax.barh(y, rhos, color=colors, height=0.55)
    ax.axvline(0, color=C["ink"], lw=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(order)
    ax.set_xlabel("Spearman ρ (PRI vs metric)")
    ax.set_title("C. Relationship summary", loc="left", fontweight="bold")
    ax.set_xlim(-0.35, 0.35)
    for yi, r in zip(y, rhos):
        if np.isfinite(r):
            ax.text(r + (0.015 if r >= 0 else -0.015), yi, f"{r:.2f}", va="center",
                    ha="left" if r >= 0 else "right", fontsize=8)

    # Panel D — ICC comparison
    ax = fig.add_subplot(gs[1, 1])
    by = {r["metric"]: r for r in icc_rows}
    icc_order = ["FD", "DVARS", "tSNR", "PRI"]
    metrics = [m for m in icc_order if m in by]
    y = np.arange(len(metrics))
    iccs = [by[m]["ICC"] for m in metrics]
    lo = [by[m]["CI_low"] for m in metrics]
    hi = [by[m]["CI_high"] for m in metrics]
    cols = [C["pri"] if m == "PRI" else C["mri"] for m in metrics]
    for i, m in enumerate(metrics):
        xerr = np.array([[iccs[i] - lo[i]], [hi[i] - iccs[i]]], dtype=float)
        ax.errorbar(
            iccs[i],
            y[i],
            xerr=xerr,
            fmt="o",
            color=cols[i],
            ecolor=cols[i],
            elinewidth=1.4,
            capsize=3,
            markersize=6,
        )
    ax.axvline(0.5, color=C["muted"], ls="--", lw=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(metrics)
    ax.set_xlabel("ICC(3,1)")
    ax.set_xlim(-0.6, 1.05)
    ax.set_title("D. ICC: PRI vs MRI metrics", loc="left", fontweight="bold")

    fig.suptitle(
        "Physiological recording quality: acquisition-level characterization",
        fontsize=12,
        fontweight="bold",
        y=0.98,
    )
    save_figure(fig, out_dir, "Figure5_physiology_summary")


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------
def write_readme(
    path: Path,
    inclusion: dict[str, Any],
    n_pairs: int,
    n_long_subj: int,
) -> None:
    excl_reason = inclusion.get("exclusions_by_reason") or {}
    text = f"""# Physiology–fMRI reproducibility publication figures

Generated: `{now_iso()}`

## Scientific question

**Does physiological recording quality influence fMRI data quality and longitudinal reproducibility?**

These figures test relationships between the Physiological Reliability Index (PRI)
and MRIQC-derived fMRI quality metrics. They are **not** simple QC dashboards.

## Inclusion rules

- Matched physiology–MRIQC runs only
- Trigger-only recordings excluded (no cardiac / respiratory / ECG biosignal)
- ECG-only recordings excluded if n < 20
- Runs with missing PRI or MRIQC (FD, DVARS, tSNR) excluded

| Item | N |
| --- | ---: |
| Input matched runs | {inclusion['n_input']} |
| Included in figures | {inclusion['n_included']} |
| Excluded | {inclusion['n_excluded']} |
| Longitudinal pairs (Fig. 3) | {n_pairs} |
| Longitudinal subjects (ICC) | {n_long_subj} |

Exclusions by reason: `{excl_reason}`

## Figures

### Figure 1 — `Figure1_PRI_vs_MRIQC`
**Question:** Does better physiological recording quality correspond to better BOLD quality within the same run?

- Panel A: PRI vs FD
- Panel B: PRI vs DVARS
- Panel C: PRI vs tSNR
- Each point = one fMRI run; Theil–Sen robust regression; Spearman ρ, p, n

### Figure 2 — `Figure2_longitudinal_ICC`
**Question:** Is physiological recording quality reproducible across sessions?

- ICC(3,1) forest plot with 95% CI
- Order: FD, DVARS, tSNR, PRI
- Highlights that PRI reproducibility differs from MRI quality metrics

### Figure 3 — `Figure3_longitudinal_delta_analysis`
**Question:** When physiological quality changes between sessions, does fMRI quality change accordingly?

- Panel A: |Δ PRI| vs |Δ tSNR|
- Panel B: |Δ PRI| vs |Δ FD|
- Each point = one subject–task–run session pair

Interpretation when associations are non-significant:
*Changes in physiological recording quality do not explain longitudinal changes in fMRI quality.*

### Figure 4 — `Figure4_variance_partition`
**Question:** Is variability driven mainly by subjects or acquisition?

- Stacked bars: between-subject vs within-subject variance fractions
- Expected pattern: FD more between-subject; PRI more within-subject (acquisition-dependent)

### Figure 5 — `Figure5_physiology_summary`
Manuscript summary panel:

- A: PRI distribution (biosignal runs; trigger-only excluded)
- B: Channel availability (Pulse/cardiac, Respiratory; ECG only if n≥20; **trigger not shown**)
- C: Compact Spearman ρ summary (PRI vs FD / DVARS / tSNR)
- D: ICC comparison (PRI vs MRI metrics)

## Statistics

All numerical values plotted or annotated are saved in `figure_statistics.csv`.

Columns: `figure`, `metric`, `n`, `rho`, `p_value`, `ICC`, `CI_low`, `CI_high`, `note`

## Privacy

Outputs use only `sub-XXX`, `ses-XX`, `task`, and `run` identifiers.
No participant names, scanner dates, absolute paths, or internal IDs are written.
"""
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input_dir",
        type=Path,
        default=Path("derivatives/physiology_characterization"),
        help="Directory with PRI / master / ICC / longitudinal tables",
    )
    ap.add_argument(
        "--output_dir",
        type=Path,
        default=None,
        help="Output directory (default: <input_dir>/figures_publication/physiology_reproducibility)",
    )
    args = ap.parse_args()
    input_dir = args.input_dir.resolve()
    out_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else (input_dir / "figures_publication" / "physiology_reproducibility")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    apply_style()

    log(f"Input:  {input_dir}")
    log(f"Output: {out_dir}")

    master_path = resolve_input(
        input_dir,
        [
            "physio_mri_quality_master.tsv",
            "physio_fmri_master_table.tsv",
            "physiology_mriqc_matching.tsv",
        ],
    )
    icc_path = resolve_input(
        input_dir,
        ["longitudinal_ICC_results.tsv", "ICC_results.tsv", "icc_results.tsv"],
    )
    pairs_path = resolve_input(
        input_dir,
        [
            "longitudinal_pairs_detail.tsv",
            "longitudinal_change_analysis.tsv",
            "longitudinal_session_difference.tsv",
            "longitudinal_pairs.tsv",
        ],
    )
    # Optional variance table
    var_path = None
    for name in ["variance_partitioning.tsv", "variance_partition.tsv"]:
        if (input_dir / name).is_file():
            var_path = input_dir / name
            break

    log(f"  master: {master_path.name}")
    log(f"  ICC:    {icc_path.name}")
    log(f"  pairs:  {pairs_path.name}")
    log(f"  var:    {var_path.name if var_path else '(computed from master)'}")

    master_raw = [normalize_master_row(r) for r in read_tsv(master_path)]
    included, inclusion = filter_runs(master_raw)
    log(
        f"Inclusion: {inclusion['n_included']}/{inclusion['n_input']} "
        f"(excluded {inclusion['n_excluded']}: {inclusion['exclusions_by_reason']})"
    )

    # Write exclusion log (BIDS entities only)
    excl_rows = inclusion.pop("exclusion_detail")
    write_csv(
        out_dir / "exclusion_log.csv",
        excl_rows,
        ["subject", "session", "task", "run", "reason"],
    )
    with (out_dir / "inclusion_summary.json").open("w", encoding="utf-8") as f:
        json.dump({**inclusion, "generated": now_iso()}, f, indent=2)

    icc_rows = [normalize_icc_row(r) for r in read_tsv(icc_path)]
    # Harmonize metric names
    for r in icc_rows:
        if r["metric"] in {"mean_FD", "fd"}:
            r["metric"] = "FD"

    pairs = [normalize_pair_row(r) for r in read_tsv(pairs_path)]
    # Keep pairs with finite absolute deltas for PRI and at least one MRI metric
    pairs_ok = [
        p
        for p in pairs
        if np.isfinite(p["delta_PRI"])
        and (np.isfinite(p["delta_FD"]) or np.isfinite(p["delta_tSNR"]))
    ]

    # Variance partition: load + ensure DVARS present
    var_rows: list[dict[str, Any]] = []
    if var_path is not None:
        var_rows = [normalize_var_row(r) for r in read_tsv(var_path)]
        for r in var_rows:
            if r["metric"] in {"mean_FD", "fd"}:
                r["metric"] = "FD"
    have = {r["metric"] for r in var_rows}
    for metric_key, label in [("PRI", "PRI"), ("FD", "FD"), ("DVARS", "DVARS"), ("tSNR", "tSNR")]:
        if label not in have:
            computed = variance_partition_metric(included, metric_key)
            computed["metric"] = label
            var_rows.append(computed)
            log(f"  computed variance partition for {label}")

    stats_out: list[dict[str, Any]] = []

    log("Figure 1 — PRI vs MRIQC")
    figure1_pri_vs_mriqc(included, out_dir, stats_out)

    log("Figure 2 — longitudinal ICC")
    figure2_icc(icc_rows, out_dir, stats_out)

    log("Figure 3 — longitudinal delta")
    figure3_delta(pairs_ok, out_dir, stats_out)

    log("Figure 4 — variance partition")
    figure4_variance(var_rows, out_dir, stats_out)

    log("Figure 5 — summary")
    figure5_summary(included, master_raw, icc_rows, stats_out, out_dir, stats_out)

    # Statistics table
    fieldnames = [
        "figure",
        "metric",
        "n",
        "rho",
        "p_value",
        "ICC",
        "CI_low",
        "CI_high",
        "note",
    ]
    write_csv(out_dir / "figure_statistics.csv", stats_out, fieldnames)

    n_long_subj = int(
        max(
            (
                to_float(r.get("n_subjects"))
                for r in icc_rows
                if np.isfinite(to_float(r.get("n_subjects")))
            ),
            default=0,
        )
    )
    write_readme(out_dir / "README.md", inclusion, len(pairs_ok), n_long_subj)

    # Privacy / PHI check on written text artifacts
    phi_hits = []
    for p in out_dir.glob("*"):
        if p.suffix.lower() not in {".md", ".csv", ".json", ".tsv", ".txt"}:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "/lustre" in text or "/home/" in text:
            # Absolute paths only allowed in this script's console log, not outputs
            # README may mention relative derivatives paths — flag absolute only
            phi_hits.append(f"absolute_path:{p.name}")
    if phi_hits:
        log(f"WARNING privacy scan: {phi_hits}")
    else:
        log("Privacy scan: PASS")

    log("PUBLICATION FIGURES COMPLETE")
    log(f"Wrote figures to {out_dir}")


if __name__ == "__main__":
    main()
