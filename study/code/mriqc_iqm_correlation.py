#!/usr/bin/env python3
"""Spearman correlations between retained anatomical IQMs, by sequence_group.

T1w and WM-nulled are analysed separately. Outlier acquisitions are never
dropped. Constant / missing columns are handled in memory only; the source
TSV is not modified.

Example:
  python code/mriqc_iqm_correlation.py
  python code/mriqc_iqm_correlation.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
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
    EXPECTED_SEQUENCE_GROUPS,
    analytic_iqm_columns,
    fail,
    require_columns,
    require_file,
    to_numeric_iqm,
)

LOGGER = logging.getLogger("mriqc_iqm.correlation")
N_RETAINED_IQMS = 58
MIN_PAIRWISE_N = 3
EXPECTED_GROUP_N = {"T1w": 264, "WMn": 116}


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
            "Does not run PCA, cohort tests, or machine learning. "
            "Does not rewrite metadata/mriqc_iqm_clean.tsv."
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


def _betacf(a: float, b: float, x: float) -> float:
    maxit = 200
    eps = 3.0e-7
    fpmin = 1.0e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    fail("Incomplete-beta continued fraction did not converge (t-distribution CDF).")
    raise AssertionError("unreachable")


def _betai(a: float, b: float, x: float) -> float:
    if x < 0.0 or x > 1.0 or not math.isfinite(x):
        return float("nan")
    if x == 0.0 or x == 1.0:
        bt = 0.0
    else:
        bt = math.exp(
            math.lgamma(a + b)
            - math.lgamma(a)
            - math.lgamma(b)
            + a * math.log(x)
            + b * math.log(1.0 - x)
        )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def spearman_pvalue(r: float, n: int) -> float:
    """Two-sided p-value for Spearman rho via the t approximation (df = n-2)."""
    if n < MIN_PAIRWISE_N or not math.isfinite(r):
        return float("nan")
    if abs(r) >= 1.0:
        return 0.0
    df = n - 2
    t_stat = r * math.sqrt(df / (1.0 - r * r))
    if not math.isfinite(t_stat):
        return float("nan")
    x = df / (df + t_stat * t_stat)
    return float(_betai(0.5 * df, 0.5, x))


def pearson_on_ranks(x: np.ndarray, y: np.ndarray) -> float:
    x = x - x.mean()
    y = y - y.mean()
    ssx = float(np.dot(x, x))
    ssy = float(np.dot(y, y))
    if ssx <= 0.0 or ssy <= 0.0:
        return float("nan")
    return float(np.dot(x, y) / math.sqrt(ssx * ssy))


def retained_iqm_columns(clean: pd.DataFrame, roles_path: Path) -> list[str]:
    require_file(roles_path, "column-role table")
    roles = pd.read_csv(roles_path, sep="\t")
    require_columns(roles, ["column", "retained_for_statistics"], "column-role table")
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
        extra = sorted(set(inferred) - set(retained))
        dropped = sorted(set(retained) - set(inferred))
        fail(
            "Retained IQM list disagrees with analytic_iqm_columns(). "
            f"extra={extra} missing_from_inferred={dropped}"
        )
    technical = roles.loc[roles["role"].astype(str) == "technical", "column"].tolist()
    leaked = [c for c in technical if c in retained]
    if leaked:
        fail(f"Technical columns were listed as retained IQMs: {leaked}")
    return retained


def load_clean(path: Path) -> pd.DataFrame:
    require_file(path, "clean IQM table")
    df = pd.read_csv(path, sep="\t")
    require_columns(df, ["sequence_group"], "clean IQM table")
    if df.empty:
        fail(f"Clean IQM table is empty: {path}")
    extra = sorted(set(df["sequence_group"].astype(str)) - set(EXPECTED_SEQUENCE_GROUPS))
    if extra:
        fail(f"Unexpected sequence_group values: {extra}")
    missing_groups = [g for g in EXPECTED_SEQUENCE_GROUPS if g not in set(df["sequence_group"])]
    if missing_groups:
        fail(f"Clean table is missing sequence_group(s): {missing_groups}")
    LOGGER.info("Loaded clean table: %s (%d rows, %d cols)", path, len(df), df.shape[1])
    return df


def numeric_block(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    block = pd.DataFrame({c: to_numeric_iqm(df[c]) for c in columns}, index=df.index)
    return block


def constant_or_empty(series: pd.Series) -> str | None:
    valid = series.dropna()
    if valid.empty:
        return "all_missing"
    if valid.nunique(dropna=True) <= 1 or float(valid.std(ddof=0)) == 0.0:
        return "zero_variance"
    return None


def spearman_matrices(block: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cols = list(block.columns)
    n_col = len(cols)
    rho = np.full((n_col, n_col), np.nan)
    pval = np.full((n_col, n_col), np.nan)
    nobs = np.full((n_col, n_col), np.nan)
    values = [block[c].to_numpy(dtype=float) for c in cols]
    ranks_cache: dict[tuple[int, tuple[int, ...]], np.ndarray] = {}

    def ranks_for(col_i: int, mask: np.ndarray) -> np.ndarray:
        key = (col_i, tuple(np.flatnonzero(mask)))
        cached = ranks_cache.get(key)
        if cached is None:
            cached = pd.Series(values[col_i][mask]).rank(method="average").to_numpy(dtype=float)
            ranks_cache[key] = cached
        return cached

    for i in range(n_col):
        for j in range(i, n_col):
            finite = np.isfinite(values[i]) & np.isfinite(values[j])
            n = int(finite.sum())
            nobs[i, j] = nobs[j, i] = n
            if n < MIN_PAIRWISE_N:
                continue
            rx = ranks_for(i, finite)
            ry = ranks_for(j, finite)
            r = pearson_on_ranks(rx, ry)
            if i == j:
                rho[i, j] = 1.0 if math.isfinite(r) else float("nan")
                pval[i, j] = float("nan")
                continue
            if math.isfinite(r):
                r = max(-1.0, min(1.0, r))
            rho[i, j] = rho[j, i] = r
            p = spearman_pvalue(r, n)
            pval[i, j] = pval[j, i] = p
    index = cols
    return (
        pd.DataFrame(rho, index=index, columns=index),
        pd.DataFrame(pval, index=index, columns=index),
        pd.DataFrame(nobs, index=index, columns=index),
    )


def group_summary(name: str, raw: pd.DataFrame, block: pd.DataFrame) -> dict:
    flags = {c: constant_or_empty(block[c]) for c in block.columns}
    n_missing = {c: int(block[c].isna().sum()) for c in block.columns if int(block[c].isna().sum())}
    constant = [c for c, flag in flags.items() if flag == "zero_variance"]
    empty = [c for c, flag in flags.items() if flag == "all_missing"]
    usable = [c for c, flag in flags.items() if flag is None]
    expected = EXPECTED_GROUP_N.get(name)
    if expected is not None and len(raw) != expected:
        fail(
            f"{name}: expected {expected} acquisitions in the clean table, found {len(raw)}. "
            "Refusing to drop or impute rows."
        )
    return {
        "sequence_group": name,
        "n_acquisitions": int(len(raw)),
        "n_iqms_in_matrix": int(block.shape[1]),
        "n_iqms_usable": len(usable),
        "n_iqms_zero_variance": len(constant),
        "n_iqms_all_missing": len(empty),
        "zero_variance_iqms": constant,
        "all_missing_iqms": empty,
        "usable_iqms": usable,
        "missing_counts": n_missing,
        "n_missing_values_total": int(block.isna().sum().sum()),
    }


def plot_matrix(
    mat: pd.DataFrame,
    title: str,
    dest_png: Path,
    dest_pdf: Path,
    vmin: float,
    vmax: float,
    cmap: str,
    cbar_label: str,
) -> None:
    n = len(mat.columns)
    fig_w = min(14.0, max(7.0, 0.22 * n + 1.5))
    fig, ax = plt.subplots(figsize=(fig_w, fig_w * 0.9))
    arr = mat.to_numpy(dtype=float)
    masked = np.ma.masked_invalid(arr)
    cmap_obj = plt.get_cmap(cmap).copy()
    cmap_obj.set_bad(color="#d9d9d9")
    im = ax.imshow(
        masked,
        vmin=vmin,
        vmax=vmax,
        cmap=cmap_obj,
        aspect="auto",
        interpolation="nearest",
    )
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    fontsize = 5 if n > 30 else 7
    ax.set_xticklabels(mat.columns, rotation=90, fontsize=fontsize)
    ax.set_yticklabels(mat.index, fontsize=fontsize)
    ax.set_title(title)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(cbar_label)
    fig.subplots_adjust(bottom=0.22, left=0.22)
    fig.savefig(dest_png, dpi=120)
    fig.savefig(dest_pdf)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest_png)
    LOGGER.info("Wrote %s", dest_pdf)


def write_matrix(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, sep="\t", float_format="%.10g")
    LOGGER.info("Wrote %s", path)


def validate_matrix(rho: pd.DataFrame, pval: pd.DataFrame, nobs: pd.DataFrame, n_iqm: int, group: str) -> None:
    for name, mat in (("rho", rho), ("p", pval), ("n", nobs)):
        if mat.shape != (n_iqm, n_iqm):
            fail(f"{group} {name} matrix shape {mat.shape} != ({n_iqm}, {n_iqm})")
        if list(mat.index) != list(mat.columns):
            fail(f"{group} {name} matrix index/columns mismatch")
    off = ~np.eye(n_iqm, dtype=bool)
    rho_v = rho.to_numpy(dtype=float)
    p_v = pval.to_numpy(dtype=float)
    if not np.allclose(rho_v, rho_v.T, equal_nan=True):
        fail(f"{group} Spearman matrix is not symmetric")
    if not np.allclose(p_v, p_v.T, equal_nan=True):
        fail(f"{group} p-value matrix is not symmetric")
    finite_r = rho_v[np.isfinite(rho_v)]
    if finite_r.size and (np.abs(finite_r).max() > 1.0 + 1e-8):
        fail(f"{group} Spearman |rho| > 1")
    finite_p = p_v[np.isfinite(p_v)]
    if finite_p.size and ((finite_p.min() < -1e-12) or (finite_p.max() > 1.0 + 1e-12)):
        fail(f"{group} p-values outside [0, 1]")
    diag = np.diag(rho_v)
    bad_diag = np.isfinite(diag) & (np.abs(diag - 1.0) > 1e-8)
    if bad_diag.any():
        fail(f"{group} Spearman diagonal is not 1 for varying IQMs")
    if np.isfinite(np.diag(p_v)).any():
        fail(f"{group} p-value diagonal must be NaN (self-correlation is not tested)")
    if off.any() and np.isfinite(rho_v[off]).sum() == 0:
        fail(f"{group} Spearman matrix has no finite off-diagonal values")


def render_report(
    path: Path,
    clean_path: Path,
    src_hash_before: str,
    src_hash_after: str,
    iqm_cols: list[str],
    summaries: dict[str, dict],
    matrices: dict[str, dict[str, pd.DataFrame]],
) -> None:
    lines = [
        "MRIQC anatomical IQM Spearman correlation report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "SCOPE",
        "  method: Spearman rank correlation (average ranks for ties)",
        "  p-values: two-sided t approximation, df = n_pairwise - 2",
        "  pairwise complete observations; no listwise deletion of acquisitions",
        "  outliers: not removed",
        "  T1w and WM-nulled: separate matrices, never pooled",
        "  PCA / cohort tests / ML: not run",
        f"  source TSV: {clean_path}",
        f"  source sha256 before: {src_hash_before}",
        f"  source sha256 after:  {src_hash_after}",
        f"  source unmodified: {src_hash_before == src_hash_after}",
        "",
        "IQMs IN EVERY MATRIX",
        f"  n_iqms: {len(iqm_cols)}",
        f"  variables: {', '.join(iqm_cols)}",
        "",
    ]
    for group in EXPECTED_SEQUENCE_GROUPS:
        summary = summaries[group]
        nobs = matrices[group]["n"]
        rho = matrices[group]["rho"]
        off = ~np.eye(len(iqm_cols), dtype=bool)
        n_off = nobs.to_numpy(dtype=float)[off]
        n_off = n_off[np.isfinite(n_off)]
        rho_off = rho.to_numpy(dtype=float)[off]
        n_finite_r = int(np.isfinite(rho_off).sum())
        n_nan_r = int(np.isnan(rho_off).sum())
        lines.extend(
            [
                f"{group}",
                f"  n_acquisitions: {summary['n_acquisitions']}",
                f"  matrix_shape: {len(iqm_cols)} x {len(iqm_cols)}",
                f"  n_iqms_usable: {summary['n_iqms_usable']}",
                f"  n_iqms_zero_variance: {summary['n_iqms_zero_variance']} {summary['zero_variance_iqms']}",
                f"  n_iqms_all_missing: {summary['n_iqms_all_missing']} {summary['all_missing_iqms']}",
                f"  n_missing_values_total: {summary['n_missing_values_total']}",
                f"  missing_by_column: {summary['missing_counts'] or 'none'}",
                f"  pairwise_n_min: {int(n_off.min()) if n_off.size else 'NA'}",
                f"  pairwise_n_max: {int(n_off.max()) if n_off.size else 'NA'}",
                f"  off_diagonal_finite_rho: {n_finite_r}",
                f"  off_diagonal_nan_rho: {n_nan_r}",
                "",
            ]
        )
    lines.extend(
        [
            "OUTPUTS",
            "  spearman_T1w.tsv / spearman_T1w_pvalues.tsv",
            "  spearman_WMn.tsv / spearman_WMn_pvalues.tsv",
            "  spearman_T1w.png/.pdf, spearman_T1w_pvalues.png/.pdf",
            "  spearman_WMn.png/.pdf, spearman_WMn_pvalues.png/.pdf",
            "",
            "Constant IQMs remain in the 58 x 58 matrices as NaN (except a NaN",
            "diagonal p-value). They are listed above and were not dropped from",
            "the source table.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    LOGGER.info("Spearman IQM correlations by sequence_group")

    src_hash_before = file_sha256(args.clean_tsv)
    clean = load_clean(args.clean_tsv)
    iqm_cols = retained_iqm_columns(clean, args.roles_tsv)
    LOGGER.info("Using %d retained IQMs", len(iqm_cols))

    args.out_dir.mkdir(parents=True, exist_ok=True)

    summaries: dict[str, dict] = {}
    matrices: dict[str, dict[str, pd.DataFrame]] = {}
    for group in EXPECTED_SEQUENCE_GROUPS:
        subset = clean.loc[clean["sequence_group"].astype(str) == group].copy()
        if subset.empty:
            fail(f"No rows for sequence_group={group}")
        block = numeric_block(subset, iqm_cols)
        summaries[group] = group_summary(group, subset, block)
        LOGGER.info(
            "%s: %d acquisitions, %d usable IQMs, %d zero-variance, missing values=%d",
            group,
            summaries[group]["n_acquisitions"],
            summaries[group]["n_iqms_usable"],
            summaries[group]["n_iqms_zero_variance"],
            summaries[group]["n_missing_values_total"],
        )
        rho, pval, nobs = spearman_matrices(block)
        validate_matrix(rho, pval, nobs, len(iqm_cols), group)
        matrices[group] = {"rho": rho, "p": pval, "n": nobs}

        stem = f"spearman_{group}"
        write_matrix(rho, args.out_dir / f"{stem}.tsv")
        write_matrix(pval, args.out_dir / f"{stem}_pvalues.tsv")
        plot_matrix(
            rho,
            f"Spearman IQM correlation — {group}",
            args.out_dir / f"{stem}.png",
            args.out_dir / f"{stem}.pdf",
            vmin=-1.0,
            vmax=1.0,
            cmap="RdBu_r",
            cbar_label="Spearman ρ",
        )
        plot_matrix(
            pval,
            f"Spearman p-values — {group}",
            args.out_dir / f"{stem}_pvalues.png",
            args.out_dir / f"{stem}_pvalues.pdf",
            vmin=0.0,
            vmax=1.0,
            cmap="viridis_r",
            cbar_label="p-value",
        )

    src_hash_after = file_sha256(args.clean_tsv)
    if src_hash_before != src_hash_after:
        fail(f"Source TSV changed during the run: {args.clean_tsv}")

    report_path = args.out_dir / "correlation_report.txt"
    render_report(
        report_path,
        args.clean_tsv,
        src_hash_before,
        src_hash_after,
        iqm_cols,
        summaries,
        matrices,
    )

    print()
    print("sequence_group T1w rows:", summaries["T1w"]["n_acquisitions"])
    print("sequence_group WMn rows:", summaries["WMn"]["n_acquisitions"])
    print("N IQMs in each matrix:", len(iqm_cols))
    print("T1w zero-variance IQMs:", summaries["T1w"]["zero_variance_iqms"] or "none")
    print("WMn zero-variance IQMs:", summaries["WMn"]["zero_variance_iqms"] or "none")
    print("source TSV unmodified: yes")
    print("report:", report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
