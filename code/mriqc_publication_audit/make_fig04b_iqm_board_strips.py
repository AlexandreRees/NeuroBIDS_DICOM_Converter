#!/usr/bin/env python3
"""Regenerate Fig04b T1w_MPR / WMn strip IQM boards (same design + sense labels).

Adds "— higher is better" / "— lower is better" to each panel title.
Does not change layout, colors, medians/n annotations, or footnotes otherwise.
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

# MRIQC sense: which direction is better for each IQM
SPECS = [
    ("cnr", "Contrast-to-noise (CNR)", "CNR", "higher is better"),
    ("cjv", "Coeff. of joint variation (CJV)", "CJV", "lower is better"),
    ("efc", "Entropy-focus criterion (EFC)", "EFC", "lower is better"),
    ("inu_med", "Intensity non-uniformity (INU med)", "inu_med", "lower is better"),
]


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
    mask = ~out.str.startswith("ses-")
    out.loc[mask] = "ses-" + out.loc[mask].str.zfill(2)
    return out


def normalize_run(s: pd.Series) -> pd.Series:
    out = s.astype(str).str.replace(r"^run-", "", regex=True)
    out = out.str.lstrip("0").replace("", "0")
    return out


def fmt_med(med: float) -> str:
    if abs(med) >= 10:
        return f"{med:.1f}"
    if abs(med) >= 1:
        return f"{med:.3g}"
    return f"{med:.3g}"


def load_anat_with_protocol() -> pd.DataFrame:
    iq = pd.read_csv(TAB / "mriqc_iqm_current.tsv", sep="\t")
    anat = iq[iq["modality"].astype(str) == "anat"].copy()
    proto = pd.read_csv(TAB / "t1w_iqm_by_protocol.tsv", sep="\t")

    for d in (anat, proto):
        d["subject"] = d["subject"].astype(str).str.replace(r"^sub-", "", regex=True)
        d["session"] = normalize_session(d["session"])
        d["run"] = normalize_run(d["run"])

    for col, _, _, _ in SPECS:
        if col in anat.columns:
            anat[col] = pd.to_numeric(anat[col], errors="coerce")

    m = anat.merge(
        proto[["subject", "session", "run", "protocol"]],
        on=["subject", "session", "run"],
        how="left",
    )
    return m


def panel_title(base: str, sense: str) -> str:
    return f"{base} — {sense}"


def save(fig, stem: str):
    FIG.mkdir(parents=True, exist_ok=True)
    png = FIG / f"{stem}.png"
    pdf = FIG / f"{stem}.pdf"
    fig.savefig(pdf, bbox_inches="tight")
    fig.savefig(png, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {png}")
    print(f"Wrote {pdf}")


def make_t1w_mpr(df: pd.DataFrame) -> None:
    mpr = df[df["protocol"] == "T1w_MPR"].copy()
    mpr = mpr[mpr["run"].isin(["1", "2"])]
    mpr = mpr[mpr["session"].isin(["ses-01", "ses-02"])]

    groups = [
        ("ses-01", "1", C["blue"], C["blue"]),
        ("ses-01", "2", C["blue_fill"], C["blue"]),
        ("ses-02", "1", C["warn"], C["warn"]),
        ("ses-02", "2", C["warn_fill"], C["warn"]),
    ]
    rng = np.random.default_rng(20260727)

    fig, axes = plt.subplots(2, 2, figsize=(11.2, 7.4))
    for ax, (col, title, ylab, sense) in zip(axes.ravel(), SPECS):
        style_ax(ax)
        meds: list[float] = []
        ns: list[int] = []
        for i, (ses, run, pt_color, med_color) in enumerate(groups):
            vals = mpr.loc[
                (mpr["session"] == ses) & (mpr["run"] == run), col
            ].dropna().to_numpy(dtype=float)
            ns.append(len(vals))
            if len(vals) == 0:
                meds.append(float("nan"))
                continue
            med = float(np.median(vals))
            meds.append(med)
            x = i + rng.uniform(-0.18, 0.18, size=len(vals))
            ax.scatter(
                x,
                vals,
                s=14,
                alpha=0.45,
                c=pt_color,
                edgecolors="none",
                zorder=2,
                rasterized=True,
            )
            ax.hlines(
                med, i - 0.22, i + 0.22, colors=med_color, linewidths=2.2, zorder=3
            )

        labels = []
        for (ses, run, _, _), med, n in zip(groups, meds, ns):
            if np.isfinite(med):
                labels.append(f"{ses} run-0{run}\nmed={fmt_med(med)}\nn={n}")
            else:
                labels.append(f"{ses} run-0{run}\nn=0")
        ax.set_xticks(range(len(groups)))
        ax.set_xticklabels(labels, fontsize=8.5)
        ax.set_xlim(-0.55, len(groups) - 0.45)
        ax.set_ylabel(ylab)
        ax.set_title(panel_title(title, sense), fontsize=11, pad=6)

    fig.suptitle(
        "MRIQC T1w IQM board — T1w_MPR — strip by session × run",
        color=C["ink"],
        y=0.995,
        fontsize=13,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.text(
        0.5,
        0.008,
        "Points = individual T1w_MPR scans · horizontal ticks = group medians · "
        "median and n under each cloud (not overlaid on points).",
        ha="center",
        fontsize=8,
        color=C["muted"],
        style="italic",
    )
    save(fig, "Fig04b_T1w_MPR_iqm_board_violin")


def make_wmn(df: pd.DataFrame) -> None:
    wmn = df[df["protocol"] == "WMn_MPRAGE_sagittal"].copy()
    wmn = wmn[wmn["session"].isin(["ses-01", "ses-02"])]
    sessions = ["ses-01", "ses-02"]
    colors = {
        "ses-01": (C["blue_fill"], C["blue"]),
        "ses-02": (C["warn_fill"], C["warn"]),
    }
    rng = np.random.default_rng(20260727)

    n_by_ses = {ses: int((wmn["session"] == ses).sum()) for ses in sessions}

    fig, axes = plt.subplots(2, 2, figsize=(9.8, 7.2))
    for ax, (col, title, ylab, sense) in zip(axes.ravel(), SPECS):
        style_ax(ax)
        meds: list[float] = []
        ns: list[int] = []
        for i, ses in enumerate(sessions):
            vals = wmn.loc[wmn["session"] == ses, col].dropna().to_numpy(dtype=float)
            ns.append(len(vals))
            pt_color, med_color = colors[ses]
            if len(vals) == 0:
                meds.append(float("nan"))
                continue
            med = float(np.median(vals))
            meds.append(med)
            x = i + rng.uniform(-0.18, 0.18, size=len(vals))
            ax.scatter(
                x,
                vals,
                s=16,
                alpha=0.45,
                c=pt_color,
                edgecolors="none",
                zorder=2,
                rasterized=True,
            )
            ax.hlines(
                med, i - 0.22, i + 0.22, colors=med_color, linewidths=2.2, zorder=3
            )

        # In-panel median annotations (original WMn design)
        annot_lines = []
        for ses, med, n in zip(sessions, meds, ns):
            if np.isfinite(med):
                annot_lines.append(f"{ses}: med={fmt_med(med)} (n={n})")
        ax.text(
            0.98,
            0.98,
            "\n".join(annot_lines),
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8,
            color=C["muted"],
            linespacing=1.35,
        )

        ax.set_xticks([0, 1])
        ax.set_xticklabels(sessions, fontsize=9)
        ax.set_xlim(-0.55, 1.55)
        ax.set_ylabel(ylab)
        ax.set_title(panel_title(title, sense), fontsize=11, pad=6)

    # Session legend (original WMn design)
    from matplotlib.lines import Line2D

    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=colors[ses][0],
            markersize=8,
            label=f"{ses} (n={n_by_ses[ses]})",
        )
        for ses in sessions
    ]
    fig.legend(
        handles=handles,
        loc="upper right",
        bbox_to_anchor=(0.99, 0.98),
        frameon=False,
        fontsize=8.5,
    )

    fig.suptitle(
        "MRIQC T1w IQM board — WMn_MPRAGE_sagittal (white-matter-nulled) — strip by session",
        color=C["ink"],
        y=0.995,
        fontsize=12.5,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    fig.text(
        0.5,
        0.008,
        "Points = individual T1w scans · horizontal ticks = session medians · "
        "ProtocolName=WMn_MPRAGE_sagittal.",
        ha="center",
        fontsize=8,
        color=C["muted"],
        style="italic",
    )
    save(fig, "Fig04b_WMn_MPRAGE_iqm_board_violin")


def main() -> int:
    df = load_anat_with_protocol()
    make_t1w_mpr(df)
    make_wmn(df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
