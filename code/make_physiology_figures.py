#!/usr/bin/env python3
"""
Publication-quality figures for physiological characterization (Scientific Data).

Reads derivatives from physiology_characterization/ (never modifies inputs).
Writes PNG (300 dpi) + PDF under figures_publication/.

Compatible with outputs of code/physiology_characterization.py and optional
legacy/alias filenames listed in the manuscript checklist.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

try:
    import seaborn as sns

    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

TASK_ORDER = ["rest", "movie", "fmri", "control"]
TASK_LABELS = {
    "rest": "Rest",
    "movie": "Movie",
    "fmri": "fMRI (grating)",
    "control": "Control",
}
STATUS_ORDER = ["PASS", "REVIEW", "FAIL"]
STATUS_COLORS = {"PASS": "#1b9e77", "REVIEW": "#d95f02", "FAIL": "#7570b3"}
CHANNEL_ORDER = ["cardiac", "respiratory", "trigger"]
CHANNEL_COLORS = {
    "cardiac": "#2c7fb8",
    "respiratory": "#41b6c4",
    "trigger": "#7fcdbb",
}

HR_RANGE = (40.0, 180.0)
RR_RANGE = (4.0, 40.0)
RMSSD_RANGE = (0.0, 500.0)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_style() -> None:
    mpl.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica", "sans-serif"],
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    if HAS_SEABORN:
        sns.set_theme(style="ticks", context="paper")


def save_fig(fig: plt.Figure, out_dir: Path, stem: str, meta: dict[str, Any]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("png", "pdf"):
        p = out_dir / f"{stem}.{ext}"
        fig.savefig(p, dpi=300 if ext == "png" else None, bbox_inches="tight", facecolor="white")
        paths.append(p)
    meta["files"] = [str(p.name) for p in paths]
    return paths


# ---------------------------------------------------------------------------
# Data loading (flexible filenames)
# ---------------------------------------------------------------------------

ALIASES = {
    "summary": [
        "physiology_characterization_summary.tsv",
        "physiology_summary.tsv",
        "physiology_features.tsv",
    ],
    "subject": [
        "physiology_characterization_subject.tsv",
        "physiology_qc_summary.tsv",
    ],
    "dataset_json": [
        "physiology_characterization_dataset.json",
        "physiology_characterization.json",
    ],
    "trigger": ["trigger_qc.tsv"],
    "starttime": ["starttime_summary.tsv"],
}


def _first_existing(input_dir: Path, names: list[str]) -> Optional[Path]:
    for n in names:
        p = input_dir / n
        if p.is_file():
            return p
    return None


def load_inputs(input_dir: Path) -> dict[str, Any]:
    summary_path = _first_existing(input_dir, ALIASES["summary"])
    if summary_path is None:
        raise FileNotFoundError(
            f"No summary TSV found in {input_dir}. Expected one of {ALIASES['summary']}"
        )
    df = pd.read_csv(summary_path, sep="\t", na_values=["n/a", "NA", ""])
    # normalize column aliases if needed
    rename = {}
    if "qc_status" in df.columns and "status" not in df.columns:
        rename["qc_status"] = "status"
    if "mean_HR" in df.columns and "card_mean_HR_bpm" not in df.columns:
        rename["mean_HR"] = "card_mean_HR_bpm"
    df = df.rename(columns=rename)

    subj_path = _first_existing(input_dir, ALIASES["subject"])
    subj = pd.read_csv(subj_path, sep="\t", na_values=["n/a", "NA", ""]) if subj_path else None

    js_path = _first_existing(input_dir, ALIASES["dataset_json"])
    dataset = json.loads(js_path.read_text()) if js_path else {}

    trig_path = _first_existing(input_dir, ALIASES["trigger"])
    trigger = pd.read_csv(trig_path, sep="\t", na_values=["n/a", "NA", ""]) if trig_path else None

    st_path = _first_existing(input_dir, ALIASES["starttime"])
    starttime = pd.read_csv(st_path, sep="\t", na_values=["n/a", "NA", ""]) if st_path else None

    return {
        "summary": df,
        "summary_path": summary_path.name,
        "subject": subj,
        "dataset": dataset,
        "trigger": trigger,
        "starttime": starttime,
    }


def physiological_filter(series: pd.Series, lo: float, hi: float, name: str) -> tuple[pd.Series, int]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    n0 = len(s)
    # IQR fence + hard physiological bounds
    if len(s) >= 8:
        q1, q3 = np.percentile(s, [25, 75])
        iqr = q3 - q1
        soft_lo, soft_hi = q1 - 3 * iqr, q3 + 3 * iqr
        lo_eff, hi_eff = max(lo, soft_lo), min(hi, soft_hi)
    else:
        lo_eff, hi_eff = lo, hi
    kept = s[(s >= lo_eff) & (s <= hi_eff)]
    n_excl = n0 - len(kept)
    if n_excl:
        print(f"  Outliers/impossible excluded for {name}: {n_excl} / {n0} (kept {len(kept)}; bounds [{lo_eff:.3g}, {hi_eff:.3g}])")
    return kept, n_excl


# ---------------------------------------------------------------------------
# Figure 1 — Dataset overview
# ---------------------------------------------------------------------------

def figure1(df: pd.DataFrame, out_dir: Path, meta: dict) -> None:
    n_rec = len(df)
    n_sub = df["subject"].nunique() if "subject" in df.columns else 0
    n_task = df["task"].nunique() if "task" in df.columns else 0

    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4), constrained_layout=True)

    # A — totals
    ax = axes[0]
    labels = ["Recordings", "Subjects", "Tasks"]
    vals = [n_rec, n_sub, n_task]
    bars = ax.bar(labels, vals, color=["#345995", "#345995", "#345995"], width=0.65)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"n={v}", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("Count")
    ax.set_title("A  Dataset size")
    ax.set_ylim(0, max(vals) * 1.18)

    # B — by task
    ax = axes[1]
    task_counts = df["task"].value_counts() if "task" in df.columns else pd.Series(dtype=int)
    tasks = [t for t in TASK_ORDER if t in task_counts.index] + [
        t for t in task_counts.index if t not in TASK_ORDER
    ]
    y = np.arange(len(tasks))
    x = [int(task_counts.get(t, 0)) for t in tasks]
    ax.barh(y, x, color="#03cea4", height=0.65)
    ax.set_yticks(y)
    ax.set_yticklabels([TASK_LABELS.get(t, t) for t in tasks])
    ax.invert_yaxis()
    for yi, xi in zip(y, x):
        ax.text(xi, yi, f"  {xi}", va="center", fontsize=8)
    ax.set_xlabel("Number of recordings")
    ax.set_title(f"B  Recordings by task (n={n_rec})")

    # C — channels
    ax = axes[2]
    fam = df["channel_family"].value_counts() if "channel_family" in df.columns else pd.Series(dtype=int)
    chans = [c for c in CHANNEL_ORDER if c in fam.index]
    counts = [int(fam[c]) for c in chans]
    pcts = [100.0 * c / n_rec if n_rec else 0 for c in counts]
    y = np.arange(len(chans))
    ax.barh(y, counts, color=[CHANNEL_COLORS[c] for c in chans], height=0.65)
    ax.set_yticks(y)
    ax.set_yticklabels([c.capitalize() for c in chans])
    ax.invert_yaxis()
    for yi, c, p in zip(y, counts, pcts):
        ax.text(c, yi, f"  {c} ({p:.0f}%)", va="center", fontsize=8)
    ax.set_xlabel("Number of recordings")
    ax.set_title("C  Channel availability")

    fig.suptitle("Figure 1. Dataset physiological overview", fontsize=11, fontweight="bold", y=1.02)
    paths = save_fig(fig, out_dir, "Figure1_dataset_overview", meta.setdefault("Figure1", {}))
    plt.close(fig)
    meta["Figure1"].update({"n_recordings": n_rec, "n_subjects": n_sub, "n_tasks": n_task, "paths": [p.name for p in paths]})


# ---------------------------------------------------------------------------
# Figure 2 — QC status
# ---------------------------------------------------------------------------

def figure2(df: pd.DataFrame, out_dir: Path, meta: dict) -> None:
    status = df["status"].astype(str).str.upper() if "status" in df.columns else pd.Series(dtype=str)
    n = len(status)
    counts = status.value_counts()
    fig, ax = plt.subplots(figsize=(5.2, 4.0), constrained_layout=True)
    xs = [s for s in STATUS_ORDER if s in counts.index]
    ys = [int(counts[s]) for s in xs]
    pct = [100.0 * y / n if n else 0 for y in ys]
    bars = ax.bar(xs, ys, color=[STATUS_COLORS[s] for s in xs], width=0.62)
    for b, y, p in zip(bars, ys, pct):
        ax.text(b.get_x() + b.get_width() / 2, y, f"{y}\n({p:.0f}%)", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Number of recordings")
    ax.set_xlabel("QC status")
    ax.set_title("Physiological QC outcome")
    ax.set_ylim(0, max(ys) * 1.22 if ys else 1)
    ax.text(0.5, -0.18, f"Automated physiological quality assessment  |  total N = {n}",
            transform=ax.transAxes, ha="center", fontsize=8, style="italic", color="#333333")
    fig.suptitle("Figure 2. Physiological QC outcome", fontsize=11, fontweight="bold")
    paths = save_fig(fig, out_dir, "Figure2_qc_status", meta.setdefault("Figure2", {}))
    plt.close(fig)
    meta["Figure2"].update({"counts": {s: int(counts.get(s, 0)) for s in STATUS_ORDER}, "N": n, "paths": [p.name for p in paths]})


# ---------------------------------------------------------------------------
# Figure 3 — Availability & completeness
# ---------------------------------------------------------------------------

def figure3(df: pd.DataFrame, subj: Optional[pd.DataFrame], out_dir: Path, meta: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.6), constrained_layout=True)

    # A — presence by subject-session if subject table available, else by recording family
    ax = axes[0]
    if subj is not None and {"cardiac_available", "resp_available", "trigger_available"}.issubset(subj.columns):
        labels = ["Cardiac", "Respiratory", "Trigger"]
        cols = ["cardiac_available", "resp_available", "trigger_available"]
        n_sess = len(subj)
        present = [(subj[c].astype(str).str.upper() == "YES").sum() for c in cols]
        pct = [100.0 * p / n_sess if n_sess else 0 for p in present]
        bars = ax.bar(labels, present, color=[CHANNEL_COLORS[c] for c in CHANNEL_ORDER], width=0.65)
        for b, p, pc in zip(bars, present, pct):
            ax.text(b.get_x() + b.get_width() / 2, p, f"{p}\n({pc:.0f}%)", ha="center", va="bottom", fontsize=8)
        ax.set_ylabel("Subject–sessions with channel")
        ax.set_title(f"A  Channel presence (n sessions={n_sess})")
        ax.set_ylim(0, max(present) * 1.25 if present else 1)
    else:
        fam = df["channel_family"].value_counts()
        labels = [c.capitalize() for c in CHANNEL_ORDER if c in fam.index]
        vals = [int(fam[c]) for c in CHANNEL_ORDER if c in fam.index]
        ax.bar(labels, vals, color=[CHANNEL_COLORS[c] for c in CHANNEL_ORDER if c in fam.index])
        ax.set_ylabel("Recordings")
        ax.set_title("A  Channel presence")

    # B — completeness / flatline proxy (missing_fraction often ~0 after conversion)
    ax = axes[1]
    miss_col = "q_missing_fraction" if "q_missing_fraction" in df.columns else None
    flat_col = "q_flatline_fraction" if "q_flatline_fraction" in df.columns else None
    if miss_col and df[miss_col].fillna(0).max() > 0:
        x = 100.0 * pd.to_numeric(df[miss_col], errors="coerce").dropna()
        xlab = "Missing samples (%)"
        title = "B  Missing-data distribution"
    elif flat_col:
        x = 100.0 * pd.to_numeric(df[flat_col], errors="coerce").dropna()
        xlab = "Flatline fraction (%)"
        title = "B  Signal flatness (completeness proxy)"
    else:
        x = pd.to_numeric(df.get("duration_seconds", pd.Series(dtype=float)), errors="coerce").dropna()
        xlab = "Recording duration (s)"
        title = "B  Duration distribution"
    if len(x):
        ax.hist(x, bins=30, color="#6c757d", edgecolor="white", linewidth=0.4)
        med, q1, q3 = np.median(x), np.percentile(x, 25), np.percentile(x, 75)
        ax.axvline(med, color="#212529", lw=1.2, label=f"median={med:.2g}")
        ax.axvspan(q1, q3, color="#adb5bd", alpha=0.35, label=f"IQR=[{q1:.2g}, {q3:.2g}]")
        ax.legend(frameon=False, fontsize=7)
        ax.set_xlabel(xlab)
        ax.set_ylabel("Number of recordings")
        ax.set_title(f"{title} (n={len(x)})")
        meta.setdefault("Figure3", {})["panel_B"] = {
            "metric": xlab,
            "median": float(med),
            "q1": float(q1),
            "q3": float(q3),
            "n": int(len(x)),
        }
    else:
        ax.text(0.5, 0.5, "No completeness metric available", ha="center", va="center")
        ax.set_axis_off()

    fig.suptitle("Figure 3. Signal availability and completeness", fontsize=11, fontweight="bold")
    paths = save_fig(fig, out_dir, "Figure3_signal_availability", meta.setdefault("Figure3", {}))
    plt.close(fig)
    meta["Figure3"]["paths"] = [p.name for p in paths]


# ---------------------------------------------------------------------------
# Figure 4 — Physiological distributions
# ---------------------------------------------------------------------------

def figure4(df: pd.DataFrame, out_dir: Path, meta: dict) -> None:
    print("Outlier filtering (Figure 4):")
    hr, n_hr_ex = physiological_filter(df.get("card_mean_HR_bpm", pd.Series(dtype=float)), *HR_RANGE, "HR")
    rr, n_rr_ex = physiological_filter(df.get("resp_mean_respiratory_rate_bpm", pd.Series(dtype=float)), *RR_RANGE, "RR")
    hrv, n_hrv_ex = physiological_filter(df.get("card_RMSSD", pd.Series(dtype=float)), *RMSSD_RANGE, "RMSSD")

    panels = [
        (hr, "Heart rate", "beats per minute (bpm)", "#2c7fb8"),
        (rr, "Respiratory rate", "breaths/min", "#41b6c4"),
        (hrv, "HRV (RMSSD)", "ms", "#253494"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(10.2, 3.6), constrained_layout=True)
    for ax, (data, title, ylab, color), letter in zip(axes, panels, "ABC"):
        if len(data) == 0:
            ax.text(0.5, 0.5, "No valid data", ha="center", va="center")
            ax.set_title(f"{letter}  {title}")
            continue
        if HAS_SEABORN:
            sns.violinplot(y=data, ax=ax, color=color, inner="quartile", cut=0)
        else:
            parts = ax.violinplot(data.values, showmeans=False, showmedians=True, showextrema=False)
            for b in parts["bodies"]:
                b.set_facecolor(color)
                b.set_alpha(0.7)
            ax.boxplot(data.values, widths=0.15, showfliers=False,
                       medianprops=dict(color="black", lw=1.2))
        med = float(np.median(data))
        q1, q3 = np.percentile(data, [25, 75])
        ax.set_ylabel(ylab)
        ax.set_title(f"{letter}  {title}\nn={len(data)}  median={med:.1f}  IQR=[{q1:.1f}, {q3:.1f}]")
        ax.set_xticks([])
    fig.suptitle("Figure 4. Physiological parameter distributions", fontsize=11, fontweight="bold")
    paths = save_fig(fig, out_dir, "Figure4_physiological_distributions", meta.setdefault("Figure4", {}))
    plt.close(fig)
    meta["Figure4"].update({
        "excluded": {"HR": n_hr_ex, "RR": n_rr_ex, "RMSSD": n_hrv_ex},
        "n": {"HR": int(len(hr)), "RR": int(len(rr)), "RMSSD": int(len(hrv))},
        "paths": [p.name for p in paths],
    })


# ---------------------------------------------------------------------------
# Figure 5 — Paradigm comparison
# ---------------------------------------------------------------------------

def _kw_and_pairwise(groups: dict[str, np.ndarray]) -> dict[str, Any]:
    keys = [k for k, v in groups.items() if len(v) >= 3]
    result: dict[str, Any] = {"kruskal_p": None, "pairwise": {}}
    if len(keys) < 2:
        return result
    samples = [groups[k] for k in keys]
    try:
        h, p = stats.kruskal(*samples)
        result["kruskal_H"] = float(h)
        result["kruskal_p"] = float(p)
    except Exception:
        return result
    if p < 0.05:
        # Mann–Whitney pairwise (Holm)
        pairs = []
        raw = []
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                _, pj = stats.mannwhitneyu(groups[keys[i]], groups[keys[j]], alternative="two-sided")
                pairs.append((keys[i], keys[j]))
                raw.append(pj)
        order = np.argsort(raw)
        m = len(raw)
        adj = np.empty(m)
        for rank, idx in enumerate(order):
            adj[idx] = min((m - rank) * raw[idx], 1.0)
        # enforce monotonicity
        for rank in range(1, m):
            prev = order[rank - 1]
            cur = order[rank]
            adj[cur] = max(adj[cur], adj[prev])
        for (a, b), pj, pa in zip(pairs, raw, adj):
            result["pairwise"][f"{a}_vs_{b}"] = {"p": float(pj), "p_holm": float(pa)}
    return result


def figure5(df: pd.DataFrame, out_dir: Path, meta: dict) -> None:
    metrics = [
        ("card_mean_HR_bpm", "Heart rate (bpm)", HR_RANGE, "A"),
        ("resp_mean_respiratory_rate_bpm", "Respiratory rate (breaths/min)", RR_RANGE, "B"),
        ("card_RMSSD", "HRV RMSSD (ms)", RMSSD_RANGE, "C"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.8), constrained_layout=True)
    stats_out: dict[str, Any] = {}

    for ax, (col, ylab, bounds, letter) in zip(axes, metrics):
        if col not in df.columns or "task" not in df.columns:
            ax.text(0.5, 0.5, "Metric unavailable", ha="center")
            ax.set_axis_off()
            continue
        plot_df = df[["task", col]].copy()
        plot_df[col] = pd.to_numeric(plot_df[col], errors="coerce")
        plot_df = plot_df.dropna()
        plot_df = plot_df[(plot_df[col] >= bounds[0]) & (plot_df[col] <= bounds[1])]
        tasks = [t for t in TASK_ORDER if t in set(plot_df["task"])]
        plot_df = plot_df[plot_df["task"].isin(tasks)]
        if plot_df.empty:
            ax.text(0.5, 0.5, "No valid data", ha="center")
            continue

        if HAS_SEABORN:
            sns.violinplot(
                data=plot_df, x="task", y=col, order=tasks, ax=ax,
                inner=None, cut=0, color="#a6cee3", linewidth=0.8,
            )
            sns.stripplot(
                data=plot_df, x="task", y=col, order=tasks, ax=ax,
                size=1.5, color="#333333", alpha=0.15, jitter=0.25,
            )
            sns.boxplot(
                data=plot_df, x="task", y=col, order=tasks, ax=ax,
                width=0.2, showfliers=False, boxprops=dict(facecolor="white", alpha=0.8),
                medianprops=dict(color="black", lw=1.2), whiskerprops=dict(lw=0.8),
                capprops=dict(lw=0.8),
            )
        else:
            data = [plot_df.loc[plot_df.task == t, col].values for t in tasks]
            ax.violinplot(data, showextrema=False)
            ax.boxplot(data, showfliers=False, widths=0.25)
            ax.set_xticks(range(1, len(tasks) + 1))
            ax.set_xticklabels([TASK_LABELS.get(t, t) for t in tasks], rotation=20, ha="right")

        ax.set_xlabel("")
        ax.set_ylabel(ylab)
        ns = [int((plot_df.task == t).sum()) for t in tasks]
        ax.set_title(f"{letter}  n=" + ", ".join(f"{TASK_LABELS.get(t,t)[0]}:{n}" for t, n in zip(tasks, ns)))
        if HAS_SEABORN:
            ax.set_xticklabels([TASK_LABELS.get(t, t) for t in tasks], rotation=20, ha="right")

        groups = {t: plot_df.loc[plot_df.task == t, col].values for t in tasks}
        st = _kw_and_pairwise(groups)
        stats_out[col] = st
        if st.get("kruskal_p") is not None:
            p = st["kruskal_p"]
            note = f"Kruskal–Wallis p={p:.3g}"
            if p < 0.05 and st.get("pairwise"):
                sig = [k for k, v in st["pairwise"].items() if v["p_holm"] < 0.05]
                if sig:
                    note += f"\n{len(sig)} pairwise Holm p<0.05"
            ax.text(0.02, 0.98, note, transform=ax.transAxes, va="top", fontsize=7, color="#222222")

    fig.suptitle("Figure 5. Physiology by acquisition paradigm", fontsize=11, fontweight="bold")
    paths = save_fig(fig, out_dir, "Figure5_paradigm_comparison", meta.setdefault("Figure5", {}))
    plt.close(fig)
    meta["Figure5"].update({"statistics": stats_out, "paths": [p.name for p in paths]})
    print("Figure 5 statistics:", json.dumps(stats_out, indent=2)[:1500])


# ---------------------------------------------------------------------------
# Figure 6 — Quality summary
# ---------------------------------------------------------------------------

def figure6(df: pd.DataFrame, out_dir: Path, meta: dict) -> None:
    d = df.copy()
    if "physiology_quality_score" in d.columns:
        d["quality_index"] = pd.to_numeric(d["physiology_quality_score"], errors="coerce")
        q_source = "physiology_quality_score"
    else:
        # Construct simple index 0–100
        status_map = {"PASS": 100.0, "REVIEW": 55.0, "FAIL": 15.0}
        base = d.get("status", pd.Series(["REVIEW"] * len(d))).astype(str).str.upper().map(status_map).fillna(40.0)
        fam_bonus = d.get("channel_family", pd.Series([""] * len(d))).isin(["cardiac", "respiratory"]).astype(float) * 5
        d["quality_index"] = (base + fam_bonus).clip(0, 100)
        q_source = "constructed_from_status"

    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.6), constrained_layout=True)

    # A distribution
    ax = axes[0]
    q = d["quality_index"].dropna()
    ax.hist(q, bins=25, color="#253494", edgecolor="white", linewidth=0.4)
    ax.axvline(np.median(q), color="black", lw=1.1, label=f"median={np.median(q):.1f}")
    ax.legend(frameon=False, fontsize=7)
    ax.set_xlabel("Quality score (0–100)")
    ax.set_ylabel("Number of recordings")
    ax.set_title(f"A  Quality distribution (n={len(q)})")

    # B by task
    ax = axes[1]
    if "task" in d.columns:
        tasks = [t for t in TASK_ORDER if t in set(d["task"])]
        data = [d.loc[d.task == t, "quality_index"].dropna().values for t in tasks]
        if HAS_SEABORN:
            sns.boxplot(
                data=d[d.task.isin(tasks)], x="task", y="quality_index", order=tasks, ax=ax,
                showfliers=False, color="#9ecae1",
            )
            ax.set_xticklabels([TASK_LABELS.get(t, t) for t in tasks], rotation=20, ha="right")
        else:
            ax.boxplot(data, showfliers=False)
            ax.set_xticks(range(1, len(tasks) + 1))
            ax.set_xticklabels([TASK_LABELS.get(t, t) for t in tasks], rotation=20, ha="right")
        ax.set_ylabel("Quality score (0–100)")
        ax.set_xlabel("")
        ax.set_title("B  Quality by task")
    else:
        ax.set_axis_off()

    # C by subject (mean score)
    ax = axes[2]
    if "subject" in d.columns:
        sub_mean = d.groupby("subject")["quality_index"].mean().sort_values()
        # anonymize display as rank order to avoid overcrowding IDs
        ax.plot(range(len(sub_mean)), sub_mean.values, color="#345995", lw=1.0)
        ax.fill_between(range(len(sub_mean)), sub_mean.values, alpha=0.15, color="#345995")
        ax.set_xlabel("Subjects (ordered by mean score)")
        ax.set_ylabel("Mean quality score")
        ax.set_title(f"C  Quality by subject (n={len(sub_mean)})")
        ax.set_ylim(0, 105)
    else:
        ax.set_axis_off()

    fig.suptitle("Figure 6. Physiology quality summary", fontsize=11, fontweight="bold")
    paths = save_fig(fig, out_dir, "Figure6_quality_summary", meta.setdefault("Figure6", {}))
    plt.close(fig)
    meta["Figure6"].update({"quality_source": q_source, "n": int(len(q)), "paths": [p.name for p in paths]})


# ---------------------------------------------------------------------------
# Figure 7 — Example traces (optional BIDS read-only)
# ---------------------------------------------------------------------------

def _load_physio_trace(tsv_gz: Path) -> tuple[np.ndarray, float, str]:
    js = Path(str(tsv_gz).replace(".tsv.gz", ".json"))
    meta = json.loads(js.read_text()) if js.is_file() else {}
    fs = float(meta.get("SamplingFrequency") or 0)
    cols = meta.get("Columns") or ["signal"]
    if isinstance(cols, str):
        cols = [cols]
    with gzip.open(tsv_gz, "rt", encoding="utf-8", errors="replace") as fh:
        lines = [ln.strip() for ln in fh.read().splitlines() if ln.strip()]
    if not lines:
        return np.array([]), fs, str(cols[0])
    start = 1 if not _is_float(lines[0].split("\t")[0].split()[0]) else 0
    vals = []
    for ln in lines[start:]:
        tok = ln.split("\t")[0] if "\t" in ln else ln.split()[0]
        try:
            vals.append(float(tok))
        except ValueError:
            continue
    return np.asarray(vals, dtype=float), fs, str(cols[0])


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def figure7(df: pd.DataFrame, bids_dir: Optional[Path], out_dir: Path, meta: dict) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(8.5, 5.8), sharex=True, constrained_layout=True)
    info_lines = []

    if bids_dir is None or not bids_dir.is_dir() or "relative_path" not in df.columns:
        for ax, lab in zip(axes, ["Cardiac", "Respiratory", "Trigger"]):
            ax.text(0.5, 0.5, f"{lab}: provide --bids_dir to load example traces",
                    ha="center", va="center", transform=ax.transAxes, fontsize=8)
            ax.set_ylabel(lab)
        axes[-1].set_xlabel("Time (s)")
        fig.suptitle("Figure 7. Representative physiological recording", fontsize=11, fontweight="bold")
        paths = save_fig(fig, out_dir, "Figure7_example_trace", meta.setdefault("Figure7", {}))
        plt.close(fig)
        meta["Figure7"].update({"note": "bids_dir not provided; placeholder figure", "paths": [p.name for p in paths]})
        return

    # Choose a PASS cardiac with long duration, then sibling resp/trigger same run
    cand = df[
        (df.get("status", "") == "PASS")
        & (df.get("channel_family", "") == "cardiac")
        & (pd.to_numeric(df.get("duration_seconds"), errors="coerce") > 30)
    ].copy()
    if cand.empty:
        cand = df[df.get("channel_family", "") == "cardiac"].copy()
    if cand.empty:
        for ax in axes:
            ax.text(0.5, 0.5, "No cardiac recording available", ha="center", va="center")
        paths = save_fig(fig, out_dir, "Figure7_example_trace", meta.setdefault("Figure7", {}))
        plt.close(fig)
        return

    cand["duration_seconds"] = pd.to_numeric(cand["duration_seconds"], errors="coerce")
    row = cand.sort_values("duration_seconds", ascending=False).iloc[0]
    sub, ses, task, run = row["subject"], row.get("session", ""), row.get("task", ""), row.get("run", "")

    def find_sibling(family: str) -> Optional[pd.Series]:
        m = (
            (df["subject"] == sub)
            & (df.get("session", "") == ses)
            & (df.get("task", "") == task)
            & (df.get("run", "").astype(str) == str(run))
            & (df["channel_family"] == family)
        )
        hit = df[m]
        return hit.iloc[0] if len(hit) else None

    families = [
        ("cardiac", axes[0], CHANNEL_COLORS["cardiac"]),
        ("respiratory", axes[1], CHANNEL_COLORS["respiratory"]),
        ("trigger", axes[2], CHANNEL_COLORS["trigger"]),
    ]
    max_t = 0.0
    fs_ann = None
    dur_ann = None
    for fam, ax, color in families:
        r = row if fam == "cardiac" else find_sibling(fam)
        if r is None:
            ax.text(0.5, 0.5, f"{fam}: not available for this run", ha="center", va="center",
                    transform=ax.transAxes, fontsize=8, color="#666666")
            ax.set_ylabel(fam.capitalize())
            continue
        path = bids_dir / r["relative_path"]
        if not path.is_file():
            ax.text(0.5, 0.5, f"{fam}: file missing", ha="center", va="center", transform=ax.transAxes)
            ax.set_ylabel(fam.capitalize())
            continue
        x, fs, _ = _load_physio_trace(path)
        if x.size == 0 or not fs:
            ax.text(0.5, 0.5, f"{fam}: empty", ha="center", va="center", transform=ax.transAxes)
            ax.set_ylabel(fam.capitalize())
            continue
        # show up to 60 s for readability
        n = int(min(x.size, 60 * fs))
        t = np.arange(n) / fs
        ax.plot(t, x[:n], color=color, lw=0.7)
        ax.set_ylabel(f"{fam.capitalize()}\n(a.u.)")
        max_t = max(max_t, t[-1] if len(t) else 0)
        if fam == "cardiac":
            fs_ann = fs
            dur_ann = float(r.get("duration_seconds") or x.size / fs)
        if fam == "trigger":
            tr = r.get("trig_median_TR")
            if pd.notna(tr):
                info_lines.append(f"TR≈{float(tr):.3f} s")

    axes[-1].set_xlabel("Time (s)")
    # Anonymized annotation
    ann = f"sub-XXX | task-{task} | run-{run} | fs={fs_ann:g} Hz | duration={dur_ann:.1f} s" if fs_ann else "sub-XXX"
    if info_lines:
        ann += " | " + " | ".join(info_lines)
    axes[0].set_title(ann, fontsize=8)
    fig.suptitle("Figure 7. Representative physiological recording (PASS)", fontsize=11, fontweight="bold")
    paths = save_fig(fig, out_dir, "Figure7_example_trace", meta.setdefault("Figure7", {}))
    plt.close(fig)
    meta["Figure7"].update({
        "anonymized_subject": "sub-XXX",
        "task": str(task),
        "run": str(run),
        "fs_Hz": fs_ann,
        "duration_s": dur_ann,
        "paths": [p.name for p in paths],
    })


# ---------------------------------------------------------------------------
# README + main
# ---------------------------------------------------------------------------

def write_readme(out_dir: Path, meta: dict, input_dir: Path) -> None:
    text = f"""# Publication figures — physiological characterization

