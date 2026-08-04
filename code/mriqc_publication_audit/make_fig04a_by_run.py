#!/usr/bin/env python3
"""Diagnose T1w_MPR run-01 vs run-02 IQM differences + regenerate Fig04a panels."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd

BIDS = Path("/home/alexrees/scratch/bids")
TAB = Path("/home/alexrees/scratch/reports/mriqc_publication_audit/tables")
FIG = Path("/home/alexrees/scratch/reports/mriqc_publication_audit/figures")
OUT = Path("/home/alexrees/scratch/reports/mriqc_publication_audit")

C = {
    "ink": "#1a1a1a",
    "muted": "#5c5c5c",
    "grid": "#e6e6e6",
    "ok": "#2a6f4e",
    "blue": "#2f5f8a",
    "warn": "#a65d16",
}


def style_ax(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(C["grid"])
    ax.spines["bottom"].set_color(C["grid"])
    ax.tick_params(colors=C["muted"])
    ax.grid(axis="y", color=C["grid"], linewidth=0.8, zorder=0)


def main() -> int:
    t = pd.read_csv(TAB / "t1w_iqm_by_protocol.tsv", sep="\t")
    mpr = t[t["protocol"] == "T1w_MPR"].copy()
    mpr["run"] = mpr["run"].astype(str).str.replace(r"^run-", "", regex=True)

    keys = [
        "ProtocolName",
        "SeriesDescription",
        "SequenceName",
        "ScanningSequence",
        "SequenceVariant",
        "RepetitionTime",
        "EchoTime",
        "FlipAngle",
        "InversionTime",
        "ReceiveCoilName",
        "PercentSampling",
        "PixelBandwidth",
        "ParallelReductionFactorInPlane",
        "PartialFourier",
        "ImageType",
        "ScanOptions",
        "PulseSequenceDetails",
        "BaseResolution",
        "ReconMatrixPE",
        "AcquisitionMatrixPE",
        "NonlinearGradientCorrection",
        "RawImage",
    ]

    rows = []
    for _, r in mpr.iterrows():
        fn = Path(str(r["filename"])).name
        stem = fn.replace(".nii.gz", "").replace(".json", "").replace(".html", "")
        sub = str(r["subject"])
        ses = str(r["session"])
        if not sub.startswith("sub-"):
            sub = f"sub-{sub}"
        if not ses.startswith("ses-"):
            ses = f"ses-{ses}"
        js = BIDS / sub / ses / "anat" / f"{stem}.json"
        nii = BIDS / sub / ses / "anat" / f"{stem}.nii.gz"
        meta = json.loads(js.read_text()) if js.is_file() else {}
        shape = zooms = None
        if nii.is_file():
            img = nib.load(str(nii))
            shape = tuple(img.shape)
            zooms = tuple(round(float(z), 3) for z in img.header.get_zooms()[:3])
        row = {k: meta.get(k) for k in keys}
        row.update(
            {
                "run": r["run"],
                "cnr": r["cnr"],
                "cjv": r["cjv"],
                "snr_total": r["snr_total"],
                "shape": str(shape),
                "zooms": str(zooms),
                "ImageType_str": str(meta.get("ImageType")),
                "subject": sub,
                "session": ses,
                "stem": stem,
            }
        )
        rows.append(row)
    df = pd.DataFrame(rows)
    print("n", len(df), df["run"].value_counts().to_dict())

    r1 = df[df["run"] == "1"]
    r2 = df[df["run"] == "2"]
    print("\n=== Differing metadata (run-01 vs run-02) ===")
    for k in keys + ["shape", "zooms", "ImageType_str"]:
        c1 = r1[k].astype(str).value_counts(dropna=False)
        c2 = r2[k].astype(str).value_counts(dropna=False)
        if dict(c1) != dict(c2):
            print(f"\n{k}:")
            print("  run-01:", list(c1.head(3).items()))
            print("  run-02:", list(c2.head(3).items()))

    pairs = []
    for (sub, ses), g in df.groupby(["subject", "session"]):
        a = g[g["run"] == "1"]
        b = g[g["run"] == "2"]
        if len(a) and len(b):
            pairs.append(
                {
                    "cnr1": a["cnr"].iloc[0],
                    "cnr2": b["cnr"].iloc[0],
                    "cjv1": a["cjv"].iloc[0],
                    "cjv2": b["cjv"].iloc[0],
                    "snr1": a["snr_total"].iloc[0],
                    "snr2": b["snr_total"].iloc[0],
                    "sd1": str(a["SeriesDescription"].iloc[0]),
                    "sd2": str(b["SeriesDescription"].iloc[0]),
                    "it1": a["ImageType_str"].iloc[0],
                    "it2": b["ImageType_str"].iloc[0],
                    "so1": str(a["ScanOptions"].iloc[0]),
                    "so2": str(b["ScanOptions"].iloc[0]),
                    "seq1": str(a["SequenceName"].iloc[0]),
                    "seq2": str(b["SequenceName"].iloc[0]),
                }
            )
    p = pd.DataFrame(pairs)
    print(f"\n=== Paired n={len(p)} ===")
    if len(p):
        print("median CNR", float(p["cnr1"].median()), float(p["cnr2"].median()))
        print("median CJV", float(p["cjv1"].median()), float(p["cjv2"].median()))
        print("median SNR", float(p["snr1"].median()), float(p["snr2"].median()))
        print("frac CNR2>CNR1", float((p["cnr2"] > p["cnr1"]).mean()))
        print(
            "SeriesDescription pairs:\n",
            p.groupby(["sd1", "sd2"]).size().sort_values(ascending=False).head(8),
        )
        print(
            "SequenceName pairs:\n",
            p.groupby(["seq1", "seq2"]).size().sort_values(ascending=False).head(8),
        )
        print(
            "ScanOptions pairs:\n",
            p.groupby(["so1", "so2"]).size().sort_values(ascending=False).head(8),
        )
        print(
            "ImageType pairs:\n",
            p.groupby(["it1", "it2"]).size().sort_values(ascending=False).head(8),
        )

    metrics = [
        ("cnr", "CNR", C["ok"]),
        ("cjv", "CJV (lower better)", C["blue"]),
        ("snr_total", "Total SNR", C["warn"]),
    ]
    for run, stem, title, subtitle in [
        (
            "1",
            "Fig04a1_T1w_MPR_run-01_cnr_cjv_snr",
            "MRIQC anatomical quality — T1w_MPR run-01",
            "Standard MPRAGE · first acquisition",
        ),
        (
            "2",
            "Fig04a2_T1w_MPR_run-02_cnr_cjv_snr",
            "MRIQC anatomical quality — T1w_MPR run-02",
            "Standard MPRAGE · second acquisition",
        ),
    ]:
        sub = mpr[mpr["run"] == run]
        fig, axes = plt.subplots(1, 3, figsize=(10, 3.8))
        for ax, (col, mtitle, color) in zip(axes, metrics):
            style_ax(ax)
            vals = sub[col].dropna().to_numpy()
            parts = ax.violinplot([vals], showmeans=False, showmedians=True, widths=0.7)
            for body in parts["bodies"]:
                body.set_facecolor(color)
                body.set_alpha(0.35)
                body.set_edgecolor(color)
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
        fig.text(0.5, 0.01, subtitle, ha="center", va="bottom", fontsize=8, color=C["muted"])
        fig.tight_layout()
        fig.savefig(FIG / f"{stem}.png", dpi=300, bbox_inches="tight")
        fig.savefig(FIG / f"{stem}.pdf", bbox_inches="tight")
        plt.close(fig)
        print("wrote", FIG / f"{stem}.png")

    fig, axes = plt.subplots(2, 3, figsize=(10.5, 7.2))
    for row_i, (run, row_title) in enumerate([("1", "run-01"), ("2", "run-02")]):
        sub = mpr[mpr["run"] == run]
        for col_i, (col, mtitle, color) in enumerate(metrics):
            ax = axes[row_i, col_i]
            style_ax(ax)
            vals = sub[col].dropna().to_numpy()
            parts = ax.violinplot([vals], showmeans=False, showmedians=True, widths=0.7)
            for body in parts["bodies"]:
                body.set_facecolor(color)
                body.set_alpha(0.35)
                body.set_edgecolor(color)
            for key in ("cmedians", "cbars", "cmins", "cmaxes"):
                if key in parts:
                    parts[key].set_color(C["ink"])
                    parts[key].set_linewidth(1.2)
            ax.set_xticks([1])
            ax.set_xticklabels([mtitle])
            med = float(np.median(vals))
            ax.set_title(f"{row_title}: {mtitle}")
            if col_i == 0:
                ax.set_ylabel(row_title, color=C["ink"])
            ax.text(
                1.32,
                med,
                f"med={med:.3g}\nn={len(vals)}",
                va="center",
                fontsize=8,
                color=C["muted"],
            )
    fig.suptitle(
        "MRIQC anatomical quality — T1w_MPR by run (run-01 vs run-02)",
        color=C["ink"],
        y=0.995,
    )
    fig.text(
        0.5,
        0.005,
        "Same ProtocolName (T1w_MPR); IQM shift is between acquisition repeats",
        ha="center",
        va="bottom",
        fontsize=8,
        color=C["muted"],
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    stem = "Fig04a_T1w_MPR_by_run_cnr_cjv_snr"
    fig.savefig(FIG / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)
    print("wrote", FIG / f"{stem}.png")

    md = OUT / "T1w_MPR_run01_vs_run02_IQM.md"
    it_pairs = (
        p.groupby(["it1", "it2"]).size().sort_values(ascending=False).head(5)
        if len(p)
        else None
    )
    frac = float((p["cnr2"] > p["cnr1"]).mean()) if len(p) else float("nan")
    lines = [
        "# Why T1w_MPR run-01 vs run-02 have different MRIQC IQMs",
        "",
        "Not FLAIR / not a different BIDS suffix: both runs are `ProtocolName=T1w_MPR` with suffix `T1w`.",
        "",
        f"Paired sessions with both runs: **{len(p)}**"
        + (f" (CNR higher on run-02 in **{frac:.0%}** of pairs)." if len(p) else "."),
        "",
        "| Run | n | CNR median | CJV median | SNR median |",
        "|---|---:|---:|---:|---:|",
        f"| run-01 | {len(r1)} | {r1['cnr'].median():.3f} | {r1['cjv'].median():.3f} | {r1['snr_total'].median():.3f} |",
        f"| run-02 | {len(r2)} | {r2['cnr'].median():.3f} | {r2['cjv'].median():.3f} | {r2['snr_total'].median():.3f} |",
        "",
    ]
    if len(p):
        lines += [
            f"Paired medians (n={len(p)}): CNR **{float(p['cnr1'].median()):.3f} vs {float(p['cnr2'].median()):.3f}**; "
            f"CJV **{float(p['cjv1'].median()):.3f} vs {float(p['cjv2'].median()):.3f}**; "
            f"SNR **{float(p['snr1'].median()):.3f} vs {float(p['snr2'].median()):.3f}**.",
            "",
        ]
    lines += [
        "## Root cause (metadata)",
        "",
        "Acquisition geometry and contrast parameters match across runs (same ProtocolName/SeriesDescription,",
        "SequenceName `*tfl3d1_16ns`, ScanOptions `IR\\\\WE`, TR/TE/FA/TI, shape `(208, 300, 320)`, zooms `0.8 mm`).",
        "",
        "The **systematic** difference is Siemens reconstruction flag **`NORM`** in `ImageType`:",
        "",
        "| Run | Typical `ImageType` |",
        "|---|---|",
        "| run-01 | `['ORIGINAL', 'PRIMARY', 'M', 'ND']` |",
        "| run-02 | `['ORIGINAL', 'PRIMARY', 'M', 'ND', 'NORM']` |",
        "",
        "`NORM` = Siemens **prescan normalize / coil-sensitivity intensity normalization**. "
        "That changes the intensity histogram, so MRIQC CNR/CJV/SNR shift even though the pulse-sequence recipe is unchanged.",
        "",
    ]
    if it_pairs is not None:
        lines += ["ImageType pair counts:", "", "```", str(it_pairs), "```", ""]
    lines += [
        "## Figures",
        "",
        "- `figures/Fig04a1_T1w_MPR_run-01_cnr_cjv_snr` — run-01 only",
        "- `figures/Fig04a2_T1w_MPR_run-02_cnr_cjv_snr` — run-02 only",
        "- `figures/Fig04a_T1w_MPR_by_run_cnr_cjv_snr` — 2-row panel",
        "",
        "Regenerate: `python3 code/mriqc_publication_audit/make_fig04a_by_run.py`",
        "",
    ]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
