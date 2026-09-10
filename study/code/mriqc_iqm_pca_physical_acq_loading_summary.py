#!/usr/bin/env python3
"""PC1–PC10 loading summary for the physical-acquisition T1w PCA.

Reads pca_physical_acq_loadings/variance only. Does not modify original PCA.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, iqm_family, require_file  # noqa: E402
from mriqc_iqm_pca_loading_summary import FAMILY_PHRASE, interpretation  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    FAMILY_COLORS,
    FAMILY_GROUP_ORDER,
    assert_unmodified,
    family_group,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.loading")
PC_NAMES = [f"PC{i}" for i in range(1, 11)]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study-root", type=Path, default=None)
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.loadings = qc / "pca_physical_acq_loadings.tsv"
    args.variance = qc / "pca_physical_acq_variance.tsv"
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
    require_file(args.loadings, "physical-acq loadings")
    require_file(args.variance, "physical-acq variance")
    loadings = pd.read_csv(args.loadings, sep="\t").set_index("iqm")
    variance = pd.read_csv(args.variance, sep="\t").set_index("component")
    tsv_rows = []
    txt: list[str] = [
        "T1w MRIQC IQM PCA — physical-acquisition loading summary (PC1–PC10)",
        "",
        "Each PC is a covariance pattern among IQMs, not a measure of image quality.",
        "Family taxonomy matches the original T1w PCA loading summary.",
        "",
    ]
    recap = []
    fam_rows = []
    for pc in PC_NAMES:
        vec = pd.to_numeric(loadings[pc], errors="coerce")
        contrib = (vec * vec) / float((vec * vec).sum())
        order = vec.abs().sort_values(ascending=False).index.tolist()
        var_ratio = float(variance.loc[pc, "explained_variance_ratio"])
        fam_share = {name: 0.0 for name in FAMILY_GROUP_ORDER}
        for iqm in vec.index:
            fam_share[family_group(str(iqm))] += float(contrib.loc[iqm])
        for grp, share in fam_share.items():
            fam_rows.append({"pc": pc, "family_group": grp, "contribution": share, "contribution_pct": 100 * share})
        ranked_fam = sorted(
            [(g, 100 * s) for g, s in fam_share.items() if g != "other" and s > 0],
            key=lambda x: -x[1],
        )
        dominant = ranked_fam[0][0]
        top_iqms = order[:10]
        top5 = float(sum(contrib.loc[i] for i in order[:5]))
        top10 = float(sum(contrib.loc[i] for i in order[:10]))
        recap.append((pc, var_ratio, dominant, top_iqms[0], top10))
        txt.append("=" * 78)
        txt.append(pc)
        txt.append(f"Variance explained: {100*var_ratio:.2f}%")
        txt.append(f"Dominant family: {dominant} ({ranked_fam[0][1]:.1f}% via squared loadings)")
        txt.append(f"Top-5 IQM concentration: {100*top5:.1f}%")
        txt.append(f"Top-10 IQM concentration: {100*top10:.1f}%")
        txt.append("")
        txt.append("Top 10 IQMs by absolute loading:")
        for rank, iqm in enumerate(top_iqms, start=1):
            loading = float(vec.loc[iqm])
            sign = "+" if loading > 0 else "-"
            fam = iqm_family(str(iqm))
            txt.append(f"  {rank:>4}  {iqm:<22}  {sign}{abs(loading):.6f}  {fam}")
            tsv_rows.append(
                {
                    "PC": pc,
                    "variance_explained": var_ratio,
                    "rank": rank,
                    "IQM": iqm,
                    "loading": loading,
                    "abs_loading": abs(loading),
                    "family": fam,
                }
            )
        txt.append("")
        txt.append("Interpretation:")
        txt.append(f"  {interpretation(pc, dominant, ranked_fam, top_iqms)}")
        txt.append("  This describes covariance among IQMs, not an image-quality score.")
        txt.append("")
    txt.append("=" * 78)
    txt.append("Summary (PC1–PC10)")
    txt.append(f"{'PC':<5}  {'var%':>7}  {'dominant family':<28}  {'leading IQM':<22}  {'top-10':>8}")
    for pc, var_ratio, dom, lead, t10 in recap:
        txt.append(f"{pc:<5}  {100*var_ratio:6.2f}%  {dom:<28}  {lead:<22}  {100*t10:6.1f}%")
    txt.append("")
    out = args.out_dir
    pd.DataFrame(tsv_rows).to_csv(out / "pca_physical_acq_loading_summary.tsv", sep="\t", index=False, float_format="%.10g")
    (out / "pca_physical_acq_loading_summary.txt").write_text("\n".join(txt), encoding="utf-8")

    fam = pd.DataFrame(fam_rows)
    pivot = fam.pivot(index="pc", columns="family_group", values="contribution").reindex(index=PC_NAMES, columns=FAMILY_GROUP_ORDER).fillna(0)
    fig, ax = plt.subplots(figsize=(11.2, 5.8))
    bottoms = np.zeros(len(PC_NAMES))
    x = np.arange(len(PC_NAMES))
    for fam_name in FAMILY_GROUP_ORDER:
        vals = pivot[fam_name].to_numpy(dtype=float)
        if np.allclose(vals, 0):
            continue
        ax.bar(x, vals, bottom=bottoms, label=fam_name, color=FAMILY_COLORS.get(fam_name, "#BAB0AC"), width=0.78)
        bottoms = bottoms + vals
    ax.set_xticks(x, PC_NAMES)
    ax.set_ylabel("Share of PC variance (sum of loading²)")
    ax.set_title("Physical-acquisition T1w PCA: IQM family contributions")
    ax.legend(loc="upper right", fontsize=8, frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(out / "pca_physical_acq_family_contributions.png", dpi=130)
    fig.savefig(out / "pca_physical_acq_family_contributions.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(2, 5, figsize=(14.5, 6.4))
    for ax, pc in zip(axes.ravel(), PC_NAMES):
        vec = pd.to_numeric(loadings[pc], errors="coerce")
        top = vec.abs().sort_values(ascending=False).head(10)
        signed = vec.loc[top.index]
        colors = ["#4C78A8" if v >= 0 else "#E45756" for v in signed]
        ax.barh(range(len(signed))[::-1], signed.values[::-1], color=colors[::-1])
        ax.set_yticks(range(len(signed))[::-1], list(signed.index[::-1]), fontsize=6)
        ax.set_title(pc, fontsize=9)
        ax.axvline(0, color="black", lw=0.6)
    fig.suptitle("Physical-acq PCA top 10 |loadings| (PC1–PC10)")
    fig.tight_layout()
    fig.savefig(out / "pca_physical_acq_top_loadings.png", dpi=130)
    fig.savefig(out / "pca_physical_acq_top_loadings.pdf")
    plt.close(fig)
    LOGGER.info("Wrote physical-acq loading summary")
    assert_unmodified(before)
    print("physical-acq loading summary written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
