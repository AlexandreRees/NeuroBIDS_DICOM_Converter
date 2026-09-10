#!/usr/bin/env python3
"""Compare original 264-row T1w PCA with physical-acquisition PCA.

Does not overwrite original PCA files. Component signs may flip; loadings
are aligned by cosine similarity before score correlations.
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

from mriqc_iqm_lib import fail, require_file  # noqa: E402
from mriqc_iqm_physical_acq_lib import assert_unmodified, snapshot_protected, study_root_default  # noqa: E402

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.pca_compare")
N_PCS = 10
PC_NAMES = [f"PC{i}" for i in range(1, N_PCS + 1)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.out_dir = qc
    args.old_load = qc / "pca_T1w_loadings.tsv"
    args.new_load = qc / "pca_physical_acq_loadings.tsv"
    args.old_var = qc / "pca_T1w_variance.tsv"
    args.new_var = qc / "pca_physical_acq_variance.tsv"
    args.old_scores = qc / "pca_T1w_scores.tsv"
    args.new_scores = qc / "pca_physical_acq_scores.tsv"
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(h)


def load_loadings(path: Path) -> pd.DataFrame:
    require_file(path, "loadings")
    df = pd.read_csv(path, sep="\t").set_index("iqm")
    return df[PC_NAMES].apply(pd.to_numeric, errors="coerce")


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return float("nan")
    return float(np.dot(a, b) / (na * nb))


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    old_l = load_loadings(args.old_load)
    new_l = load_loadings(args.new_load)
    common = [i for i in old_l.index if i in new_l.index]
    if len(common) != len(old_l):
        fail(f"IQM mismatch: {len(common)} common vs {len(old_l)} original.")
    old_v = pd.read_csv(args.old_var, sep="\t").set_index("component")
    new_v = pd.read_csv(args.new_var, sep="\t").set_index("component")
    old_s = pd.read_csv(args.old_scores, sep="\t")
    new_s = pd.read_csv(args.new_scores, sep="\t")
    merged = new_s.merge(old_s, on=["bids_name", "subject_id", "session", "run"], suffixes=("_new", "_old"))
    if len(merged) != len(new_s):
        fail(f"Score join on selected bids_name produced {len(merged)} rows, expected {len(new_s)}.")

    rows = []
    aligned_cos = []
    for pc in PC_NAMES:
        ov = old_l.loc[common, pc].to_numpy(dtype=float)
        nv = new_l.loc[common, pc].to_numpy(dtype=float)
        cos = cosine(ov, nv)
        sign = 1.0 if (cos >= 0 or not np.isfinite(cos)) else -1.0
        cos_aligned = cosine(ov, sign * nv)
        old_scores = merged[f"{pc}_old"].to_numpy(dtype=float)
        new_scores = sign * merged[f"{pc}_new"].to_numpy(dtype=float)
        if np.std(old_scores) == 0 or np.std(new_scores) == 0:
            r = float("nan")
        else:
            r = float(np.corrcoef(old_scores, new_scores)[0, 1])
        aligned_cos.append(cos_aligned)
        rows.append(
            {
                "PC": pc,
                "var_original": float(old_v.loc[pc, "explained_variance_ratio"]),
                "var_physical": float(new_v.loc[pc, "explained_variance_ratio"]),
                "var_delta": float(new_v.loc[pc, "explained_variance_ratio"] - old_v.loc[pc, "explained_variance_ratio"]),
                "loading_cosine_raw": cos,
                "sign_flip": int(sign < 0),
                "loading_cosine_aligned": cos_aligned,
                "score_pearson_aligned": r,
                "n_scores_compared": int(len(merged)),
            }
        )
    cmp = pd.DataFrame(rows)
    out = args.out_dir
    cmp.to_csv(out / "pca_physical_acq_comparison.tsv", sep="\t", index=False, float_format="%.10g")

    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    x = np.arange(N_PCS)
    ax.bar(x - 0.18, 100 * cmp["var_original"], 0.36, label="original 264 rows", color="#4C78A8")
    ax.bar(x + 0.18, 100 * cmp["var_physical"], 0.36, label="physical-acq 133 rows", color="#F58518")
    ax.set_xticks(x, PC_NAMES)
    ax.set_ylabel("Variance explained (%)")
    ax.set_title("T1w IQM PCA variance: original vs physical-acquisition")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "pca_physical_acq_variance_comparison.png", dpi=130)
    fig.savefig(out / "pca_physical_acq_variance_comparison.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    ax.bar(x, cmp["loading_cosine_aligned"], color="#54A24B")
    ax.set_xticks(x, PC_NAMES)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Absolute cosine similarity of loadings")
    ax.set_title("Loading similarity after sign alignment")
    fig.tight_layout()
    fig.savefig(out / "pca_physical_acq_loading_similarity.png", dpi=130)
    fig.savefig(out / "pca_physical_acq_loading_similarity.pdf")
    plt.close(fig)

    mean_cos = float(np.nanmean(cmp["loading_cosine_aligned"]))
    min_cos = float(np.nanmin(cmp["loading_cosine_aligned"]))
    pc1_cos = float(cmp.loc[cmp["PC"] == "PC1", "loading_cosine_aligned"].iloc[0])
    pc1_r = float(cmp.loc[cmp["PC"] == "PC1", "score_pearson_aligned"].iloc[0])
    if min_cos >= 0.90 and abs(float(cmp.loc[cmp["PC"]=="PC1","var_delta"].iloc[0])) < 0.05:
        verdict = (
            "No: after dropping paired reconstructions, PC1–PC10 loading structure "
            "remains highly similar (sign-aligned cosine). Pseudoreplication inflated "
            "N but did not rebuild the covariance axes."
        )
    elif pc1_cos >= 0.85:
        verdict = (
            "Partly: leading components are recognizably the same, but later PCs "
            "and/or variance shares moved. Treat original 264-row PCA as "
            "reconstruction-inflated, not as a different scientific construct."
        )
    else:
        verdict = (
            "Yes: loadings of leading PCs changed enough that the original 264-row "
            "PCA should not be treated as interchangeable with the physical-acquisition PCA."
        )

    lines = [
        "Original vs physical-acquisition T1w IQM PCA",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Original PCA: 264 reconstruction-level T1w rows.",
        f"Physical-acq PCA: {len(new_s)} rows. Score correlation uses the 133 selected files' original scores vs new scores.",
        "PCA signs were aligned per PC (cosine of loadings).",
        "PCs are not quality scores.",
        "",
        cmp.to_string(index=False, float_format=lambda v: f"{v:.4f}"),
        "",
        f"Mean sign-aligned loading cosine PC1–PC10: {mean_cos:.3f}",
        f"Minimum: {min_cos:.3f}",
        f"PC1 score Pearson (aligned): {pc1_r:.3f}",
        "",
        "Does NORM/non-NORM pseudoreplication substantially change PCA structure?",
        verdict,
        "",
    ]
    (out / "pca_physical_acq_comparison_report.txt").write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Wrote comparison outputs")
    assert_unmodified(before)
    print(f"loading cosine mean={mean_cos:.3f} min={min_cos:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
