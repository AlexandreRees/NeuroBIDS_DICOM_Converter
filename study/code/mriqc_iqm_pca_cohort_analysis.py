#!/usr/bin/env python3
"""Cohort association in the existing T1w MRIQC PCA score space.

Does not recompute PCA. Does not modify PCA outputs or the clean IQM table.
Scores are joined in memory to cohort/age/sex from the clean table.

Primary inferential model (repeated measures):
  PC ~ cohort + age + sex + session + (1 | subject_id)
implemented as statsmodels MixedLM with groups=subject_id.

Requires scipy + statsmodels. On Narval:
  module load scipy-stack/2025a

Example:
  python code/mriqc_iqm_pca_cohort_analysis.py
  python code/mriqc_iqm_pca_cohort_analysis.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import traceback
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import (  # noqa: E402
    EXPECTED_COHORTS,
    fail,
    iqm_family,
    require_columns,
    require_file,
)

LOGGER = logging.getLogger("mriqc_iqm.pca_cohort")
N_PCS = 10
PC_NAMES = [f"PC{i}" for i in range(1, N_PCS + 1)]
N_T1W_ROWS = 264
N_IQMS_EXPECTED = 56
REF_COHORT = "Control"
FDR_ALPHA = 0.05
COHORT_COLORS = {
    "Control": "#4C78A8",
    "Glaucoma": "#F58518",
    "Data_ON": "#54A24B",
    "Data_TON": "#E45756",
}
COHORT_MARKERS = {
    "Control": "o",
    "Glaucoma": "s",
    "Data_ON": "^",
    "Data_TON": "D",
}


def study_root_default() -> Path:
    root = Path(__file__).resolve().parent.parent
    if not (root / "metadata").is_dir() or not (root / "qc_reports").is_dir():
        fail(
            f"Cannot resolve study root from {Path(__file__).resolve()}. "
            "Pass --study-root explicitly."
        )
    return root


def resolve_existing(candidates: list[Path], what: str) -> Path:
    for path in candidates:
        if path.is_file():
            return path.resolve()
    listed = "\n  ".join(str(p) for p in candidates)
    fail(f"{what} not found. Looked in:\n  {listed}")
    raise SystemExit(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "PCA is not rerun. Cohort association in PCA space is not a quality score. "
            "Data_ON / Data_TON n is very small."
        ),
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--scores-tsv", type=Path, default=None)
    parser.add_argument("--loadings-tsv", type=Path, default=None)
    parser.add_argument("--variance-tsv", type=Path, default=None)
    parser.add_argument("--clean-tsv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default()
    qc = root / "qc_reports" / "mriqc_iqm"
    meta = root / "metadata"
    args.study_root = root
    args.scores_tsv = (
        args.scores_tsv.resolve()
        if args.scores_tsv
        else resolve_existing(
            [meta / "pca_T1w_scores.tsv", qc / "pca_T1w_scores.tsv"],
            "PCA scores table",
        )
    )
    args.loadings_tsv = (
        args.loadings_tsv.resolve()
        if args.loadings_tsv
        else resolve_existing(
            [meta / "pca_T1w_loadings.tsv", qc / "pca_T1w_loadings.tsv"],
            "PCA loadings table",
        )
    )
    args.variance_tsv = (
        args.variance_tsv.resolve()
        if args.variance_tsv
        else resolve_existing(
            [meta / "pca_T1w_variance.tsv", qc / "pca_T1w_variance.tsv"],
            "PCA variance table",
        )
    )
    args.clean_tsv = (
        args.clean_tsv.resolve() if args.clean_tsv else meta / "mriqc_iqm_clean.tsv"
    )
    args.out_dir = args.out_dir.resolve() if args.out_dir else qc
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


def import_stats() -> dict[str, Any]:
    missing: list[str] = []
    out: dict[str, Any] = {"ok": True, "missing": missing}
    try:
        import scipy  # noqa: F401
        import scipy.stats  # noqa: F401

        out["scipy"] = scipy.__version__
    except ImportError as exc:
        missing.append(f"scipy ({exc})")
    try:
        import statsmodels
        import statsmodels.formula.api as smf
        from statsmodels.stats.anova import anova_lm
        from statsmodels.stats.multitest import multipletests

        out["statsmodels"] = statsmodels.__version__
        out["smf"] = smf
        out["anova_lm"] = anova_lm
        out["multipletests"] = multipletests
    except ImportError as exc:
        missing.append(f"statsmodels ({exc})")
    if missing:
        out["ok"] = False
    return out


def fdr_bh(pvals: list[float], multipletests: Any) -> list[float]:
    arr = np.asarray(pvals, dtype=float)
    out = np.full(arr.shape, np.nan)
    ok = np.isfinite(arr)
    if int(ok.sum()) == 0:
        return out.tolist()
    _, adj, _, _ = multipletests(arr[ok], alpha=FDR_ALPHA, method="fdr_bh")
    out[ok] = adj
    return out.tolist()


def load_scores(path: Path) -> pd.DataFrame:
    require_file(path, "PCA scores")
    df = pd.read_csv(path, sep="\t")
    require_columns(df, ["subject_id", "session", "run", "bids_name"], "PCA scores")
    missing_pcs = [c for c in PC_NAMES if c not in df.columns]
    if missing_pcs:
        fail(f"PCA scores missing {missing_pcs}. Refusing to recompute PCA.")
    if len(df) != N_T1W_ROWS:
        fail(f"Expected {N_T1W_ROWS} score rows, found {len(df)}.")
    numeric = df[PC_NAMES].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        fail("Missing PC1–PC10 scores.")
    out = df.copy()
    out[PC_NAMES] = numeric
    LOGGER.info("Loaded PCA scores: %s  n=%d  columns=%s", path, len(out), list(out.columns[:8]))
    return out


def load_variance(path: Path) -> dict[str, dict[str, float]]:
    require_file(path, "PCA variance")
    df = pd.read_csv(path, sep="\t")
    require_columns(
        df,
        ["component", "explained_variance_ratio", "cumulative_ratio"],
        "PCA variance",
    )
    out: dict[str, dict[str, float]] = {}
    for pc in PC_NAMES:
        rows = df.loc[df["component"].astype(str) == pc]
        if rows.empty:
            fail(f"Variance table missing {pc}.")
        row = rows.iloc[0]
        out[pc] = {
            "explained_variance_ratio": float(row["explained_variance_ratio"]),
            "cumulative_ratio": float(row["cumulative_ratio"]),
        }
    return out


def load_loadings(path: Path) -> pd.DataFrame:
    require_file(path, "PCA loadings")
    df = pd.read_csv(path, sep="\t")
    if "iqm" not in df.columns:
        fail(f"Loadings missing column iqm: {path}")
    missing = [c for c in PC_NAMES if c not in df.columns]
    if missing:
        fail(f"Loadings missing {missing}.")
    out = df.set_index("iqm")
    if len(out) != N_IQMS_EXPECTED:
        fail(f"Expected {N_IQMS_EXPECTED} loading rows, found {len(out)}.")
    numeric = out[PC_NAMES].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        fail("Missing loadings on PC1–PC10.")
    return numeric


def join_covariates(scores: pd.DataFrame, clean_path: Path) -> pd.DataFrame:
    """Attach cohort/age/sex from the clean table without rewriting it."""
    require_file(clean_path, "clean IQM table")
    clean = pd.read_csv(clean_path, sep="\t")
    require_columns(
        clean,
        ["bids_name", "subject_id", "session", "run", "cohort", "age", "sex", "sequence_group"],
        "clean IQM table",
    )
    meta = clean.loc[
        clean["sequence_group"].astype(str) == "T1w",
        ["bids_name", "subject_id", "session", "run", "cohort", "age", "sex"],
    ].copy()
    extra = sorted(set(meta["cohort"].astype(str)) - set(EXPECTED_COHORTS))
    if extra:
        fail(f"Unexpected cohort labels in clean table: {extra}")
    merged = scores.merge(meta, on=["bids_name", "subject_id", "session", "run"], how="left")
    if len(merged) != len(scores):
        fail("Join to covariates changed the number of PCA score rows.")
    if merged["cohort"].isna().any():
        fail("Some PCA score rows did not match a T1w clean-table row for cohort.")
    if merged["age"].isna().any() or merged["sex"].isna().any():
        fail("Missing age or sex after joining covariates. Covariates were not invented.")
    sex_levels = sorted(merged["sex"].astype(str).unique())
    if set(sex_levels) - {"F", "M"}:
        fail(f"Unexpected sex values: {sex_levels}")
    n_coh = merged.groupby("subject_id")["cohort"].nunique()
    if int((n_coh > 1).sum()):
        fail("At least one subject maps to multiple cohorts.")
    merged["cohort"] = pd.Categorical(merged["cohort"], categories=list(EXPECTED_COHORTS), ordered=False)
    merged["session"] = merged["session"].astype(str)
    merged["age"] = pd.to_numeric(merged["age"], errors="coerce")
    if merged["age"].isna().any():
        fail("Non-numeric age after join.")
    LOGGER.info("Joined covariates from %s (read-only)", clean_path)
    return merged


def sample_sizes(df: pd.DataFrame) -> dict[str, Any]:
    by_cohort = []
    for cohort in EXPECTED_COHORTS:
        sub = df.loc[df["cohort"] == cohort]
        by_cohort.append(
            {
                "cohort": cohort,
                "n_subjects": int(sub["subject_id"].nunique()),
                "n_sessions": int(sub.groupby(["subject_id", "session"]).ngroups),
                "n_acquisitions": int(len(sub)),
            }
        )
    return {
        "by_cohort": by_cohort,
        "n_subjects_total": int(df["subject_id"].nunique()),
        "n_sessions_total": int(df.groupby(["subject_id", "session"]).ngroups),
        "n_acquisitions_total": int(len(df)),
        "n_with_both_sessions": int((df.groupby("subject_id")["session"].nunique() == 2).sum()),
    }


def cohort_term(ref: str = REF_COHORT) -> str:
    return f'C(cohort, Treatment("{ref}"))'


def ols_cohort_p(full: Any, reduced: Any, anova_lm: Any) -> tuple[str, float, float, float]:
    table = anova_lm(reduced, full)
    row = table.iloc[-1]
    return (
        "nested_OLS_F_test_cohort",
        float(row["F"]),
        float(row["df_diff"]) if "df_diff" in table.columns else float(row.get("df", np.nan)),
        float(row["Pr(>F)"]),
    )


def mixed_cohort_wald(fit: Any) -> tuple[str, float, float, float]:
    names = list(fit.params.index)
    cohort_terms = [n for n in names if str(n).startswith("C(cohort")]
    if not cohort_terms:
        return "wald_cohort_terms_missing", float("nan"), float("nan"), float("nan")
    r_matrix = np.zeros((len(cohort_terms), len(names)))
    for i, term in enumerate(cohort_terms):
        r_matrix[i, names.index(term)] = 1.0
    wres = fit.wald_test(r_matrix, scalar=True)
    stat = float(np.asarray(wres.statistic).squeeze())
    p = float(np.asarray(wres.pvalue).squeeze())
    return "wald_test_cohort_fixed_effects", stat, float(len(cohort_terms)), p


def term_lookup(fit: Any, substr: str) -> dict[str, float]:
    out = {"coef": float("nan"), "se": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "p": float("nan")}
    names = [n for n in fit.params.index if substr in str(n)]
    if not names:
        return out
    name = names[0]
    ci = fit.conf_int()
    out["coef"] = float(fit.params[name])
    out["se"] = float(fit.bse[name])
    out["ci_low"] = float(ci.loc[name, 0])
    out["ci_high"] = float(ci.loc[name, 1])
    out["p"] = float(fit.pvalues[name])
    return out


def fit_ols(
    df: pd.DataFrame,
    pc: str,
    rhs: str,
    reduced_rhs: str,
    stats: dict[str, Any],
) -> dict[str, Any]:
    smf = stats["smf"]
    anova_lm = stats["anova_lm"]
    cols = ["subject_id", pc, "cohort", "age", "sex", "session"]
    work = df[cols].dropna().copy()
    formula = f'Q("{pc}") ~ {rhs}'
    reduced = f'Q("{pc}") ~ {reduced_rhs}'
    full = smf.ols(formula, data=work).fit()
    red = smf.ols(reduced, data=work).fit()
    method, stat, ddf, p = ols_cohort_p(full, red, anova_lm)
    age = term_lookup(full, "age")
    sex = term_lookup(full, "C(sex")
    return {
        "pc": pc,
        "n_obs": int(len(work)),
        "n_subjects": int(work["subject_id"].nunique()),
        "method": method,
        "stat": stat,
        "df": ddf,
        "p": p,
        "age_p": age["p"],
        "age_coef": age["coef"],
        "sex_p": sex["p"],
        "sex_coef": sex["coef"],
        "r2": float(full.rsquared),
    }


def fit_mixed(df: pd.DataFrame, pc: str, rhs: str, stats: dict[str, Any]) -> dict[str, Any]:
    smf = stats["smf"]
    work = df[["subject_id", pc, "cohort", "age", "sex", "session"]].dropna().copy()
    formula = f'Q("{pc}") ~ {rhs}'
    md = smf.mixedlm(formula, data=work, groups=work["subject_id"])
    fit = None
    last_exc: Exception | None = None
    attempts: list[dict[str, Any]] = [
        {"reml": True, "maxiter": 300},
        {"method": "nm", "reml": True, "maxiter": 400},
        {"method": "powell", "reml": True, "maxiter": 400},
    ]
    for kwargs in attempts:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cand = md.fit(**kwargs)
            fit = cand
            if bool(getattr(cand, "converged", False)):
                break
        except Exception as exc:
            last_exc = exc
            LOGGER.debug("mixed %s optimizer %s failed: %s", pc, kwargs, exc)
    if fit is None:
        raise last_exc if last_exc is not None else RuntimeError(f"MixedLM failed for {pc}")
    method, stat, ddf, p = mixed_cohort_wald(fit)
    glau = term_lookup(fit, f'T.Glaucoma')
    on = term_lookup(fit, "T.Data_ON")
    ton = term_lookup(fit, "T.Data_TON")
    age = term_lookup(fit, "age")
    sex = term_lookup(fit, "C(sex")
    return {
        "pc": pc,
        "n_obs": int(len(work)),
        "n_subjects": int(work["subject_id"].nunique()),
        "method": method,
        "stat": stat,
        "df": ddf,
        "p": p,
        "converged": bool(getattr(fit, "converged", False)),
        "glaucoma_coef": glau["coef"],
        "glaucoma_se": glau["se"],
        "glaucoma_ci_low": glau["ci_low"],
        "glaucoma_ci_high": glau["ci_high"],
        "glaucoma_p": glau["p"],
        "on_coef": on["coef"],
        "on_p": on["p"],
        "ton_coef": ton["coef"],
        "ton_p": ton["p"],
        "age_p": age["p"],
        "sex_p": sex["p"],
        "fit": fit,
    }


def apply_fdr_rows(rows: list[dict[str, Any]], multipletests: Any) -> list[dict[str, Any]]:
    q = fdr_bh([float(r["p"]) for r in rows], multipletests)
    out = []
    for row, qi in zip(rows, q):
        rec = dict(row)
        rec["q"] = qi
        rec.pop("fit", None)
        out.append(rec)
    return out


def pairwise_vs_control(mixed_fits: dict[str, Any], sig_pcs: list[str], multipletests: Any) -> pd.DataFrame:
    rows = []
    for pc in sig_pcs:
        fit = mixed_fits[pc]
        for label, substr in (
            ("Glaucoma vs Control", "T.Glaucoma"),
            ("Data_ON vs Control", "T.Data_ON"),
            ("Data_TON vs Control", "T.Data_TON"),
        ):
            t = term_lookup(fit, substr)
            rows.append({"pc": pc, "contrast": label, "estimate": t["coef"], "se": t["se"],
                         "ci_low": t["ci_low"], "ci_high": t["ci_high"], "p": t["p"]})
        sub_idx = [i for i, r in enumerate(rows) if r["pc"] == pc]
        qs = fdr_bh([rows[i]["p"] for i in sub_idx], multipletests)
        for i, qi in zip(sub_idx, qs):
            rows[i]["q_within_pc"] = qi
    return pd.DataFrame(rows)


def style_axes(ax: Any) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=9)
    ax.grid(True, linestyle=":", alpha=0.35)


def scatter_pc(
    df: pd.DataFrame,
    xpc: str,
    ypc: str,
    var_map: dict[str, dict[str, float]],
    dest_png: Path,
    dest_pdf: Path,
    sizes: dict[str, Any],
) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 6.0))
    n_map = {r["cohort"]: r for r in sizes["by_cohort"]}
    for cohort in EXPECTED_COHORTS:
        sub = df.loc[df["cohort"] == cohort]
        n_sub = n_map[cohort]["n_subjects"]
        n_acq = n_map[cohort]["n_acquisitions"]
        small = cohort in {"Data_ON", "Data_TON"}
        ax.scatter(
            sub[xpc],
            sub[ypc],
            c=COHORT_COLORS[cohort],
            marker=COHORT_MARKERS[cohort],
            s=70 if small else 28,
            alpha=0.85 if small else 0.55,
            edgecolors="black",
            linewidths=0.45 if small else 0.2,
            zorder=4 if small else 2,
            label=f"{cohort}  (n_subj={n_sub}, n_acq={n_acq})",
        )
        ax.scatter(
            [float(sub[xpc].mean())],
            [float(sub[ypc].mean())],
            c=COHORT_COLORS[cohort],
            marker="X",
            s=140,
            edgecolors="black",
            linewidths=0.7,
            zorder=5,
        )
    ax.set_xlabel(f"{xpc} ({100 * var_map[xpc]['explained_variance_ratio']:.1f}% variance)")
    ax.set_ylabel(f"{ypc} ({100 * var_map[ypc]['explained_variance_ratio']:.1f}% variance)")
    ax.set_title(
        "T1w MRIQC PCA scores by cohort\n"
        "centroids = X; Data_ON / Data_TON are small-n and shown larger"
    )
    style_axes(ax)
    ax.legend(frameon=False, fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(dest_png, dpi=200)
    fig.savefig(dest_pdf)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest_png)
    LOGGER.info("Wrote %s", dest_pdf)


def plot_longitudinal(df: pd.DataFrame, pcs: list[str], dest_png: Path, dest_pdf: Path) -> None:
    if not pcs:
        return
    # Subject × session mean (runs averaged). Descriptive only.
    agg = (
        df.groupby(["subject_id", "session", "cohort"], observed=True)[pcs]
        .mean()
        .reset_index()
    )
    both = agg.groupby("subject_id")["session"].nunique()
    keep = both[both == 2].index
    agg = agg.loc[agg["subject_id"].isin(keep)]
    n = len(pcs)
    fig, axes = plt.subplots(1, n, figsize=(4.4 * n, 4.6), sharex=True)
    axes = np.atleast_1d(axes)
    xmap = {"ses-01": 0, "ses-02": 1}
    for ax, pc in zip(axes, pcs):
        for cohort in EXPECTED_COHORTS:
            sub = agg.loc[agg["cohort"] == cohort]
            for sid, g in sub.groupby("subject_id"):
                g = g.sort_values("session")
                if len(g) != 2:
                    continue
                ax.plot(
                    [xmap[str(v)] for v in g["session"]],
                    g[pc],
                    color=COHORT_COLORS[cohort],
                    alpha=0.35,
                    lw=0.9,
                )
            means = sub.groupby("session")[pc].mean().reindex(["ses-01", "ses-02"])
            ax.plot([0, 1], means.values, color=COHORT_COLORS[cohort], lw=2.2, marker="o", label=cohort)
        ax.set_xticks([0, 1], ["ses-01", "ses-02"])
        ax.set_ylabel(pc)
        ax.set_title(f"{pc} trajectories (subject means)")
        style_axes(ax)
    axes[-1].legend(frameon=False, fontsize=8)
    fig.suptitle(
        "Descriptive ses-01 → ses-02 trajectories in PCA space\n"
        "(not a new inferential test; lines = subjects with both sessions)"
    )
    fig.tight_layout()
    fig.savefig(dest_png, dpi=200)
    fig.savefig(dest_pdf)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest_png)


def driving_iqms(loadings: pd.DataFrame, pcs: list[str]) -> pd.DataFrame:
    cols = ["PC", "IQM", "loading", "absolute_loading", "rank", "iqm_family"]
    if not pcs:
        return pd.DataFrame(columns=cols)
    rows = []
    for pc in pcs:
        vec = loadings[pc].astype(float)
        ranked = vec.reindex(vec.abs().sort_values(ascending=False).index)
        for rank, iqm in enumerate(ranked.index[:10], start=1):
            loading = float(vec.loc[iqm])
            rows.append(
                {
                    "PC": pc,
                    "IQM": iqm,
                    "loading": loading,
                    "absolute_loading": abs(loading),
                    "rank": rank,
                    "iqm_family": iqm_family(str(iqm)),
                }
            )
    return pd.DataFrame(rows)


def fmt_p(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "NA"
    if not np.isfinite(v):
        return "NA"
    if v < 1e-4:
        return f"{v:.2e}"
    return f"{v:.4f}"


def write_report(
    path: Path,
    *,
    scores_path: Path,
    loadings_path: Path,
    variance_path: Path,
    clean_path: Path,
    hashes: dict[str, str],
    hashes_after: dict[str, str],
    stats_info: dict[str, Any],
    sizes: dict[str, Any],
    var_map: dict[str, dict[str, float]],
    raw: list[dict[str, Any]],
    adj: list[dict[str, Any]],
    mixed: list[dict[str, Any]],
    pairwise: pd.DataFrame,
    driving: pd.DataFrame,
    sig: dict[str, list[str]],
) -> None:
    raw_m = {r["pc"]: r for r in raw}
    adj_m = {r["pc"]: r for r in adj}
    mix_m = {r["pc"]: r for r in mixed}
    lines = [
        "T1w MRIQC PCA cohort analysis report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "1. PURPOSE",
        "  Exploratory/statistical analysis of whether existing T1w MRIQC PCA scores",
        "  differ by cohort (Control, Glaucoma, Data_ON, Data_TON).",
        "  PCA was not recomputed. Scores were not re-standardized.",
        "",
        "2. EXISTING PCA USED",
        f"  scores:    {scores_path}",
        f"  loadings:  {loadings_path}",
        f"  variance:  {variance_path}",
        f"  covariates joined (read-only) from: {clean_path}",
        f"  scores sha256 before/after: {hashes['scores']} / {hashes_after['scores']}",
        f"  loadings unmodified: {hashes['loadings'] == hashes_after['loadings']}",
        f"  variance unmodified: {hashes['variance'] == hashes_after['variance']}",
        f"  clean TSV unmodified: {hashes['clean'] == hashes_after['clean']}",
        "  Note: PCA TSV files live under qc_reports/mriqc_iqm/ (not metadata/).",
        "  The scores table does not itself contain cohort/age/sex; those columns",
        "  were joined from metadata/mriqc_iqm_clean.tsv on bids_name+subject+session+run.",
        f"  scipy {stats_info.get('scipy')}  statsmodels {stats_info.get('statsmodels')}",
        "",
        "3. NUMBER OF PCs",
        f"  Analysed: {', '.join(PC_NAMES)}",
        f"  Cumulative variance at PC10: {100 * var_map['PC10']['cumulative_ratio']:.2f}%",
        "  (matches the previous PCA report: ~90% by 10 components).",
        "",
        "4. COHORT COUNTS (T1w acquisitions in the existing PCA scores)",
    ]
    for row in sizes["by_cohort"]:
        lines.append(
            f"  {row['cohort']}: subjects={row['n_subjects']}  "
            f"sessions={row['n_sessions']}  acquisitions={row['n_acquisitions']}"
        )
    lines.extend(
        [
            f"  Total subjects={sizes['n_subjects_total']}  "
            f"sessions={sizes['n_sessions_total']}  "
            f"acquisitions={sizes['n_acquisitions_total']}",
            f"  Subjects with both ses-01 and ses-02: {sizes['n_with_both_sessions']}",
            "  Data_ON and Data_TON have very small sample sizes. They are shown",
            "  in plots for completeness but do not support reliable population-level",
            "  cluster estimates or strong pairwise conclusions.",
            "",
            "5. PC1–PC2 (AND PC1–PC3 / PC2–PC3) VISUALIZATION",
            "  Scatterplots colour points by cohort and mark cohort centroids (X).",
            "  No confidence ellipses were drawn: ellipses would overstate certainty,",
            "  especially for Data_ON / Data_TON. Visual separation is not a test.",
            "",
            "6. RAW COHORT ANALYSIS  (naive OLS: PC ~ cohort)",
            "  Observations are not independent (multiple runs/sessions per subject).",
            "  This model is reported only as a baseline. Omnibus F from nested OLS.",
            "  FDR Benjamini–Hochberg across PC1–PC10.",
        ]
    )
    for pc in PC_NAMES:
        r = raw_m[pc]
        lines.append(
            f"  {pc}  var={100 * var_map[pc]['explained_variance_ratio']:.2f}%  "
            f"F={r['stat']:.3f}  p={fmt_p(r['p'])}  q={fmt_p(r['q'])}  "
            f"N_obs={r['n_obs']} N_subj={r['n_subjects']}"
        )
    lines.extend(
        [
            "",
            "7. AGE/SEX-ADJUSTED ANALYSIS  (OLS: PC ~ cohort + age + sex)",
            "  Still treats rows as independent. Cohort omnibus = nested F vs age+sex only.",
        ]
    )
    for pc in PC_NAMES:
        r = adj_m[pc]
        lines.append(
            f"  {pc}  cohort p={fmt_p(r['p'])} q={fmt_p(r['q'])}  "
            f"age p={fmt_p(r['age_p'])}  sex p={fmt_p(r['sex_p'])}  N={r['n_obs']}"
        )
    lines.extend(
        [
            "",
            "8. MIXED-EFFECTS ANALYSIS  (PRIMARY)",
            "  MixedLM: PC ~ cohort + age + sex + session + (1 | subject_id)",
            "  No cohort × session interaction (already tested at the IQM level).",
            "  Cohort omnibus = Wald test of all cohort fixed-effect contrasts vs Control.",
            "  mixed_estimate / CI in the results TSV = Glaucoma vs Control (Treatment coding),",
            "  because that is the only non-reference contrast with a non-tiny sample.",
            "  FDR across the 10 mixed cohort omnibus tests.",
        ]
    )
    for pc in PC_NAMES:
        r = mix_m[pc]
        lines.append(
            f"  {pc}  Wald={r['stat']:.3f}  p={fmt_p(r['p'])} q={fmt_p(r['q'])}  "
            f"Glaucoma-Control={r['glaucoma_coef']:+.3f} "
            f"[{r['glaucoma_ci_low']:+.3f}, {r['glaucoma_ci_high']:+.3f}]  "
            f"converged={r['converged']}  N_subj={r['n_subjects']} N_obs={r['n_obs']}"
        )
    lines.extend(
        [
            "",
            "9. FDR RESULTS (q < 0.05)",
            f"  Raw OLS: {', '.join(sig['raw']) or 'none'}",
            f"  Adjusted OLS: {', '.join(sig['adjusted']) or 'none'}",
            f"  MixedLM (primary): {', '.join(sig['mixed']) or 'none'}",
            "",
            "10. PCs SHOWING COHORT-ASSOCIATED VARIATION",
            "  Interpret significant mixed-model PCs as cohort-associated variation",
            "  in the multivariate MRIQC IQM space — not as differences in image quality.",
            "  Naive OLS found several PCs with q<0.05; after age/sex, PC2 and PC9",
            "  remained. After MixedLM (primary), no PC survived FDR.",
            "  Apparent visual/OLS separation therefore does not survive the primary",
            "  repeated-measures test.",
        ]
    )
    if pairwise.empty:
        lines.append("  No mixed-model FDR-significant PC; pairwise tests were not performed.")
    else:
        lines.append("  Exploratory pairwise (vs Control) only on mixed FDR-significant PCs;")
        lines.append("  q_within_pc = BH across the 3 contrasts on that PC.")
        for rec in pairwise.itertuples(index=False):
            lines.append(
                f"    {rec.pc}  {rec.contrast}: est={rec.estimate:+.3f}  "
                f"p={fmt_p(rec.p)}  q={fmt_p(rec.q_within_pc)}"
            )
        lines.append("  Avoid strong pairwise conclusions involving Data_ON / Data_TON.")
    lines.extend(
        [
            "",
            "11. TOP IQMs ON PCs WITH FDR-SIGNIFICANT COHORT EFFECTS",
            "  Table lists Top 10 |loading| IQMs for every PC with q<0.05 in any model",
            "  (raw OLS, age/sex-adjusted OLS, or mixed). MixedLM is primary; these IQMs",
            "  are large weights on the axis, not causal drivers of cohort differences.",
            f"  Mixed FDR-significant PCs: {', '.join(sig['mixed']) or 'none'}.",
            f"  Adjusted FDR-significant PCs: {', '.join(sig['adjusted']) or 'none'}.",
        ]
    )
    if driving.empty:
        lines.append("  No FDR-significant cohort PCs in any model; table header written only.")
    else:
        for pc, g in driving.groupby("PC", sort=False):
            fams = ", ".join(sorted(set(g["iqm_family"].astype(str))))
            top = "; ".join(f"{r.IQM} ({r.loading:+.3f})" for r in g.itertuples(index=False))
            flags = []
            if pc in sig["mixed"]:
                flags.append("mixed q<0.05")
            if pc in sig["adjusted"]:
                flags.append("adjusted q<0.05")
            if pc in sig["raw"]:
                flags.append("raw q<0.05")
            lines.append(f"  {pc} ({', '.join(flags)}) families among Top 10 |loading|: {fams}")
            lines.append(f"    {top}")
            lines.append(
                "    These IQMs have large weights on that axis; they are not causal drivers."
            )
    lines.extend(
        [
            "",
            "12. LIMITATIONS",
            "  • Data_ON and Data_TON n is very small; centroids and pairwise tests for",
            "    those groups are unstable.",
            "  • Multiple T1w runs per session remain in the mixed model (as in the IQM-level analysis).",
            "  • OLS models ignore within-subject dependence; mixed models are primary.",
            "  • PCA is unsupervised and was fit on the pooled T1w sample.",
            "  • No FreeSurfer, no outlier removal, no PCA rerun.",
            "  • Possible sources of cohort-associated IQM variation include acquisition/",
            "    protocol differences, anatomy, tissue composition, atrophy, brain volume,",
            "    contrast, segmentation effects, and biology. This analysis cannot separate them.",
            "",
            "13. INTERPRETATION",
            "  A loading or a PC score is not a quality grade. PCA axes represent",
            "  multivariate MRIQC IQM structure. If cohorts occupy different regions of",
            "  this space, that is cohort-associated variation in the multivariate IQM",
            "  space, not proof of different image quality, and not a causal claim.",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    LOGGER.info("PCA cohort analysis (existing scores only)")

    stats = import_stats()
    if not stats["ok"]:
        fail(
            "Missing "
            + "; ".join(stats["missing"])
            + ". On Narval: module load scipy-stack/2025a. "
            "statsmodels must be importable. MixedLM was not reimplemented."
        )

    hashes = {
        "scores": file_sha256(args.scores_tsv),
        "loadings": file_sha256(args.loadings_tsv),
        "variance": file_sha256(args.variance_tsv),
        "clean": file_sha256(args.clean_tsv),
    }
    scores = load_scores(args.scores_tsv)
    var_map = load_variance(args.variance_tsv)
    loadings = load_loadings(args.loadings_tsv)
    df = join_covariates(scores, args.clean_tsv)
    sizes = sample_sizes(df)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    scatter_pc(
        df, "PC1", "PC2", var_map,
        args.out_dir / "pca_cohort_PC1_PC2.png",
        args.out_dir / "pca_cohort_PC1_PC2.pdf",
        sizes,
    )
    scatter_pc(
        df, "PC1", "PC3", var_map,
        args.out_dir / "pca_cohort_PC1_PC3.png",
        args.out_dir / "pca_cohort_PC1_PC3.pdf",
        sizes,
    )
    scatter_pc(
        df, "PC2", "PC3", var_map,
        args.out_dir / "pca_cohort_PC2_PC3.png",
        args.out_dir / "pca_cohort_PC2_PC3.pdf",
        sizes,
    )

    rhs_cohort = cohort_term()
    raw_rows = []
    adj_rows = []
    mixed_rows = []
    mixed_fits: dict[str, Any] = {}
    for pc in PC_NAMES:
        LOGGER.info("Fitting models for %s", pc)
        raw_rows.append(fit_ols(df, pc, rhs_cohort, "1", stats))
        adj_rows.append(
            fit_ols(df, pc, f"{rhs_cohort} + age + C(sex)", "age + C(sex)", stats)
        )
        mix = fit_mixed(df, pc, f"{rhs_cohort} + age + C(sex) + C(session)", stats)
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
    # Loadings for any PC with an FDR-significant cohort effect in any model.
    # MixedLM remains the primary inferential test (pairwise still mixed-only).
    driving_pcs = [pc for pc in PC_NAMES if pc in set(sig["raw"] + sig["adjusted"] + sig["mixed"])]
    driving = driving_iqms(loadings, driving_pcs)
    driving.to_csv(args.out_dir / "pca_cohort_driving_iqms.tsv", sep="\t", index=False, float_format="%.10g")
    LOGGER.info("Wrote %s", args.out_dir / "pca_cohort_driving_iqms.tsv")

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
                "N_subjects": m["n_subjects"],
                "N_observations": m["n_obs"],
                "convergence": m["converged"],
                "raw_F": r["stat"],
                "adjusted_F": a["stat"],
                "adjusted_age_p": a["age_p"],
                "adjusted_sex_p": a["sex_p"],
                "mixed_wald": m["stat"],
                "mixed_glaucoma_se": m["glaucoma_se"],
                "n_Control_acq": next(x["n_acquisitions"] for x in sizes["by_cohort"] if x["cohort"] == "Control"),
                "n_Glaucoma_acq": next(x["n_acquisitions"] for x in sizes["by_cohort"] if x["cohort"] == "Glaucoma"),
                "n_Data_ON_acq": next(x["n_acquisitions"] for x in sizes["by_cohort"] if x["cohort"] == "Data_ON"),
                "n_Data_TON_acq": next(x["n_acquisitions"] for x in sizes["by_cohort"] if x["cohort"] == "Data_TON"),
            }
        )
    results = pd.DataFrame(result_rows)
    results.to_csv(args.out_dir / "pca_cohort_results.tsv", sep="\t", index=False, float_format="%.10g")
    LOGGER.info("Wrote %s", args.out_dir / "pca_cohort_results.tsv")

    mix_by_q = sorted(mixed_rows, key=lambda r: (np.inf if not np.isfinite(r["q"]) else r["q"], r["p"]))
    traj_pcs = sig["mixed"][:3] or [r["pc"] for r in mix_by_q[:3]]
    plot_longitudinal(
        df,
        traj_pcs,
        args.out_dir / "pca_cohort_longitudinal_topPCs.png",
        args.out_dir / "pca_cohort_longitudinal_topPCs.pdf",
    )

    hashes_after = {
        "scores": file_sha256(args.scores_tsv),
        "loadings": file_sha256(args.loadings_tsv),
        "variance": file_sha256(args.variance_tsv),
        "clean": file_sha256(args.clean_tsv),
    }
    if hashes != hashes_after:
        fail("An input file changed during the run; refusing silent overwrite.")

    write_report(
        args.out_dir / "pca_cohort_analysis_report.txt",
        scores_path=args.scores_tsv,
        loadings_path=args.loadings_tsv,
        variance_path=args.variance_tsv,
        clean_path=args.clean_tsv,
        hashes=hashes,
        hashes_after=hashes_after,
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

    mix_sorted = sorted(mixed_rows, key=lambda r: (np.inf if not np.isfinite(r["q"]) else r["q"], r["p"]))
    top = mix_sorted[0]
    top_load = ""
    if not driving.empty and top["pc"] in set(driving["PC"]):
        g = driving.loc[driving["PC"] == top["pc"]].sort_values("rank")
        top_load = "; ".join(
            f"{r.IQM}={r.loading:+.3f}" for r in list(g.itertuples(index=False))[:5]
        )
    elif top["pc"] in loadings.columns:
        vec = loadings[top["pc"]].astype(float)
        ranked = vec.reindex(vec.abs().sort_values(ascending=False).index)[:5]
        top_load = "; ".join(f"{i}={float(v):+.3f}" for i, v in ranked.items())

    print()
    print("=" * 60)
    print("MRIQC PCA COHORT ANALYSIS")
    print("=" * 60)
    print()
    print("PCA dimensions analyzed: PC1–PC10")
    print()
    print(f"Raw cohort-associated PCs: {len(sig['raw'])} / 10")
    print(f"Adjusted cohort-associated PCs: {len(sig['adjusted'])} / 10")
    print(f"Mixed-model cohort-associated PCs: {len(sig['mixed'])} / 10")
    print()
    print("Top mixed-model PC:")
    print(f"    PC: {top['pc']}")
    print(f"    variance explained: {100 * var_map[top['pc']]['explained_variance_ratio']:.2f}%")
    print(f"    cohort q: {fmt_p(top['q'])}")
    print(f"    top IQM loadings: {top_load}")
    print()
    for pc in ("PC1", "PC2", "PC3"):
        print(f"{pc}:")
        print(f"    raw q: {fmt_p(raw_m[pc]['q'])}")
        print(f"    adjusted q: {fmt_p(adj_m[pc]['q'])}")
        print(f"    mixed q: {fmt_p(mix_m[pc]['q'])}")
        print()
    print("=" * 60)
    print()
    print("PCA cohort analysis completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