**Generated:** `{meta.get('generated')}`  
**Input:** `{input_dir.name}/` (read-only)  
**Output:** `{out_dir.name}/`

## Figures

| Figure | File stem | Content |
|---|---|---|
| 1 | `Figure1_dataset_overview` | Dataset size, recordings by task, channel availability |
| 2 | `Figure2_qc_status` | PASS / REVIEW / FAIL counts and percentages |
| 3 | `Figure3_signal_availability` | Channel presence and completeness / flatness |
| 4 | `Figure4_physiological_distributions` | HR, respiratory rate, HRV RMSSD |
| 5 | `Figure5_paradigm_comparison` | Physiology by rest / movie / fmri / control |
| 6 | `Figure6_quality_summary` | Quality score distribution, by task, by subject |
| 7 | `Figure7_example_trace` | Anonymized PASS multi-channel example |

Each figure is exported as **PNG (300 dpi)** and **PDF** (vector text).

## Notes

- Impossible / extreme physiological values are filtered before plotting (see console and `figure_metadata.json`).
- Subject identifiers in example traces are anonymized as `sub-XXX`.
- Kruskal–Wallis (+ Holm-corrected Mann–Whitney when significant) is reported for Figure 5 without over-interpretation.
- Technical BIDS QC vs physiological characterization remain distinct; these figures support the latter for Scientific Data.

