#!/usr/bin/env python3
"""T1w IQM PCA on the physical-acquisition table.

Uses the same 56 IQMs, z-scoring, and SVD/PCA method as the original
T1w PCA. Does not modify the original PCA files or the clean TSV.

Example:
  python code/mriqc_iqm_pca_physical_acq.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, require_columns, require_file, to_numeric_iqm  # noqa: E402
from mriqc_iqm_pca import (  # noqa: E402
    N_T1W_USABLE,
    VARIANCE_THRESHOLDS,
    detect_sklearn,
    n_components_for,
    plot_loadings,
    plot_variance,
    run_pca,
    verify_reproducibility,
)
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    assert_unmodified,
    file_sha256,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.pca")
ID_COLS = (
    "physical_acquisition_id",
    "subject_id",
    "session",
    "run",
    "bids_name",
    "selected_run",
    "selected_reconstruction",
    "selection_rule",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    args.study_root = root
    args.phys_tsv = root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    args.orig_loadings = root / "qc_reports" / "mriqc_iqm" / "pca_T1w_loadings.tsv"
    args.orig_variance = root / "qc_reports" / "mriqc_iqm" / "pca_T1w_variance.tsv"
    args.out_dir = root / "qc_reports" / "mriqc_iqm"
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)


def original_iqms(path: Path) -> list[str]:
    require_file(path, "original PCA loadings")
    df = pd.read_csv(path, sep="\t")
    if "iqm" not in df.columns:
        fail(f"{path} missing iqm column")
    iqms = df["iqm"].astype(str).tolist()
    if len(iqms) != N_T1W_USABLE:
        fail(f"Original PCA used {len(iqms)} IQMs, expected {N_T1W_USABLE}.")
    return iqms


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    require_file(args.phys_tsv, "physical-acquisition table")
    phys = pd.read_csv(args.phys_tsv, sep="\t")
    require_columns(phys, ["sequence_group", *ID_COLS], "physical-acquisition table")
    if len(phys) != EXPECTED_PHYSICAL_N:
        fail(f"Expected {EXPECTED_PHYSICAL_N} physical acquisitions, found {len(phys)}.")
    iqm_used = original_iqms(args.orig_loadings)
    missing = [c for c in iqm_used if c not in phys.columns]
    if missing:
        fail(f"Physical table missing original PCA IQMs: {missing}")

    x = np.column_stack([to_numeric_iqm(phys[c]).to_numpy(dtype=float) for c in iqm_used])
    if x.shape != (EXPECTED_PHYSICAL_N, N_T1W_USABLE):
        fail(f"PCA matrix shape {x.shape} != ({EXPECTED_PHYSICAL_N}, {N_T1W_USABLE})")
    if not np.isfinite(x).all():
        fail("Non-finite values in the physical-acquisition IQM matrix. No imputation.")

    sklearn_ok, sklearn_info = detect_sklearn()
    backend = (
        f"sklearn.decomposition.PCA (svd_solver=full) {sklearn_info}"
        if sklearn_ok
        else "numpy.linalg.svd matching sklearn full SVD + svd_flip"
    )
    result, x_std, _, _ = run_pca(x, sklearn_ok)
    if np.max(np.abs(x_std.mean(axis=0))) > 1e-10:
        fail("Standardized IQMs do not have mean 0.")
    if np.max(np.abs(x_std.std(axis=0, ddof=0) - 1.0)) > 1e-10:
        fail("Standardized IQMs do not have SD 1.")
    score_delta = verify_reproducibility(x, result, sklearn_ok)

    n_rows, n_components = result["scores"].shape
    pc_names = [f"PC{i}" for i in range(1, n_components + 1)]
    scores = phys.loc[:, [c for c in ID_COLS if c in phys.columns]].reset_index(drop=True)
    for i, name in enumerate(pc_names):
        scores[name] = result["scores"][:, i]
    loadings = pd.DataFrame(result["loadings"], index=iqm_used, columns=pc_names)
    loadings.index.name = "iqm"
    variance = pd.DataFrame(
        {
            "component": pc_names,
            "explained_variance": result["explained_variance"],
            "explained_variance_ratio": result["explained_variance_ratio"],
            "cumulative_ratio": result["cumulative_ratio"],
            "singular_value": result["singular_values"],
        }
    )
    n_marks = {
        label: n_components_for(result["cumulative_ratio"], thr)
        for label, thr in zip(("80%", "90%", "95%"), VARIANCE_THRESHOLDS)
    }

    orig_var = pd.read_csv(args.orig_variance, sep="\t")
    orig_pc1 = float(orig_var.loc[orig_var["component"].astype(str) == "PC1", "explained_variance_ratio"].iloc[0])
    orig_k = {
        label: n_components_for(orig_var["cumulative_ratio"].to_numpy(dtype=float), thr)
        for label, thr in zip(("80%", "90%", "95%"), VARIANCE_THRESHOLDS)
    }

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    scores.to_csv(out / "pca_physical_acq_scores.tsv", sep="\t", index=False, float_format="%.10g")
    loadings.to_csv(out / "pca_physical_acq_loadings.tsv", sep="\t", float_format="%.10g")
    variance.to_csv(out / "pca_physical_acq_variance.tsv", sep="\t", index=False, float_format="%.10g")
    plot_variance(variance, n_marks, out / "pca_physical_acq_variance.png", out / "pca_physical_acq_variance.pdf")
    plot_loadings(loadings, n_show=n_marks["95%"], dest_png=out / "pca_physical_acq_loadings.png", dest_pdf=out / "pca_physical_acq_loadings.pdf")

    lines = [
        "MRIQC T1w IQM PCA — physical-acquisition level",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "This PCA is a new analysis. Original pca_T1w_* files were not overwritten.",
        "PCs are covariance axes among IQMs, not quality scores.",
        "",
        f"N original T1w rows (acquisition/reconstruction-level): 264",
        f"N physical acquisitions: {n_rows}",
        f"IQMs: the same {len(iqm_used)} as pca_T1w_loadings.tsv",
        f"backend: {backend}",
        "standardization: column z-score, ddof=0 (StandardScaler)",
        "outliers: not removed; no imputation; T1w only",
        f"reproducibility max |Δ scores|: {score_delta}",
        "",
        "VARIANCE PC1–PC10 (physical-acq vs original)",
    ]
    for i in range(10):
        pc = f"PC{i+1}"
        new_r = float(variance.loc[i, "explained_variance_ratio"])
        old_r = float(orig_var.loc[orig_var["component"].astype(str) == pc, "explained_variance_ratio"].iloc[0])
        lines.append(f"  {pc}: physical={100*new_r:.2f}%  original={100*old_r:.2f}%  Δ={100*(new_r-old_r):+.2f} pp")
    lines.extend(
        [
            "",
            f"  80% variance: physical PC{n_marks['80%']} vs original PC{orig_k['80%']}",
            f"  90% variance: physical PC{n_marks['90%']} vs original PC{orig_k['90%']}",
            f"  95% variance: physical PC{n_marks['95%']} vs original PC{orig_k['95%']}",
            f"  PC1 original ratio: {orig_pc1:.6f}",
            "",
            "OUTPUTS: pca_physical_acq_scores/loadings/variance .tsv and variance/loadings figures.",
            "",
        ]
    )
    (out / "pca_physical_acq_report.txt").write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Wrote pca_physical_acq_report.txt")
    assert_unmodified(before)
    print(f"physical-acq PCA n={n_rows} IQMs={len(iqm_used)} PC1={100*float(variance.loc[0,'explained_variance_ratio']):.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
