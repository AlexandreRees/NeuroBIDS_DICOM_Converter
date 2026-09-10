#!/usr/bin/env python3
"""Cohort differences in T1w MRIQC IQMs (Control, Glaucoma, Data_ON, Data_TON).

Models (T1w only; no outlier exclusion):
  raw:      IQM ~ cohort
  adjusted: IQM ~ cohort + age + sex
  mixed:    IQM ~ cohort + age + sex + session + (1|subject_id)
            implemented as statsmodels MixedLM with groups=subject_id

Requires scipy and statsmodels. On Narval:
  module load scipy-stack/2025a

Does not recompute PCA, does not use FreeSurfer, does not modify the clean TSV.

Example:
  python code/mriqc_iqm_cohort_analysis.py
  python code/mriqc_iqm_cohort_analysis.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import (  # noqa: E402
    EXPECTED_COHORTS,
    analytic_iqm_columns,
    fail,
    require_columns,
    require_file,
    to_numeric_iqm,
)

LOGGER = logging.getLogger("mriqc_iqm.cohort")
N_RETAINED_IQMS = 58
N_T1W_USABLE = 56
N_T1W_ROWS = 264
REF_COHORT = "Control"
MAX_FIGURE_IQMS = 12
FDR_ALPHA = 0.05


def study_root_default() -> Path:
    root = Path(__file__).resolve().parent.parent
    if not (root / "metadata").is_dir() or not (root / "qc_reports").is_dir():
        fail(
            f"Cannot resolve study root from {Path(__file__).resolve()}. "
            "Pass --study-root explicitly."
        )
    return root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--clean-tsv", type=Path, default=None)
    parser.add_argument("--roles-tsv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
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


def retained_iqm_columns(clean: pd.DataFrame, roles_path: Path) -> list[str]:
    require_file(roles_path, "column-role table")
    roles = pd.read_csv(roles_path, sep="\t")
    require_columns(roles, ["column", "retained_for_statistics", "role"], "column-role table")
    retained = roles.loc[roles["retained_for_statistics"].astype(bool), "column"].tolist()
    if len(retained) != N_RETAINED_IQMS:
        fail(f"Expected {N_RETAINED_IQMS} retained IQMs, found {len(retained)}.")
    missing = [c for c in retained if c not in clean.columns]
    if missing:
        fail(f"Retained IQMs absent from the clean table: {missing}")
    inferred = analytic_iqm_columns(clean)
    if set(inferred) != set(retained):
        fail("Retained IQM list disagrees with analytic_iqm_columns().")
    return retained


def select_t1w_iqms(t1: pd.DataFrame, iqm_cols: list[str]) -> tuple[list[str], list[str]]:
    dropped: list[str] = []
    kept: list[str] = []
    for col in iqm_cols:
        series = to_numeric_iqm(t1[col])
        valid = series.dropna()
        if valid.empty or valid.nunique(dropna=True) <= 1 or float(valid.std(ddof=0)) == 0.0:
            dropped.append(col)
        else:
            kept.append(col)
    if len(kept) != N_T1W_USABLE:
        fail(
            f"Expected {N_T1W_USABLE} non-constant T1w IQMs, found {len(kept)}. "
            f"Dropped: {dropped}"
        )
    return kept, dropped


def load_t1w(path: Path) -> pd.DataFrame:
    require_file(path, "clean IQM table")
    df = pd.read_csv(path, sep="\t")
    require_columns(
        df,
        ["sequence_group", "subject_id", "session", "run", "cohort"],
        "clean IQM table",
    )
    t1 = df.loc[df["sequence_group"].astype(str) == "T1w"].copy()
    if len(t1) != N_T1W_ROWS:
        fail(f"Expected {N_T1W_ROWS} T1w rows, found {len(t1)}. No row dropping.")
    extra = sorted(set(t1["cohort"].astype(str)) - set(EXPECTED_COHORTS))
    if extra:
        fail(f"Unexpected cohort labels: {extra}")
    missing_c = [c for c in EXPECTED_COHORTS if c not in set(t1["cohort"].astype(str))]
    if missing_c:
        fail(f"Cohorts absent from T1w table: {missing_c}")
    n_cohorts = t1.groupby("subject_id")["cohort"].nunique()
    if int((n_cohorts > 1).sum()):
        fail("At least one subject maps to multiple cohorts.")
    LOGGER.info("Loaded T1w rows: %d", len(t1))
    return t1


def covariate_status(t1: pd.DataFrame) -> dict[str, Any]:
    status = {
        "age_available": "age" in t1.columns and int(t1["age"].isna().sum()) == 0,
        "sex_available": "sex" in t1.columns and int(t1["sex"].isna().sum()) == 0,
        "session_available": "session" in t1.columns and int(t1["session"].isna().sum()) == 0,
        "subject_available": "subject_id" in t1.columns and int(t1["subject_id"].isna().sum()) == 0,
        "age_n_missing": int(t1["age"].isna().sum()) if "age" in t1.columns else None,
        "sex_n_missing": int(t1["sex"].isna().sum()) if "sex" in t1.columns else None,
    }
    if status["sex_available"]:
        levels = sorted(t1["sex"].astype(str).unique())
        if set(levels) - {"F", "M"}:
            fail(f"Unexpected sex values: {levels}")
    return status


def sample_sizes(t1: pd.DataFrame) -> dict[str, Any]:
    by_cohort = []
    for cohort in EXPECTED_COHORTS:
        sub = t1.loc[t1["cohort"] == cohort]
        by_cohort.append(
            {
                "cohort": cohort,
                "n_subjects": int(sub["subject_id"].nunique()),
                "n_sessions": int(sub.groupby(["subject_id", "session"]).ngroups),
                "n_acquisitions": int(len(sub)),
            }
        )
    n_ses = t1.groupby("subject_id")["session"].nunique()
    n_acq = t1.groupby("subject_id").size()
    return {
        "by_cohort": by_cohort,
        "n_subjects_total": int(t1["subject_id"].nunique()),
        "n_sessions_total": int(t1.groupby(["subject_id", "session"]).ngroups),
        "n_acquisitions_total": int(len(t1)),
        "sessions_per_subject": {str(k): int(v) for k, v in n_ses.value_counts().sort_index().items()},
        "acquisitions_per_subject_min": int(n_acq.min()),
        "acquisitions_per_subject_median": float(n_acq.median()),
        "acquisitions_per_subject_max": int(n_acq.max()),
    }


def cohort_term(ref: str = REF_COHORT) -> str:
    return f'C(cohort, Treatment("{ref}"))'


def fdr_bh(pvals: list[float], multipletests: Any) -> list[float]:
    arr = np.asarray(pvals, dtype=float)
    out = np.full(arr.shape, np.nan)
    ok = np.isfinite(arr)
    if ok.sum() == 0:
        return out.tolist()
    _, adj, _, _ = multipletests(arr[ok], alpha=FDR_ALPHA, method="fdr_bh")
    out[ok] = adj
    return out.tolist()


def empty_result(iqm: str, model: str, status: str, **extra: Any) -> dict[str, Any]:
    row = {
        "iqm": iqm,
        "model": model,
        "n_obs": np.nan,
        "n_subjects": np.nan,
        "r2": np.nan,
        "r2_adj": np.nan,
        "r2_marginal": np.nan,
        "r2_conditional": np.nan,
        "aic": np.nan,
        "bic": np.nan,
        "converged": False,
        "status": status,
        "global_test_method": "",
        "global_test_stat": np.nan,
        "global_test_df": np.nan,
        "global_test_p": np.nan,
        "global_test_p_fdr": np.nan,
        "term": "",
        "coef": np.nan,
        "se": np.nan,
        "ci_low": np.nan,
        "ci_high": np.nan,
        "p_value": np.nan,
        "p_fdr_term": np.nan,
    }
    row.update(extra)
    return row


def extract_terms(fit: Any, iqm: str, model: str, extras: dict[str, Any]) -> list[dict[str, Any]]:
    params = fit.params
    bse = fit.bse
    pvalues = fit.pvalues
    ci = fit.conf_int()
    rows = []
    for term in params.index:
        rows.append(
            {
                "iqm": iqm,
                "model": model,
                "term": str(term),
                "coef": float(params[term]),
                "se": float(bse[term]),
                "ci_low": float(ci.loc[term, 0]),
                "ci_high": float(ci.loc[term, 1]),
                "p_value": float(pvalues[term]) if np.isfinite(pvalues[term]) else np.nan,
                "p_fdr_term": np.nan,
                **extras,
            }
        )
    return rows


def ols_global_cohort_p(full: Any, reduced: Any, anova_lm: Any) -> tuple[str, float, float, float]:
    table = anova_lm(reduced, full)
    # last row is the full vs reduced comparison
    row = table.iloc[-1]
    stat = float(row["F"])
    p = float(row["Pr(>F)"])
    df = float(row["df_diff"]) if "df_diff" in table.columns else float(row.get("df", np.nan))
    return "nested_OLS_F_test_cohort", stat, df, p


def mixed_global_cohort_p(fit: Any, cohort_terms: list[str]) -> tuple[str, float, float, float]:
    if not cohort_terms:
        return "wald_cohort_terms_missing", float("nan"), float("nan"), float("nan")
    names = list(fit.params.index)
    r_matrix = np.zeros((len(cohort_terms), len(names)))
    for i, term in enumerate(cohort_terms):
        if term not in names:
            return "wald_cohort_term_not_in_params", float("nan"), float("nan"), float("nan")
        r_matrix[i, names.index(term)] = 1.0
    wres = fit.wald_test(r_matrix, scalar=True)
    stat = float(np.asarray(wres.statistic).squeeze())
    p = float(np.asarray(wres.pvalue).squeeze())
    df = float(len(cohort_terms))
    return "wald_test_cohort_fixed_effects", stat, df, p


def nakagawa_r2(fit: Any, fe_fitted: np.ndarray) -> tuple[float, float]:
    var_f = float(np.var(fe_fitted, ddof=1)) if len(fe_fitted) > 1 else float("nan")
    re_var = float("nan")
    cov = getattr(fit, "cov_re", None)
    if cov is not None and np.size(np.asarray(cov)) >= 1:
        re_var = float(np.asarray(cov).reshape(-1)[0])
    scale = float(fit.scale)
    denom = var_f + re_var + scale
    if not math.isfinite(denom) or denom <= 0:
        return float("nan"), float("nan")
    r2m = var_f / denom
    r2c = (var_f + re_var) / denom
    return r2m, r2c


def fit_ols_model(
    t1: pd.DataFrame,
    iqm: str,
    rhs: str,
    reduced_rhs: str,
    model: str,
    stats: dict[str, Any],
) -> list[dict[str, Any]]:
    smf = stats["smf"]
    anova_lm = stats["anova_lm"]
    work = t1[["subject_id", iqm] + [c for c in ("cohort", "age", "sex", "session") if c in t1.columns]].copy()
    work[iqm] = to_numeric_iqm(work[iqm])
    work = work.dropna(subset=[iqm])
    n_obs = int(len(work))
    n_subj = int(work["subject_id"].nunique())
    formula = f"{iqm} ~ {rhs}"
    try:
        full = smf.ols(formula, data=work).fit()
        reduced = smf.ols(f"{iqm} ~ {reduced_rhs}", data=work).fit()
        method, stat, df, p = ols_global_cohort_p(full, reduced, anova_lm)
        extras = {
            "n_obs": n_obs,
            "n_subjects": n_subj,
            "r2": float(full.rsquared),
            "r2_adj": float(full.rsquared_adj),
            "r2_marginal": np.nan,
            "r2_conditional": np.nan,
            "aic": float(full.aic),
            "bic": float(full.bic),
            "converged": True,
            "status": "ok",
            "global_test_method": method,
            "global_test_stat": stat,
            "global_test_df": df,
            "global_test_p": p,
            "global_test_p_fdr": np.nan,
        }
        return extract_terms(full, iqm, model, extras)
    except Exception as exc:
        LOGGER.warning("%s %s failed: %s", model, iqm, exc)
        return [empty_result(iqm, model, f"failed: {exc}")]


def fit_mixed_model(
    t1: pd.DataFrame,
    iqm: str,
    rhs: str,
    model: str,
    stats: dict[str, Any],
) -> list[dict[str, Any]]:
    smf = stats["smf"]
    work = t1[["subject_id", iqm, "cohort", "age", "sex", "session"]].copy()
    work[iqm] = to_numeric_iqm(work[iqm])
    work = work.dropna(subset=[iqm, "subject_id", "cohort", "age", "sex", "session"])
    n_obs = int(len(work))
    n_subj = int(work["subject_id"].nunique())
    formula = f"{iqm} ~ {rhs}"
    try:
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
                LOGGER.debug("mixed %s optimizer %s failed: %s", iqm, kwargs, exc)
        if fit is None:
            raise last_exc if last_exc is not None else RuntimeError("MixedLM produced no fit")
        converged = bool(getattr(fit, "converged", False))
        status = "ok" if converged else "not_converged"
        cohort_terms = [n for n in fit.params.index if n.startswith("C(cohort")]
        method, stat, df, p = mixed_global_cohort_p(fit, cohort_terms)
        try:
            re = fit.random_effects
            blup = work["subject_id"].map(lambda s: float(np.asarray(re[s]).reshape(-1)[0]))
            fe_fitted = np.asarray(fit.fittedvalues) - blup.to_numpy(dtype=float)
            r2m, r2c = nakagawa_r2(fit, fe_fitted)
        except Exception:
            r2m, r2c = float("nan"), float("nan")
        extras = {
            "n_obs": n_obs,
            "n_subjects": n_subj,
            "r2": np.nan,
            "r2_adj": np.nan,
            "r2_marginal": r2m,
            "r2_conditional": r2c,
            "aic": float(fit.aic) if fit.aic is not None else np.nan,
            "bic": float(fit.bic) if fit.bic is not None else np.nan,
            "converged": converged,
            "status": status,
            "global_test_method": method,
            "global_test_stat": stat,
            "global_test_df": df,
            "global_test_p": p,
            "global_test_p_fdr": np.nan,
        }
        rows = extract_terms(fit, iqm, model, extras)
        # drop Group Var from "coefficient" interpretation but keep it as a term
        return rows
    except Exception as exc:
        LOGGER.warning("mixed %s failed: %s", iqm, exc)
        LOGGER.debug(traceback.format_exc())
        return [empty_result(iqm, model, f"failed: {exc}", n_obs=n_obs, n_subjects=n_subj)]


def apply_fdr(rows: list[dict[str, Any]], multipletests: Any) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # one global p per IQM
    uniq = df.drop_duplicates("iqm")[["iqm", "global_test_p"]].copy()
    uniq["global_test_p_fdr"] = fdr_bh(uniq["global_test_p"].tolist(), multipletests)
    df = df.drop(columns=["global_test_p_fdr"], errors="ignore")
    df = df.merge(uniq[["iqm", "global_test_p_fdr"]], on="iqm", how="left")
    df["p_fdr_term"] = np.nan
    is_cohort = df["term"].astype(str).str.startswith("C(cohort")
    for term, idx in df.loc[is_cohort].groupby("term").groups.items():
        p_adj = fdr_bh(df.loc[idx, "p_value"].tolist(), multipletests)
        df.loc[idx, "p_fdr_term"] = p_adj
    return df


def plot_significant_boxplots(
    t1: pd.DataFrame,
    mixed_df: pd.DataFrame,
    dest_png: Path,
    dest_pdf: Path,
) -> list[str]:
    if mixed_df.empty or mixed_df["global_test_p_fdr"].isna().all():
        LOGGER.info("No mixed-model FDR values to plot.")
        return []
    per_iqm = mixed_df.drop_duplicates("iqm").copy()
    sig = per_iqm.loc[per_iqm["global_test_p_fdr"] < FDR_ALPHA].sort_values("global_test_p_fdr")
    note = "FDR q < 0.05 (mixed model global cohort test)"
    if sig.empty:
        sig = per_iqm.sort_values("global_test_p_fdr").head(6)
        note = "no IQM passed FDR; showing 6 smallest mixed-model FDR q-values"
    iqms = sig["iqm"].tolist()[:MAX_FIGURE_IQMS]
    n = len(iqms)
    ncols = 3 if n > 3 else max(n, 1)
    nrows = int(math.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.0 * ncols, 3.2 * nrows))
    axes = np.atleast_1d(axes).ravel()
    order = list(EXPECTED_COHORTS)
    for i, iqm in enumerate(iqms):
        ax = axes[i]
        data = [to_numeric_iqm(t1.loc[t1["cohort"] == c, iqm]).dropna().to_numpy() for c in order]
        bp = ax.boxplot(data, tick_labels=order, showfliers=True)
        for median in bp.get("medians", []):
            median.set_color("#222222")
        q = float(sig.loc[sig["iqm"] == iqm, "global_test_p_fdr"].iloc[0])
        ax.set_title(f"{iqm}\nq={q:.3g}", fontsize=9)
        ax.tick_params(axis="x", labelrotation=30, labelsize=7)
        ax.tick_params(axis="y", labelsize=7)
    for j in range(i + 1, len(axes)):
        axes[j].axis("off")
    fig.suptitle(f"T1w IQMs by cohort — {note}")
    fig.subplots_adjust(left=0.07, right=0.99, top=0.86, bottom=0.16, wspace=0.35, hspace=0.55)
    fig.savefig(dest_png, dpi=120)
    fig.savefig(dest_pdf)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest_png)
    LOGGER.info("Wrote %s", dest_pdf)
    return iqms


def write_report(
    path: Path,
    *,
    src_before: str,
    src_after: str,
    clean_path: Path,
    stats_info: dict[str, Any],
    sizes: dict[str, Any],
    cov: dict[str, Any],
    iqm_used: list[str],
    iqm_dropped: list[str],
    executed: dict[str, str],
    mixed_df: pd.DataFrame,
    raw_df: pd.DataFrame,
    adj_df: pd.DataFrame,
    plotted: list[str],
) -> None:
    def n_sig(df: pd.DataFrame) -> str:
        if df.empty or "global_test_p_fdr" not in df.columns:
            return "not executed"
        u = df.drop_duplicates("iqm")
        n_ok = int((u["status"] == "ok").sum())
        n_conv = int(u["converged"].sum()) if "converged" in u.columns else n_ok
        n_fdr = int((u["global_test_p_fdr"] < FDR_ALPHA).sum())
        return f"IQMs fitted={len(u)}, status_ok={n_ok}, converged={n_conv}, FDR_q<{FDR_ALPHA}: {n_fdr}"

    lines = [
        "T1w IQM cohort analysis report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "SCOPE",
        "  sequence_group: T1w only",
        "  outlier/MRIQC-flag exclusions: none",
        "  FreeSurfer / anatomical volumes / extra PCA / ML: not used",
        f"  source TSV: {clean_path}",
        f"  source sha256 before: {src_before}",
        f"  source sha256 after:  {src_after}",
        f"  source unmodified: {src_before == src_after}",
        "",
        "DEPENDENCIES",
        f"  scipy: {stats_info.get('scipy', 'MISSING')}",
        f"  statsmodels: {stats_info.get('statsmodels', 'MISSING')}",
        "  If scipy is missing on Narval: module load scipy-stack/2025a",
        "",
        "MODELS",
        "  raw:      IQM ~ C(cohort, Treatment(Control))",
        "            global cohort test: nested OLS F-test vs intercept-only",
        "  adjusted: IQM ~ C(cohort, Treatment(Control)) + age + C(sex)",
        "            global cohort test: nested OLS F-test vs age + sex",
        "  mixed:    IQM ~ C(cohort, Treatment(Control)) + age + C(sex) + C(session)",
        "            + random intercept (1|subject_id) via MixedLM(groups=subject_id)",
        "            global cohort test: Wald test of cohort fixed effects",
        "            (REML coefficients; Wald avoids invalid REML LRTs for fixed effects)",
        "  mixed pseudo-R2: Nakagawa-style marginal/conditional using var(FE fitted),",
        "            random-intercept variance, and residual scale",
        "",
        "EXECUTED",
        f"  raw: {executed.get('raw')}",
        f"  adjusted: {executed.get('adjusted')}",
        f"  mixed: {executed.get('mixed')}",
        "",
        "SAMPLE SIZE",
        f"  n_subjects: {sizes['n_subjects_total']}",
        f"  n_sessions: {sizes['n_sessions_total']}",
        f"  n_acquisitions: {sizes['n_acquisitions_total']}",
        f"  sessions_per_subject: {sizes['sessions_per_subject']}",
        f"  acquisitions_per_subject min/median/max: "
        f"{sizes['acquisitions_per_subject_min']}/"
        f"{sizes['acquisitions_per_subject_median']}/"
        f"{sizes['acquisitions_per_subject_max']}",
    ]
    for row in sizes["by_cohort"]:
        lines.append(
            f"  {row['cohort']}: subjects={row['n_subjects']} "
            f"sessions={row['n_sessions']} acquisitions={row['n_acquisitions']}"
        )
    lines.extend(
        [
            "",
            "COVARIATES",
            f"  age available (complete): {cov['age_available']}  missing={cov['age_n_missing']}",
            f"  sex available (complete): {cov['sex_available']}  missing={cov['sex_n_missing']}",
            f"  session available: {cov['session_available']}",
            f"  subject_id available: {cov['subject_available']}",
            "  Missing covariates are not imputed.",
            "",
            "IQMs",
            f"  n_used: {len(iqm_used)}",
            f"  n_dropped_zero_variance: {len(iqm_dropped)} {iqm_dropped}",
            f"  variables: {', '.join(iqm_used)}",
            "",
            "FDR",
            "  Benjamini-Hochberg across the 56 IQMs, separately within each model,",
            "  applied to (1) the global cohort p-value and (2) each cohort contrast vs Control.",
            f"  alpha={FDR_ALPHA}",
            f"  raw: {n_sig(raw_df)}",
            f"  adjusted: {n_sig(adj_df)}",
            f"  mixed: {n_sig(mixed_df)}",
            "",
            "FIGURE",
            f"  plotted IQMs: {plotted or 'none'}",
            "",
            "NOTES",
            "  Data_TON has very few subjects; mixed-model cohort contrasts for that",
            "  group are expected to be imprecise. Coefficients remain reported.",
            "  Multiple T1w runs within a session are retained; clustering is at subject_id.",
            "  A significant cohort term is a statistical association with IQMs, not a",
            "  biological or diagnostic interpretation.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def placeholder_table(iqms: list[str], model: str, status: str) -> pd.DataFrame:
    return pd.DataFrame([empty_result(iqm, model, status) for iqm in iqms])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    LOGGER.info("T1w IQM cohort analysis")

    stats = import_stats()
    if not stats["ok"]:
        msg = (
            "Missing statistical dependencies: "
            + "; ".join(stats["missing"])
            + ". On Narval run: module load scipy-stack/2025a "
            "(scipy). statsmodels must be importable (pip install --user statsmodels). "
            "No models were fitted. Complex methods were not reimplemented."
        )
        fail(msg)

    src_before = file_sha256(args.clean_tsv)
    t1 = load_t1w(args.clean_tsv)
    iqm_all = retained_iqm_columns(t1, args.roles_tsv)
    iqm_used, iqm_dropped = select_t1w_iqms(t1, iqm_all)
    cov = covariate_status(t1)
    sizes = sample_sizes(t1)

    rhs_cohort = cohort_term()
    executed = {}
    raw_rows: list[dict[str, Any]] = []
    LOGGER.info("Fitting raw OLS for %d IQMs", len(iqm_used))
    for iqm in iqm_used:
        raw_rows.extend(
            fit_ols_model(t1, iqm, rhs_cohort, "1", "raw", stats)
        )
    raw_df = apply_fdr(raw_rows, stats["multipletests"])
    executed["raw"] = "OLS IQM ~ cohort"

    if cov["age_available"] and cov["sex_available"]:
        rhs_adj = f"{rhs_cohort} + age + C(sex)"
        reduced_adj = "age + C(sex)"
        adj_rows: list[dict[str, Any]] = []
        LOGGER.info("Fitting adjusted OLS for %d IQMs", len(iqm_used))
        for iqm in iqm_used:
            adj_rows.extend(fit_ols_model(t1, iqm, rhs_adj, reduced_adj, "adjusted", stats))
        adj_df = apply_fdr(adj_rows, stats["multipletests"])
        executed["adjusted"] = "OLS IQM ~ cohort + age + sex"
    else:
        LOGGER.warning("age/sex incomplete; adjusted model not executed")
        adj_df = placeholder_table(iqm_used, "adjusted", "not_executed: age or sex unavailable")
        executed["adjusted"] = "not executed (age or sex unavailable; not invented)"

    mixed_ok = (
        cov["age_available"]
        and cov["sex_available"]
        and cov["session_available"]
        and cov["subject_available"]
    )
    if mixed_ok:
        rhs_mix = f"{rhs_cohort} + age + C(sex) + C(session)"
        mixed_rows: list[dict[str, Any]] = []
        LOGGER.info("Fitting mixed models for %d IQMs", len(iqm_used))
        for i, iqm in enumerate(iqm_used, start=1):
            if i == 1 or i % 10 == 0:
                LOGGER.info("  mixed %d/%d %s", i, len(iqm_used), iqm)
            mixed_rows.extend(fit_mixed_model(t1, iqm, rhs_mix, "mixed", stats))
        mixed_df = apply_fdr(mixed_rows, stats["multipletests"])
        executed["mixed"] = "MixedLM IQM ~ cohort + age + sex + session + (1|subject_id)"
    else:
        LOGGER.warning("mixed model covariates incomplete; not executed")
        mixed_df = placeholder_table(iqm_used, "mixed", "not_executed: required covariate unavailable")
        executed["mixed"] = "not executed (required covariate unavailable; not invented)"

    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.out_dir / "cohort_results_raw.tsv"
    adj_path = args.out_dir / "cohort_results_adjusted.tsv"
    mix_path = args.out_dir / "cohort_results_mixed.tsv"
    raw_df.to_csv(raw_path, sep="\t", index=False, float_format="%.10g")
    adj_df.to_csv(adj_path, sep="\t", index=False, float_format="%.10g")
    mixed_df.to_csv(mix_path, sep="\t", index=False, float_format="%.10g")
    LOGGER.info("Wrote %s", raw_path)
    LOGGER.info("Wrote %s", adj_path)
    LOGGER.info("Wrote %s", mix_path)

    plotted = plot_significant_boxplots(
        t1,
        mixed_df if executed["mixed"].startswith("MixedLM") else adj_df,
        args.out_dir / "cohort_iqm_boxplots_fdr.png",
        args.out_dir / "cohort_iqm_boxplots_fdr.pdf",
    )

    src_after = file_sha256(args.clean_tsv)
    if src_before != src_after:
        fail("Source TSV changed during the run.")

    write_report(
        args.out_dir / "cohort_analysis_report.txt",
        src_before=src_before,
        src_after=src_after,
        clean_path=args.clean_tsv,
        stats_info=stats,
        sizes=sizes,
        cov=cov,
        iqm_used=iqm_used,
        iqm_dropped=iqm_dropped,
        executed=executed,
        mixed_df=mixed_df,
        raw_df=raw_df,
        adj_df=adj_df,
        plotted=plotted,
    )

    def count_fdr(df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        return int((df.drop_duplicates("iqm")["global_test_p_fdr"] < FDR_ALPHA).sum())

    print()
    print("N T1w acquisitions:", sizes["n_acquisitions_total"])
    print("N subjects:", sizes["n_subjects_total"])
    for row in sizes["by_cohort"]:
        print(
            f"  {row['cohort']}: subjects={row['n_subjects']} "
            f"sessions={row['n_sessions']} acq={row['n_acquisitions']}"
        )
    print("N IQMs:", len(iqm_used))
    print("raw FDR-significant IQMs:", count_fdr(raw_df))
    print("adjusted FDR-significant IQMs:", count_fdr(adj_df))
    print("mixed FDR-significant IQMs:", count_fdr(mixed_df))
    print("mixed executed:", executed["mixed"])
    print("source TSV unmodified: yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
