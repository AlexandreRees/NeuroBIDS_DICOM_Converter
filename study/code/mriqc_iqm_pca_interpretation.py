#!/usr/bin/env python3
"""Characterize PC1–PC10 loadings from the existing T1w IQM PCA.

Does not recompute PCA. Does not modify source tables or previous PCA files.

Example:
  python code/mriqc_iqm_pca_interpretation.py
  python code/mriqc_iqm_pca_interpretation.py --help
"""

from __future__ import annotations

import argparse
import hashlib
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

from mriqc_iqm_lib import fail, iqm_family, require_columns, require_file  # noqa: E402

LOGGER = logging.getLogger("mriqc_iqm.pca_interpretation")
N_PCS = 10
TOP_N = 10
FIGURE_PCS = 6
N_IQMS_EXPECTED = 56
PC_NAMES = [f"PC{i}" for i in range(1, N_PCS + 1)]
FIGURE_PC_NAMES = [f"PC{i}" for i in range(1, FIGURE_PCS + 1)]


def study_root_default() -> Path:
    root = Path(__file__).resolve().parent.parent
    if not (root / "metadata").is_dir() or not (root / "qc_reports").is_dir():
        fail(
            f"Cannot resolve study root from {Path(__file__).resolve()}. "
            "Expected metadata/ and qc_reports/ next to code/. "
            "Pass --study-root explicitly."
        )
    return root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Loadings are associations with a PCA axis, not causal effects "
            "and not direct quality scores. No cohort tests, ML, or PC renaming."
        ),
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--loadings-tsv", type=Path, default=None)
    parser.add_argument("--variance-tsv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default()
    out = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.loadings_tsv = (
        args.loadings_tsv.resolve() if args.loadings_tsv else out / "pca_T1w_loadings.tsv"
    )
    args.variance_tsv = (
        args.variance_tsv.resolve() if args.variance_tsv else out / "pca_T1w_variance.tsv"
    )
    args.out_dir = args.out_dir.resolve() if args.out_dir else out
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    LOGGER.addHandler(handler)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_loadings(path: Path) -> pd.DataFrame:
    require_file(path, "PCA loadings table")
    df = pd.read_csv(path, sep="\t")
    if "iqm" not in df.columns:
        fail(f"{path} is missing column 'iqm'.")
    missing_pcs = [c for c in PC_NAMES if c not in df.columns]
    if missing_pcs:
        fail(f"{path} is missing {missing_pcs}. Refusing to recompute PCA.")
    df = df.set_index("iqm")
    if df.index.has_duplicates:
        fail(f"Duplicate IQM rows in {path}.")
    if len(df) != N_IQMS_EXPECTED:
        fail(f"Expected {N_IQMS_EXPECTED} IQM rows in loadings, found {len(df)}.")
    numeric = df[PC_NAMES].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        fail(f"Non-numeric or missing loadings for PC1–PC10 in {path}.")
    return numeric


def load_variance(path: Path) -> pd.DataFrame:
    require_file(path, "PCA variance table")
    df = pd.read_csv(path, sep="\t")
    require_columns(
        df,
        ["component", "explained_variance_ratio", "cumulative_ratio"],
        "PCA variance table",
    )
    missing = [c for c in PC_NAMES if c not in set(df["component"].astype(str))]
    if missing:
        fail(f"{path} is missing variance rows {missing}.")
    out = df.copy()
    out["component"] = out["component"].astype(str)
    return out


def characterize(loadings: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for pc in PC_NAMES:
        vec = loadings[pc].astype(float)
        ss = float(np.square(vec).sum())
        if ss <= 0:
            fail(f"{pc} has a zero loading vector.")
        contrib = np.square(vec) / ss
        if abs(ss - 1.0) > 1e-6:
            LOGGER.warning("%s sum(loading^2)=%.8f (contributions still normalized)", pc, ss)
        ranked = vec.reindex(vec.abs().sort_values(ascending=False).index)
        for rank, iqm in enumerate(ranked.index, start=1):
            loading = float(vec.loc[iqm])
            if loading > 0:
                sign = "+"
            elif loading < 0:
                sign = "-"
            else:
                sign = "0"
            rows.append(
                {
                    "pc": pc,
                    "rank_abs_loading": rank,
                    "iqm": iqm,
                    "iqm_family": iqm_family(iqm),
                    "loading": loading,
                    "abs_loading": abs(loading),
                    "sign": sign,
                    "loading_squared": float(loading * loading),
                    "contribution": float(contrib.loc[iqm]),
                    "sum_loading_squared": ss,
                    "in_top10": rank <= TOP_N,
                }
            )
    interpretation = pd.DataFrame(rows)
    top = interpretation.loc[interpretation["in_top10"]].copy()
    if len(top) != N_PCS * TOP_N:
        fail(f"Expected {N_PCS * TOP_N} top-loading rows, found {len(top)}.")
    return interpretation, top


def plot_top_loadings(top: pd.DataFrame, dest_png: Path, dest_pdf: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(11.5, 7.8))
    axes = np.atleast_1d(axes).ravel()
    for i, pc in enumerate(FIGURE_PC_NAMES):
        ax = axes[i]
        sub = top.loc[top["pc"] == pc].sort_values("abs_loading", ascending=True)
        colors = ["#4C78A8" if s == "+" else "#E45756" for s in sub["sign"]]
        ax.barh(sub["iqm"], sub["loading"], color=colors)
        ax.axvline(0.0, color="#333333", lw=0.8)
        ax.set_title(pc, fontsize=10)
        ax.tick_params(labelsize=7)
        if i % 3 == 0:
            ax.set_xlabel("")
        ax.set_xlabel("loading" if i >= 3 else "")
    fig.suptitle(
        "T1w PCA: 10 IQMs with largest |loading| on PC1–PC6\n"
        "blue = positive loading; red = negative loading"
    )
    fig.subplots_adjust(left=0.16, right=0.98, top=0.88, bottom=0.08, wspace=0.55, hspace=0.35)
    fig.savefig(dest_png, dpi=120)
    fig.savefig(dest_pdf)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest_png)
    LOGGER.info("Wrote %s", dest_pdf)


def pc_variance_map(variance: pd.DataFrame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for pc in PC_NAMES:
        row = variance.loc[variance["component"] == pc].iloc[0]
        out[pc] = {
            "explained_variance_ratio": float(row["explained_variance_ratio"]),
            "cumulative_ratio": float(row["cumulative_ratio"]),
        }
    return out


def write_report(
    path: Path,
    *,
    loadings_path: Path,
    variance_path: Path,
    hashes: dict[str, str],
    interpretation: pd.DataFrame,
    top: pd.DataFrame,
    var_map: dict[str, dict[str, float]],
) -> None:
    lines = [
        "T1w IQM PCA interpretation report (PC1–PC10)",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "SCOPE",
        "  PCA was not recomputed. Loadings and variance were read from existing files.",
        "  Cohorts, FreeSurfer, statistical tests, and ML were not used.",
        "  Principal components were not assigned biological names.",
        "",
        "INPUTS (read-only)",
        f"  loadings: {loadings_path}",
        f"  loadings sha256: {hashes['loadings']}",
        f"  variance: {variance_path}",
        f"  variance sha256: {hashes['variance']}",
        "",
        "DEFINITIONS",
        "  loading: weight of an IQM on a principal component after z-scoring.",
        "  A loading describes an association with that PCA axis. It is not a",
        "  causal effect, not a quality grade, and not a direct MRIQC pass/fail.",
        "  contribution: loading^2 / sum(loading^2) on that component",
        "  (relative share of that axis; sums to 1 per PC).",
        "  sign: retained from the original loading; the global PC sign is",
        "  arbitrary (SVD sign flip) but relative signs within a PC are meaningful.",
        "",
        f"MATRIX: {N_IQMS_EXPECTED} IQMs, characterizing {N_PCS} components, top {TOP_N} listed per PC.",
        "",
    ]
    for pc in PC_NAMES:
        info = var_map[pc]
        sub = top.loc[top["pc"] == pc].sort_values("rank_abs_loading")
        top_share = float(sub["contribution"].sum())
        lines.append(
            f"{pc}  variance_ratio={info['explained_variance_ratio']:.6f}  "
            f"cumulative={info['cumulative_ratio']:.6f}  "
            f"top{TOP_N}_contribution_sum={top_share:.4f}"
        )
        for row in sub.itertuples(index=False):
            lines.append(
                f"  {int(row.rank_abs_loading):2d}. {row.iqm:18s}  "
                f"family={row.iqm_family:18s}  "
                f"loading={row.loading:+.4f}  "
                f"contribution={row.contribution:.4f}"
            )
        lines.append("")
    lines.extend(
        [
            "READING NOTE",
            "  Dominant IQMs are those with the largest |loading| on an axis.",
            "  Opposite signs mean those IQMs co-vary in opposite directions along",
            "  that axis in this T1w sample. That is a description of the linear",
            "  combination, not evidence that one metric causes another, and not a",
            "  statement about clinical image quality.",
            "",
            "OUTPUTS",
            "  pca_T1w_interpretation.tsv  (all IQMs × PC1–PC10)",
            "  pca_T1w_top_loadings.tsv    (10 largest |loading| per PC)",
            "  pca_T1w_top_loadings_PC1-PC6.png/.pdf",
            "  pca_T1w_interpretation_report.txt",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    LOGGER.info("Characterizing existing T1w PCA loadings (PC1–PC10)")

    hashes = {
        "loadings": file_sha256(args.loadings_tsv),
        "variance": file_sha256(args.variance_tsv),
    }
    loadings = load_loadings(args.loadings_tsv)
    variance = load_variance(args.variance_tsv)
    interpretation, top = characterize(loadings)
    var_map = pc_variance_map(variance)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    interp_path = args.out_dir / "pca_T1w_interpretation.tsv"
    top_path = args.out_dir / "pca_T1w_top_loadings.tsv"
    interpretation.to_csv(interp_path, sep="\t", index=False, float_format="%.10g")
    top.to_csv(top_path, sep="\t", index=False, float_format="%.10g")
    LOGGER.info("Wrote %s", interp_path)
    LOGGER.info("Wrote %s", top_path)

    plot_top_loadings(
        top,
        args.out_dir / "pca_T1w_top_loadings_PC1-PC6.png",
        args.out_dir / "pca_T1w_top_loadings_PC1-PC6.pdf",
    )

    hashes_after = {
        "loadings": file_sha256(args.loadings_tsv),
        "variance": file_sha256(args.variance_tsv),
    }
    if hashes != hashes_after:
        fail("Input PCA files changed during the run; refusing silent overwrite.")

    write_report(
        args.out_dir / "pca_T1w_interpretation_report.txt",
        loadings_path=args.loadings_tsv,
        variance_path=args.variance_tsv,
        hashes=hashes,
        interpretation=interpretation,
        top=top,
        var_map=var_map,
    )

    shares = (
        top.groupby("pc", sort=False)["contribution"].sum().reindex(PC_NAMES)
    )
    print()
    print("N PCs characterized:", N_PCS)
    print("N IQMs:", loadings.shape[0])
    print("N top loadings listed:", len(top))
    print("Top-10 contribution sum by PC:")
    for pc, share in shares.items():
        print(f"  {pc}: {share:.4f}")
    print("PCA recomputed: no")
    print("source PCA files unmodified: yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
