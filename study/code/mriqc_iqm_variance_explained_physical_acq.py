#!/usr/bin/env python3
"""Mixed-model explained variation: acquisition vs cohort (physical-acquisition).

For each of the 56 T1w IQMs:

  Acquisition: IQM ~ software_platform + age + sex + session + (1|subject_id)
  Cohort:      IQM ~ cohort + age + sex + session + (1|subject_id)
  Full:        IQM ~ cohort + software_platform + age + sex + session + (1|subject_id)

Primary measure: Nakagawa marginal R² (fixed-effect variance share).
Conditional R² is reported separately. These are model-explained variation,
not causal variance, and not 'biology R²' (FreeSurfer anatomy is not included).
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

from mriqc_iqm_lib import fail  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    FAMILY_COLORS,
    FAMILY_GROUP_ORDER,
    assert_unmodified,
    family_group,
    load_physical_acquisition_table,
    load_t1w_iqm_names,
    snapshot_protected,
    study_root_default,
)
from mriqc_iqm_physical_acq_models import (  # noqa: E402
    ACQUISITION_RHS,
    COHORT_ONLY_RHS,
    FULL_RHS,
    fit_mixed_iqm,
    import_stats,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.variance")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study-root", type=Path, default=None)
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.phys = root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    args.loadings = qc / "pca_physical_acq_loadings.tsv"
    args.out_dir = qc
    return args


def configure_logging():
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    LOGGER.addHandler(h)


def plot_r2_heatmap(df: pd.DataFrame, dest: Path) -> None:
    order = sorted(df["IQM"].tolist(), key=lambda x: (FAMILY_GROUP_ORDER.index(family_group(x)), x))
    work = df.set_index("IQM").loc[order]
    mat = work[["R2_acquisition", "R2_cohort", "R2_full"]].to_numpy(dtype=float)
    fig_h = max(10.0, 0.22 * len(order) + 1.6)
    fig, ax = plt.subplots(figsize=(6.6, fig_h))
    im = ax.imshow(mat, cmap="viridis", vmin=0.0, vmax=max(0.35, float(np.nanmax(mat))), aspect="auto")
    ax.set_xticks(range(3), ["Acquisition R²", "Cohort R²", "Full R²"])
    ax.set_yticks(range(len(order)), [f"{n}  [{family_group(n)}]" for n in order], fontsize=7)
    ax.set_title("Nakagawa marginal R²  (model-explained variation, not causal)")
    for i in range(mat.shape[0]):
        for j in range(3):
            val = mat[i, j]
            if np.isfinite(val):
                ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=6, color="white" if val > 0.18 else "black")
    fig.colorbar(im, ax=ax, fraction=0.04, pad=0.04, label="marginal R²")
    fig.subplots_adjust(left=0.42, right=0.96, top=0.95, bottom=0.05)
    fig.savefig(dest, dpi=160)
    plt.close(fig)


def plot_scatter(df: pd.DataFrame, dest: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    for fam in FAMILY_GROUP_ORDER:
        sub = df.loc[df["family_group"] == fam]
        if sub.empty:
            continue
        ax.scatter(
            sub["R2_acquisition"],
            sub["R2_cohort"],
            s=36,
            c=FAMILY_COLORS.get(fam, "#BAB0AC"),
            label=fam,
            edgecolors="white",
            linewidths=0.4,
            zorder=3,
        )
    lim = max(
        0.2,
        float(np.nanmax(df[["R2_acquisition", "R2_cohort"]].to_numpy())) * 1.08,
    )
    ax.plot([0, lim], [0, lim], color="#888888", lw=0.8, ls="--")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("Acquisition marginal R² (software_platform + covariates)")
    ax.set_ylabel("Cohort marginal R² (cohort + covariates)")
    ax.set_title("Acquisition vs cohort model-explained variation\n(not biology; anatomy not included)")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(dest, dpi=160)
    plt.close(fig)


def write_report(path: Path, df: pd.DataFrame, n_obs: int, n_subj: int) -> None:
    def top(col: str, n: int = 8) -> pd.DataFrame:
        return df.sort_values(col, ascending=False, kind="mergesort").head(n)

    lines = [
        "Physical-acquisition IQM explained-variation report",
        f"generated_utc: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Models (MixedLM, random intercept subject_id):",
        "  Acquisition: IQM ~ software_platform + age + sex + session + (1|subject_id)",
        "  Cohort:      IQM ~ cohort + age + sex + session + (1|subject_id)",
        "  Full:        IQM ~ cohort + software_platform + age + sex + session + (1|subject_id)",
        "",
        "Acquisition variable: software_platform only (E11 vs XA30).",
        "SAR/TxRefAmp were not combined with software_platform: 6/133 missing",
        "(exactly the XA30 rows) and they are near-unique per scan.",
        "is_norm is collinear with software_platform in this selected table",
        "(all XA30 rows are the 6 non-NORM reconstructions without a NORM pair).",
        "",
        "R² is Nakagawa & Schielzeth marginal R² (fixed-effect share of variation).",
        "Conditional R² (fixed + subject intercept) is reported separately.",
        "These quantities are model-explained variation, not causal variance.",
        "Cohort R² is NOT biology R²: FreeSurfer anatomy is not in the model.",
        "",
        f"N observations={n_obs}  N subjects={n_subj}  N IQMs={len(df)}",
        f"mean R2_acquisition={df['R2_acquisition'].mean():.4f}  "
        f"median={df['R2_acquisition'].median():.4f}",
        f"mean R2_cohort={df['R2_cohort'].mean():.4f}  "
        f"median={df['R2_cohort'].median():.4f}",
        f"mean R2_full={df['R2_full'].mean():.4f}  "
        f"median={df['R2_full'].median():.4f}",
        f"IQMs with R2_acquisition > R2_cohort: "
        f"{int((df['R2_acquisition'] > df['R2_cohort']).sum())}/{len(df)}",
        f"IQMs with R2_cohort > R2_acquisition: "
        f"{int((df['R2_cohort'] > df['R2_acquisition']).sum())}/{len(df)}",
        "",
        "Highest acquisition R²:",
    ]
    for _, r in top("R2_acquisition").iterrows():
        lines.append(f"  {r['IQM']} ({r['family_group']}): {r['R2_acquisition']:.4f}")
    lines.append("Highest cohort R²:")
    for _, r in top("R2_cohort").iterrows():
        lines.append(f"  {r['IQM']} ({r['family_group']}): {r['R2_cohort']:.4f}")
    lines.append("")
    lines.append("By family (mean marginal R²):")
    for fam in FAMILY_GROUP_ORDER:
        sub = df.loc[df["family_group"] == fam]
        if sub.empty:
            continue
        lines.append(
            f"  {fam}: acq={sub['R2_acquisition'].mean():.3f}  "
            f"cohort={sub['R2_cohort'].mean():.3f}  full={sub['R2_full'].mean():.3f}  n={len(sub)}"
        )
    lines.append("")
    lines.append("Planned FreeSurfer extension (not implemented):")
    lines.append("  IQM ~ acquisition + anatomy + cohort + age + sex + session + (1|subject_id)")
    lines.append("  compare R2_acquisition / R2_anatomy / R2_cohort / R2_full")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    stats = import_stats()
    if not stats["ok"]:
        fail("scipy+statsmodels required: " + "; ".join(stats["missing"]))
    iqms = load_t1w_iqm_names(args.loadings)
    df = load_physical_acquisition_table(args.phys, iqms)
    rows = []
    for iqm in iqms:
        LOGGER.info("Variance models for %s", iqm)
        acq = fit_mixed_iqm(df, iqm, ACQUISITION_RHS, stats)
        coh = fit_mixed_iqm(df, iqm, COHORT_ONLY_RHS, stats)
        full = fit_mixed_iqm(df, iqm, FULL_RHS, stats)
        rows.append(
            {
                "IQM": iqm,
                "family_group": family_group(iqm),
                "R2_acquisition": acq["r2_marginal"],
                "R2_cohort": coh["r2_marginal"],
                "R2_full": full["r2_marginal"],
                "R2_conditional_acquisition": acq["r2_conditional"],
                "R2_conditional_cohort": coh["r2_conditional"],
                "R2_conditional_full": full["r2_conditional"],
                "acq_converged": acq["converged"],
                "cohort_converged": coh["converged"],
                "full_converged": full["converged"],
                "acq_status": acq["status"],
                "cohort_status": coh["status"],
                "full_status": full["status"],
                "n_obs": full["n_obs"],
                "n_subjects": full["n_subjects"],
                "acquisition_p": acq["acquisition_p"],
                "cohort_p": coh["cohort_p"],
                "full_acquisition_p": full["acquisition_p"],
                "full_cohort_p": full["cohort_p"],
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(
        args.out_dir / "iqm_variance_explained_physical_acq.tsv",
        sep="\t",
        index=False,
        float_format="%.10g",
    )
    plot_r2_heatmap(out, args.out_dir / "iqm_variance_explained_plot.png")
    plot_scatter(out, args.out_dir / "iqm_acquisition_vs_cohort_r2.png")
    write_report(
        args.out_dir / "iqm_variance_explained_physical_acq_report.txt",
        out,
        n_obs=len(df),
        n_subj=int(df["subject_id"].nunique()),
    )
    assert_unmodified(before)
    print(
        "mean R2 acq/cohort/full:",
        f"{out['R2_acquisition'].mean():.3f}",
        f"{out['R2_cohort'].mean():.3f}",
        f"{out['R2_full'].mean():.3f}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
