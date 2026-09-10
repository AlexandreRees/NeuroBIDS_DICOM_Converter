#!/usr/bin/env python3
"""Exploratory PCA of T1w MRIQC IQMs.

Uses sequence_group == T1w only. Zero-variance IQMs are dropped in memory.
The source TSV is never modified. Outlier acquisitions are never removed.

scikit-learn is used when importable; otherwise PCA is computed with a
NumPy SVD that matches sklearn.decomposition.PCA (full SVD + svd_flip).

Example:
  python code/mriqc_iqm_pca.py
  python code/mriqc_iqm_pca.py --help
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

from mriqc_iqm_lib import (  # noqa: E402
    analytic_iqm_columns,
    fail,
    require_columns,
    require_file,
    to_numeric_iqm,
)

LOGGER = logging.getLogger("mriqc_iqm.pca")
N_RETAINED_IQMS = 58
N_T1W_USABLE = 56
N_T1W_ROWS = 264
VARIANCE_THRESHOLDS = (0.80, 0.90, 0.95)
ID_COLS = ("subject_id", "session", "run", "bids_name")


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
            "T1w only. No cohort tests, no t-SNE/UMAP, no biological "
            "interpretation. Does not rewrite metadata/mriqc_iqm_clean.tsv."
        ),
    )
    parser.add_argument(
        "--study-root",
        type=Path,
        default=None,
        help="Study directory (default: parent of this script).",
    )
    parser.add_argument(
        "--clean-tsv",
        type=Path,
        default=None,
        help="Clean IQM table (default: <study-root>/metadata/mriqc_iqm_clean.tsv).",
    )
    parser.add_argument(
        "--roles-tsv",
        type=Path,
        default=None,
        help="Column-role table (default: <study-root>/metadata/mriqc_iqm_column_roles.tsv).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <study-root>/qc_reports/mriqc_iqm).",
    )
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default()
    args.study_root = root
    args.clean_tsv = (
        args.clean_tsv.resolve()
        if args.clean_tsv
        else root / "metadata" / "mriqc_iqm_clean.tsv"
    )
    args.roles_tsv = (
        args.roles_tsv.resolve()
        if args.roles_tsv
        else root / "metadata" / "mriqc_iqm_column_roles.tsv"
    )
    args.out_dir = (
        args.out_dir.resolve() if args.out_dir else root / "qc_reports" / "mriqc_iqm"
    )
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


def detect_sklearn() -> tuple[bool, str]:
    try:
        import sklearn  # noqa: F401
        from sklearn.decomposition import PCA  # noqa: F401
        from sklearn.preprocessing import StandardScaler  # noqa: F401
    except ImportError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    import sklearn

    return True, str(sklearn.__version__)


def retained_iqm_columns(clean: pd.DataFrame, roles_path: Path) -> list[str]:
    require_file(roles_path, "column-role table")
    roles = pd.read_csv(roles_path, sep="\t")
    require_columns(roles, ["column", "retained_for_statistics", "role"], "column-role table")
    retained = roles.loc[roles["retained_for_statistics"].astype(bool), "column"].tolist()
    if len(retained) != N_RETAINED_IQMS:
        fail(
            f"Expected {N_RETAINED_IQMS} retained IQMs in {roles_path}, found {len(retained)}."
        )
    missing = [c for c in retained if c not in clean.columns]
    if missing:
        fail(f"Retained IQMs absent from the clean table: {missing}")
    inferred = analytic_iqm_columns(clean)
    if set(inferred) != set(retained):
        fail(
            "Retained IQM list disagrees with analytic_iqm_columns(). "
            f"extra={sorted(set(inferred) - set(retained))} "
            f"missing_from_inferred={sorted(set(retained) - set(inferred))}"
        )
    technical = set(roles.loc[roles["role"].astype(str) == "technical", "column"])
    leaked = [c for c in retained if c in technical]
    if leaked:
        fail(f"Technical columns were listed as retained IQMs: {leaked}")
    return retained


def load_t1w(path: Path) -> pd.DataFrame:
    require_file(path, "clean IQM table")
    df = pd.read_csv(path, sep="\t")
    require_columns(df, ["sequence_group", *ID_COLS], "clean IQM table")
    t1 = df.loc[df["sequence_group"].astype(str) == "T1w"].copy()
    if t1.empty:
        fail("No rows with sequence_group == T1w.")
    if len(t1) != N_T1W_ROWS:
        fail(
            f"Expected {N_T1W_ROWS} T1w acquisitions in the clean table, found {len(t1)}. "
            "Refusing to drop or impute rows."
        )
    dup = t1.duplicated(["subject_id", "session", "run"], keep=False)
    if dup.any():
        fail(
            "Ambiguous T1w subject/session/run duplicates:\n"
            + t1.loc[dup, list(ID_COLS)].to_string(index=False)
        )
    LOGGER.info("Loaded T1w rows: %d from %s", len(t1), path)
    return t1


def select_pca_columns(t1: pd.DataFrame, iqm_cols: list[str]) -> tuple[list[str], list[str]]:
    dropped: list[str] = []
    kept: list[str] = []
    missing_total = 0
    for col in iqm_cols:
        series = to_numeric_iqm(t1[col])
        n_missing = int(series.isna().sum())
        missing_total += n_missing
        valid = series.dropna()
        if n_missing:
            LOGGER.warning("IQM %s has %d missing T1w values", col, n_missing)
        if valid.empty or valid.nunique(dropna=True) <= 1 or float(valid.std(ddof=0)) == 0.0:
            dropped.append(col)
            continue
        kept.append(col)
    if missing_total:
        fail(
            f"T1w IQM block has {missing_total} missing values. "
            "PCA requires a complete numeric matrix; the source TSV was not modified."
        )
    if len(kept) != N_T1W_USABLE:
        fail(
            f"Expected {N_T1W_USABLE} non-constant T1w IQMs, found {len(kept)}. "
            f"Dropped zero-variance columns: {dropped}"
        )
    if not dropped:
        fail("No zero-variance T1w IQMs were found; expected qi_1 and summary_bg_p05.")
    return kept, dropped


def standardize(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Column-wise z-score matching sklearn StandardScaler (ddof=0)."""
    mean = x.mean(axis=0)
    scale = x.std(axis=0, ddof=0)
    if np.any(scale <= 0):
        bad = np.where(scale <= 0)[0].tolist()
        fail(f"Zero scale after numeric conversion for column indices {bad}.")
    return (x - mean) / scale, mean, scale


