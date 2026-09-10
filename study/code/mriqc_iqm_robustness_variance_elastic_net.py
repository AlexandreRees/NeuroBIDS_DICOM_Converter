#!/usr/bin/env python3
"""Run physical-acquisition robustness, variance, and Elastic Net, then summarize.

Does not modify previous MRIQC/PCA/cohort/longitudinal tables.
Uses only study/metadata/mriqc_iqm_physical_acquisition.tsv as the IQM source.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, require_file  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    FDR_ALPHA,
    assert_unmodified,
    family_group,
    snapshot_protected,
    study_root_default,
)
import mriqc_iqm_elastic_net_physical_acq as enet  # noqa: E402
import mriqc_iqm_family_robustness_physical_acq as fam  # noqa: E402
import mriqc_iqm_variance_explained_physical_acq as var  # noqa: E402

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.rve")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study-root", type=Path, default=None)
    p.add_argument("--skip-family", action="store_true")
    p.add_argument("--skip-variance", action="store_true")
    p.add_argument("--skip-elastic-net", action="store_true")
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    args.study_root = root
    args.out_dir = root / "qc_reports" / "mriqc_iqm"
    return args


def configure_logging():
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    LOGGER.addHandler(h)


def _hits(df: pd.DataFrame, subset: str, col: str) -> list[str]:
    sub = df.loc[df["subset"] == subset]
    return sub.loc[sub[col] < FDR_ALPHA, "IQM"].astype(str).tolist()


def write_summary(qc: Path) -> None:
    fam_path = qc / "iqm_family_robustness_results.tsv"
    var_path = qc / "iqm_variance_explained_physical_acq.tsv"
    en_path = qc / "elastic_net_subject_grouped_results.tsv"
    stab_path = qc / "elastic_net_coefficient_stability.tsv"
    for path in (fam_path, var_path, en_path, stab_path):
        require_file(path, path.name)
    fam_df = pd.read_csv(fam_path, sep="\t")
    var_df = pd.read_csv(var_path, sep="\t")
    en_df = pd.read_csv(en_path, sep="\t")
    stab = pd.read_csv(stab_path, sep="\t")

    overall_c = str(fam_df["overall_cohort_finding"].iloc[0])
    overall_a = str(fam_df["overall_acquisition_finding"].iloc[0])
    full_c = _hits(fam_df, "FULL_56", "cohort_q")
    core_c = _hits(fam_df, "CORE_QUALITY", "cohort_q")
    tissue_c = _hits(fam_df, "TISSUE_SENSITIVE", "cohort_q")
    full_a = _hits(fam_df, "FULL_56", "acquisition_q")
    core_a = _hits(fam_df, "CORE_QUALITY", "acquisition_q")
    tissue_a = _hits(fam_df, "TISSUE_SENSITIVE", "acquisition_q")

    oof = en_df.loc[en_df["split"].astype(str) == "oof_pooled"].iloc[0]
    folds = en_df.loc[en_df["split"].astype(str).str.startswith("fold_")]
    top_coef = (
        stab.assign(abs_mean=stab["mean_coefficient"].abs())
        .sort_values("abs_mean", ascending=False, kind="mergesort")
        .head(8)
    )
    stable = stab.loc[(stab["nonzero_fraction"] >= 0.8) & (stab["sign_consistency"] >= 0.8), "IQM"]
    mixed_glaucoma = set(full_c)
    pred_iqms = set(top_coef["IQM"].astype(str))
    overlap = sorted(mixed_glaucoma & pred_iqms)

    lines = [
        "Physical-acquisition robustness, variance and Elastic Net — summary",
        f"generated_utc: {datetime.now(timezone.utc).isoformat()}",
        "Source table: study/metadata/mriqc_iqm_physical_acquisition.tsv (~133 rows, 56 IQMs).",
        "Previous 264-row analyses, PCA, MRIQC and FreeSurfer were not rerun or overwritten.",
        "NORM/non-NORM remains a separate sensitivity analysis.",
        "",
        "1. IQM-family robustness",
        f"  Model: IQM ~ cohort + software_platform + age + sex + session + (1|subject_id)",
        f"  Cohort finding class: {overall_c}",
        f"  FULL_56 FDR IQMs ({len(full_c)}): {', '.join(full_c) or 'none'}",
        f"  CORE_QUALITY FDR IQMs ({len(core_c)}): {', '.join(core_c) or 'none'}",
        f"  TISSUE_SENSITIVE FDR IQMs ({len(tissue_c)}): {', '.join(tissue_c) or 'none'}",
        "  CORE_QUALITY uses conventional quality families (SNR, CNR, FBER, EFC, FWHM, CJV).",
        "  TISSUE_SENSITIVE uses morphology/tissue + intensity families from the same taxonomy.",
        "  ROBUST_ACROSS_FAMILIES here means both subsets have ≥1 FDR hit; CORE is a single",
        "  smoothness IQM (fwhm_y), so this is not a broad conventional-quality effect.",
        "",
        "2. Acquisition-associated variation",
        f"  Acquisition finding class: {overall_a}",
        f"  FULL_56 FDR IQMs ({len(full_a)}): {', '.join(full_a[:12]) or 'none'}"
        + (" ..." if len(full_a) > 12 else ""),
        f"  CORE_QUALITY FDR ({len(core_a)}); TISSUE_SENSITIVE FDR ({len(tissue_a)}).",
        "  Acquisition variable = software_platform (E11 vs XA30), not a stack of collinear",
        "  scanner/coil/NORM aliases. SAR was not entered (missing on the 6 XA30 rows).",
        "",
        "3. Cohort-associated variation",
        "  Current cohort-associated variation is NOT yet demonstrated to be anatomical.",
        "  FreeSurfer morphology is not in these models. Small Data_ON / Data_TON n remains.",
        "  IQMs are heterogeneous (image properties, segmentation/tissue, acquisition).",
        "  They are not automatically pure quality measures.",
        "",
        "4. Explained variance (Nakagawa marginal R²; model-explained, not causal)",
        f"  mean R2_acquisition={var_df['R2_acquisition'].mean():.4f}  "
        f"median={var_df['R2_acquisition'].median():.4f}",
        f"  mean R2_cohort={var_df['R2_cohort'].mean():.4f}  "
        f"median={var_df['R2_cohort'].median():.4f}",
        f"  mean R2_full={var_df['R2_full'].mean():.4f}  "
        f"median={var_df['R2_full'].median():.4f}",
        f"  IQMs with acquisition R² > cohort R²: "
        f"{int((var_df['R2_acquisition'] > var_df['R2_cohort']).sum())}/{len(var_df)}",
        "",
        "5. Elastic Net performance (Control vs Glaucoma; exploratory)",
        f"  Outer-fold mean ROC-AUC={folds['roc_auc'].mean():.3f}  "
        f"balanced accuracy={folds['balanced_accuracy'].mean():.3f}",
        f"  Pooled OOF ROC-AUC={float(oof['roc_auc']):.3f}  "
        f"balanced accuracy={float(oof['balanced_accuracy']):.3f}",
        f"  OOF sensitivity={float(oof['sensitivity']):.3f}  "
        f"specificity={float(oof['specificity']):.3f}  "
        f"precision={float(oof['precision']):.3f}  F1={float(oof['f1']):.3f}",
        "  Elastic Net is exploratory. It does not establish that IQMs cause diagnosis",
        "  or that selected IQMs are quality scores.",
        "",
        "6. Coefficient stability (outer folds)",
        f"  IQMs with nonzero_fraction>=0.8 and sign_consistency>=0.8: "
        f"{', '.join(stable.astype(str)) or 'none'}",
        "  Highest |mean coefficient|:",
    ]
    for _, r in top_coef.iterrows():
        lines.append(
            f"    {r['IQM']} ({family_group(str(r['IQM']))}): {r['mean_coefficient']:.4g}  "
            f"nonzero={r['nonzero_fraction']:.2f}"
        )
    lines.extend(
        [
            "",
            "7. Agreement between mixed-model and predictive results",
            f"  MixedLM FULL cohort FDR IQMs overlapping Elastic Net top-|coef|: "
            f"{', '.join(overlap) or 'none'}",
            "  MixedLM tests adjusted software_platform + covariates; Elastic Net predicts",
            "  diagnosis from IQMs alone under subject-grouped CV. Agreement is descriptive.",
            "",
            "8. Limitations",
            "  - Physical-acq n=133, Glaucoma subjects=19, Data_TON subjects=2.",
            "  - XA30 n=6, collinear with non-NORM reconstruction in this selected table.",
            "  - IQMs are collinear; Elastic Net coefficients are unstable when l1_ratio<1.",
            "  - No anatomical covariates yet; cohort R² is not biology R².",
            "  - Subject-grouped CV prevents longitudinal leakage but does not create an",
            "    external test set.",
            "",
            "9. Planned FreeSurfer extension (not implemented here)",
            "  IQM ~ acquisition + anatomy + cohort + age + sex + session + (1|subject_id)",
            "  Future variance comparison: R2_acquisition / R2_anatomy / R2_cohort / R2_full.",
            "",
            "Design notes reused later: software_platform is the acquisition term;",
            "Nakagawa marginal R² is the explained-variation metric; BH-FDR is within family;",
            "subject_id remains the MixedLM grouping factor.",
        ]
    )
    (qc / "robustness_variance_elastic_net_summary.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main(argv=None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    if not args.skip_family:
        LOGGER.info("Running family robustness")
        fam.main([])
    if not args.skip_variance:
        LOGGER.info("Running variance explained")
        var.main([])
    if not args.skip_elastic_net:
        LOGGER.info("Running Elastic Net")
        enet.main([])
    write_summary(args.out_dir)
    assert_unmodified(before)
    print("MRIQC physical-acquisition robustness, variance and Elastic Net analyses completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
