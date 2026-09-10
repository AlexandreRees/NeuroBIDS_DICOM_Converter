#!/usr/bin/env python3
"""ÉTAPE 2 — Clean and characterize anatomical MRIQC IQMs.

Identifies true IQM columns, documents missingness / zero-variance /
robust outliers, and compares T1w vs WM-nulled structure.

Does NOT drop outliers. Does NOT run PCA, ICA, t-SNE, UMAP, Elastic Net,
cohort tests, or longitudinal models.

Example:
  python code/mriqc_iqm_cleaning.py
  python code/mriqc_iqm_cleaning.py --help
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import (
    DEFAULT_SCRATCH,
    EXPECTED_COHORTS,
    EXPECTED_SEQUENCE_GROUPS,
    IQR_K,
    LOGGER,
    MAIN_IQMS_FOR_PLOTS,
    NEAR_ZERO_REL_SD,
    ROBUST_Z_THRESH,
    analytic_iqm_columns,
    classify_column,
    configure_logging,
    default_paths,
    fail,
    iqm_family,
    iqr_outlier_mask,
    require_columns,
    require_file,
    robust_z,
    technical_columns,
    to_numeric_iqm,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    paths = default_paths(DEFAULT_SCRATCH)
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "T1w and WM-nulled are characterized separately. Outliers are "
            "flagged with IQR and robust z-score but never deleted."
        ),
    )
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--master-tsv", type=Path, default=None)
    parser.add_argument("--clean-tsv", type=Path, default=None)
    parser.add_argument("--figures-dir", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument(
        "--near-zero-rel-sd",
        type=float,
        default=NEAR_ZERO_REL_SD,
        help="Relative SD threshold (|SD|/(|mean|+eps)) for quasi-null variance.",
    )
    parser.add_argument("--iqr-k", type=float, default=IQR_K)
    parser.add_argument("--robust-z", type=float, default=ROBUST_Z_THRESH)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    study = args.study_root or paths["study"]
    args.study_root = study
    args.master_tsv = args.master_tsv or (study / "metadata" / "mriqc_iqm_master.tsv")
    args.clean_tsv = args.clean_tsv or (study / "metadata" / "mriqc_iqm_clean.tsv")
    args.figures_dir = args.figures_dir or (study / "qc_reports" / "mriqc_iqm")
    args.report = args.report or (study / "qc_reports" / "mriqc_iqm_cleaning_report.txt")
    args.log_file = args.log_file or (study / "qc_reports" / "mriqc_iqm_cleaning.log")
    args.meta_dir = study / "metadata"
    return args


def load_master(path: Path) -> pd.DataFrame:
    require_file(path, "master dataframe")
    df = pd.read_csv(path, sep="\t")
    require_columns(
        df,
        [
            "subject_id",
            "session",
            "cohort",
            "sequence_group",
            "modality",
            "run",
            "mriqc_source_file",
        ],
        "master dataframe",
    )
    if df.empty:
        fail("Master dataframe is empty.")
    if (df["modality"].astype(str) != "anat").any():
        fail("Master dataframe contains non-anat rows; refusing to mix fMRI.")
    unknown = sorted(set(df["sequence_group"].astype(str)) - set(EXPECTED_SEQUENCE_GROUPS))
    if unknown:
        fail(f"Unexpected sequence_group values: {unknown}")
    unknown_c = sorted(set(df["cohort"].dropna().astype(str)) - set(EXPECTED_COHORTS))
    if unknown_c:
        fail(f"Unexpected cohort values: {unknown_c}")
    key = ["subject_id", "session", "sequence_group", "run"]
    dups = df.duplicated(key, keep=False)
    if dups.any():
        fail(
            "Ambiguous duplicate subject/session/sequence_group/run in master:\n"
            + df.loc[dups, key + ["input_file"]].to_string(index=False)
        )
    LOGGER.info("Loaded master: %s (%d rows)", path, len(df))
    return df


def describe_series(x: pd.Series) -> dict[str, Any]:
    v = to_numeric_iqm(x)
    n_total = int(len(v))
    n_valid = int(v.notna().sum())
    n_missing = n_total - n_valid
    missing_pct = 100.0 * n_missing / n_total if n_total else np.nan
    if n_valid == 0:
        return {
            "n": n_valid,
            "n_total": n_total,
            "missing": n_missing,
            "missing_pct": missing_pct,
            "mean": np.nan,
            "sd": np.nan,
            "median": np.nan,
            "iqr": np.nan,
            "min": np.nan,
            "max": np.nan,
            "p01": np.nan,
            "p99": np.nan,
            "variance": np.nan,
        }
    q1 = float(v.quantile(0.25))
    q3 = float(v.quantile(0.75))
    return {
        "n": n_valid,
        "n_total": n_total,
        "missing": n_missing,
        "missing_pct": missing_pct,
        "mean": float(v.mean()),
        "sd": float(v.std(ddof=1)) if n_valid > 1 else 0.0,
        "median": float(v.median()),
        "iqr": float(q3 - q1),
        "min": float(v.min()),
        "max": float(v.max()),
        "p01": float(v.quantile(0.01)),
        "p99": float(v.quantile(0.99)),
        "variance": float(v.var(ddof=1)) if n_valid > 1 else 0.0,
    }


def variance_flags(stats: dict[str, Any], rel_sd: float) -> tuple[bool, bool]:
    n = stats["n"]
    sd = stats["sd"]
    mean = stats["mean"]
    var = stats["variance"]
    if n == 0 or pd.isna(sd) or pd.isna(var):
        return False, False
    zero = var == 0 or sd == 0
    rel = abs(sd) / (abs(mean) + 1e-12)
    near = (not zero) and rel < rel_sd
    return zero, near


def catalog_and_descriptives(
    df: pd.DataFrame,
    iqm_cols: list[str],
    rel_sd: float,
    iqr_k: float,
    z_thresh: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    catalog_rows = []
    desc_rows = []
    outlier_rows = []

    splits: list[tuple[str, str, pd.DataFrame]] = [("all", "all", df)]
    for g in EXPECTED_SEQUENCE_GROUPS:
        splits.append(("sequence_group", g, df.loc[df["sequence_group"] == g]))
    for g in EXPECTED_COHORTS:
        splits.append(("cohort", g, df.loc[df["cohort"] == g]))
    for g in sorted(df["session"].dropna().astype(str).unique()):
        splits.append(("session", g, df.loc[df["session"].astype(str) == g]))

    for col in iqm_cols:
        # Primary catalog is within each sequence_group plus overall.
        overall = describe_series(df[col])
        zero, near = variance_flags(overall, rel_sd)
        miss = overall["missing_pct"]
        n_out_iqr_all = 0
        n_out_z_all = 0
        n_out_union_all = 0
        # Outliers are computed within sequence_group so T1w vs WMn scale
        # differences are not treated as anomalies.
        flagged_index = set()
        for group in EXPECTED_SEQUENCE_GROUPS:
            sub = df.loc[df["sequence_group"] == group]
            if sub.empty:
                continue
            iqr_m = iqr_outlier_mask(sub[col], k=iqr_k)
            z = robust_z(sub[col])
            z_m = z.abs() > z_thresh
            z_m = z_m.fillna(False)
            union = iqr_m | z_m
            n_out_iqr_all += int(iqr_m.sum())
            n_out_z_all += int(z_m.sum())
            n_out_union_all += int(union.sum())
            for idx in sub.index[union]:
                flagged_index.add(idx)
                outlier_rows.append(
                    {
                        "subject_id": df.at[idx, "subject_id"],
                        "session": df.at[idx, "session"],
                        "sequence_group": df.at[idx, "sequence_group"],
                        "run": df.at[idx, "run"],
                        "mriqc_source_file": df.at[idx, "mriqc_source_file"],
                        "iqm": col,
                        "value": to_numeric_iqm(pd.Series([df.at[idx, col]])).iloc[0],
                        "outlier_iqr": bool(iqr_m.loc[idx]),
                        "outlier_robust_z": bool(z_m.loc[idx]),
                        "robust_z": float(z.loc[idx]) if pd.notna(z.loc[idx]) else np.nan,
                        "split": f"sequence_group={group}",
                    }
                )
        catalog_rows.append(
            {
                "iqm": col,
                "family": iqm_family(col),
                "role": "iqm",
                "n_valid": overall["n"],
                "missing": overall["missing"],
                "missing_pct": overall["missing_pct"],
                "missing_gt_0": miss > 0,
                "missing_gt_5": miss > 5,
                "missing_gt_10": miss > 10,
                "variance": overall["variance"],
                "sd": overall["sd"],
                "zero_variance": zero,
                "near_zero_variance": near,
                "n_outliers_iqr_within_sequence": n_out_iqr_all,
                "n_outliers_robust_z_within_sequence": n_out_z_all,
                "n_outliers_union_within_sequence": n_out_union_all,
                "n_acquisitions_flagged": len(flagged_index),
            }
        )

        for split_name, split_value, sub in splits:
            stats = describe_series(sub[col] if not sub.empty else pd.Series(dtype=float))
            zflag, nflag = variance_flags(stats, rel_sd)
            desc_rows.append(
                {
                    "iqm": col,
                    "family": iqm_family(col),
                    "split": split_name,
                    "split_value": split_value,
                    **stats,
                    "zero_variance": zflag,
                    "near_zero_variance": nflag,
                }
            )

    catalog = pd.DataFrame(catalog_rows)
    descriptives = pd.DataFrame(desc_rows)
    outliers = pd.DataFrame(outlier_rows)
    return catalog, descriptives, outliers


def availability_table(df: pd.DataFrame, iqm_cols: list[str]) -> pd.DataFrame:
    rows = []
    for col in iqm_cols:
        row: dict[str, Any] = {"iqm": col, "family": iqm_family(col)}
        for g in EXPECTED_SEQUENCE_GROUPS:
            sub = df.loc[df["sequence_group"] == g, col]
            v = to_numeric_iqm(sub)
            n = int(len(v))
            n_valid = int(v.notna().sum())
            row[f"{g}_n"] = n
            row[f"{g}_n_valid"] = n_valid
            row[f"{g}_missing_pct"] = 100.0 * (n - n_valid) / n if n else np.nan
            row[f"{g}_variance"] = float(v.var(ddof=1)) if n_valid > 1 else np.nan
        t1 = to_numeric_iqm(df.loc[df["sequence_group"] == "T1w", col])
        wmn = to_numeric_iqm(df.loc[df["sequence_group"] == "WMn", col])
        row["available_in_both"] = bool(t1.notna().any() and wmn.notna().any())
        row["missingness_diff_pp"] = row["T1w_missing_pct"] - row["WMn_missing_pct"]
        rows.append(row)
    return pd.DataFrame(rows)


def correlation_matrices(df: pd.DataFrame, iqm_cols: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    usable = []
    for col in iqm_cols:
        v = to_numeric_iqm(df[col])
        if v.notna().sum() >= 3 and float(v.std(skipna=True) or 0) > 0:
            usable.append(col)
    if not usable:
        fail("No IQM columns with non-null variance for correlation.")
    for method in ("pearson", "spearman"):
        mat = df[usable].apply(to_numeric_iqm).corr(method=method, min_periods=10)
        out[f"all_{method}"] = mat
        for g in EXPECTED_SEQUENCE_GROUPS:
            sub = df.loc[df["sequence_group"] == g, usable].apply(to_numeric_iqm)
            keep = [c for c in usable if sub[c].notna().sum() >= 3 and float(sub[c].std(skipna=True) or 0) > 0]
            out[f"{g}_{method}"] = sub[keep].corr(method=method, min_periods=10)
    return out


def corr_structure_note(mats: dict[str, pd.DataFrame]) -> dict[str, Any]:
    t1 = mats["T1w_spearman"]
    wmn = mats["WMn_spearman"]
    common = [c for c in t1.columns if c in wmn.columns]
    if len(common) < 2:
        return {"common_iqms": len(common), "spearman_frobenius_diff": np.nan}
    a = t1.loc[common, common].to_numpy(dtype=float)
    b = wmn.loc[common, common].to_numpy(dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    diff = a[mask] - b[mask]
    return {
        "common_iqms": len(common),
        "spearman_mean_abs_diff": float(np.mean(np.abs(diff))) if diff.size else np.nan,
        "spearman_frobenius_diff": float(np.sqrt(np.nansum(diff ** 2))) if diff.size else np.nan,
        "note": (
            "T1w and WM-nulled Spearman matrices are compared on shared IQMs. "
            "A large mean absolute difference supports keeping the two sequence "
            "groups in separate later analyses (PCA / models). No biological "
            "interpretation is made here."
        ),
    }


def save_corr_tables(mats: dict[str, pd.DataFrame], meta_dir: Path) -> None:
    meta_dir.mkdir(parents=True, exist_ok=True)
    for name, mat in mats.items():
        dest = meta_dir / f"mriqc_iqm_correlation_{name}.tsv"
        mat.to_csv(dest, sep="\t")
        LOGGER.info("Wrote %s", dest)


def plot_missingness(catalog: pd.DataFrame, dest: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, max(4, 0.18 * len(catalog))))
    order = catalog.sort_values("missing_pct")
    ax.barh(order["iqm"], order["missing_pct"], color="#4C78A8")
    ax.set_xlabel("Missing (%)")
    ax.set_title("Anatomical IQM missingness (T1w + WM-nulled combined)")
    ax.axvline(5, color="#F58518", ls="--", lw=1, label="5%")
    ax.axvline(10, color="#E45756", ls="--", lw=1, label="10%")
    ax.legend(frameon=False)
    fig.savefig(dest, dpi=120, bbox_inches="tight")
    plt.close(fig)
    LOGGER.info("Wrote %s", dest)


def plot_distributions(df: pd.DataFrame, iqm_cols: list[str], dest: Path) -> None:
    cols = [c for c in MAIN_IQMS_FOR_PLOTS if c in iqm_cols]
    if not cols:
        cols = iqm_cols[:12]
    n = len(cols)
    nrows = int(np.ceil(n / 3))
    fig, axes = plt.subplots(nrows, 3, figsize=(11, 2.6 * nrows))
    axes = np.atleast_1d(axes).ravel()
    colors = {"T1w": "#4C78A8", "WMn": "#F58518"}
    for i, col in enumerate(cols):
        ax = axes[i]
        for g in EXPECTED_SEQUENCE_GROUPS:
            v = to_numeric_iqm(df.loc[df["sequence_group"] == g, col]).dropna()
            if v.empty:
                continue
            ax.hist(v, bins=25, alpha=0.55, label=g, color=colors[g], density=True)
        ax.set_title(col, fontsize=10)
        ax.tick_params(labelsize=8)
        if i == 0:
            ax.legend(frameon=False, fontsize=8)
    for j in range(i + 1, len(axes)):
        axes[j].axis("off")
    fig.suptitle("Main IQM distributions by sequence group (density)")
    fig.savefig(dest, dpi=120, bbox_inches="tight")
    plt.close(fig)
    LOGGER.info("Wrote %s", dest)


def plot_t1w_vs_wmn_box(df: pd.DataFrame, iqm_cols: list[str], dest: Path) -> None:
    cols = [c for c in MAIN_IQMS_FOR_PLOTS if c in iqm_cols]
    if not cols:
        return
    n = len(cols)
    nrows = int(np.ceil(n / 3))
    fig, axes = plt.subplots(nrows, 3, figsize=(11, 2.8 * nrows))
    axes = np.atleast_1d(axes).ravel()
    for i, col in enumerate(cols):
        ax = axes[i]
        data = []
        labels = []
        for g in EXPECTED_SEQUENCE_GROUPS:
            v = to_numeric_iqm(df.loc[df["sequence_group"] == g, col]).dropna()
            data.append(v.to_numpy())
            labels.append(g)
        ax.boxplot(data, tick_labels=labels, showfliers=True)
        ax.set_title(col, fontsize=10)
        ax.tick_params(labelsize=8)
    for j in range(i + 1, len(axes)):
        axes[j].axis("off")
    fig.suptitle("T1w vs WM-nulled: main IQMs (outliers shown, not removed)")
    fig.savefig(dest, dpi=120, bbox_inches="tight")
    plt.close(fig)
    LOGGER.info("Wrote %s", dest)


def plot_heatmap(mat: pd.DataFrame, title: str, dest: Path) -> None:
    if mat.empty:
        return
    n = len(mat.columns)
    fig_w = min(14, max(7, 0.22 * n + 1.5))
    fig, ax = plt.subplots(figsize=(fig_w, fig_w * 0.9))
    arr = mat.to_numpy(dtype=float)
    im = ax.imshow(arr, vmin=-1, vmax=1, cmap="RdBu_r", aspect="auto", interpolation="nearest")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    fontsize = 5 if n > 30 else 7
    ax.set_xticklabels(mat.columns, rotation=90, fontsize=fontsize)
    ax.set_yticklabels(mat.index, fontsize=fontsize)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.subplots_adjust(bottom=0.22, left=0.22)
    fig.savefig(dest, dpi=120)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest)


def write_cleaning_report(
    path: Path,
    master: pd.DataFrame,
    catalog: pd.DataFrame,
    availability: pd.DataFrame,
    outliers: pd.DataFrame,
    structure: dict[str, Any],
    roles: dict[str, list[str]],
    n_missing_values: int,
) -> str:
    miss0 = catalog.loc[catalog["missing_gt_0"], "iqm"].tolist()
    miss5 = catalog.loc[catalog["missing_gt_5"], "iqm"].tolist()
    miss10 = catalog.loc[catalog["missing_gt_10"], "iqm"].tolist()
    zero = catalog.loc[catalog["zero_variance"], "iqm"].tolist()
    near = catalog.loc[catalog["near_zero_variance"], "iqm"].tolist()
    n_acq_out = (
        outliers[["subject_id", "session", "sequence_group", "run"]].drop_duplicates().shape[0]
        if not outliers.empty
        else 0
    )
    lines = [
        "MRIQC anatomical IQM cleaning — QC report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "COLUMN ROLES",
        f"  IQMs retained for statistics: {len(roles['iqm'])}",
        f"  technical excluded from statistics (kept in tables): {len(roles['technical'])}",
        f"  metadata: {len(roles['metadata'])}",
        f"  bold_excluded: {len(roles['bold_excluded'])}",
        "",
        "MISSINGNESS",
        f"  IQMs with >0% missing: {miss0 or 'none'}",
        f"  IQMs with >5% missing: {miss5 or 'none'}",
        f"  IQMs with >10% missing: {miss10 or 'none'}",
        f"  total missing IQM values: {n_missing_values}",
        "",
        "VARIANCE",
        f"  zero variance: {zero or 'none'}",
        f"  near-zero variance: {near or 'none'}",
        "",
        "OUTLIERS (documented, not removed; flags computed within sequence_group)",
        f"  n_iqm_value_flags: {0 if outliers.empty else len(outliers)}",
        f"  n_acquisitions_with_any_flag: {n_acq_out}",
        "  methods: Tukey IQR (k=1.5) and robust z-score (MAD, |z|>3.5)",
        "",
        "T1w vs WM-nulled availability",
        f"  T1w rows: {int((master['sequence_group']=='T1w').sum())}",
        f"  WMn rows: {int((master['sequence_group']=='WMn').sum())}",
        f"  IQMs available in both groups: {int(availability['available_in_both'].sum())}",
        f"  Spearman mean |Δr|: {structure.get('spearman_mean_abs_diff')}",
        f"  Spearman Frobenius |R_T1w - R_WMn|: {structure.get('spearman_frobenius_diff')}",
        f"  {structure.get('note')}",
        "",
        "NOT DONE (later steps)",
        "  PCA, ICA, t-SNE, UMAP, Elastic Net, cohort tests, longitudinal models.",
        "",
        "No original MRIQC files were modified. Outliers were not deleted.",
    ]
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(logging.DEBUG if args.verbose else logging.INFO, args.log_file)
    LOGGER.info("Cleaning / characterizing anatomical IQMs")

    master = load_master(args.master_tsv)
    roles: dict[str, list[str]] = {"iqm": [], "technical": [], "metadata": [], "bold_excluded": []}
    for col in master.columns:
        roles.setdefault(classify_column(col), []).append(col)

    iqm_cols = analytic_iqm_columns(master)
    tech_cols = technical_columns(master)
    if not iqm_cols:
        fail("No analytic IQM columns identified in the master dataframe.")

    # Clean table: same rows as master; IQMs coerced numeric; inf → NA.
    clean = master.copy()
    for col in iqm_cols + tech_cols:
        clean[col] = to_numeric_iqm(clean[col])

    catalog, descriptives, outliers = catalog_and_descriptives(
        clean, iqm_cols, args.near_zero_rel_sd, args.iqr_k, args.robust_z
    )
    availability = availability_table(clean, iqm_cols)
    mats = correlation_matrices(clean, iqm_cols)
    structure = corr_structure_note(mats)

    args.meta_dir.mkdir(parents=True, exist_ok=True)
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    clean.to_csv(args.clean_tsv, sep="\t", index=False)
    catalog.to_csv(args.meta_dir / "mriqc_iqm_catalog.tsv", sep="\t", index=False)
    descriptives.to_csv(args.meta_dir / "mriqc_iqm_descriptives.tsv", sep="\t", index=False)
    availability.to_csv(args.meta_dir / "mriqc_iqm_availability_T1w_vs_WMn.tsv", sep="\t", index=False)
    if outliers.empty:
        outliers = pd.DataFrame(
            columns=[
                "subject_id",
                "session",
                "sequence_group",
                "run",
                "mriqc_source_file",
                "iqm",
                "value",
                "outlier_iqr",
                "outlier_robust_z",
                "robust_z",
                "split",
            ]
        )
    outliers.to_csv(args.meta_dir / "mriqc_iqm_outliers.tsv", sep="\t", index=False)
    role_rows = []
    for role, cols in roles.items():
        for c in cols:
            role_rows.append(
                {
                    "column": c,
                    "role": role,
                    "family": iqm_family(c) if role == "iqm" else "",
                    "retained_for_statistics": role == "iqm",
                }
            )
    pd.DataFrame(role_rows).to_csv(args.meta_dir / "mriqc_iqm_column_roles.tsv", sep="\t", index=False)
    save_corr_tables(mats, args.meta_dir)

    plot_missingness(catalog, args.figures_dir / "iqm_missingness.png")
    plot_distributions(clean, iqm_cols, args.figures_dir / "iqm_distributions_main.png")
    plot_t1w_vs_wmn_box(clean, iqm_cols, args.figures_dir / "iqm_T1w_vs_WMn.png")
    plot_heatmap(mats["T1w_spearman"], "IQM Spearman correlation — T1w", args.figures_dir / "iqm_corr_heatmap_T1w.png")
    plot_heatmap(mats["WMn_spearman"], "IQM Spearman correlation — WM-nulled", args.figures_dir / "iqm_corr_heatmap_WMn.png")
    plot_heatmap(
        mats["T1w_pearson"],
        "IQM Pearson correlation — T1w",
        args.figures_dir / "iqm_corr_heatmap_T1w_pearson.png",
    )
    plot_heatmap(
        mats["WMn_pearson"],
        "IQM Pearson correlation — WM-nulled",
        args.figures_dir / "iqm_corr_heatmap_WMn_pearson.png",
    )

    master_summary_path = args.meta_dir / "mriqc_iqm_master_summary.json"
    n_unmapped = 0
    n_dup = 0
    if master_summary_path.is_file():
        master_summary = json.loads(master_summary_path.read_text(encoding="utf-8"))
        n_unmapped = int(master_summary.get("n_unmapped_mriqc_files", 0))
        n_dup = int(master_summary.get("n_duplicated_mappings", 0))
    n_missing_values = int(sum(int(to_numeric_iqm(clean[c]).isna().sum()) for c in iqm_cols))
    n_out_acq = (
        outliers[["subject_id", "session", "sequence_group", "run"]].drop_duplicates().shape[0]
        if not outliers.empty
        else 0
    )
    n_excluded = len(roles.get("technical", [])) + len(roles.get("bold_excluded", []))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_subjects": int(clean["subject_id"].nunique()),
        "n_sessions": int(clean.groupby(["subject_id", "session"]).ngroups),
        "n_t1w": int((clean["sequence_group"] == "T1w").sum()),
        "n_wmn": int((clean["sequence_group"] == "WMn").sum()),
        "n_iqms": len(iqm_cols),
        "n_iqms_retained": len(iqm_cols),
        "n_iqms_excluded": n_excluded,
        "n_missing_values": n_missing_values,
        "n_potential_outliers": int(n_out_acq),
        "n_outlier_value_flags": int(len(outliers)),
        "n_unmapped_mriqc_files": n_unmapped,
        "n_duplicated_mappings": n_dup,
        "zero_variance_iqms": catalog.loc[catalog["zero_variance"], "iqm"].tolist(),
        "t1w_vs_wmn": structure,
        "outliers_removed": False,
    }
    (args.meta_dir / "mriqc_iqm_cleaning_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    write_cleaning_report(
        args.report, clean, catalog, availability, outliers, structure, roles, n_missing_values
    )
    LOGGER.info("Wrote %s", args.clean_tsv)
    LOGGER.info("Wrote %s", args.report)

    print()
    print("N subjects:", summary["n_subjects"])
    print("N sessions:", summary["n_sessions"])
    print("N T1w acquisitions:", summary["n_t1w"])
    print("N WM-nulled acquisitions:", summary["n_wmn"])
    print("N IQMs:", summary["n_iqms"])
    print("N IQMs retained:", summary["n_iqms_retained"])
    print("N IQMs excluded:", summary["n_iqms_excluded"])
    print("N missing values:", summary["n_missing_values"])
    print("N potential outliers:", summary["n_potential_outliers"])
    print("N unmapped MRIQC files:", n_unmapped)
    print("N duplicated mappings:", n_dup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