## Re-run

```bash
python code/make_physiology_figures.py \\
  --input_dir derivatives/physiology_characterization \\
  --output_dir derivatives/physiology_characterization/figures_publication \\
  --bids_dir bids
```
"""
    (out_dir / "README.md").write_text(text, encoding="utf-8")


def print_summary(df: pd.DataFrame) -> None:
    print("\n=== Summary statistics ===")
    print(f"Recordings: {len(df)}")
    if "subject" in df.columns:
        print(f"Subjects: {df['subject'].nunique()}")
    if "task" in df.columns:
        print("By task:\n", df["task"].value_counts().to_string())
    if "status" in df.columns:
        print("By status:\n", df["status"].value_counts().to_string())
    for col, name in [
        ("card_mean_HR_bpm", "HR bpm"),
        ("resp_mean_respiratory_rate_bpm", "RR /min"),
        ("card_RMSSD", "RMSSD ms"),
        ("physiology_quality_score", "Quality score"),
    ]:
        if col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(s):
                print(f"{name}: median={s.median():.2f}, IQR=[{s.quantile(0.25):.2f}, {s.quantile(0.75):.2f}], n={len(s)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Publication figures for physiological characterization")
    ap.add_argument("--input_dir", type=Path, required=True)
    ap.add_argument("--output_dir", type=Path, required=True)
    ap.add_argument("--bids_dir", type=Path, default=None, help="optional BIDS root for Figure 7 traces (read-only)")
    args = ap.parse_args(argv)

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not input_dir.is_dir():
        print(f"ERROR: input_dir not found: {input_dir}", file=sys.stderr)
        return 2

    setup_style()
    data = load_inputs(input_dir)
    df = data["summary"]
    print(f"Loaded summary: {data['summary_path']} ({len(df)} rows)")
    print(f"seaborn: {'yes' if HAS_SEABORN else 'no (matplotlib fallback)'}")
    print_summary(df)

    meta: dict[str, Any] = {
        "generated": _utc(),
        "input_dir": str(input_dir.name),
        "summary_file": data["summary_path"],
        "seaborn": HAS_SEABORN,
    }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        figure1(df, output_dir, meta)
        figure2(df, output_dir, meta)
        figure3(df, data["subject"], output_dir, meta)
        figure4(df, output_dir, meta)
        figure5(df, output_dir, meta)
        figure6(df, output_dir, meta)
        figure7(df, args.bids_dir.resolve() if args.bids_dir else None, output_dir, meta)

    write_readme(output_dir, meta, input_dir)
    (output_dir / "figure_metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote figures to {output_dir}")
    for p in sorted(output_dir.glob("Figure*")):
        print(f"  {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
