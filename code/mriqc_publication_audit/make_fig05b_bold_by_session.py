#!/usr/bin/env python3
"""Fig05b BOLD IQM board — strip plots by session (ses-01 vs ses-02).

Mirrors the style of Fig04b_T1w_MPR_iqm_board_violin.png, but with BOLD IQMs
from Fig05b_BOLD_iqm_board.png and exactly two point columns (session).
Does not overwrite the histogram Fig05b.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = Path("/home/alexrees/scratch/reports/mriqc_publication_audit")
FIG = OUT / "figures"
TAB = OUT / "tables"

C = {
    "ink": "#1a1a1a",
    "muted": "#5c5c5c",
    "grid": "#e6e6e6",
    "blue": "#2f5f8a",
    "blue_fill": "#6a9bc4",
    "warn": "#a65d16",
    "warn_fill": "#d4a574",
}

SPECS = [
    ("fd_mean", "Head motion (fd_mean)", "fd_mean (mm)", "lower is better"),
    ("tsnr", "Temporal SNR", "tSNR (a.u.)", "higher is better"),
    ("snr", "Signal-to-noise (SNR)", "SNR (a.u.)", "higher is better"),
    ("gcor", "Global correlation (GCOR)", "GCOR", "lower is better"),
    ("gsr_y", "Ghost-to-signal GSR (PE)", "gsr_y", "lower is better"),
    ("gsr_x", "Ghost-to-signal GSR (X)", "gsr_x", "lower is better"),
]

SESSIONS = ["ses-01", "ses-02"]
SES_COLOR = {
    "ses-01": C["blue_fill"],
    "ses-02": C["warn_fill"],
}
SES_MEDIAN = {
    "ses-01": C["blue"],
    "ses-02": C["warn"],
}


def style_ax(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(C["grid"])
    ax.spines["bottom"].set_color(C["grid"])
    ax.tick_params(colors=C["muted"])
    ax.yaxis.label.set_color(C["ink"])
    ax.xaxis.label.set_color(C["ink"])
    ax.title.set_color(C["ink"])
    ax.grid(axis="y", color=C["grid"], linewidth=0.8, zorder=0)


def normalize_session(s: pd.Series) -> pd.Series:
    out = s.astype(str).str.strip()
    out = out.replace(
        {
            "1": "ses-01",
            "01": "ses-01",
            "ses-1": "ses-01",
            "2": "ses-02",
            "02": "ses-02",
            "ses-2": "ses-02",
        }
    )
    # already "ses-01" / "ses-02" kept as-is
    return out


def load_bold() -> pd.DataFrame:
    path = TAB / "mriqc_iqm_current.tsv"
    if not path.is_file():
        path = Path(
            "/home/alexrees/scratch/derivatives/mriqc/group_qc/mriqc_iqm_all_acquisitions.tsv"
        )
    df = pd.read_csv(path, sep="\t")
    bold = df[df["modality"].astype(str) == "func"].copy()
    bold["session"] = normalize_session(bold["session"])
    for col, *_ in SPECS:
        if col in bold.columns:
            bold[col] = pd.to_numeric(bold[col], errors="coerce")
    return bold


def strip_panel(
    ax,
    bold: pd.DataFrame,
    col: str,
    title: str,
    ylab: str,
    sense: str,
    rng: np.random.Generator,
):
    style_ax(ax)
    meds: list[float] = []
    ns: list[int] = []
    for i, ses in enumerate(SESSIONS):
        vals = bold.loc[bold["session"] == ses, col].dropna().to_numpy(dtype=float)
        ns.append(len(vals))
        if len(vals) == 0:
            meds.append(float("nan"))
            continue
        med = float(np.median(vals))
        meds.append(med)
        # Dense BOLD: modest jitter + low alpha so clouds remain readable
        x = i + rng.uniform(-0.18, 0.18, size=len(vals))
        ax.scatter(
            x,
            vals,
            s=9,
            alpha=0.28,
            c=SES_COLOR[ses],
            edgecolors="none",
            zorder=2,
            rasterized=True,
        )
        ax.hlines(
            med,
            i - 0.22,
            i + 0.22,
            colors=SES_MEDIAN[ses],
            linewidths=2.2,
            zorder=3,
        )

    ax.set_xticks([0, 1])
    labels = []
    for ses, med, n in zip(SESSIONS, meds, ns):
        if np.isfinite(med):
            # compact formatting adapted to IQM scale
            if abs(med) >= 10:
                mtxt = f"{med:.1f}"
            elif abs(med) >= 1:
                mtxt = f"{med:.3g}"
            else:
                mtxt = f"{med:.3g}"
            labels.append(f"{ses}\nmed={mtxt}\nn={n}")
        else:
            labels.append(f"{ses}\nn=0")
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_xlim(-0.55, 1.55)
    ax.set_ylabel(ylab)
    ax.set_title(f"{title} — {sense}", fontsize=11, pad=6)


def main() -> int:
    bold = load_bold()
    bold = bold[bold["session"].isin(SESSIONS)].copy()
    rng = np.random.default_rng(1010)

    fig, axes = plt.subplots(2, 3, figsize=(12.5, 7.4))
    for ax, (col, title, ylab, sense) in zip(axes.ravel(), SPECS):
        if col not in bold.columns:
            ax.set_visible(False)
            continue
        strip_panel(ax, bold, col, title, ylab, sense, rng)

    fig.suptitle(
        "MRIQC BOLD IQM board — strip by session (ses-01 vs ses-02)",
        color=C["ink"],
        y=0.995,
        fontsize=13,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.text(
        0.5,
        0.008,
        "Points = individual BOLD runs · horizontal ticks = session medians · "
        "median and n under each cloud (not overlaid on points).",
        ha="center",
        fontsize=8,
        color=C["muted"],
        style="italic",
    )

    stem = "Fig05b_BOLD_iqm_board_by_session"
    FIG.mkdir(parents=True, exist_ok=True)
    png = FIG / f"{stem}.png"
    pdf = FIG / f"{stem}.pdf"
    fig.savefig(pdf, bbox_inches="tight")
    fig.savefig(png, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {png}")
    print(f"Wrote {pdf}")
    print(
        f"n BOLD rows used: {len(bold)} "
        f"(ses-01={int((bold.session == 'ses-01').sum())}, "
        f"ses-02={int((bold.session == 'ses-02').sum())})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
