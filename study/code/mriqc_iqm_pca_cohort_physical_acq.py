#!/usr/bin/env python3
"""Cohort tests on physical-acquisition T1w PCA scores.

Primary model remains MixedLM: PC ~ cohort + age + sex + session + (1|subject_id).
sub-043 ses-02 has two physical acquisitions in one session; that does not
identify a nested random intercept, so no extra grouping level is added.
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

from mriqc_iqm_lib import EXPECTED_COHORTS, fail, require_columns, require_file  # noqa: E402
from mriqc_iqm_pca_cohort_analysis import (  # noqa: E402
    COHORT_COLORS,
    FDR_ALPHA,
    N_PCS,
    PC_NAMES,
    apply_fdr_rows,
    cohort_term,
    driving_iqms,
    fit_mixed,
    fit_ols,
    fmt_p,
    import_stats,
    pairwise_vs_control,
    sample_sizes,
    scatter_pc,
    write_report,
)
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    assert_unmodified,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.cohort")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study-root", type=Path, default=None)
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.scores = qc / "pca_physical_acq_scores.tsv"
    args.loadings = qc / "pca_physical_acq_loadings.tsv"
    args.variance = qc / "pca_physical_acq_variance.tsv"
    args.phys = root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    args.out_dir = qc
    return args


def configure_logging():
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    LOGGER.addHandler(h)


def plot_cohort_heatmap(results: pd.DataFrame, dest_png: Path, dest_pdf: Path) -> None:
    pcs = results["PC"].tolist()
    cohorts = ["Glaucoma", "Data_ON", "Data_TON"]
    coef_cols = {"Glaucoma": "mixed_estimate", "Data_ON": "mixed_on_coef", "Data_TON": "mixed_ton_coef"}
    mat = np.column_stack([results[coef_cols[c]].to_numpy(dtype=float) for c in cohorts])
    q = results["mixed_cohort_q"].to_numpy(dtype=float)
    vmax = np.nanmax(np.abs(mat)) or 1.0
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    im = ax.imshow(mat, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(3), cohorts)
    ax.set_yticks(range(len(pcs)), pcs)
    ax.set_title("MixedLM cohort effects vs Control (physical-acq PCA)\n* mixed omnibus q<0.05")
    for i, qi in enumerate(q):
        mark = "*" if np.isfinite(qi) and qi < FDR_ALPHA else ""
        ax.text(-0.7, i, f"q={qi:.3g}{mark}", fontsize=7, ha="right", va="center")
        for j in range(3):
            ax.text(j, i, f"{mat[i, j]:+.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.04, pad=0.08, label="estimate vs Control")
    fig.subplots_adjust(left=0.28, right=0.95)
    fig.savefig(dest_png, dpi=160)
    fig.savefig(dest_pdf)
    plt.close(fig)


def main(argv=None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    stats = import_stats()
    if not stats["ok"]:
        fail("scipy+statsmodels required: " + "; ".join(stats["missing"]))
    scores = pd.read_csv(args.scores, sep="\t")
    phys = pd.read_csv(args.phys, sep="\t")
    require_columns(scores, ["bids_name", "subject_id", "session", "run", *PC_NAMES], "physical-acq scores")
    require_columns(phys, ["bids_name", "cohort", "age", "sex"], "physical table")
    df = scores.merge(
        phys[["bids_name", "subject_id", "session", "run", "cohort", "age", "sex"]],
        on=["bids_name", "subject_id", "session", "run"],
        how="left",
    )
    if len(df) != EXPECTED_PHYSICAL_N:
        fail(f"Joined physical-acq scores n={len(df)}, expected {EXPECTED_PHYSICAL_N}.")
    if df["cohort"].isna().any() or df["age"].isna().any():
        fail("Missing cohort/age after join.")
    extra = sorted(set(df["cohort"].astype(str)) - set(EXPECTED_COHORTS))
    if extra:
        fail(f"Unexpected cohorts: {extra}")
    df["cohort"] = pd.Categorical(df["cohort"], categories=list(EXPECTED_COHORTS), ordered=False)
    df["age"] = pd.to_numeric(df["age"], errors="coerce")
    n_multi = int((df.groupby(["subject_id", "session"]).size() > 1).sum())
    LOGGER.info("subject×session cells with >1 physical acq: %d (expected 1: sub-043 ses-02)", n_multi)

    var_df = pd.read_csv(args.variance, sep="\t")
    var_map = {}
    for pc in PC_NAMES:
        row = var_df.loc[var_df["component"].astype(str) == pc].iloc[0]
        var_map[pc] = {
            "explained_variance_ratio": float(row["explained_variance_ratio"]),
            "cumulative_ratio": float(row["cumulative_ratio"]),
        }
    loadings = pd.read_csv(args.loadings, sep="\t").set_index("iqm")
    loadings = loadings[PC_NAMES].apply(pd.to_numeric, errors="coerce")
    sizes = sample_sizes(df)

    scatter_pc(df, "PC1", "PC2", var_map, args.out_dir / "pca_physical_acq_cohort_PC1_PC2.png", args.out_dir / "pca_physical_acq_cohort_PC1_PC2.pdf", sizes)
    scatter_pc(df, "PC1", "PC3", var_map, args.out_dir / "pca_physical_acq_cohort_PC1_PC3.png", args.out_dir / "pca_physical_acq_cohort_PC1_PC3.pdf", sizes)
    scatter_pc(df, "PC2", "PC3", var_map, args.out_dir / "pca_physical_acq_cohort_PC2_PC3.png", args.out_dir / "pca_physical_acq_cohort_PC2_PC3.pdf", sizes)

    rhs = cohort_term()
    raw_rows, adj_rows, mixed_rows, mixed_fits = [], [], [], {}
    for pc in PC_NAMES:
        LOGGER.info("Fitting physical-acq models for %s", pc)
        raw_rows.append(fit_ols(df, pc, rhs, "1", stats))
        adj_rows.append(fit_ols(df, pc, f"{rhs} + age + C(sex)", "age + C(sex)", stats))
        mix = fit_mixed(df, pc, f"{rhs} + age + C(sex) + C(session)", stats)
        mixed_fits[pc] = mix["fit"]
        mixed_rows.append(mix)
    raw_rows = apply_fdr_rows(raw_rows, stats["multipletests"])
    adj_rows = apply_fdr_rows(adj_rows, stats["multipletests"])
    mixed_rows = apply_fdr_rows(mixed_rows, stats["multipletests"])
    sig = {
        "raw": [r["pc"] for r in raw_rows if np.isfinite(r["q"]) and r["q"] < FDR_ALPHA],
        "adjusted": [r["pc"] for r in adj_rows if np.isfinite(r["q"]) and r["q"] < FDR_ALPHA],
        "mixed": [r["pc"] for r in mixed_rows if np.isfinite(r["q"]) and r["q"] < FDR_ALPHA],
    }
    pairwise = pairwise_vs_control(mixed_fits, sig["mixed"], stats["multipletests"]) if sig["mixed"] else pd.DataFrame()
    driving_pcs = [pc for pc in PC_NAMES if pc in set(sig["raw"] + sig["adjusted"] + sig["mixed"])]
    driving = driving_iqms(loadings, driving_pcs)
    driving.to_csv(args.out_dir / "pca_cohort_physical_acq_driving_iqms.tsv", sep="\t", index=False, float_format="%.10g")

    result_rows = []
    raw_m = {r["pc"]: r for r in raw_rows}
    adj_m = {r["pc"]: r for r in adj_rows}
    mix_m = {r["pc"]: r for r in mixed_rows}
    for pc in PC_NAMES:
        r, a, m = raw_m[pc], adj_m[pc], mix_m[pc]
        result_rows.append(
            {
                "PC": pc,
                "variance_explained": var_map[pc]["explained_variance_ratio"],
                "raw_p": r["p"],
                "raw_q": r["q"],
                "adjusted_p": a["p"],
                "adjusted_q": a["q"],
                "mixed_cohort_p": m["p"],
                "mixed_cohort_q": m["q"],
                "mixed_estimate": m["glaucoma_coef"],
                "mixed_ci_low": m["glaucoma_ci_low"],
                "mixed_ci_high": m["glaucoma_ci_high"],
                "mixed_on_coef": m["on_coef"],
                "mixed_ton_coef": m["ton_coef"],
                "N_subjects": m["n_subjects"],
                "N_observations": m["n_obs"],
                "convergence": m["converged"],
                "raw_F": r["stat"],
                "adjusted_F": a["stat"],
                "mixed_wald": m["stat"],
            }
        )
    results = pd.DataFrame(result_rows)
    results.to_csv(args.out_dir / "pca_cohort_physical_acq_results.tsv", sep="\t", index=False, float_format="%.10g")
    plot_cohort_heatmap(
        results,
        args.out_dir / "pca_physical_acq_cohort_heatmap.png",
        args.out_dir / "pca_physical_acq_cohort_heatmap.pdf",
    )

    hashes = {str(args.scores): "physical-acq scores (new)"}
    write_report(
        args.out_dir / "pca_cohort_physical_acq_analysis_report.txt",
        scores_path=args.scores,
        loadings_path=args.loadings,
        variance_path=args.variance,
        clean_path=args.phys,
        hashes={"scores": "n/a", "loadings": "n/a", "variance": "n/a", "clean": "n/a"},
        hashes_after={"scores": "n/a", "loadings": "n/a", "variance": "n/a", "clean": "n/a"},
        stats_info=stats,
        sizes=sizes,
        var_map=var_map,
        raw=raw_rows,
        adj=adj_rows,
        mixed=mixed_rows,
        pairwise=pairwise,
        driving=driving,
        sig=sig,
    )
    # Prefix a physical-acq note at the top of the generated report.
    report_path = args.out_dir / "pca_cohort_physical_acq_analysis_report.txt"
    extra = (
        "PHYSICAL-ACQUISITION COHORT ANALYSIS\n"
        f"N observations={len(df)} (not 264). Extra grouping: {n_multi} subject×session "
        "cell(s) have 2 physical acquisitions (sub-043 ses-02). MixedLM still uses "
        "(1|subject_id) only; a session-level random intercept is not identifiable.\n"
        "PCs are not quality scores. Data_ON / Data_TON remain small-n.\n\n"
    )
    report_path.write_text(extra + report_path.read_text(encoding="utf-8"), encoding="utf-8")
    assert_unmodified(before)
    print("mixed FDR PCs:", ", ".join(sig["mixed"]) or "none")
    print("raw FDR PCs:", ", ".join(sig["raw"]) or "none")
    print("adjusted FDR PCs:", ", ".join(sig["adjusted"]) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
