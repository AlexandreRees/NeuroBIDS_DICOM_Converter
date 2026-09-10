#!/usr/bin/env python3
"""Descriptive NORM vs non-NORM IQM differences on paired reconstructions.

Pairs are not treated as independent acquisitions. No inferential claim
that one reconstruction is better image quality.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, iqm_family, require_file, to_numeric_iqm  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    FAMILY_GROUP_ORDER,
    assert_unmodified,
    family_group,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.norm")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study-root", type=Path, default=None)
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.clean = root / "metadata" / "mriqc_iqm_clean.tsv"
    args.audit = qc / "t1w_reconstruction_audit.tsv"
    args.loadings = qc / "pca_T1w_loadings.tsv"
    args.out_dir = qc
    return args


def configure_logging():
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(h)


def main(argv=None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    clean = pd.read_csv(args.clean, sep="\t")
    audit = pd.read_csv(args.audit, sep="\t")
    iqms = pd.read_csv(args.loadings, sep="\t")["iqm"].astype(str).tolist()
    t1 = clean.loc[clean["sequence_group"].astype(str) == "T1w"].copy()
    pairs = audit.loc[audit["session_pattern"].astype(str) == "PAIRED_NORM_NON_NORM"].copy()
    n_sessions = pairs.groupby(["subject", "session"]).ngroups
    rows = []
    for (subject, session), g in pairs.groupby(["subject", "session"]):
        norm = g.loc[g["NORM_status"] == "NORM"]
        non = g.loc[g["NORM_status"] == "non-NORM"]
        if len(norm) != 1 or len(non) != 1:
            fail(f"{subject} {session}: expected 1 NORM and 1 non-NORM, found {len(norm)}/{len(non)}")
        n_row = t1.loc[t1["bids_name"] == norm.iloc[0]["bids_name"]].iloc[0]
        u_row = t1.loc[t1["bids_name"] == non.iloc[0]["bids_name"]].iloc[0]
        rec = {"subject_id": subject, "session": session}
        for iqm in iqms:
            rec[iqm] = float(to_numeric_iqm(pd.Series([n_row[iqm]])).iloc[0] - to_numeric_iqm(pd.Series([u_row[iqm]])).iloc[0])
        rows.append(rec)
    diffs = pd.DataFrame(rows)
    summary = []
    for iqm in iqms:
        d = diffs[iqm].to_numpy(dtype=float)
        # paired values for correlation
        paired_r = []
        for (subject, session), g in pairs.groupby(["subject", "session"]):
            n_row = t1.loc[t1["bids_name"] == g.loc[g["NORM_status"]=="NORM"].iloc[0]["bids_name"]].iloc[0]
            u_row = t1.loc[t1["bids_name"] == g.loc[g["NORM_status"]=="non-NORM"].iloc[0]["bids_name"]].iloc[0]
            paired_r.append((float(to_numeric_iqm(pd.Series([n_row[iqm]])).iloc[0]),
                             float(to_numeric_iqm(pd.Series([u_row[iqm]])).iloc[0])))
        nv = np.array([a for a, b in paired_r], dtype=float)
        uv = np.array([b for a, b in paired_r], dtype=float)
        if np.std(nv) == 0 or np.std(uv) == 0:
            r = float("nan")
        else:
            r = float(np.corrcoef(nv, uv)[0, 1])
        summary.append(
            {
                "IQM": iqm,
                "iqm_family": iqm_family(iqm),
                "family_group": family_group(iqm),
                "n_pairs": int(len(d)),
                "mean_NORM_minus_nonNORM": float(np.nanmean(d)),
                "sd_difference": float(np.nanstd(d, ddof=1)),
                "median_difference": float(np.nanmedian(d)),
                "pearson_paired": r,
            }
        )
    sumdf = pd.DataFrame(summary).sort_values("IQM")
    out = args.out_dir
    sumdf.to_csv(out / "norm_vs_non_norm_sensitivity.tsv", sep="\t", index=False, float_format="%.10g")

    fam_order = FAMILY_GROUP_ORDER
    fig, ax = plt.subplots(figsize=(11.0, max(6.0, 0.18 * len(iqms) + 1.2)))
    y = np.arange(len(sumdf))
    colors = [{"signal / SNR": "#4C78A8", "contrast": "#F58518", "intensity": "#54A24B",
               "homogeneity / bias field": "#E45756", "artifact": "#B279A2",
               "entropy / information": "#72B7B2", "morphology / tissue": "#FF9DA6",
               "smoothness / sharpness": "#9D755D"}.get(g, "#BAB0AC") for g in sumdf["family_group"]]
    ax.barh(y, sumdf["mean_NORM_minus_nonNORM"], color=colors)
    ax.set_yticks(y, sumdf["IQM"], fontsize=6)
    ax.axvline(0, color="black", lw=0.7)
    ax.set_xlabel("Mean (NORM − non-NORM)")
    ax.set_title(f"Paired reconstruction IQM differences (n_pairs={n_sessions})\nnot independent scans; not quality grades")
    fig.tight_layout()
    fig.savefig(out / "norm_vs_non_norm_iqm_difference.png", dpi=130)
    fig.savefig(out / "norm_vs_non_norm_iqm_difference.pdf")
    plt.close(fig)

    # heatmap of standardized differences (z of paired delta)
    z = diffs[iqms].apply(lambda s: (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) else s * 0)
    fig, ax = plt.subplots(figsize=(12.5, 5.5))
    im = ax.imshow(z.to_numpy(dtype=float).T, aspect="auto", cmap="RdBu_r", vmin=-3, vmax=3, interpolation="nearest")
    ax.set_yticks(range(len(iqms)), iqms, fontsize=5)
    ax.set_xlabel("paired session (NORM − non-NORM)")
    ax.set_title("Paired reconstruction differences (column-z of Δ IQM)")
    fig.colorbar(im, ax=ax, fraction=0.02, pad=0.02, label="z(Δ)")
    fig.tight_layout()
    fig.savefig(out / "norm_vs_non_norm_difference_heatmap.png", dpi=130)
    fig.savefig(out / "norm_vs_non_norm_difference_heatmap.pdf")
    plt.close(fig)

    by_fam = sumdf.groupby("family_group", dropna=False)["mean_NORM_minus_nonNORM"].apply(lambda s: float(s.abs().mean()))
    lines = [
        "NORM vs non-NORM reconstruction sensitivity (descriptive)",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"n paired sessions (NORM+non-NORM): {n_sessions}",
        "These are two reconstructions of the same scan, not independent acquisitions.",
        "Differences are not quality grades.",
        "",
        "Mean |paired difference| by IQM family:",
    ]
    for fam in fam_order:
        if fam in by_fam.index:
            lines.append(f"  {fam}: {by_fam.loc[fam]:.6g}")
    top = sumdf.reindex(sumdf["mean_NORM_minus_nonNORM"].abs().sort_values(ascending=False).index).head(8)
    lines.append("")
    lines.append("Largest |mean Δ| IQMs:")
    for _, r in top.iterrows():
        lines.append(f"  {r['IQM']} ({r['family_group']}): mean Δ={r['mean_NORM_minus_nonNORM']:.6g}  paired r={r['pearson_paired']:.3f}")
    lines.append("")
    lines.append(
        "Intensity, bias-field (inu_*), and contrast IQMs are expected to move with "
        "Prescan Normalize. SNR/CNR often follow intensity scaling. Smoothness and "
        "morphology/tissue IQMs typically change less if geometry is shared."
    )
    lines.append("No hypothesis tests were used as discovery claims.")
    lines.append("")
    (out / "norm_vs_non_norm_sensitivity_report.txt").write_text("\n".join(lines), encoding="utf-8")
    assert_unmodified(before)
    print(f"NORM/non-NORM pairs analyzed: {n_sessions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
