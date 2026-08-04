#!/usr/bin/env python3
"""Figure 1b — subjects with physiological recordings (by task / by channel).

Panel B shows Respiratory and Pulse only (no ECG). Bar labels are counts only
(no percentages).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path("/home/alexrees/scratch")
SUMMARY = ROOT / "derivatives/physiology_characterization/physiology_characterization_summary.tsv"
OUT = ROOT / "derivatives/physiology_characterization/figures_publication"

TASK_ORDER = ["rest", "movie", "fmri", "control"]
TASK_LABELS = {
    "rest": "Rest",
    "movie": "Movie",
    "fmri": "fMRI (grating)",
    "control": "Control",
}
CHAN_ORDER = ["Respiratory", "Pulse"]  # ECG omitted (not released / not usable)
SES = ["ses-01", "ses-02"]
SES_COLORS = {"ses-01": "#9ecae1", "ses-02": "#08519c"}


def modality(row: pd.Series) -> str | None:
    rec = str(row.get("recording", "")).lower()
    fam = str(row.get("channel_family", "")).lower()
    if rec == "pulse":
        return "Pulse"
    if rec == "ecg":
        return "ECG"
    if fam == "respiratory" or rec == "respiratory":
        return "Respiratory"
    if fam == "cardiac" and rec != "ecg":
        return "Pulse"
    return None


def grouped_vertical(
    ax: plt.Axes,
    categories: list[str],
    labels: list[str],
    values_by_ses: pd.Series,
    ylabel: str,
    title: str,
) -> None:
    x = np.arange(len(categories))
    width = 0.36
    for i, ses in enumerate(SES):
        vals = [int(values_by_ses.loc[(ses, c)]) for c in categories]
        bars = ax.bar(
            x + (i - 0.5) * width,
            vals,
            width=width,
            color=SES_COLORS[ses],
            label=ses,
            edgecolor="white",
            linewidth=0.4,
        )
        for b, v in zip(bars, vals):
            ax.text(
                b.get_x() + b.get_width() / 2,
                v,
                f"{v}",
                ha="center",
                va="bottom",
                fontsize=7,
            )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_ylim(0, max(int(values_by_ses.max()), 1) * 1.22)
    ax.legend(frameon=False, loc="upper right")


def main() -> None:
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

    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(SUMMARY, sep="\t", na_values=["n/a", "NA", ""])
    df["modality"] = df.apply(modality, axis=1)
    phys = df[df["modality"].isin(CHAN_ORDER)].copy()

    task_s = (
        df.groupby(["session", "task"])["subject"]
        .nunique()
        .reindex(
            pd.MultiIndex.from_product([SES, TASK_ORDER], names=["session", "task"]),
            fill_value=0,
        )
    )
    chan_s = (
        phys.groupby(["session", "modality"])["subject"]
        .nunique()
        .reindex(
            pd.MultiIndex.from_product([SES, CHAN_ORDER], names=["session", "modality"]),
            fill_value=0,
        )
    )

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8), constrained_layout=True)
    grouped_vertical(
        axes[0],
        TASK_ORDER,
        [TASK_LABELS[t] for t in TASK_ORDER],
        task_s,
        "Number of subjects",
        f"A  By task (n={int(task_s.sum())})",
    )
    grouped_vertical(
        axes[1],
        CHAN_ORDER,
        CHAN_ORDER,
        chan_s,
        "Number of subjects",
        f"B  Channel availability (n={int(chan_s.sum())})",
    )
    fig.suptitle(
        "Figure 1b. Subjects with physiological recordings",
        fontsize=11,
        fontweight="bold",
    )
    for ext in ("png", "pdf"):
        fig.savefig(
            OUT / f"Figure1b_subjects_overview.{ext}",
            dpi=300 if ext == "png" else None,
            bbox_inches="tight",
            facecolor="white",
        )
    plt.close(fig)

    # Standalone panel B (matches the cropped view often used in slides)
    fig, ax = plt.subplots(figsize=(5.2, 3.8), constrained_layout=True)
    grouped_vertical(
        ax,
        CHAN_ORDER,
        CHAN_ORDER,
        chan_s,
        "Number of subjects",
        f"Channel availability (n={int(chan_s.sum())})",
    )
    for ext in ("png", "pdf"):
        fig.savefig(
            OUT / f"Figure1b_channel_availability.{ext}",
            dpi=300 if ext == "png" else None,
            bbox_inches="tight",
            facecolor="white",
        )
    plt.close(fig)

    print(chan_s.unstack(fill_value=0))
    print("Wrote", OUT / "Figure1b_subjects_overview.png")
    print("Wrote", OUT / "Figure1b_channel_availability.png")

    # Channel × BOLD task × session (Respiratory | Pulse panels)
    counts = (
        phys[phys["task"].isin(TASK_ORDER)]
        .groupby(["modality", "session", "task"])["subject"]
        .nunique()
        .reindex(
            pd.MultiIndex.from_product(
                [CHAN_ORDER, SES, TASK_ORDER],
                names=["modality", "session", "task"],
            ),
            fill_value=0,
        )
    )

    def draw_channel_by_task(ax: plt.Axes, channel: str, letter: str) -> None:
        x = np.arange(len(TASK_ORDER))
        width = 0.36
        ymax = 1
        for i, ses in enumerate(SES):
            vals = [int(counts.loc[(channel, ses, t)]) for t in TASK_ORDER]
            ymax = max(ymax, max(vals) if vals else 0)
            bars = ax.bar(
                x + (i - 0.5) * width,
                vals,
                width=width,
                color=SES_COLORS[ses],
                label=ses,
                edgecolor="white",
                linewidth=0.4,
            )
            for b, v in zip(bars, vals):
                ax.text(
                    b.get_x() + b.get_width() / 2,
                    v,
                    f"{v}",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                )
        ax.set_xticks(x)
        ax.set_xticklabels([TASK_LABELS[t] for t in TASK_ORDER], rotation=15, ha="right")
        ax.set_ylabel("Number of subjects")
        ax.set_title(f"{letter}  {channel} by BOLD task", fontweight="bold")
        ax.set_ylim(0, ymax * 1.22)
        ax.legend(frameon=False, loc="upper right")

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8), constrained_layout=True)
    draw_channel_by_task(axes[0], "Respiratory", "A")
    draw_channel_by_task(axes[1], "Pulse", "B")
    fig.suptitle(
        "Subjects with physiology by channel × BOLD task × session",
        fontsize=11,
        fontweight="bold",
    )
    fig.text(
        0.5,
        -0.02,
        "A subject is counted if ≥1 *_physio.tsv.gz of that channel is linked to a "
        "BOLD run of that task in that session. Physiology was acquired during the "
        "functional EPI runs (same task labels as BIDS).",
        ha="center",
        fontsize=7.5,
        style="italic",
        color="#555555",
    )
    for ext in ("png", "pdf"):
        fig.savefig(
            OUT / f"Figure1b_channel_by_task.{ext}",
            dpi=300 if ext == "png" else None,
            bbox_inches="tight",
            facecolor="white",
        )
    plt.close(fig)
    print(counts.unstack("task"))
    print("Wrote", OUT / "Figure1b_channel_by_task.png")


if __name__ == "__main__":
    main()
