#!/usr/bin/env python3
"""Generate PI / publication figures for MRIQC audit (English labels)."""
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
FIG.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)

C = {
    "ink": "#1a1a1a",
    "muted": "#5c5c5c",
    "grid": "#e6e6e6",
    "ok": "#2a6f4e",
    "ok_fill": "#d8ebe1",
    "warn": "#a65d16",
    "warn_fill": "#f3e2cf",
    "bad": "#9b2c2c",
    "blue": "#2f5f8a",
    "blue_fill": "#d6e3ef",
    "gray": "#7a7a7a",
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


def save(fig, stem: str):
    pdf = FIG / f"{stem}.pdf"
    png = FIG / f"{stem}.png"
    fig.savefig(pdf, bbox_inches="tight")
    fig.savefig(png, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return pdf, png


def load_iqms():
    current = TAB / "mriqc_iqm_current.tsv"
    fallback = Path(
        "/home/alexrees/scratch/derivatives/mriqc/group_qc/mriqc_iqm_all_acquisitions.tsv"
    )
    path = current if current.exists() else fallback
    df = pd.read_csv(path, sep="\t")
    for col in [
        "fd_mean",
        "tsnr",
        "dvars",
        "cnr",
        "cjv",
        "snr_total",
        "snr",
        "aqi",
        "ghost",
        "efc",
        "fwhm_avg",
        "fwhm",
        "size_t",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df, path


def fig01_coverage_summary():
    labels = ["Complete\nsessions", "T1w IQMs", "BOLD IQMs", "T1w+BOLD\nscans"]
    got = np.array([120, 354, 1494, 1848])
    exp = np.array([124, 356, 1496, 1852])
    pct = 100 * got / exp

    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    style_ax(ax)
    x = np.arange(len(labels))
    bars = ax.bar(x, pct, color=[C["warn"], C["ok"], C["ok"], C["ok"]], width=0.62, zorder=2)
    ax.axhline(100, color=C["grid"], ls="--", lw=1)
    ax.set_ylim(90, 101.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Coverage (%)")
    ax.set_title("MRIQC — cohort coverage (audit 24 July 2026)")
    for b, g, e, p in zip(bars, got, exp, pct):
        ax.text(
            b.get_x() + b.get_width() / 2,
            p + 0.25,
            f"{p:.1f}%\n{g}/{e}",
            ha="center",
            va="bottom",
            fontsize=9,
            color=C["ink"],
        )
    ax.text(
        0.99,
        0.04,
        "4 missing scans = truncated / out-of-protocol acquisitions (not a software bug)",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        color=C["muted"],
    )
    fig.tight_layout()
    return save(fig, "Fig01_MRIQC_coverage_summary")


def fig02_coverage_progression():
    stages = ["Before ACF\npatch\n(23 Jul)", "After ACF\npatch\n(24 Jul)"]
    sess = [78.2, 96.8]
    bold = [91.4, 99.9]
    t1 = [99.2, 99.4]
    x = np.arange(len(stages))
    w = 0.25
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    style_ax(ax)
    ax.bar(x - w, sess, w, label="Sessions", color=C["warn"], zorder=2)
    ax.bar(x, t1, w, label="T1w", color=C["ok"], zorder=2)
    ax.bar(x + w, bold, w, label="BOLD", color=C["blue"], zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels(stages)
    ax.set_ylabel("Coverage (%)")
    ax.set_ylim(70, 105)
    ax.set_title("MRIQC coverage after AFNI 3dFWHMx ACF fix")
    ax.legend(frameon=False, loc="lower right")
    for i, vals in enumerate([sess, t1, bold]):
        offs = [-w, 0, w][i]
        for xi, v in enumerate(vals):
            ax.text(xi + offs, v + 0.6, f"{v:.1f}", ha="center", fontsize=8, color=C["ink"])
    fig.tight_layout()
    return save(fig, "Fig02_MRIQC_coverage_progression")


def _hist_iqm_panel(ax, vals, title: str, xlab: str, ylabel: str) -> None:
    style_ax(ax)
    vals = np.asarray(vals, dtype=float)
    vals = vals[np.isfinite(vals)]
    ax.hist(vals, bins=40, color=C["blue_fill"], edgecolor=C["blue"], linewidth=0.6, zorder=2)
    med = float(np.median(vals))
    p95 = float(np.percentile(vals, 95))
    ax.axvline(med, color=C["ok"], lw=1.8, label=f"Median = {med:.3g}")
    ax.axvline(p95, color=C["warn"], lw=1.4, ls="--", label=f"p95 = {p95:.3g}")
    ax.set_title(f"{title}   (n = {len(vals)})", color=C["ink"])
    ax.set_xlabel(xlab)
    ax.set_ylabel(ylabel)
    ax.legend(frameon=False, fontsize=7.5, loc="upper right")


def fig03_bold_quality(df: pd.DataFrame):
    bold = df[df["modality"] == "func"].copy() if "modality" in df.columns else df
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4.2))
    for ax, col, title, xlab in [
        (axes[0], "fd_mean", "Head motion (fd_mean)", "fd_mean (mm)"),
        (axes[1], "tsnr", "Temporal SNR", "tSNR (a.u.)"),
    ]:
        style_ax(ax)
        vals = bold[col].dropna().to_numpy()
        ax.hist(vals, bins=40, color=C["blue_fill"], edgecolor=C["blue"], linewidth=0.6, zorder=2)
        med = float(np.median(vals))
        p95 = float(np.percentile(vals, 95))
        ax.axvline(med, color=C["ok"], lw=1.8, label=f"Median = {med:.3g}")
        ax.axvline(p95, color=C["warn"], lw=1.4, ls="--", label=f"p95 = {p95:.3g}")
        ax.set_title(title)
        ax.set_xlabel(xlab)
        ax.set_ylabel("Number of BOLD runs")
        ax.legend(frameon=False, fontsize=8)
        ax.text(
            0.98,
            0.95,
            f"n = {len(vals)}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            color=C["muted"],
        )
    fig.suptitle("MRIQC functional quality — cohort distributions", color=C["ink"], y=1.02)
    fig.tight_layout()
    return save(fig, "Fig03_BOLD_fd_tsnr_distributions")


def fig05b_bold_iqm_board(df: pd.DataFrame):
    """AOMIC Fig. 5–inspired BOLD IQM board (Fig03 design)."""
    bold = df[df["modality"] == "func"].copy()
    specs = [
        ("fd_mean", "Head motion (fd_mean)", "fd_mean (mm)"),
        ("tsnr", "Temporal SNR", "tSNR (a.u.)"),
        ("snr", "Signal-to-noise (SNR)", "SNR (a.u.)"),
        ("gcor", "Global correlation (GCOR)", "GCOR"),
        ("gsr_y", "Ghost-to-signal GSR (PE)", "gsr_y"),
        ("gsr_x", "Ghost-to-signal GSR (X)", "gsr_x"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 7.2))
    for ax, (col, title, xlab) in zip(axes.ravel(), specs):
        _hist_iqm_panel(ax, bold[col].to_numpy(), title, xlab, "Number of BOLD runs")
    fig.suptitle(
        "MRIQC BOLD IQM board — cohort distributions (AOMIC Fig. 5 inspired)",
        color=C["ink"],
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.text(
        0.5,
        0.005,
        "Source: mriqc_iqm_current.tsv (func). GSR shown separately for PE (gsr_y) and X (gsr_x).",
        ha="center",
        fontsize=8,
        color=C["muted"],
        style="italic",
    )
    return save(fig, "Fig05b_BOLD_iqm_board")


def fig04b_t1w_iqm_board(df: pd.DataFrame):
    """AOMIC Fig. 4–inspired T1w IQM board (Fig03 design)."""
    anat = df[df["modality"] == "anat"].copy()
    specs = [
        ("cnr", "Contrast-to-noise (CNR)", "CNR"),
        ("cjv", "Coeff. of joint variation (CJV)", "CJV"),
        ("efc", "Entropy-focus criterion (EFC)", "EFC"),
        ("inu_med", "Intensity non-uniformity (INU med)", "inu_med"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(9.5, 7.2))
    for ax, (col, title, xlab) in zip(axes.ravel(), specs):
        _hist_iqm_panel(ax, anat[col].to_numpy(), title, xlab, "Number of T1w scans")
    fig.suptitle(
        "MRIQC T1w IQM board — cohort distributions (AOMIC Fig. 4 inspired)",
        color=C["ink"],
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.text(
        0.5,
        0.005,
        "Source: mriqc_iqm_current.tsv (anat / T1w). INU = MRIQC inu_med.",
        ha="center",
        fontsize=8,
        color=C["muted"],
        style="italic",
    )
    return save(fig, "Fig04b_T1w_iqm_board")


def attach_anat_protocol(anat: pd.DataFrame) -> pd.DataFrame:
    """Add ProtocolName from BIDS anat JSON sidecars (T1w_MPR vs WMn_MPRAGE_sagittal)."""
    import json

    bids = Path("/home/alexrees/scratch/bids")
    out = anat.copy()
    protocols: list[str] = []
    for _, r in out.iterrows():
        fn = Path(str(r.get("filename", ""))).name
        if fn.endswith(".json"):
            stem = fn[:-5]
        elif fn.endswith(".html"):
            stem = fn[:-5]
        elif fn.endswith(".nii.gz"):
            stem = fn[: -len(".nii.gz")]
        else:
            stem = fn
        sub = str(r.get("subject", ""))
        ses = str(r.get("session", ""))
        if sub and not sub.startswith("sub-"):
            sub = f"sub-{sub}"
        if ses and not ses.startswith("ses-"):
            ses = f"ses-{ses}"
        js = bids / sub / ses / "anat" / f"{stem}.json"
        proto = ""
        if js.is_file():
            try:
                meta = json.loads(js.read_text(encoding="utf-8"))
                proto = str(meta.get("ProtocolName") or meta.get("SeriesDescription") or "")
            except Exception:  # noqa: BLE001
                proto = ""
        protocols.append(proto)
    out["protocol"] = protocols
    return out


def _violin_iqm_panel(
    anat: pd.DataFrame,
    *,
    title: str,
    stem: str,
    subtitle: str = "",
):
    metrics = [
        ("cnr", "CNR", C["ok"]),
        ("cjv", "CJV (lower better)", C["blue"]),
        ("snr_total", "Total SNR", C["warn"]),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.8))
    for ax, (col, mtitle, color) in zip(axes, metrics):
        style_ax(ax)
        vals = anat[col].dropna().to_numpy() if col in anat.columns else np.array([])
        if len(vals) == 0:
            ax.set_visible(False)
            continue
        parts = ax.violinplot([vals], showmeans=False, showmedians=True, widths=0.7)
        for b in parts["bodies"]:
            b.set_facecolor(color)
            b.set_alpha(0.35)
            b.set_edgecolor(color)
        for key in ("cmedians", "cbars", "cmins", "cmaxes"):
            if key in parts:
                parts[key].set_color(C["ink"])
                parts[key].set_linewidth(1.2)
        ax.set_xticks([1])
        ax.set_xticklabels([mtitle])
        ax.set_title(mtitle)
        med = float(np.median(vals))
        ax.text(
            1.35,
            med,
            f"med={med:.3g}\nn={len(vals)}",
            va="center",
            fontsize=8,
            color=C["muted"],
        )
    fig.suptitle(title, color=C["ink"], y=1.03)
    if subtitle:
        fig.text(0.5, 0.01, subtitle, ha="center", va="bottom", fontsize=8, color=C["muted"])
    fig.tight_layout()
    return save(fig, stem)


def fig04_anat_quality(df: pd.DataFrame):
    anat = df[df["modality"] == "anat"].copy() if "modality" in df.columns else df
    if "suffix" in anat.columns:
        anat = anat[anat["suffix"].astype(str).str.contains("T1w", na=False)]
    if "filename" in anat.columns:
        anat = anat.drop_duplicates(subset=["filename"])
    return _violin_iqm_panel(
        anat,
        title="MRIQC T1w anatomical quality — IQMs (all protocols)",
        stem="Fig04_T1w_cnr_cjv_snr",
        subtitle="Includes both T1w_MPR and WMn_MPRAGE_sagittal (bimodal)",
    )


def fig04_anat_quality_by_protocol(df: pd.DataFrame):
    """Separate CNR/CJV/SNR figures for T1w_MPR vs WMn_MPRAGE_sagittal."""
    anat = df[df["modality"] == "anat"].copy() if "modality" in df.columns else df.copy()
    if "suffix" in anat.columns:
        anat = anat[anat["suffix"].astype(str).str.contains("T1w", na=False)]
    if "filename" in anat.columns:
        anat = anat.drop_duplicates(subset=["filename"])
    anat = attach_anat_protocol(anat)

    # Persist protocol assignment for reproducibility
    keep = [
        c
        for c in [
            "subject",
            "session",
            "run",
            "filename",
            "protocol",
            "cnr",
            "cjv",
            "snr_total",
        ]
        if c in anat.columns
    ]
    anat[keep].to_csv(TAB / "t1w_iqm_by_protocol.tsv", sep="\t", index=False)

    outputs = []
    splits = [
        (
            "T1w_MPR",
            "Fig04a_T1w_MPR_cnr_cjv_snr",
            "MRIQC anatomical quality — T1w_MPR (standard MPRAGE)",
            "0.8 mm isotropic · typically run-01/run-02",
        ),
        (
            "WMn_MPRAGE_sagittal",
            "Fig04b_WMn_MPRAGE_cnr_cjv_snr",
            "MRIQC anatomical quality — WMn_MPRAGE_sagittal (white-matter-nulled)",
            "1.0 mm · typically run-03 · different contrast → different IQM scale",
        ),
    ]
    for proto, stem, title, subtitle in splits:
        sub = anat[anat["protocol"] == proto].copy()
        if len(sub) == 0:
            print(f"WARN: no rows for protocol {proto}")
            continue
        outputs.append(
            _violin_iqm_panel(sub, title=title, stem=stem, subtitle=subtitle)
        )
    return outputs


def fig05_motion_by_task(df: pd.DataFrame):
    from matplotlib.patches import Patch

    bold = df[df["modality"] == "func"].copy() if "modality" in df.columns else df
    if "task" not in bold.columns or "session" not in bold.columns:
        return None
    bold["session"] = bold["session"].astype(str)
    bold.loc[bold["session"].isin(["1", "01", "ses-1"]), "session"] = "ses-01"
    bold.loc[bold["session"].isin(["2", "02", "ses-2"]), "session"] = "ses-02"

    order = ["control", "fmri", "movie", "rest"]
    sessions = ["ses-01", "ses-02"]
    ses_style = {
        "ses-01": ("#e8e8e8", C["gray"]),
        "ses-02": (C["blue_fill"], C["blue"]),
    }
    fig, axes = plt.subplots(2, 1, figsize=(9.2, 7.6), sharex=False)

    for ax, col, ylab, title in [
        (axes[0], "fd_mean", "fd_mean (mm)", "Motion by task"),
        (axes[1], "tsnr", "tSNR", "tSNR by task"),
    ]:
        style_ax(ax)
        data = []
        positions = []
        box_colors = []
        tick_pos = []
        tick_labels = []
        for i, t in enumerate(order):
            n_tot = 0
            for j, ses in enumerate(sessions):
                v = bold.loc[
                    (bold["task"].astype(str) == t) & (bold["session"] == ses), col
                ].dropna()
                n_tot += len(v)
                if len(v) == 0:
                    continue
                positions.append(i * 3 + j + 1)
                data.append(v.to_numpy())
                box_colors.append(ses_style[ses])
            tick_pos.append(i * 3 + 1.5)
            tick_labels.append(f"{t}\n(n={n_tot})")

        bp = ax.boxplot(
            data,
            positions=positions,
            widths=0.72,
            patch_artist=True,
            medianprops=dict(color=C["ink"], linewidth=1.5),
            whiskerprops=dict(color=C["muted"]),
            capprops=dict(color=C["muted"]),
            flierprops=dict(
                marker="o", markersize=3, markerfacecolor=C["gray"], alpha=0.4
            ),
        )
        for patch, (fc, ec) in zip(bp["boxes"], box_colors):
            patch.set_facecolor(fc)
            patch.set_edgecolor(ec)
        ax.set_xticks(tick_pos)
        ax.set_xticklabels(tick_labels)
        ax.set_xlim(0.2, len(order) * 3 - 0.2)
        ax.set_ylabel(ylab)
        ax.set_title(title)
        ax.legend(
            handles=[
                Patch(facecolor="#e8e8e8", edgecolor=C["gray"], label="ses-01"),
                Patch(facecolor=C["blue_fill"], edgecolor=C["blue"], label="ses-02"),
            ],
            frameon=False,
            loc="upper right",
            fontsize=9,
        )

    fig.suptitle("MRIQC BOLD quality by paradigm", color=C["ink"], y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    return save(fig, "Fig05_BOLD_quality_by_task")


def fig06_completeness_donut():
    fig, ax = plt.subplots(figsize=(5.2, 5.0))
    sizes = [1848, 4]
    colors = [C["ok"], C["bad"]]
    wedges, _ = ax.pie(
        sizes,
        colors=colors,
        startangle=90,
        wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
    )
    ax.text(
        0,
        0.08,
        "99.8%",
        ha="center",
        va="center",
        fontsize=28,
        fontweight="bold",
        color=C["ok"],
    )
    ax.text(
        0,
        -0.18,
        "scans with IQM\n1848 / 1852",
        ha="center",
        va="center",
        fontsize=10,
        color=C["muted"],
    )
    ax.set_title("MRIQC completeness (T1w + magnitude BOLD)")
    ax.legend(
        wedges,
        ["IQM available", "Pathological acquisition (n=4)"],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.05),
        frameon=False,
    )
    fig.tight_layout()
    return save(fig, "Fig06_MRIQC_completeness_donut")


def fig07_high_motion(df: pd.DataFrame):
    bold = df[df["modality"] == "func"].copy() if "modality" in df.columns else df
    sub = (
        bold.groupby("subject", as_index=False)["fd_mean"]
        .mean()
        .sort_values("fd_mean", ascending=False)
        .head(10)
    )
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    style_ax(ax)
    y = np.arange(len(sub))[::-1]
    ax.barh(y, sub["fd_mean"], color=C["warn_fill"], edgecolor=C["warn"], zorder=2)
    ax.axvline(0.5, color=C["bad"], ls="--", lw=1.2, label="Exploratory 0.5 mm marker")
    ax.set_yticks(y)
    ax.set_yticklabels(list(sub["subject"])[::-1])
    ax.set_xlabel("Mean fd_mean (mm) — all BOLD runs per subject")
    ax.set_title("Subjects with highest mean head motion")
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    ax.text(
        0.99,
        0.02,
        "Exploratory flags — not a priori exclusions for publication",
        transform=ax.transAxes,
        ha="right",
        fontsize=8,
        color=C["muted"],
    )
    fig.tight_layout()
    return save(fig, "Fig07_high_motion_subjects")


def fig08_missing_runs_panel():
    rows = [
        ("sub-002 ses-01", "task-fmri run-07", "Truncated BOLD", "4 / ~226 volumes"),
        ("sub-011 ses-01", "task-fmri run-03", "Truncated BOLD", "3 / ~226 volumes"),
        ("sub-039 ses-02", "T1w run-03", "Out-of-protocol T1w", "Abnormal FOV/intensity"),
        ("sub-058 ses-01", "T1w run-03", "Out-of-protocol T1w", "Abnormal FOV/intensity"),
    ]
    fig, ax = plt.subplots(figsize=(9.0, 3.6))
    ax.axis("off")
    ax.set_title(
        "Four scans without IQM — data pathology (justified for publication)",
        color=C["ink"],
        pad=12,
    )
    col_x = [0.02, 0.28, 0.52, 0.72]
    headers = ["Session", "Run", "Diagnosis", "BIDS evidence"]
    for x, h in zip(col_x, headers):
        ax.text(
            x,
            0.92,
            h,
            fontsize=10,
            fontweight="bold",
            color=C["muted"],
            transform=ax.transAxes,
        )
    for i, r in enumerate(rows):
        y = 0.72 - i * 0.18
        ax.add_patch(
            plt.Rectangle(
                (0.01, y - 0.06),
                0.98,
                0.16,
                transform=ax.transAxes,
                facecolor=C["warn_fill"] if i < 2 else "#f5e6e6",
                edgecolor="none",
                zorder=0,
            )
        )
        for x, val in zip(col_x, r):
            ax.text(
                x, y, val, fontsize=10, color=C["ink"], transform=ax.transAxes, va="center"
            )
    ax.text(
        0.02,
        0.05,
        'MRIQC error: "Input inhomogeneity-corrected data seem empty" — expected failure, not a pipeline defect.',
        fontsize=8,
        color=C["muted"],
        transform=ax.transAxes,
    )
    fig.tight_layout()
    return save(fig, "Fig08_four_missing_acquisitions")


def fig09_pi_onepager(df: pd.DataFrame):
    bold = df[df["modality"] == "func"].copy() if "modality" in df.columns else df
    anat = df[df["modality"] == "anat"].copy() if "modality" in df.columns else df
    fd_med = bold["fd_mean"].median()
    tsnr_med = bold["tsnr"].median()
    cnr_med = anat["cnr"].median() if "cnr" in anat.columns else np.nan
    low_motion = (bold["fd_mean"] < 0.2).mean() * 100

    fig = plt.figure(figsize=(11, 6.0))
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(
        0.04,
        0.90,
        "MRIQC — quality summary (PI)",
        fontsize=20,
        fontweight="bold",
        color=C["ink"],
    )
    ax.text(
        0.04,
        0.83,
        "84 subjects · 124 sessions · MRIQC 24.0.2 · derivatives/mriqc",
        fontsize=11,
        color=C["muted"],
    )

    boxes = [
        (0.04, 0.52, "99.8%", "Scan coverage\n1848 / 1852", C["ok_fill"], C["ok"]),
        (
            0.28,
            0.52,
            f"{fd_med:.2f} mm",
            "Median motion\n(fd_mean BOLD)",
            C["blue_fill"],
            C["blue"],
        ),
        (0.52, 0.52, f"{tsnr_med:.1f}", "Median tSNR\nBOLD", C["ok_fill"], C["ok"]),
        (0.76, 0.52, f"{cnr_med:.2f}", "Median CNR\nT1w", C["blue_fill"], C["blue"]),
    ]
    for x, y, val, lab, fill, edge in boxes:
        ax.add_patch(
            plt.Rectangle(
                (x, y),
                0.20,
                0.24,
                transform=ax.transAxes,
                facecolor=fill,
                edgecolor=edge,
                linewidth=1.5,
            )
        )
        ax.text(
            x + 0.10,
            y + 0.14,
            val,
            ha="center",
            va="center",
            fontsize=20,
            fontweight="bold",
            color=edge,
        )
        ax.text(
            x + 0.10,
            y + 0.05,
            lab,
            ha="center",
            va="center",
            fontsize=9,
            color=C["muted"],
        )

    bullets = [
        f"• {low_motion:.0f}% of BOLD runs have fd_mean < 0.2 mm (low motion).",
        "• After AFNI ACF patch: sessions 78% → 97%; BOLD 91% → 99.9%.",
        "• 4 scans without IQM = aborted / out-of-protocol acquisitions (verified on NIfTI).",
        "• IQM outliers = exploratory within-cohort flags (z/IQR), not exclusion criteria.",
        "• Publication recommendation: document the 4 cases in Technical Validation; do not block OpenNeuro.",
    ]
    y = 0.42
    for b in bullets:
        ax.text(0.04, y, b, fontsize=11, color=C["ink"], va="top")
        y -= 0.07

    ax.text(
        0.04,
        0.05,
        "Sources: reports/mriqc_publication_audit · reports/mriqc_coverage_audit · derivatives/mriqc/group_qc",
        fontsize=8,
        color=C["muted"],
    )
    return save(fig, "Fig09_PI_onepager_quality_summary")


def write_warning_tables(df: pd.DataFrame):
    bold = df[df["modality"] == "func"].copy() if "modality" in df.columns else df
    hi = bold[bold["fd_mean"] >= 0.5].sort_values("fd_mean", ascending=False)
    cols = [
        c
        for c in ["subject", "session", "task", "run", "fd_mean", "tsnr", "dvars", "filename"]
        if c in hi.columns
    ]
    hi[cols].to_csv(TAB / "warning_high_motion_runs.tsv", sep="\t", index=False)

    missing = pd.DataFrame(
        [
            {
                "subject": "sub-002",
                "session": "ses-01",
                "acquisition": "task-fmri_run-07_bold",
                "warning_class": "MISSING_IQM",
                "severity": "truncated_bold",
                "evidence": "NIfTI shape 104x104x88x4 (expected ~226 vols)",
                "publication_action": "Document as incomplete acquisition; do not treat as MRIQC software failure",
            },
            {
                "subject": "sub-011",
                "session": "ses-01",
                "acquisition": "task-fmri_run-03_bold",
                "warning_class": "MISSING_IQM",
                "severity": "truncated_bold",
                "evidence": "NIfTI shape 104x104x88x3 (expected ~226 vols)",
                "publication_action": "Document as incomplete acquisition; do not treat as MRIQC software failure",
            },
            {
                "subject": "sub-039",
                "session": "ses-02",
                "acquisition": "run-03_T1w",
                "warning_class": "MISSING_IQM",
                "severity": "abnormal_t1w",
                "evidence": "FOV 192x224x224, max intensity ~390 vs sibling T1w 208x300x320 max~4095",
                "publication_action": "Document as out-of-protocol / failed anatomical series",
            },
            {
                "subject": "sub-058",
                "session": "ses-01",
                "acquisition": "run-03_T1w",
                "warning_class": "MISSING_IQM",
                "severity": "abnormal_t1w",
                "evidence": "FOV 192x224x224, max intensity ~294",
                "publication_action": "Document as out-of-protocol / failed anatomical series",
            },
        ]
    )
    missing.to_csv(TAB / "warning_missing_iqms.tsv", sep="\t", index=False)

    out_path = Path("/home/alexrees/scratch/derivatives/mriqc/group_qc/iqm_outliers.tsv")
    if out_path.exists():
        out = pd.read_csv(out_path, sep="\t")
        counts = (
            out.groupby("subject")
            .size()
            .reset_index(name="n_outlier_flags")
            .sort_values("n_outlier_flags", ascending=False)
        )
        counts["publication_note"] = (
            "Exploratory within-dataset outlier flags (z>3 and/or Tukey IQR); "
            "not automatic exclusions"
        )
        counts.to_csv(TAB / "warning_outlier_flag_counts_by_subject.tsv", sep="\t", index=False)
        out.to_csv(TAB / "warning_iqm_outliers_full.tsv", sep="\t", index=False)


def main():
    df, src = load_iqms()
    print(f"Loaded IQMs from {src}  shape={df.shape}")
    for fn in [
        fig01_coverage_summary,
        fig02_coverage_progression,
        fig06_completeness_donut,
        fig08_missing_runs_panel,
        lambda: fig03_bold_quality(df),
        lambda: fig05b_bold_iqm_board(df),
        lambda: fig04_anat_quality(df),
        lambda: fig04b_t1w_iqm_board(df),
        lambda: fig04_anat_quality_by_protocol(df),
        lambda: fig05_motion_by_task(df),
        lambda: fig07_high_motion(df),
        lambda: fig09_pi_onepager(df),
    ]:
        res = fn()
        if res:
            if isinstance(res, list):
                for item in res:
                    print("wrote", item[1])
            else:
                print("wrote", res[1])
    write_warning_tables(df)
    print("tables written under", TAB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