def svd_flip(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Match sklearn.utils.extmath.svd_flip (sign of max |U| per component)."""
    max_abs = np.argmax(np.abs(u), axis=0)
    signs = np.sign(u[max_abs, range(u.shape[1])])
    signs = np.where(signs == 0.0, 1.0, signs)
    return u * signs, v * signs[:, np.newaxis]


def pca_numpy(x_std: np.ndarray) -> dict[str, np.ndarray]:
    n_samples = x_std.shape[0]
    u, s, vt = np.linalg.svd(x_std, full_matrices=False)
    u, vt = svd_flip(u, vt)
    explained_variance = (s ** 2) / (n_samples - 1)
    total = float(explained_variance.sum())
    if total <= 0:
        fail("Total PCA variance is zero.")
    ratio = explained_variance / total
    scores = u * s
    return {
        "scores": scores,
        "loadings": vt.T,
        "singular_values": s,
        "explained_variance": explained_variance,
        "explained_variance_ratio": ratio,
        "cumulative_ratio": np.cumsum(ratio),
    }


def pca_sklearn(x: np.ndarray) -> dict[str, np.ndarray]:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler(with_mean=True, with_std=True)
    x_std = scaler.fit_transform(x)
    pca = PCA(svd_solver="full")
    scores = pca.fit_transform(x_std)
    return {
        "scores": scores,
        "loadings": pca.components_.T,
        "singular_values": pca.singular_values_,
        "explained_variance": pca.explained_variance_,
        "explained_variance_ratio": pca.explained_variance_ratio_,
        "cumulative_ratio": np.cumsum(pca.explained_variance_ratio_),
        "scaler_mean": scaler.mean_,
        "scaler_scale": scaler.scale_,
        "x_std": x_std,
    }


def n_components_for(cumulative: np.ndarray, threshold: float) -> int:
    hits = np.where(cumulative >= threshold)[0]
    if hits.size == 0:
        fail(f"Cumulative variance never reaches {threshold:.0%}.")
    return int(hits[0] + 1)


def run_pca(x: np.ndarray, use_sklearn: bool) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, np.ndarray]:
    x_std, mean, scale = standardize(x)
    if use_sklearn:
        result = pca_sklearn(x)
        return result, result["x_std"], result["scaler_mean"], result["scaler_scale"]
    result = pca_numpy(x_std)
    return result, x_std, mean, scale


def verify_reproducibility(x: np.ndarray, result: dict[str, np.ndarray], use_sklearn: bool) -> float:
    again, _, _, _ = run_pca(x, use_sklearn)
    delta = float(np.max(np.abs(again["scores"] - result["scores"])))
    if not np.isfinite(delta) or delta > 1e-10:
        fail(f"PCA scores are not reproducible (max |Δ| = {delta}).")
    return delta


def plot_variance(variance: pd.DataFrame, n_marks: dict[str, int], dest_png: Path, dest_pdf: Path) -> None:
    fig, ax1 = plt.subplots(figsize=(8.5, 4.5))
    idx = np.arange(1, len(variance) + 1)
    ax1.bar(idx, variance["explained_variance_ratio"] * 100.0, color="#4C78A8", width=0.8)
    ax1.set_xlabel("Principal component")
    ax1.set_ylabel("Variance explained (%)")
    ax2 = ax1.twinx()
    ax2.plot(idx, variance["cumulative_ratio"] * 100.0, color="#F58518", lw=1.8)
    ax2.set_ylabel("Cumulative variance explained (%)")
    ax2.set_ylim(0, 105)
    colors = {"80%": "#59A14F", "90%": "#E45756", "95%": "#B279A2"}
    for label, n in n_marks.items():
        ax2.axvline(n, color=colors[label], ls="--", lw=1, label=f"{label}: PC{n}")
    ax2.legend(frameon=False, loc="lower right", fontsize=8)
    ax1.set_title("T1w IQM PCA — variance explained")
    fig.subplots_adjust(left=0.10, right=0.90, bottom=0.14, top=0.90)
    fig.savefig(dest_png, dpi=120)
    fig.savefig(dest_pdf)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest_png)
    LOGGER.info("Wrote %s", dest_pdf)


def plot_loadings(loadings: pd.DataFrame, n_show: int, dest_png: Path, dest_pdf: Path) -> None:
    keep = [c for c in loadings.columns if c.startswith("PC")][:n_show]
    mat = loadings[keep]
    n_iqm, n_pc = mat.shape
    fig_w = max(6.5, 0.45 * n_pc + 3.5)
    fig_h = max(7.0, 0.18 * n_iqm + 1.2)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    vmax = float(np.nanmax(np.abs(mat.to_numpy()))) or 1.0
    im = ax.imshow(
        mat.to_numpy(dtype=float),
        aspect="auto",
        cmap="RdBu_r",
        vmin=-vmax,
        vmax=vmax,
        interpolation="nearest",
    )
    ax.set_xticks(range(n_pc))
    ax.set_xticklabels(keep, fontsize=8)
    ax.set_yticks(range(n_iqm))
    ax.set_yticklabels(mat.index, fontsize=6)
    ax.set_title(f"T1w IQM PCA — loadings (PC1–PC{n_show})")
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("Loading")
    fig.subplots_adjust(left=0.22, right=0.95, bottom=0.08, top=0.94)
    fig.savefig(dest_png, dpi=120)
    fig.savefig(dest_pdf)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest_png)
    LOGGER.info("Wrote %s", dest_pdf)


def write_report(
    path: Path,
    *,
    clean_path: Path,
    src_before: str,
    src_after: str,
    sklearn_ok: bool,
    sklearn_info: str,
    backend: str,
    iqm_all: list[str],
    iqm_used: list[str],
    iqm_dropped: list[str],
    n_rows: int,
    n_features: int,
    n_components: int,
    n_marks: dict[str, int],
    variance: pd.DataFrame,
    n_missing: int,
    score_delta: float,
    scaled_mean_max: float,
    scaled_sd_delta: float,
) -> None:
    lines = [
        "MRIQC T1w IQM exploratory PCA report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "SCOPE",
        "  sequence_group: T1w only",
        "  WM-nulled: not analysed",
        "  outliers: not removed",
        "  MRIQC flags: not used as exclusions",
        "  cohort tests / inferential statistics / ML / t-SNE / UMAP: not run",
        "  biological interpretation: not made",
        f"  source TSV: {clean_path}",
        f"  source sha256 before: {src_before}",
        f"  source sha256 after:  {src_after}",
        f"  source unmodified: {src_before == src_after}",
        "",
        "DEPENDENCY",
        f"  scikit-learn available: {sklearn_ok}",
        f"  scikit-learn detail: {sklearn_info}",
        f"  PCA backend: {backend}",
        "  standardization: column z-score, population SD (ddof=0), matching StandardScaler",
        "  SVD sign convention: sklearn svd_flip (max |U| per component)",
        "",
        "MATRIX",
        f"  n_acquisitions: {n_rows}",
        f"  n_retained_iqms_in_table: {len(iqm_all)}",
        f"  n_iqms_dropped_zero_variance: {len(iqm_dropped)} {iqm_dropped}",
        f"  n_iqms_used: {n_features}",
        f"  n_components: {n_components}",
        f"  scores_shape: {n_rows} x {n_components}",
        f"  loadings_shape: {n_features} x {n_components}",
        f"  n_missing_values_in_pca_matrix: {n_missing}",
        f"  max_abs_standardized_feature_mean: {scaled_mean_max:.3e}",
        f"  max_abs_standardized_feature_sd_minus_1: {scaled_sd_delta:.3e}",
        f"  reproducibility_max_abs_score_delta: {score_delta}",
        "",
        "IQMs USED",
        f"  {', '.join(iqm_used)}",
        "",
        "VARIANCE THRESHOLDS (smallest k with cumulative ratio >= threshold)",
        f"  80%: {n_marks['80%']} components ({variance.loc[n_marks['80%'] - 1, 'cumulative_ratio']:.6f})",
        f"  90%: {n_marks['90%']} components ({variance.loc[n_marks['90%'] - 1, 'cumulative_ratio']:.6f})",
        f"  95%: {n_marks['95%']} components ({variance.loc[n_marks['95%'] - 1, 'cumulative_ratio']:.6f})",
        f"  PC1 variance ratio: {variance.loc[0, 'explained_variance_ratio']:.6f}",
        "",
        "OUTPUTS",
        "  pca_T1w_scores.tsv",
        "  pca_T1w_loadings.tsv",
        "  pca_T1w_variance.tsv",
        "  pca_T1w_variance.png/.pdf",
        "  pca_T1w_loadings.png/.pdf",
        "  pca_T1w_report.txt",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    LOGGER.info("T1w IQM exploratory PCA")

    sklearn_ok, sklearn_info = detect_sklearn()
    if sklearn_ok:
        backend = f"sklearn.decomposition.PCA (svd_solver=full) {sklearn_info}"
        LOGGER.info("Using scikit-learn %s", sklearn_info)
    else:
        backend = "numpy.linalg.svd (sklearn unavailable; implementation matches sklearn full SVD)"
        LOGGER.warning("scikit-learn is not available (%s). Using NumPy SVD fallback.", sklearn_info)

    src_before = file_sha256(args.clean_tsv)
    t1 = load_t1w(args.clean_tsv)
    iqm_all = retained_iqm_columns(t1, args.roles_tsv)
    iqm_used, iqm_dropped = select_pca_columns(t1, iqm_all)

    x = np.column_stack([to_numeric_iqm(t1[c]).to_numpy(dtype=float) for c in iqm_used])
    if x.shape != (N_T1W_ROWS, N_T1W_USABLE):
        fail(f"PCA matrix shape {x.shape} != ({N_T1W_ROWS}, {N_T1W_USABLE})")
    if not np.isfinite(x).all():
        fail("Non-finite values in the T1w IQM matrix.")
    n_missing = int(np.isnan(x).sum())

    result, x_std, mean, scale = run_pca(x, sklearn_ok)
    if x_std.shape != x.shape:
        fail(f"Standardized matrix shape {x_std.shape} != {x.shape}")
    if np.max(np.abs(x_std.mean(axis=0))) > 1e-10:
        fail("Standardized IQMs do not have mean 0.")
    if np.max(np.abs(x_std.std(axis=0, ddof=0) - 1.0)) > 1e-10:
        fail("Standardized IQMs do not have SD 1.")

    n_rows, n_components = result["scores"].shape
    n_features = result["loadings"].shape[0]
    if result["loadings"].shape != (n_features, n_components):
        fail(f"Loadings shape {result['loadings'].shape} is inconsistent.")
    if n_rows != N_T1W_ROWS or n_features != N_T1W_USABLE:
        fail(f"Unexpected PCA dimensions scores={result['scores'].shape} loadings={result['loadings'].shape}")
    if n_components != min(n_rows, n_features):
        fail(f"Expected {min(n_rows, n_features)} components, found {n_components}.")

    score_delta = verify_reproducibility(x, result, sklearn_ok)
    LOGGER.info("Reproducibility max |Δ scores| = %.3e", score_delta)

    pc_names = [f"PC{i}" for i in range(1, n_components + 1)]
    scores = t1.loc[:, list(ID_COLS)].reset_index(drop=True).copy()
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

    args.out_dir.mkdir(parents=True, exist_ok=True)
    scores_path = args.out_dir / "pca_T1w_scores.tsv"
    loadings_path = args.out_dir / "pca_T1w_loadings.tsv"
    variance_path = args.out_dir / "pca_T1w_variance.tsv"
    scores.to_csv(scores_path, sep="\t", index=False, float_format="%.10g")
    loadings.to_csv(loadings_path, sep="\t", float_format="%.10g")
    variance.to_csv(variance_path, sep="\t", index=False, float_format="%.10g")
    LOGGER.info("Wrote %s", scores_path)
    LOGGER.info("Wrote %s", loadings_path)
    LOGGER.info("Wrote %s", variance_path)

    plot_variance(
        variance,
        n_marks,
        args.out_dir / "pca_T1w_variance.png",
        args.out_dir / "pca_T1w_variance.pdf",
    )
    plot_loadings(
        loadings,
        n_show=n_marks["95%"],
        dest_png=args.out_dir / "pca_T1w_loadings.png",
        dest_pdf=args.out_dir / "pca_T1w_loadings.pdf",
    )

    src_after = file_sha256(args.clean_tsv)
    if src_before != src_after:
        fail(f"Source TSV changed during the run: {args.clean_tsv}")

    write_report(
        args.out_dir / "pca_T1w_report.txt",
        clean_path=args.clean_tsv,
        src_before=src_before,
        src_after=src_after,
        sklearn_ok=sklearn_ok,
        sklearn_info=sklearn_info,
        backend=backend,
        iqm_all=iqm_all,
        iqm_used=iqm_used,
        iqm_dropped=iqm_dropped,
        n_rows=n_rows,
        n_features=n_features,
        n_components=n_components,
        n_marks=n_marks,
        variance=variance,
        n_missing=n_missing,
        score_delta=score_delta,
        scaled_mean_max=float(np.max(np.abs(x_std.mean(axis=0)))),
        scaled_sd_delta=float(np.max(np.abs(x_std.std(axis=0, ddof=0) - 1.0))),
    )

    print()
    print("N T1w acquisitions:", n_rows)
    print("N IQMs used:", n_features)
    print("N IQMs dropped (zero variance):", len(iqm_dropped), iqm_dropped)
    print("N components:", n_components)
    print("N components for 80%:", n_marks["80%"])
    print("N components for 90%:", n_marks["90%"])
    print("N components for 95%:", n_marks["95%"])
    print("scikit-learn:", "yes" if sklearn_ok else f"NO ({sklearn_info})")
    print("PCA backend:", backend)
    print("source TSV unmodified: yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
