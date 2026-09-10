#!/usr/bin/env python3
"""Longitudinal T1w IQM models: does change from ses-01 to ses-02 differ by cohort?

Principal model:
  IQM ~ C(cohort) * C(session) + age + C(sex) + (1|subject_id)

The interaction cohort:session is the primary longitudinal question.
Session main effect = overall change ses-01 → ses-02 (reference Control at ses-01
in the dummy coding, plus the session term).

Does not modify previous cohort scripts, the clean TSV, or PCA outputs.

Requires scipy + statsmodels. On Narval:
  module load scipy-stack/2025a

Example:
  python code/mriqc_iqm_longitudinal.py
  python code/mriqc_iqm_longitudinal.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
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
    analytic_iqm_columns,
    fail,
    require_columns,
    require_file,
    to_numeric_iqm,
)

LOGGER = logging.getLogger("mriqc_iqm.longitudinal")
N_RETAINED_IQMS = 58
N_T1W_USABLE = 56
N_T1W_ROWS = 264
REF_COHORT = "Control"
REF_SESSION = "ses-01"
FDR_ALPHA = 0.05
TOP_N_PLOT = 6
PRIOR_RESULTS = {
    "raw_fdr": "31/56",
    "adjusted_fdr": "20/56",
    "mixed_additive_fdr": "0/56",
}
COHORT_COLORS = {
    "Control": "#4C78A8",
    "Glaucoma": "#F58518",
    "Data_ON": "#54A24B",
    "Data_TON": "#E45756",
}


def study_root_default() -> Path:
    root = Path(__file__).resolve().parent.parent
    if not (root / "metadata").is_dir() or not (root / "qc_reports").is_dir():
        fail(f"Cannot resolve study root from {Path(__file__).resolve()}.")
    return root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Two distinct questions: (1) session = do IQMs change overall "
            "between ses-01 and ses-02? (2) cohort:session = does that change "
            "differ by cohort? The second is the primary result."
        ),
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

        out["scipy"] = scipy.__version__
    except ImportError as exc:
        missing.append(f"scipy ({exc})")
    try:
        import statsmodels
        import statsmodels.formula.api as smf
        from statsmodels.stats.multitest import multipletests

        out["statsmodels"] = statsmodels.__version__
        out["smf"] = smf
        out["multipletests"] = multipletests
    except ImportError as exc:
        missing.append(f"statsmodels ({exc})")
    if missing:
        out["ok"] = False
    return out


def retained_iqm_columns(clean: pd.DataFrame, roles_path: Path) -> list[str]:
    require_file(roles_path, "column-role table")
    roles = pd.read_csv(roles_path, sep="\t")
    require_columns(roles, ["column", "retained_for_statistics"], "column-role table")
    retained = roles.loc[roles["retained_for_statistics"].astype(bool), "column"].tolist()
    if len(retained) != N_RETAINED_IQMS:
        fail(f"Expected {N_RETAINED_IQMS} retained IQMs, found {len(retained)}.")
    missing = [c for c in retained if c not in clean.columns]
    if missing:
        fail(f"Retained IQMs missing from clean table: {missing}")
    if set(analytic_iqm_columns(clean)) != set(retained):
        fail("Retained IQM list disagrees with analytic_iqm_columns().")
    return retained


def select_t1w_iqms(t1: pd.DataFrame, iqm_cols: list[str]) -> tuple[list[str], list[str]]:
    kept, dropped = [], []
    for col in iqm_cols:
        series = to_numeric_iqm(t1[col])
        valid = series.dropna()
        if valid.empty or valid.nunique(dropna=True) <= 1 or float(valid.std(ddof=0)) == 0.0:
            dropped.append(col)
        else:
            kept.append(col)
    if len(kept) != N_T1W_USABLE:
        fail(f"Expected {N_T1W_USABLE} non-constant T1w IQMs, found {len(kept)}: {dropped}")
    return kept, dropped


def load_t1w(path: Path) -> pd.DataFrame:
    require_file(path, "clean IQM table")
    df = pd.read_csv(path, sep="\t")
    need = ["sequence_group", "subject_id", "session", "run", "cohort", "age", "sex"]
    require_columns(df, need, "clean IQM table")
    t1 = df.loc[df["sequence_group"].astype(str) == "T1w"].copy()
    if len(t1) != N_T1W_ROWS:
        fail(f"Expected {N_T1W_ROWS} T1w rows, found {len(t1)}.")
    extra = sorted(set(t1["cohort"].astype(str)) - set(EXPECTED_COHORTS))
    if extra:
        fail(f"Unexpected cohorts: {extra}")
    sessions = sorted(t1["session"].astype(str).unique())
    if set(sessions) != {"ses-01", "ses-02"}:
        fail(f"Unexpected session values: {sessions}")
    n_coh = t1.groupby("subject_id")["cohort"].nunique()
    if int((n_coh > 1).sum()):
        fail("A subject maps to more than one cohort.")
    key_dups = t1.duplicated(["subject_id", "session", "run"], keep=False)
    if key_dups.any():
        fail("Duplicate subject_id+session+run rows in T1w table.")
    LOGGER.info("Loaded T1w rows: %d", len(t1))
    return t1


def longitudinal_status(sessions: set[str]) -> str:
    has1 = REF_SESSION in sessions
    has2 = "ses-02" in sessions
    if has1 and has2:
        return "both_sessions"
    if has1:
        return "ses01_only"
    if has2:
        return "ses02_only"
    return "none"


def audit_structure(t1: pd.DataFrame) -> dict[str, Any]:
    subj_ses = t1.groupby("subject_id")["session"].apply(lambda s: set(s.astype(str)))
    status = subj_ses.map(longitudinal_status)
    coh = t1.drop_duplicates("subject_id").set_index("subject_id")["cohort"].astype(str)
    status_df = pd.DataFrame({"cohort": coh, "longitudinal_status": status})
    counts = (
        status_df.reset_index()
        .groupby(["cohort", "longitudinal_status"], dropna=False)
        .size()
        .rename("n_subjects")
        .reset_index()
    )
    # complete grid
    grid = pd.MultiIndex.from_product(
        [EXPECTED_COHORTS, ["ses01_only", "ses02_only", "both_sessions"]],
        names=["cohort", "longitudinal_status"],
    )
    counts = (
        counts.set_index(["cohort", "longitudinal_status"])
        .reindex(grid, fill_value=0)
        .reset_index()
    )
    cell = (
        t1.groupby(["cohort", "session"])
        .agg(
            n_subjects=("subject_id", "nunique"),
            n_acquisitions=("subject_id", "size"),
        )
        .reset_index()
    )
    acq_per_cell = t1.groupby(["subject_id", "session"]).size()
    n_multi = int((acq_per_cell > 1).sum())
    by_cohort = []
    for cohort in EXPECTED_COHORTS:
        sub = t1.loc[t1["cohort"] == cohort]
        st = status_df.loc[status_df["cohort"] == cohort, "longitudinal_status"]
        by_cohort.append(
            {
                "cohort": cohort,
                "n_subjects": int(sub["subject_id"].nunique()),
                "n_sessions": int(sub.groupby(["subject_id", "session"]).ngroups),
                "n_acquisitions": int(len(sub)),
                "n_ses01_only": int((st == "ses01_only").sum()),
                "n_ses02_only": int((st == "ses02_only").sum()),
                "n_both_sessions": int((st == "both_sessions").sum()),
            }
        )
    missing = {
        "age": int(t1["age"].isna().sum()),
        "sex": int(t1["sex"].isna().sum()),
        "session": int(t1["session"].isna().sum()),
        "cohort": int(t1["cohort"].isna().sum()),
        "subject_id": int(t1["subject_id"].isna().sum()),
    }
    return {
        "n_subjects": int(t1["subject_id"].nunique()),
        "n_sessions": int(t1.groupby(["subject_id", "session"]).ngroups),
        "n_acquisitions": int(len(t1)),
        "n_ses01_only": int((status == "ses01_only").sum()),
        "n_ses02_only": int((status == "ses02_only").sum()),
        "n_both_sessions": int((status == "both_sessions").sum()),
        "by_cohort": by_cohort,
        "counts_table": counts,
        "cell_table": cell,
        "n_subject_session_cells": int(len(acq_per_cell)),
        "n_subject_session_with_multiple_t1w": n_multi,
        "acq_per_subject_session": {
            str(k): int(v) for k, v in acq_per_cell.value_counts().sort_index().items()
        },
        "missing": missing,
        "status_by_subject": status,
    }


def wald_terms(fit: Any, terms: list[str]) -> tuple[float, float, int]:
    if not terms:
        return float("nan"), float("nan"), 0
    names = list(fit.params.index)
    r_matrix = np.zeros((len(terms), len(names)))
    for i, term in enumerate(terms):
        if term not in names:
            return float("nan"), float("nan"), len(terms)
        r_matrix[i, names.index(term)] = 1.0
    wres = fit.wald_test(r_matrix, scalar=True)
    stat = float(np.asarray(wres.statistic).squeeze())
    p = float(np.asarray(wres.pvalue).squeeze())
    return stat, p, len(terms)


def coef_block(fit: Any, term: str) -> dict[str, float]:
    if term not in fit.params.index:
        return {
            "estimate": float("nan"),
            "se": float("nan"),
            "ci_low": float("nan"),
            "ci_high": float("nan"),
            "p": float("nan"),
        }
    ci = fit.conf_int().loc[term]
    return {
        "estimate": float(fit.params[term]),
        "se": float(fit.bse[term]),
        "ci_low": float(ci.iloc[0]),
        "ci_high": float(ci.iloc[1]),
        "p": float(fit.pvalues[term]),
    }


def classify_terms(param_names: list[str]) -> dict[str, list[str]]:
    cohort, session, interaction = [], [], []
    for name in param_names:
        is_coh = "C(cohort" in name
        is_ses = "C(session" in name
        if is_coh and is_ses:
            interaction.append(name)
        elif is_coh:
            cohort.append(name)
        elif is_ses:
            session.append(name)
    return {"cohort": cohort, "session": session, "interaction": interaction}


def fit_one(t1: pd.DataFrame, iqm: str, smf: Any, n_long: int) -> dict[str, Any]:
    work = t1[
        ["subject_id", "cohort", "session", "age", "sex", iqm]
    ].copy()
    work[iqm] = to_numeric_iqm(work[iqm])
    work = work.dropna(subset=[iqm, "subject_id", "cohort", "session", "age", "sex"])
    rhs = (
        f'C(cohort, Treatment("{REF_COHORT}")) * C(session, Treatment("{REF_SESSION}"))'
        " + age + C(sex)"
    )
    formula = f"{iqm} ~ {rhs}"
    warns: list[str] = []
    n_obs = int(len(work))
    n_subj = int(work["subject_id"].nunique())
    base = {
        "IQM": iqm,
        "N_subjects": n_subj,
        "N_observations": n_obs,
        "N_longitudinal_subjects": n_long,
        "cohort_effect": np.nan,
        "cohort_p": np.nan,
        "cohort_q": np.nan,
        "session_effect": np.nan,
        "session_se": np.nan,
        "session_ci_low": np.nan,
        "session_ci_high": np.nan,
        "session_p": np.nan,
        "session_q": np.nan,
        "interaction": np.nan,
        "interaction_p": np.nan,
        "interaction_q": np.nan,
        "convergence": False,
        "warnings": "",
        "status": "failed",
    }
    try:
        md = smf.mixedlm(formula, data=work, groups=work["subject_id"])
        fit = None
        last_exc: Exception | None = None
        for kwargs in (
            {"reml": True, "maxiter": 300},
            {"method": "nm", "reml": True, "maxiter": 400},
            {"method": "powell", "reml": True, "maxiter": 400},
        ):
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    cand = md.fit(**kwargs)
                fit = cand
                warns.extend(str(w.message) for w in caught)
                if bool(getattr(cand, "converged", False)):
                    break
            except Exception as exc:
                last_exc = exc
        if fit is None:
            raise last_exc if last_exc is not None else RuntimeError("no MixedLM fit")
        groups = classify_terms(list(fit.params.index))
        c_stat, c_p, _ = wald_terms(fit, groups["cohort"])
        s_stat, s_p, _ = wald_terms(fit, groups["session"])
        i_stat, i_p, _ = wald_terms(fit, groups["interaction"])
        ses_name = groups["session"][0] if groups["session"] else ""
        ses = coef_block(fit, ses_name) if ses_name else coef_block(fit, "")
        inter_detail = []
        for term in groups["interaction"]:
            blk = coef_block(fit, term)
            inter_detail.append(
                f"{term}: est={blk['estimate']:.6g} SE={blk['se']:.6g} "
                f"CI=[{blk['ci_low']:.6g},{blk['ci_high']:.6g}] p={blk['p']:.4g}"
            )
        # model-based ses-02 minus ses-01 change per cohort (reference coding)
        change = {"Control": ses["estimate"]}
        for term in groups["interaction"]:
            # e.g. ...[T.Glaucoma]:C(session, Treatment("ses-01"))[T.ses-02]
            cohort_label = None
            for c in EXPECTED_COHORTS:
                if f"[T.{c}]" in term.split(":")[0]:
                    cohort_label = c
                    break
            if cohort_label:
                change[cohort_label] = ses["estimate"] + coef_block(fit, term)["estimate"]
        uniq_warns = sorted({w.split("\n")[0][:160] for w in warns if w})
        base.update(
            {
                "cohort_effect": c_stat,
                "cohort_p": c_p,
                "session_effect": ses["estimate"],
                "session_se": ses["se"],
                "session_ci_low": ses["ci_low"],
                "session_ci_high": ses["ci_high"],
                "session_p": ses["p"] if math.isfinite(ses["p"]) else s_p,
                "interaction": i_stat,
                "interaction_p": i_p,
                "convergence": bool(getattr(fit, "converged", False)),
                "warnings": " | ".join(uniq_warns)[:1000],
                "status": "ok" if bool(getattr(fit, "converged", False)) else "not_converged",
                "interaction_coefficients": " || ".join(inter_detail),
                "change_Control": change.get("Control", np.nan),
                "change_Glaucoma": change.get("Glaucoma", np.nan),
                "change_Data_ON": change.get("Data_ON", np.nan),
                "change_Data_TON": change.get("Data_TON", np.nan),
            }
        )
        return base
    except Exception as exc:
        LOGGER.warning("%s failed: %s", iqm, exc)
        LOGGER.debug(traceback.format_exc())
        base["warnings"] = f"failed: {exc}"
        base["status"] = "failed"
        return base


def fdr_column(series: pd.Series, multipletests: Any) -> pd.Series:
    out = pd.Series(np.nan, index=series.index, dtype=float)
    ok = series.notna() & np.isfinite(series.to_numpy(dtype=float))
    if int(ok.sum()) == 0:
        return out
    _, adj, _, _ = multipletests(series.loc[ok].to_numpy(dtype=float), alpha=FDR_ALPHA, method="fdr_bh")
    out.loc[ok] = adj
    return out


def subject_session_means(t1: pd.DataFrame, iqm: str, both_ids: set[str]) -> pd.DataFrame:
    sub = t1.loc[t1["subject_id"].isin(both_ids), ["subject_id", "cohort", "session", iqm]].copy()
    sub[iqm] = to_numeric_iqm(sub[iqm])
    return (
        sub.groupby(["subject_id", "cohort", "session"], as_index=False)[iqm]
        .mean()
        .rename(columns={iqm: "value"})
    )


def plot_top_interactions(
    t1: pd.DataFrame,
    results: pd.DataFrame,
    both_ids: set[str],
    dest_png: Path,
    dest_pdf: Path,
) -> list[str]:
    ranked = results.sort_values("interaction_q", na_position="last")
    iqms = ranked["IQM"].head(TOP_N_PLOT).tolist()
    fig, axes = plt.subplots(2, 3, figsize=(11.2, 7.2))
    axes = np.atleast_1d(axes).ravel()
    xmap = {"ses-01": 0, "ses-02": 1}
    for i, iqm in enumerate(iqms):
        ax = axes[i]
        means = subject_session_means(t1, iqm, both_ids)
        q = ranked.loc[ranked["IQM"] == iqm, "interaction_q"].iloc[0]
        p = ranked.loc[ranked["IQM"] == iqm, "interaction_p"].iloc[0]
        for cohort in EXPECTED_COHORTS:
            color = COHORT_COLORS[cohort]
            cdat = means.loc[means["cohort"] == cohort]
            for sid, g in cdat.groupby("subject_id"):
                if set(g["session"]) != {"ses-01", "ses-02"}:
                    continue
                g = g.sort_values("session")
                ax.plot(
                    [xmap[s] for s in g["session"]],
                    g["value"],
                    color=color,
                    alpha=0.18,
                    lw=0.8,
                )
            ys, yerr = [], []
            for ses in ("ses-01", "ses-02"):
                v = cdat.loc[cdat["session"] == ses, "value"]
                ys.append(float(v.mean()) if len(v) else np.nan)
                if len(v) >= 2:
                    yerr.append(1.96 * float(v.std(ddof=1)) / math.sqrt(len(v)))
                else:
                    yerr.append(np.nan)
            ax.errorbar(
                [0, 1],
                ys,
                yerr=[0 if np.isnan(e) else e for e in yerr],
                color=color,
                lw=2.2,
                marker="o",
                capsize=3,
                label=cohort,
            )
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["ses-01", "ses-02"])
        ax.set_title(f"{iqm}\ninteraction q={q:.3g}  p={p:.3g}", fontsize=9)
        ax.tick_params(labelsize=8)
        if i == 0:
            ax.legend(frameon=False, fontsize=7, loc="best")
    for j in range(i + 1, len(axes)):
        axes[j].axis("off")
    fig.suptitle(
        "T1w IQM trajectories (subject-session means) for the 6 smallest "
        "cohort×session interaction q-values\n"
        "Thin lines: subjects with both sessions. Bold: cohort mean ± 95% CI "
        "(CI omitted if n<2). Display aggregation only; models used all T1w runs."
    )
    fig.subplots_adjust(left=0.07, right=0.99, top=0.84, bottom=0.08, wspace=0.32, hspace=0.42)
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
    audit: dict[str, Any],
    iqm_used: list[str],
    iqm_dropped: list[str],
    results: pd.DataFrame,
    plotted: list[str],
) -> None:
    n_ok = int((results["status"] == "ok").sum())
    n_conv = int(results["convergence"].astype(bool).sum())
    n_fail = int((results["status"] == "failed").sum())
    n_int = int((results["interaction_q"] < FDR_ALPHA).sum())
    n_coh = int((results["cohort_q"] < FDR_ALPHA).sum())
    n_ses = int((results["session_q"] < FDR_ALPHA).sum())
    top = results.sort_values("interaction_q", na_position="last").head(TOP_N_PLOT)
    sig = results.loc[results["interaction_q"] < FDR_ALPHA]
    lines = [
        "T1w IQM longitudinal analysis report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "TWO QUESTIONS (do not conflate)",
        "  Session main effect: do IQMs change globally between ses-01 and ses-02?",
        "  Interaction cohort × session: does that change differ by cohort?",
        "  The interaction is the primary longitudinal result.",
        "",
        "SCOPE",
        "  sequence_group: T1w only; 56 non-constant IQMs; outliers not removed",
        "  FreeSurfer / extra PCA / previous cohort script: not modified, not rerun",
        f"  source TSV: {clean_path}",
        f"  source sha256 before: {src_before}",
        f"  source sha256 after:  {src_after}",
        f"  source unmodified: {src_before == src_after}",
        "",
        "1. LONGITUDINAL STRUCTURE",
        f"  n_subjects: {audit['n_subjects']}",
        f"  n_sessions (subject×session cells): {audit['n_sessions']}",
        f"  n_acquisitions: {audit['n_acquisitions']}",
        f"  ses01_only subjects: {audit['n_ses01_only']}",
        f"  ses02_only subjects: {audit['n_ses02_only']}",
        f"  both_sessions (truly longitudinal): {audit['n_both_sessions']}",
        f"  subject×session cells with >1 T1w run: {audit['n_subject_session_with_multiple_t1w']}"
        f" / {audit['n_subject_session_cells']}",
        f"  acquisitions per subject×session: {audit['acq_per_subject_session']}",
        "  Multiple T1w runs in the same session were KEPT in MixedLM (not dropped).",
        "  Trajectories in the figure use the mean of those runs for display only.",
        "",
        "2. COUNTS BY COHORT",
    ]
    for row in audit["by_cohort"]:
        lines.append(
            f"  {row['cohort']}: subjects={row['n_subjects']} sessions={row['n_sessions']} "
            f"acq={row['n_acquisitions']} | ses01_only={row['n_ses01_only']} "
            f"ses02_only={row['n_ses02_only']} both={row['n_both_sessions']}"
        )
    lines.append("  cohort × longitudinal_status:")
    for rec in audit["counts_table"].to_dict("records"):
        lines.append(
            f"    {rec['cohort']:10s}  {rec['longitudinal_status']:14s}  n={rec['n_subjects']}"
        )
    lines.extend(
        [
            "",
            "  Missing values in model covariates:",
            f"    {audit['missing']}",
            "",
            "3. METHOD",
            f"  scipy {stats_info.get('scipy')}  statsmodels {stats_info.get('statsmodels')}",
            "  MixedLM: IQM ~ C(cohort, Treatment(Control)) * C(session, Treatment(ses-01))",
            "            + age + C(sex), groups=subject_id, REML",
            "  Session term: model-based change ses-02 − ses-01 for the Control reference.",
            "  Cohort terms: main-effect contrasts vs Control at ses-01.",
            "  Interaction terms: additional change (ses-02 − ses-01) vs Control.",
            "  Global tests: Wald on the corresponding blocks of fixed effects.",
            "  FDR Benjamini-Hochberg applied separately to 56 cohort tests, 56 session",
            "  tests, and 56 interaction tests (three families, not pooled).",
            "",
            "4. PREVIOUS COHORT MODELS (not recomputed)",
            f"  raw IQM ~ cohort: {PRIOR_RESULTS['raw_fdr']} FDR < 0.05",
            f"  adjusted IQM ~ cohort + age + sex: {PRIOR_RESULTS['adjusted_fdr']} FDR < 0.05",
            f"  mixed without interaction: {PRIOR_RESULTS['mixed_additive_fdr']} FDR < 0.05",
            "",
            "5. COHORT MAIN EFFECT (this model, at ses-01 vs Control)",
            f"  N FDR q<0.05: {n_coh} / 56",
            f"  min q: {results['cohort_q'].min():.6g}",
            "",
            "6. SESSION MAIN EFFECT (overall ses-02 vs ses-01, Control coding)",
            f"  N FDR q<0.05: {n_ses} / 56",
            f"  min q: {results['session_q'].min():.6g}",
            "",
            "7. INTERACTION COHORT × SESSION (PRIMARY)",
            f"  N tested: 56",
            f"  N FDR q<0.05: {n_int}",
            f"  min q: {results['interaction_q'].min():.6g}",
            f"  IQM with min q: {results.sort_values('interaction_q').iloc[0]['IQM']}",
            "",
        ]
    )
    if sig.empty:
        lines.append(
            "  No IQM had a significant cohort×session interaction after FDR."
        )
        lines.append(
            "  No mass post-hoc contrast set was run (interaction not FDR-significant)."
        )
    else:
        lines.append("  FDR-significant interactions:")
        for rec in sig.sort_values("interaction_q").itertuples(index=False):
            lines.append(
                f"    {rec.IQM}: Wald={rec.interaction:.4g} p={rec.interaction_p:.4g} "
                f"q={rec.interaction_q:.4g}"
            )
            lines.append(f"      {rec.interaction_coefficients}")
            lines.append(
                "      model-based Δ (ses-02 − ses-01): "
                f"Control={rec.change_Control:.4g} Glaucoma={rec.change_Glaucoma:.4g} "
                f"Data_ON={rec.change_Data_ON:.4g} Data_TON={rec.change_Data_TON:.4g}"
            )
    lines.extend(
        [
            "",
            "8. SMALLEST INTERACTION q-VALUES (plotted)",
        ]
    )
    for rec in top.itertuples(index=False):
        lines.append(
            f"  {rec.IQM}: interaction_p={rec.interaction_p:.4g} q={rec.interaction_q:.4g} "
            f"session_est={rec.session_effect:.4g} [{rec.session_ci_low:.4g},{rec.session_ci_high:.4g}]"
        )
    lines.extend(
        [
            "",
            "9. LIMITATIONS",
            "  Data_ON has only 1 subject with both sessions; Data_TON has only 1.",
            "  Interaction coefficients for those cohorts are extremely imprecise.",
            "  Do not draw strong conclusions from Data_TON (or Data_ON) trajectories.",
            "  Control has 39 longitudinal subjects; Glaucoma has 8.",
            "  Multiple T1w runs per session inflate N_observations relative to N_sessions.",
            "  Age is a between-subject covariate (not time-varying in this table).",
            "",
            "10. CONVERGENCE",
            f"  fitted_ok: {n_ok}  converged: {n_conv}  failed: {n_fail}  / 56",
            f"  IQMs used: {len(iqm_used)}  dropped zero-variance: {iqm_dropped}",
            f"  plotted: {plotted}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    LOGGER.info("T1w IQM longitudinal MixedLM (cohort × session)")

    stats = import_stats()
    if not stats["ok"]:
        fail(
            "Missing statistical dependencies: "
            + "; ".join(stats["missing"])
            + ". On Narval: module load scipy-stack/2025a. MixedLM was not reimplemented."
        )

    src_before = file_sha256(args.clean_tsv)
    t1 = load_t1w(args.clean_tsv)
    iqm_all = retained_iqm_columns(t1, args.roles_tsv)
    iqm_used, iqm_dropped = select_t1w_iqms(t1, iqm_all)
    audit = audit_structure(t1)
    both_ids = set(audit["status_by_subject"].loc[lambda s: s == "both_sessions"].index)
    n_long = len(both_ids)

    LOGGER.info(
        "Longitudinal subjects (both sessions): %d / %d",
        n_long,
        audit["n_subjects"],
    )
    LOGGER.info(
        "Keeping %d subject×session cells with multiple T1w runs (not dropped)",
        audit["n_subject_session_with_multiple_t1w"],
    )

    rows = []
    for i, iqm in enumerate(iqm_used, start=1):
        if i == 1 or i % 10 == 0:
            LOGGER.info("  mixed %d/%d %s", i, len(iqm_used), iqm)
        rows.append(fit_one(t1, iqm, stats["smf"], n_long))
    results = pd.DataFrame(rows)
    mt = stats["multipletests"]
    results["cohort_q"] = fdr_column(results["cohort_p"], mt)
    results["session_q"] = fdr_column(results["session_p"], mt)
    results["interaction_q"] = fdr_column(results["interaction_p"], mt)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    counts_path = args.out_dir / "longitudinal_subject_counts.tsv"
    audit["counts_table"].to_csv(counts_path, sep="\t", index=False)
    LOGGER.info("Wrote %s", counts_path)

    keep_cols = [
        "IQM",
        "N_subjects",
        "N_observations",
        "N_longitudinal_subjects",
        "cohort_effect",
        "cohort_p",
        "cohort_q",
        "session_effect",
        "session_se",
        "session_ci_low",
        "session_ci_high",
        "session_p",
        "session_q",
        "interaction",
        "interaction_p",
        "interaction_q",
        "convergence",
        "warnings",
        "status",
        "interaction_coefficients",
        "change_Control",
        "change_Glaucoma",
        "change_Data_ON",
        "change_Data_TON",
    ]
    out = results[keep_cols].copy()
    res_path = args.out_dir / "longitudinal_results.tsv"
    out.to_csv(res_path, sep="\t", index=False, float_format="%.10g")
    LOGGER.info("Wrote %s", res_path)

    plotted = plot_top_interactions(
        t1,
        results,
        both_ids,
        args.out_dir / "mixed_longitudinal_top_interactions.png",
        args.out_dir / "mixed_longitudinal_top_interactions.pdf",
    )

    src_after = file_sha256(args.clean_tsv)
    if src_before != src_after:
        fail("Source TSV changed during the run.")

    write_report(
        args.out_dir / "longitudinal_analysis_report.txt",
        src_before=src_before,
        src_after=src_after,
        clean_path=args.clean_tsv,
        stats_info=stats,
        audit=audit,
        iqm_used=iqm_used,
        iqm_dropped=iqm_dropped,
        results=results,
        plotted=plotted,
    )

    long_by_c = {r["cohort"]: r["n_both_sessions"] for r in audit["by_cohort"]}
    imin = results.sort_values("interaction_q").iloc[0]
    print()
    print("Longitudinal subjects:")
    print(f"Control: {long_by_c['Control']}")
    print(f"Glaucoma: {long_by_c['Glaucoma']}")
    print(f"Data_ON: {long_by_c['Data_ON']}")
    print(f"Data_TON: {long_by_c['Data_TON']}")
    print()
    print("Interaction cohort × session:")
    print("N tested: 56")
    print("N FDR < 0.05:", int((results["interaction_q"] < FDR_ALPHA).sum()))
    print("Minimum q:", f"{imin['interaction_q']:.6g}")
    print("IQM with minimum q:", imin["IQM"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
