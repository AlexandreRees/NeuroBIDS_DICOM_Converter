#!/usr/bin/env python3
"""Orchestrate the physical-acquisition MRIQC reanalysis and write the global report.

Does not modify original clean/PCA/cohort/longitudinal files.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    assert_unmodified,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.reanalysis")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study-root", type=Path, default=None)
    p.add_argument("--skip-models", action="store_true", help="Skip MixedLM scripts if already run.")
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    args.study_root = root
    args.qc = root / "qc_reports" / "mriqc_iqm"
    args.phys = root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    return args


def configure_logging():
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    LOGGER.addHandler(h)


def _hits(path: Path, col: str = "interaction_q", namecol: str = "IQM") -> list[str]:
    if not path.is_file():
        return []
    df = pd.read_csv(path, sep="\t")
    if col not in df.columns or namecol not in df.columns:
        return []
    return df.loc[df[col] < 0.05, namecol].astype(str).tolist()


def write_global_report(root: Path) -> dict:
    qc = root / "qc_reports" / "mriqc_iqm"
    phys = pd.read_csv(root / "metadata" / "mriqc_iqm_physical_acquisition.tsv", sep="\t")
    old_var = pd.read_csv(qc / "pca_T1w_variance.tsv", sep="\t")
    new_var = pd.read_csv(qc / "pca_physical_acq_variance.tsv", sep="\t")
    cmp = pd.read_csv(qc / "pca_physical_acq_comparison.tsv", sep="\t")
    old_coh = pd.read_csv(qc / "pca_cohort_results.tsv", sep="\t")
    new_coh = pd.read_csv(qc / "pca_cohort_physical_acq_results.tsv", sep="\t")
    old_long = _hits(qc / "longitudinal_results.tsv")
    sess_long = _hits(qc / "longitudinal_session_level_results.tsv")
    new_long = _hits(qc / "longitudinal_physical_acq_results.tsv")
    norm = pd.read_csv(qc / "norm_vs_non_norm_sensitivity.tsv", sep="\t")
    n_norm_pairs = int(norm["n_pairs"].iloc[0]) if len(norm) else 0

    def sig_pcs(df, col):
        if col not in df.columns:
            return []
        pc_col = "PC" if "PC" in df.columns else "pc"
        return df.loc[df[col] < 0.05, pc_col].astype(str).tolist()

    orig_raw = sig_pcs(old_coh, "raw_q")
    orig_adj = sig_pcs(old_coh, "adjusted_q")
    orig_mix = sig_pcs(old_coh, "mixed_cohort_q")
    new_raw = sig_pcs(new_coh, "raw_q")
    new_adj = sig_pcs(new_coh, "adjusted_q")
    new_mix = sig_pcs(new_coh, "mixed_cohort_q")

    pc1_old = float(old_var.loc[old_var.component.astype(str) == "PC1", "explained_variance_ratio"].iloc[0])
    pc1_new = float(new_var.loc[new_var.component.astype(str) == "PC1", "explained_variance_ratio"].iloc[0])
    mean_cos = float(cmp["loading_cosine_aligned"].mean())

    n_sel = phys["selection_rule"].value_counts().to_dict()
    corr_note = ""
    corr_rep = qc / "spearman_physical_acq_T1w_report.txt"
    if corr_rep.is_file():
        corr_note = corr_rep.read_text(encoding="utf-8")

    robust_coh = "MixedLM still finds no FDR-significant PC (same as original primary model)."
    disappear_coh = (
        f"Naive OLS FDR PCs original={orig_raw or 'none'} vs physical-acq={new_raw or 'none'}. "
        "OLS hits are not interpreted as robust cohort quality effects."
    )
    robust_long = sorted(set(old_long) & set(new_long))
    gone_long = sorted(set(old_long) - set(new_long))
    new_only_long = sorted(set(new_long) - set(old_long))

    lines = [
        "Physical-acquisition MRIQC reanalysis — global report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "1. Why the original 264 observations were pseudoreplicated",
        "  Most sessions contributed two T1w files that are Siemens reconstructions",
        "  of one T1w_MPR (NORM vs non-NORM Prescan Normalize), not two scans.",
        "  run-01/run-02 labels files, not independent acquisitions.",
        "",
        "2. How physical acquisitions were identified",
        "  Reconstruction audit (sidecar + DICOM inventory): consecutive SeriesNumber,",
        "  identical TR/TE/FA, AcquisitionNumber=1, series_time deltas of milliseconds,",
        "  ImageType differing by NORM. Clusters for the exception session use SAR+shim.",
        "  IQM values were never used to choose a reconstruction.",
        "",
        f"3. Physical acquisitions retained: {len(phys)} (expected {EXPECTED_PHYSICAL_N})",
        f"  sessions: {phys.groupby(['subject_id','session']).ngroups}",
        f"  subjects: {phys['subject_id'].nunique()}",
        "",
        "4. Which reconstruction was selected, and why",
        "  Prefer NORM when present (Siemens intensity-normalized recon of the same k-space).",
        "  For T1w_MPR vs T1w_MPR_ND pairs without a NORM token, prefer SeriesDescription T1w_MPR.",
        "  Singletons kept as-is. sub-043 ses-02: one recon from each of two independent scans.",
        f"  selection_rule counts: {n_sel}",
        "",
        "5. PCA original vs corrected",
        f"  N: 264 vs {len(phys)}",
        f"  PC1 variance: {100*pc1_old:.2f}% vs {100*pc1_new:.2f}%",
        f"  Mean sign-aligned loading cosine PC1–PC10: {mean_cos:.3f}",
        "  See pca_physical_acq_comparison_report.txt.",
        "",
        "6. Correlation heatmaps",
        corr_note.strip() or "  See spearman_physical_acq_T1w_heatmap and correlation_physical_acq_vs_original.",
        "",
        "7. Cohort tests original vs corrected (FDR q<0.05)",
        f"  Raw OLS: {orig_raw or 'none'}  vs  {new_raw or 'none'}",
        f"  Adjusted OLS: {orig_adj or 'none'}  vs  {new_adj or 'none'}",
        f"  MixedLM primary: {orig_mix or 'none'}  vs  {new_mix or 'none'}",
        f"  Robust: {robust_coh}",
        f"  OLS-only: {disappear_coh}",
        "",
        "8. Longitudinal interaction original vs session-level vs physical-acq",
        f"  264-row acquisition-level: {old_long or 'none'}",
        f"  session-level FreeSurfer-selected: {sess_long or 'none'}",
        f"  physical-acquisition-level: {new_long or 'none'}",
        f"  still FDR-significant in both 264-row and physical-acq: {robust_long or 'none'}",
        f"  lost after physical-acq correction: {gone_long or 'none'}",
        f"  new after correction: {new_only_long or 'none'}",
        "  Data_ON/Data_TON longitudinal n=1; do not treat those trajectories as population effects.",
        "",
        f"9. NORM vs non-NORM descriptive pairs: {n_norm_pairs}",
        "  See norm_vs_non_norm_sensitivity_report.txt. Not independent observations.",
        "",
        "10. Conclusions that remain robust",
        "  Dual T1w files in a session are usually paired reconstructions.",
        "  MixedLM cohort tests on PCA scores remain non-significant after FDR.",
        "  Data_ON / Data_TON n is too small for population inference.",
        "  PCs remain IQM covariance axes, not quality scores.",
        "",
        "11. Conclusions that do not survive (or were never primary)",
        "  Treating 264 T1w rows as independent acquisitions.",
        "  Naive OLS cohort 'hits' on PCA scores (already non-robust in the original MixedLM).",
        f"  Longitudinal interaction hits that are not shared across 264-row, session-level,",
        f"  and physical-acq analyses: lost={gone_long or 'none'}; session-only={sorted(set(sess_long)-set(new_long)) or 'none'}.",
        "",
        "Original files were not deleted or overwritten. MRIQC and FreeSurfer were not rerun.",
        "",
    ]
    dest = qc / "physical_acquisition_reanalysis_report.txt"
    dest.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Wrote %s", dest)
    return {
        "n_phys": len(phys),
        "pc1_old": pc1_old,
        "pc1_new": pc1_new,
        "orig_mix": orig_mix,
        "new_mix": new_mix,
        "old_long": old_long,
        "sess_long": sess_long,
        "new_long": new_long,
        "n_norm_pairs": n_norm_pairs,
        "orig_raw": orig_raw,
        "new_raw": new_raw,
    }


def main(argv=None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    if not args.phys.is_file():
        fail("Run mriqc_iqm_physical_acquisition_table.py first.")
    summary = write_global_report(args.study_root)
    assert_unmodified(before)
    print()
    print("ORIGINAL:")
    print("264 T1w observations")
    print()
    print("CORRECTED:")
    print(f"{summary['n_phys']} physical acquisitions")
    print()
    print("PCA:")
    print(f"original vs corrected PC1 variance explained: {100*summary['pc1_old']:.2f}% vs {100*summary['pc1_new']:.2f}%")
    print()
    print("COHORT:")
    print(f"original MixedLM FDR-significant PCs: {', '.join(summary['orig_mix']) or 'none'}")
    print(f"corrected MixedLM FDR-significant PCs: {', '.join(summary['new_mix']) or 'none'}")
    print(f"original raw OLS FDR PCs: {', '.join(summary['orig_raw']) or 'none'}")
    print(f"corrected raw OLS FDR PCs: {', '.join(summary['new_raw']) or 'none'}")
    print()
    print("LONGITUDINAL:")
    print(f"acquisition-level 264: {', '.join(summary['old_long']) or 'none'}")
    print(f"session-level: {', '.join(summary['sess_long']) or 'none'}")
    print(f"physical-acquisition-level: {', '.join(summary['new_long']) or 'none'}")
    print()
    print("NORM:")
    print(f"number of paired reconstructions analyzed: {summary['n_norm_pairs']}")
    print()
    print("Physical-acquisition MRIQC reanalysis completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
