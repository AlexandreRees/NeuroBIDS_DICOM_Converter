#!/usr/bin/env python3
"""Spearman IQM correlations at physical-acquisition T1w level.

Does not drop outliers. Does not modify the original Spearman matrices.
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

from mriqc_iqm_correlation import (  # noqa: E402
    numeric_block,
    plot_matrix,
    spearman_matrices,
    validate_matrix,
    write_matrix,
)
from mriqc_iqm_lib import fail, require_file  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    assert_unmodified,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.corr")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study-root", type=Path, default=None)
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.phys = root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    args.orig_rho = qc / "spearman_T1w.tsv"
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
    require_file(args.phys, "physical-acquisition table")
    require_file(args.orig_rho, "original T1w Spearman matrix")
    phys = pd.read_csv(args.phys, sep="\t")
    if len(phys) != EXPECTED_PHYSICAL_N:
        fail(f"Expected {EXPECTED_PHYSICAL_N} rows, found {len(phys)}.")
    orig = pd.read_csv(args.orig_rho, sep="\t", index_col=0)
    iqms = [c for c in orig.columns if c in phys.columns]
    if len(iqms) != len(orig.columns):
        LOGGER.warning("Using %d/%d original Spearman IQMs present in the physical table", len(iqms), len(orig.columns))
    block = numeric_block(phys, iqms)
    rho, pval, nobs = spearman_matrices(block)
    validate_matrix(rho, pval, nobs, len(iqms), "physical_acq_T1w")
    out = args.out_dir
    write_matrix(rho, out / "spearman_physical_acq_T1w.tsv")
    write_matrix(pval, out / "spearman_physical_acq_T1w_pvalues.tsv")
    plot_matrix(
        rho,
        "Spearman IQM correlation — physical-acquisition T1w",
        out / "spearman_physical_acq_T1w_heatmap.png",
        out / "spearman_physical_acq_T1w_heatmap.pdf",
        vmin=-1.0,
        vmax=1.0,
        cmap="RdBu_r",
        cbar_label="Spearman ρ",
    )
    orig_sub = orig.loc[iqms, iqms].apply(pd.to_numeric, errors="coerce")
    delta = (rho - orig_sub).abs()
    off = ~np.eye(len(iqms), dtype=bool)
    mean_abs = float(np.nanmean(delta.to_numpy()[off]))
    max_abs = float(np.nanmax(delta.to_numpy()[off]))

    fig, axes = plt.subplots(1, 3, figsize=(15.6, 5.0))
    for ax, mat, title, vmin, vmax, cmap in (
        (axes[0], orig_sub, "Original 264 T1w", -1, 1, "RdBu_r"),
        (axes[1], rho, "Physical-acq 133 T1w", -1, 1, "RdBu_r"),
        (axes[2], delta, "|Δρ|", 0, max(0.15, max_abs), "YlOrRd"),
    ):
        arr = np.ma.masked_invalid(mat.to_numpy(dtype=float))
        im = ax.imshow(arr, vmin=vmin, vmax=vmax, cmap=cmap, aspect="auto", interpolation="nearest")
        ax.set_title(title, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.suptitle("T1w IQM Spearman: original vs physical-acquisition")
    fig.tight_layout()
    fig.savefig(out / "correlation_physical_acq_vs_original.png", dpi=130)
    fig.savefig(out / "correlation_physical_acq_vs_original.pdf")
    plt.close(fig)

    report = [
        "Physical-acquisition T1w Spearman correlations",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        f"n physical acquisitions: {len(phys)}",
        f"n IQMs: {len(iqms)}",
        "outliers: not removed",
        f"mean |Δρ| vs original 264-row matrix (off-diagonal): {mean_abs:.4f}",
        f"max |Δρ|: {max_abs:.4f}",
        "Original spearman_T1w.tsv was not modified.",
        "",
    ]
    (out / "spearman_physical_acq_T1w_report.txt").write_text("\n".join(report), encoding="utf-8")
    LOGGER.info("mean |Δρ|=%.4f max=%.4f", mean_abs, max_abs)
    assert_unmodified(before)
    print(f"spearman physical-acq T1w n={len(phys)} mean|Δρ|={mean_abs:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
