#!/usr/bin/env python3
"""IQM-family robustness of the physical-acquisition MixedLM.

Main model (same for every subset):
  IQM ~ cohort + software_platform + age + sex + session + (1|subject_id)

software_platform (E11 vs XA30) is the acquisition_variable. Scanner,
coil, SoftwareVersions and reconstruction NORM/non-NORM are collinear
aliases in this selected table and are not entered together.

BH-FDR is applied within each IQM subset. IQMs are not quality scores.
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
    FAMILY_GROUP_ORDER,
    FDR_ALPHA,
    assert_unmodified,
    family_group,
    iqm_subsets,
    load_physical_acquisition_table,
    load_t1w_iqm_names,
    snapshot_protected,
    study_root_default,
)
from mriqc_iqm_physical_acq_models import (  # noqa: E402
    FULL_RHS,
    classify_family_findings,
    fdr_bh,
    finite,
    fit_mixed_iqm,
    import_stats,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.family_robustness")
SUBSET_ORDER = ["FULL_56", "CORE_QUALITY", "TISSUE_SENSITIVE"]


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


def per_iqm_class(
    iqm: str,
    q_full: float,
    q_core: float,
    q_tissue: float,
    overall: str,
) -> str:
    sig_full = finite(q_full) and q_full < FDR_ALPHA
    sig_core = finite(q_core) and q_core < FDR_ALPHA
    sig_tissue = finite(q_tissue) and q_tissue < FDR_ALPHA
    if not (sig_full or sig_core or sig_tissue):
        return "NOT_REPLICATED"
    if overall == "SINGLE_IQM_DRIVEN":
        return "SINGLE_IQM_DRIVEN"
    if sig_core and sig_tissue:
        return "ROBUST_ACROSS_FAMILIES"
    if sig_core or sig_tissue:
        if overall == "ROBUST_ACROSS_FAMILIES" and sig_full:
            return "ROBUST_ACROSS_FAMILIES"
        return "FAMILY_DEPENDENT"
    return "FAMILY_DEPENDENT"


def plot_heatmap(wide: pd.DataFrame, dest: Path) -> None:
    iqms = wide["IQM"].tolist()
    mat = np.column_stack([wide[f"neglog10_q_{s}"].to_numpy(dtype=float) for s in SUBSET_ORDER])
    fig_h = max(10.0, 0.22 * len(iqms) + 1.8)
    fig, ax = plt.subplots(figsize=(7.4, fig_h))
    masked = np.ma.masked_invalid(mat)
    cmap = plt.cm.YlOrRd.copy()
    cmap.set_bad("#E8E8E8")
    vmax = max(1.3, float(np.nanmax(mat)) if np.isfinite(mat).any() else 1.3)
    im = ax.imshow(masked, cmap=cmap, vmin=0.0, vmax=vmax, aspect="auto")
    ax.set_xticks(range(3), ["FULL_56", "CORE_QUALITY", "TISSUE_SENSITIVE"], rotation=20, ha="right")
    ax.set_yticks(range(len(iqms)), [f"{n}  [{family_group(n)}]" for n in iqms], fontsize=7)
    ax.set_title(
        "Physical-acq MixedLM cohort omnibus  −log10(q)\n"
        f"IQM ~ cohort + software_platform + age + sex + session + (1|subject)   * q<{FDR_ALPHA}"
    )
    for i, iqm in enumerate(iqms):
        for j, subset in enumerate(SUBSET_ORDER):
            q = wide.loc[wide["IQM"] == iqm, f"cohort_q_{subset}"].iloc[0]
            if not finite(q):
                ax.text(j, i, "n/a", ha="center", va="center", fontsize=6, color="#666666")
                continue
            mark = "*" if q < FDR_ALPHA else ""
            ax.text(j, i, f"{q:.3g}{mark}", ha="center", va="center", fontsize=6)
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04, label="−log10(q) cohort")
    fig.subplots_adjust(left=0.42, right=0.98, top=0.94, bottom=0.06)
    fig.savefig(dest, dpi=160)
    plt.close(fig)


def write_report(
    path: Path,
    subsets: dict[str, list[str]],
    summary: pd.DataFrame,
    overall_cohort: str,
    overall_acq: str,
    n_obs: int,
    n_subj: int,
) -> None:
    lines = [
        "Physical-acquisition IQM-family robustness",
        f"generated_utc: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Model (all subsets):",
        "  IQM ~ C(cohort, Treatment(Control)) + C(software_platform, Treatment(E11))",
        "        + age + C(sex) + C(session) + (1|subject_id)",
        "Acquisition variable: software_platform (E11=Prisma vs XA30=MAGNETOM Prisma).",
        "Not combined with scanner/coil/SoftwareVersions/is_norm: they partition the",
        "same 6 XA30 rows in this selected physical-acquisition table.",
        "BH-FDR is within each subset, separately for cohort and acquisition Wald tests.",
        "IQMs are not interpreted as pure image-quality scores.",
        "",
        f"N observations={n_obs}  N subjects={n_subj}",
        "",
        "Subsets (existing family taxonomy):",
    ]
    for name in SUBSET_ORDER:
        iqms = subsets[name]
        fams = sorted({family_group(x) for x in iqms})
        lines.append(f"  {name}: n={len(iqms)}  families={', '.join(fams)}")
    lines.append("")
    lines.append("Cohort omnibus (primary):")
    for name in SUBSET_ORDER:
        sub = summary.loc[summary["subset"] == name]
        n_sig = int((sub["cohort_q"] < FDR_ALPHA).sum())
        qmin = float(sub["cohort_q"].min()) if len(sub) else float("nan")
        top = sub.sort_values("cohort_q", kind="mergesort").head(5)
        lines.append(f"  {name}: significant IQMs={n_sig}/{len(sub)}  min q={qmin:.6g}")
        for _, row in top.iterrows():
            star = "*" if row["cohort_q"] < FDR_ALPHA else ""
            lines.append(
                f"    {row['IQM']} ({row['family_group']}): q={row['cohort_q']:.4g}{star}  "
                f"Glaucoma coef={row['glaucoma_coef']:.4g}"
            )
    lines.append("")
    lines.append("Acquisition (software_platform XA30 vs E11):")
    for name in SUBSET_ORDER:
        sub = summary.loc[summary["subset"] == name]
        n_sig = int((sub["acquisition_q"] < FDR_ALPHA).sum())
        qmin = float(sub["acquisition_q"].min()) if len(sub) else float("nan")
        top = sub.sort_values("acquisition_q", kind="mergesort").head(5)
        lines.append(f"  {name}: significant IQMs={n_sig}/{len(sub)}  min q={qmin:.6g}")
        for _, row in top.iterrows():
            lines.append(
                f"    {row['IQM']}: q={row['acquisition_q']:.4g}  XA30 coef={row['xa30_coef']:.4g}"
            )
    lines.append("")
    lines.append(f"Cohort finding class: {overall_cohort}")
    lines.append(f"Acquisition finding class: {overall_acq}")
    lines.append(
        "ROBUST_ACROSS_FAMILIES = FDR hits in both CORE_QUALITY and TISSUE_SENSITIVE. "
        "FAMILY_DEPENDENT = hits confined to one family subset. "
        "SINGLE_IQM_DRIVEN = a single IQM. NOT_REPLICATED = no FDR hit."
    )
    lines.append(
        "The cohort label does not mean a broad quality-metric effect: CORE_QUALITY "
        "contributes one smoothness IQM (fwhm_y); TISSUE_SENSITIVE contributes "
        "intensity summaries. Acquisition FDR hits are confined to FWHM (CORE_QUALITY)."
    )
    lines.append("")
    lines.append("Future anatomy extension (not implemented):")
    lines.append("  IQM ~ acquisition + anatomy + cohort + age + sex + session + (1|subject_id)")
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
    subsets = iqm_subsets(iqms)
    if len(subsets["FULL_56"]) != 56:
        fail(f"FULL_56 has {len(subsets['FULL_56'])} IQMs, expected 56.")
    if not subsets["CORE_QUALITY"] or not subsets["TISSUE_SENSITIVE"]:
        fail("CORE_QUALITY or TISSUE_SENSITIVE is empty.")

    cache: dict[str, dict] = {}
    rows = []
    for subset in SUBSET_ORDER:
        LOGGER.info("Fitting subset %s n_iqm=%d", subset, len(subsets[subset]))
        fitted = []
        for iqm in subsets[subset]:
            if iqm not in cache:
                cache[iqm] = fit_mixed_iqm(df, iqm, FULL_RHS, stats)
            rec = dict(cache[iqm])
            rec["subset"] = subset
            rec["family_group"] = family_group(iqm)
            rec["in_core_quality"] = iqm in subsets["CORE_QUALITY"]
            rec["in_tissue_sensitive"] = iqm in subsets["TISSUE_SENSITIVE"]
            fitted.append(rec)
        cq = fdr_bh([r["cohort_p"] for r in fitted], stats["multipletests"])
        aq = fdr_bh([r["acquisition_p"] for r in fitted], stats["multipletests"])
        for rec, qi, qj in zip(fitted, cq, aq):
            rec["cohort_q"] = qi
            rec["acquisition_q"] = qj
            rec["IQM"] = rec["iqm"]
            rows.append(rec)

    long_df = pd.DataFrame(rows)
    full_hits = long_df.loc[
        (long_df["subset"] == "FULL_56") & (long_df["cohort_q"] < FDR_ALPHA), "IQM"
    ].astype(str).tolist()
    core_hits = long_df.loc[
        (long_df["subset"] == "CORE_QUALITY") & (long_df["cohort_q"] < FDR_ALPHA), "IQM"
    ].astype(str).tolist()
    tissue_hits = long_df.loc[
        (long_df["subset"] == "TISSUE_SENSITIVE") & (long_df["cohort_q"] < FDR_ALPHA), "IQM"
    ].astype(str).tolist()
    acq_full = long_df.loc[
        (long_df["subset"] == "FULL_56") & (long_df["acquisition_q"] < FDR_ALPHA), "IQM"
    ].astype(str).tolist()
    acq_core = long_df.loc[
        (long_df["subset"] == "CORE_QUALITY") & (long_df["acquisition_q"] < FDR_ALPHA), "IQM"
    ].astype(str).tolist()
    acq_tissue = long_df.loc[
        (long_df["subset"] == "TISSUE_SENSITIVE") & (long_df["acquisition_q"] < FDR_ALPHA), "IQM"
    ].astype(str).tolist()
    overall_cohort = classify_family_findings(full_hits, core_hits, tissue_hits)
    overall_acq = classify_family_findings(acq_full, acq_core, acq_tissue)

    qmap = {}
    for subset in SUBSET_ORDER:
        sub = long_df.loc[long_df["subset"] == subset].set_index("IQM")
        qmap[subset] = sub
    class_rows = []
    for iqm in iqms:
        q_full = float(qmap["FULL_56"].loc[iqm, "cohort_q"])
        q_core = (
            float(qmap["CORE_QUALITY"].loc[iqm, "cohort_q"])
            if iqm in qmap["CORE_QUALITY"].index
            else float("nan")
        )
        q_tissue = (
            float(qmap["TISSUE_SENSITIVE"].loc[iqm, "cohort_q"])
            if iqm in qmap["TISSUE_SENSITIVE"].index
            else float("nan")
        )
        class_rows.append(
            {
                "IQM": iqm,
                "finding_class_cohort": per_iqm_class(iqm, q_full, q_core, q_tissue, overall_cohort),
            }
        )
    class_df = pd.DataFrame(class_rows)
    long_df = long_df.merge(class_df, on="IQM", how="left")
    long_df["overall_cohort_finding"] = overall_cohort
    long_df["overall_acquisition_finding"] = overall_acq
    out_cols = [
        "subset",
        "IQM",
        "family_group",
        "in_core_quality",
        "in_tissue_sensitive",
        "n_obs",
        "n_subjects",
        "converged",
        "status",
        "cohort_stat",
        "cohort_p",
        "cohort_q",
        "glaucoma_coef",
        "glaucoma_p",
        "on_coef",
        "ton_coef",
        "acquisition_stat",
        "acquisition_p",
        "acquisition_q",
        "xa30_coef",
        "xa30_p",
        "r2_marginal",
        "r2_conditional",
        "finding_class_cohort",
        "overall_cohort_finding",
        "overall_acquisition_finding",
        "formula",
    ]
    long_df[out_cols].to_csv(
        args.out_dir / "iqm_family_robustness_results.tsv",
        sep="\t",
        index=False,
        float_format="%.10g",
    )

    wide_rows = []
    for iqm in sorted(iqms, key=lambda x: (FAMILY_GROUP_ORDER.index(family_group(x)), x)):
        rec = {"IQM": iqm, "family_group": family_group(iqm)}
        for subset in SUBSET_ORDER:
            if iqm in qmap[subset].index:
                q = float(qmap[subset].loc[iqm, "cohort_q"])
                rec[f"cohort_q_{subset}"] = q
                rec[f"neglog10_q_{subset}"] = -np.log10(q) if finite(q) and q > 0 else float("nan")
            else:
                rec[f"cohort_q_{subset}"] = float("nan")
                rec[f"neglog10_q_{subset}"] = float("nan")
        wide_rows.append(rec)
    wide = pd.DataFrame(wide_rows)
    plot_heatmap(wide, args.out_dir / "iqm_family_robustness_heatmap.png")
    write_report(
        args.out_dir / "iqm_family_robustness_report.txt",
        subsets,
        long_df,
        overall_cohort,
        overall_acq,
        n_obs=len(df),
        n_subj=int(df["subject_id"].nunique()),
    )
    assert_unmodified(before)
    print("cohort class:", overall_cohort)
    print("acquisition class:", overall_acq)
    print("FULL cohort FDR:", ", ".join(full_hits) or "none")
    print("CORE cohort FDR:", ", ".join(core_hits) or "none")
    print("TISSUE cohort FDR:", ", ".join(tissue_hits) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
