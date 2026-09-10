#!/usr/bin/env python3
"""Session-level T1w MRIQC validation of the longitudinal cohort × session model.

Selects, for each subject × session, the exact T1w run recorded in the
FreeSurfer manifest. Does not average IQMs. Does not modify previous
longitudinal outputs, the clean TSV, or mriqc_iqm_longitudinal.py.

Requires scipy + statsmodels. On Narval:
  module load scipy-stack/2025a

Example:
  python code/mriqc_iqm_session_level.py
  python code/mriqc_iqm_session_level.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import re
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
    normalize_run,
    require_columns,
    require_file,
    to_numeric_iqm,
)

LOGGER = logging.getLogger("mriqc_iqm.session_level")
N_RETAINED_IQMS = 58
N_T1W_USABLE = 56
REF_COHORT = "Control"
REF_SESSION = "ses-01"
FDR_ALPHA = 0.05
TOP_N_PLOT = 6
FOCUS_IQMS = ("rpve_csf", "summary_csf_p05")
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
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--clean-tsv", type=Path, default=None)
    parser.add_argument("--roles-tsv", type=Path, default=None)
    parser.add_argument("--freesurfer-manifest", type=Path, default=None)
    parser.add_argument("--previous-results", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default()
    args.study_root = root
    args.clean_tsv = args.clean_tsv.resolve() if args.clean_tsv else root / "metadata" / "mriqc_iqm_clean.tsv"
    args.roles_tsv = args.roles_tsv.resolve() if args.roles_tsv else root / "metadata" / "mriqc_iqm_column_roles.tsv"
    if args.freesurfer_manifest:
        args.freesurfer_manifest = args.freesurfer_manifest.resolve()
    else:
        local = root / "metadata" / "freesurfer_manifest.tsv"
        sibling = root.parent / "metadata" / "freesurfer_manifest.tsv"
        args.freesurfer_manifest = local if local.is_file() else sibling
    args.previous_results = (
        args.previous_results.resolve()
        if args.previous_results
        else root / "qc_reports" / "mriqc_iqm" / "longitudinal_results.tsv"
    )
    args.out_dir = args.out_dir.resolve() if args.out_dir else root / "qc_reports" / "mriqc_iqm"
    args.qc_root = root / "qc_reports"
    args.session_tsv = root / "metadata" / "mriqc_iqm_session_t1w.tsv"
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
        import scipy

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


def rel_to_study(path: Path, study_root: Path) -> str:
    path = path.resolve()
    root = study_root.resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            return Path("..", path.relative_to(root.parent)).as_posix()
        except ValueError:
            return path.name


def bids_stem_from_path(path_str: str) -> str:
    name = Path(str(path_str)).name
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")]
    if name.endswith(".nii"):
        return name[: -len(".nii")]
    return Path(name).stem


def schema_summary(mriqc: pd.DataFrame, manifest: pd.DataFrame) -> str:
    mriqc_ids = [
        c
        for c in [
            "subject_id",
            "session",
            "run",
            "bids_name",
            "filename",
            "input_file",
            "cohort",
            "age",
            "sex",
            "sequence_group",
            "protocol_name",
        ]
        if c in mriqc.columns
    ]
    lines = [
        f"mriqc_iqm_clean.tsv: {mriqc.shape[0]} rows, {mriqc.shape[1]} columns",
        f"id/metadata columns present: {mriqc_ids}",
        f"freesurfer_manifest.tsv: {manifest.shape[0]} rows, columns={list(manifest.columns)}",
        "Matching keys: subject_id + session + normalized run, confirmed by bids_name vs t1w_path stem.",
        "sequence_group == T1w is the MRIQC anatomical MPRAGE subset (WM-nulled is sequence_group=WMn).",
    ]
    return "\n".join(lines)


def load_mriqc(path: Path) -> pd.DataFrame:
    require_file(path, "clean IQM table")
    df = pd.read_csv(path, sep="\t")
    require_columns(
        df,
        ["subject_id", "session", "run", "bids_name", "cohort", "age", "sex", "sequence_group"],
        "clean IQM table",
    )
    LOGGER.info("Loaded MRIQC clean table: %s (%d rows)", path, len(df))
    return df


def load_freesurfer_manifest(path: Path) -> pd.DataFrame:
    require_file(path, "FreeSurfer manifest")
    df = pd.read_csv(path, sep="\t")
    require_columns(df, ["subject_id", "session", "run", "t1w_path"], "FreeSurfer manifest")
    if df.duplicated(["subject_id", "session"]).any():
        fail("FreeSurfer manifest has duplicate subject_id × session rows.")
    LOGGER.info("Loaded FreeSurfer manifest: %s (%d rows)", path, len(df))
    return df


def identify_iqms(clean: pd.DataFrame, roles_path: Path) -> tuple[list[str], list[str]]:
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
    t1 = clean.loc[clean["sequence_group"].astype(str) == "T1w"]
    kept, dropped = [], []
    for col in retained:
        series = to_numeric_iqm(t1[col])
        valid = series.dropna()
        if valid.empty or valid.nunique(dropna=True) <= 1 or float(valid.std(ddof=0)) == 0.0:
            dropped.append(col)
        else:
            kept.append(col)
    if len(kept) != N_T1W_USABLE:
        fail(f"Expected {N_T1W_USABLE} non-constant T1w IQMs, found {len(kept)} dropped={dropped}")
    return kept, dropped


def match_session_level_t1w(t1: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    t1 = t1.copy()
    t1["run_norm"] = t1["run"].map(normalize_run)
    t1["bids_stem"] = t1["bids_name"].astype(str)
    manifest = manifest.copy()
    manifest["run_norm"] = manifest["run"].map(normalize_run)
    manifest["fs_bids_stem"] = manifest["t1w_path"].map(bids_stem_from_path)
    rows = []
    for fs in manifest.itertuples(index=False):
        sub, ses = fs.subject_id, fs.session
        cand = t1.loc[(t1["subject_id"] == sub) & (t1["session"] == ses)]
        n_cand = int(len(cand))
        run_hits = cand.loc[cand["run_norm"] == fs.run_norm]
        stem_hits = cand.loc[cand["bids_stem"] == fs.fs_bids_stem]
        status = "OTHER"
        reason = ""
        matched = None
        if n_cand == 0:
            status = "NO_MRIQC"
            reason = "No T1w MRIQC row for this subject × session"
        elif len(run_hits) == 1:
            matched = run_hits.iloc[0]
            if matched["bids_stem"] != fs.fs_bids_stem:
                status = "IDENTIFIER_MISMATCH"
                reason = (
                    f"run {fs.run_norm} matched uniquely but bids_name "
                    f"{matched['bids_stem']} != FreeSurfer {fs.fs_bids_stem}"
                )
                matched = None
            else:
                status = "MATCHED"
                reason = f"unique subject+session+run match ({getattr(fs, 'selection_reason', '')})"
        elif len(run_hits) > 1:
            status = "MULTIPLE_POSSIBLE_MATCHES"
            reason = f"{len(run_hits)} MRIQC rows share subject, session, run={fs.run_norm}"
        elif len(stem_hits) == 1:
            status = "IDENTIFIER_MISMATCH"
            reason = (
                f"bids_name matched {fs.fs_bids_stem} but run did not "
                f"(FS run={fs.run_norm}, MRIQC runs={sorted(cand['run_norm'].unique())})"
            )
        elif len(stem_hits) > 1:
            status = "MULTIPLE_POSSIBLE_MATCHES"
            reason = f"{len(stem_hits)} MRIQC rows share bids_name {fs.fs_bids_stem}"
        else:
            status = "IDENTIFIER_MISMATCH"
            reason = (
                f"No MRIQC row with run={fs.run_norm} or bids_name={fs.fs_bids_stem}; "
                f"candidates runs={sorted(cand['run_norm'].unique())}"
            )
        rows.append(
            {
                "subject_id": sub,
                "session": ses,
                "cohort": None if matched is None else matched["cohort"],
                "freesurfer_selected_run": fs.run,
                "freesurfer_selected_bids_name": fs.fs_bids_stem,
                "freesurfer_t1w_path": fs.t1w_path,
                "freesurfer_selection_reason": getattr(fs, "selection_reason", ""),
                "mriqc_matched_run": "" if matched is None else matched["run"],
                "mriqc_matched_bids_name": "" if matched is None else matched["bids_name"],
                "match_status": status,
                "reason": reason,
                "n_mriqc_t1w_candidates": n_cand,
            }
        )
    audit = pd.DataFrame(rows)
    extra_fs_missing = []
    fs_keys = set(zip(manifest["subject_id"].astype(str), manifest["session"].astype(str)))
    t1_keys = set(zip(t1["subject_id"].astype(str), t1["session"].astype(str)))
    for sub, ses in sorted(t1_keys - fs_keys):
        extra_fs_missing.append(
            {
                "subject_id": sub,
                "session": ses,
                "cohort": t1.loc[(t1.subject_id == sub) & (t1.session == ses), "cohort"].iloc[0],
                "freesurfer_selected_run": "",
                "freesurfer_selected_bids_name": "",
                "freesurfer_t1w_path": "",
                "freesurfer_selection_reason": "",
                "mriqc_matched_run": "",
                "mriqc_matched_bids_name": "",
                "match_status": "NO_FREESURFER_ENTRY",
                "reason": "T1w MRIQC exists for this cell but FreeSurfer manifest has no row",
                "n_mriqc_t1w_candidates": int(
                    ((t1.subject_id == sub) & (t1.session == ses)).sum()
                ),
            }
        )
    if extra_fs_missing:
        audit = pd.concat([audit, pd.DataFrame(extra_fs_missing)], ignore_index=True)
    return audit.sort_values(["subject_id", "session"]).reset_index(drop=True)


def audit_matching(audit: pd.DataFrame, manifest: pd.DataFrame, t1: pd.DataFrame) -> dict[str, Any]:
    counts = audit["match_status"].value_counts().to_dict()
    n_matched = int((audit["match_status"] == "MATCHED").sum())
    n_unmatched = int((audit["match_status"] != "MATCHED").sum())
    n_ambig = int((audit["match_status"] == "MULTIPLE_POSSIBLE_MATCHES").sum())
    n_mismatch = int((audit["match_status"] == "IDENTIFIER_MISMATCH").sum())
    summary = {
        "fs_rows": int(len(manifest)),
        "fs_subjects": int(manifest["subject_id"].nunique()),
        "fs_ses01": int((manifest["session"] == "ses-01").sum()),
        "fs_ses02": int((manifest["session"] == "ses-02").sum()),
        "match_status_counts": counts,
        "n_matched": n_matched,
        "n_unmatched": n_unmatched,
        "n_ambiguous": n_ambig,
        "n_identifier_mismatch": n_mismatch,
        "n_mriqc_t1w_acquisitions": int(len(t1)),
        "n_mriqc_subject_session_cells": int(t1.groupby(["subject_id", "session"]).ngroups),
        "n_cells_with_multiple_t1w": int((audit["n_mriqc_t1w_candidates"] > 1).sum()),
        "collapsed_acquisitions": int(len(t1) - n_matched) if n_matched else int(len(t1)),
    }
    if n_ambig:
        fail(
            "Ambiguous FreeSurfer-to-MRIQC matches prevent unique session-level selection:\n"
            + audit.loc[audit.match_status == "MULTIPLE_POSSIBLE_MATCHES"].to_string(index=False)
        )
    if n_mismatch:
        fail(
            "Identifier mismatches prevent unique session-level selection:\n"
            + audit.loc[audit.match_status == "IDENTIFIER_MISMATCH"].to_string(index=False)
        )
    unmatched_fs = audit.loc[audit["match_status"] != "MATCHED"]
    if not unmatched_fs.empty:
        fail(
            "Not every FreeSurfer/MRIQC session has a unique MATCHED acquisition:\n"
            + unmatched_fs.to_string(index=False)
        )
    if n_matched != int(len(manifest)):
        fail(
            f"Matched sessions ({n_matched}) != FreeSurfer manifest rows ({len(manifest)})."
        )
    return summary


def build_session_table(
    t1: pd.DataFrame, audit: pd.DataFrame, iqm_cols: list[str]
) -> pd.DataFrame:
    matched = audit.loc[audit["match_status"] == "MATCHED"].copy()
    if matched.empty:
        fail("No MATCHED FreeSurfer–MRIQC sessions.")
    t1 = t1.copy()
    t1["run_norm"] = t1["run"].map(normalize_run)
    matched["run_norm"] = matched["freesurfer_selected_run"].map(normalize_run)
    meta_cols = [
        "subject_id",
        "session",
        "run_norm",
        "freesurfer_selected_run",
        "freesurfer_selected_bids_name",
        "freesurfer_selection_reason",
        "match_status",
        "reason",
        "n_mriqc_t1w_candidates",
    ]
    merged = matched[meta_cols].merge(
        t1,
        on=["subject_id", "session", "run_norm"],
        how="left",
        validate="one_to_one",
    )
    if merged[iqm_cols].isna().any().any():
        bad = merged.loc[merged[iqm_cols].isna().any(axis=1), ["subject_id", "session", "bids_name"]]
        fail(f"Matched sessions have missing IQMs:\n{bad.to_string(index=False)}")
    n_key = merged.groupby(["subject_id", "session"]).ngroups
    if n_key != len(merged):
        fail(
            f"Session table is not unique on subject_id × session "
            f"({n_key} keys, {len(merged)} rows). Refusing to drop duplicates."
        )
    if merged.duplicated(["subject_id", "session", "run"]).any():
        fail("Duplicate subject_id × session × run in session table.")
    if merged.duplicated(["subject_id", "session", "bids_name"]).any():
        fail("Duplicate subject_id × session × bids_name in session table.")
    extra = sorted(set(merged["cohort"].astype(str)) - set(EXPECTED_COHORTS))
    if extra:
        fail(f"Unexpected cohorts in session table: {extra}")
    n_coh = merged.groupby("subject_id")["cohort"].nunique()
    if int((n_coh > 1).sum()):
        fail("A subject maps to more than one cohort in the session table.")
    LOGGER.info("Session-level table: %d unique subject × session rows", len(merged))
    return merged.sort_values(["subject_id", "session", "run"]).reset_index(drop=True)


def duplicate_checks(df: pd.DataFrame) -> dict[str, Any]:
    n = len(df)
    n_ss = int(df.groupby(["subject_id", "session"]).ngroups)
    n_ssr = int(df.groupby(["subject_id", "session", "run"]).ngroups)
    n_ssb = int(df.groupby(["subject_id", "session", "bids_name"]).ngroups)
    checks = {
        "n_rows": n,
        "n_unique_subject_session": n_ss,
        "n_unique_subject_session_run": n_ssr,
        "n_unique_subject_session_bids_name": n_ssb,
        "subject_session_unique": n_ss == n,
        "subject_session_run_unique": n_ssr == n,
        "subject_session_bids_unique": n_ssb == n,
    }
    if n_ss != n:
        fail(
            f"n_unique(subject_id, session)={n_ss} != n_rows={n}. "
            "Refusing to drop duplicates."
        )
    if n_ssr != n:
        fail("Duplicate subject_id × session × run in session table.")
    if n_ssb != n:
        fail("Duplicate subject_id × session × bids_name in session table.")
    return checks


def longitudinal_structure(df: pd.DataFrame) -> dict[str, Any]:
    ses = df.groupby("subject_id")["session"].apply(lambda s: set(s.astype(str)))

    def status(x: set[str]) -> str:
        has1, has2 = "ses-01" in x, "ses-02" in x
        if has1 and has2:
            return "both_sessions"
        if has1:
            return "ses01_only"
        if has2:
            return "ses02_only"
        return "none"

    st = ses.map(status)
    coh = df.drop_duplicates("subject_id").set_index("subject_id")["cohort"].astype(str)
    by_cohort = []
    for cohort in EXPECTED_COHORTS:
        ids = coh.loc[coh == cohort].index
        sub_st = st.reindex(ids)
        sub = df.loc[df["cohort"] == cohort]
        by_cohort.append(
            {
                "cohort": cohort,
                "n_subjects": int(sub["subject_id"].nunique()),
                "n_sessions": int(sub.groupby(["subject_id", "session"]).ngroups),
                "n_ses01_only": int((sub_st == "ses01_only").sum()),
                "n_ses02_only": int((sub_st == "ses02_only").sum()),
                "n_both": int((sub_st == "both_sessions").sum()),
            }
        )
    both_ids = set(st.loc[st == "both_sessions"].index)
    return {
        "n_subjects": int(df["subject_id"].nunique()),
        "n_sessions": int(df.groupby(["subject_id", "session"]).ngroups),
        "n_ses01": int((df["session"] == "ses-01").sum()),
        "n_ses02": int((df["session"] == "ses-02").sum()),
        "n_ses01_only": int((st == "ses01_only").sum()),
        "n_ses02_only": int((st == "ses02_only").sum()),
        "n_both": int((st == "both_sessions").sum()),
        "by_cohort": by_cohort,
        "both_ids": both_ids,
        "cell_counts": df.groupby(["cohort", "session"]).size().to_dict(),
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
    return (
        float(np.asarray(wres.statistic).squeeze()),
        float(np.asarray(wres.pvalue).squeeze()),
        len(terms),
    )


def coef_block(fit: Any, term: str) -> dict[str, float]:
    empty = {k: float("nan") for k in ("estimate", "se", "ci_low", "ci_high", "p")}
    if term not in fit.params.index:
        return empty
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


def parse_named_coefficient(text: str, cohort_label: str) -> dict[str, float]:
    empty = {k: float("nan") for k in ("estimate", "se", "ci_low", "ci_high", "p")}
    if not isinstance(text, str) or not text:
        return empty
    pattern = (
        rf"\[T\.{re.escape(cohort_label)}\].*?est=([-+0-9.eE]+)\s+"
        rf"SE=([-+0-9.eE]+)\s+CI=\[([-+0-9.eE]+),([-+0-9.eE]+)\]\s+p=([-+0-9.eE]+)"
    )
    match = re.search(pattern, text)
    if not match:
        return empty
    return {
        "estimate": float(match.group(1)),
        "se": float(match.group(2)),
        "ci_low": float(match.group(3)),
        "ci_high": float(match.group(4)),
        "p": float(match.group(5)),
    }


def named_term(terms: list[str], cohort_label: str) -> str:
    for term in terms:
        if f"[T.{cohort_label}]" in term.split(":")[0]:
            return term
    return ""


def fit_one(df: pd.DataFrame, iqm: str, smf: Any, n_long: int) -> dict[str, Any]:
    work = df[["subject_id", "cohort", "session", "age", "sex", iqm]].copy()
    work[iqm] = to_numeric_iqm(work[iqm])
    work = work.dropna(subset=[iqm, "subject_id", "cohort", "session", "age", "sex"])
    rhs = (
        f'C(cohort, Treatment("{REF_COHORT}")) * C(session, Treatment("{REF_SESSION}"))'
        " + age + C(sex)"
    )
    formula = f"{iqm} ~ {rhs}"
    warns: list[str] = []
    base = {
        "IQM": iqm,
        "N_subjects": int(work["subject_id"].nunique()),
        "N_observations": int(len(work)),
        "N_longitudinal_subjects": n_long,
        "cohort_effect": np.nan,
        "cohort_se": np.nan,
        "cohort_ci_low": np.nan,
        "cohort_ci_high": np.nan,
        "cohort_p": np.nan,
        "cohort_q": np.nan,
        "cohort_wald": np.nan,
        "session_effect": np.nan,
        "session_se": np.nan,
        "session_ci_low": np.nan,
        "session_ci_high": np.nan,
        "session_p": np.nan,
        "session_q": np.nan,
        "interaction": np.nan,
        "interaction_se": np.nan,
        "interaction_ci_low": np.nan,
        "interaction_ci_high": np.nan,
        "interaction_p": np.nan,
        "interaction_q": np.nan,
        "glaucoma_cohort_estimate": np.nan,
        "glaucoma_interaction": np.nan,
        "convergence": False,
        "warnings": "",
        "status": "failed",
        "interaction_coefficients": "",
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
        ses = coef_block(fit, groups["session"][0]) if groups["session"] else coef_block(fit, "")
        glauc_main = coef_block(fit, named_term(groups["cohort"], "Glaucoma"))
        glauc = coef_block(fit, named_term(groups["interaction"], "Glaucoma"))
        change = {"Control": ses["estimate"]}
        detail = []
        for term in groups["interaction"]:
            blk = coef_block(fit, term)
            detail.append(
                f"{term}: est={blk['estimate']:.6g} SE={blk['se']:.6g} "
                f"CI=[{blk['ci_low']:.6g},{blk['ci_high']:.6g}] p={blk['p']:.4g}"
            )
            for cohort in EXPECTED_COHORTS:
                if f"[T.{cohort}]" in term.split(":")[0]:
                    change[cohort] = ses["estimate"] + blk["estimate"]
        uniq_warns = sorted({w.split("\n")[0][:160] for w in warns if w})
        base.update(
            {
                "cohort_effect": glauc_main["estimate"],
                "cohort_se": glauc_main["se"],
                "cohort_ci_low": glauc_main["ci_low"],
                "cohort_ci_high": glauc_main["ci_high"],
                "cohort_wald": c_stat,
                "cohort_p": c_p,
                "session_effect": ses["estimate"],
                "session_se": ses["se"],
                "session_ci_low": ses["ci_low"],
                "session_ci_high": ses["ci_high"],
                "session_p": ses["p"] if math.isfinite(ses["p"]) else s_p,
                "interaction": i_stat,
                "interaction_se": glauc["se"],
                "interaction_ci_low": glauc["ci_low"],
                "interaction_ci_high": glauc["ci_high"],
                "interaction_p": i_p,
                "glaucoma_cohort_estimate": glauc_main["estimate"],
                "glaucoma_interaction": glauc["estimate"],
                "convergence": bool(getattr(fit, "converged", False)),
                "warnings": " | ".join(uniq_warns)[:1000],
                "status": "ok" if bool(getattr(fit, "converged", False)) else "not_converged",
                "interaction_coefficients": " || ".join(detail),
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
        return base


def fdr_column(series: pd.Series, multipletests: Any) -> pd.Series:
    out = pd.Series(np.nan, index=series.index, dtype=float)
    ok = series.notna() & np.isfinite(series.to_numpy(dtype=float))
    if int(ok.sum()) == 0:
        return out
    _, adj, _, _ = multipletests(series.loc[ok].to_numpy(dtype=float), alpha=FDR_ALPHA, method="fdr_bh")
    out.loc[ok] = adj
    return out


def fit_mixed_models(df: pd.DataFrame, iqms: list[str], smf: Any, mt: Any, n_long: int) -> pd.DataFrame:
    rows = []
    for i, iqm in enumerate(iqms, start=1):
        if i == 1 or i % 10 == 0:
            LOGGER.info("  session-level mixed %d/%d %s", i, len(iqms), iqm)
        rows.append(fit_one(df, iqm, smf, n_long))
    results = pd.DataFrame(rows)
    results["cohort_q"] = fdr_column(results["cohort_p"], mt)
    results["session_q"] = fdr_column(results["session_p"], mt)
    results["interaction_q"] = fdr_column(results["interaction_p"], mt)
    return results


def classify_robustness(prev_q: float, new_q: float, prev_g: float, new_g: float, new_p: float) -> str:
    """FDR-primary robustness class for a previously highlighted interaction.

    Direction is the Glaucoma × session coefficient (additional ses-02−ses-01
    change versus Control), not the Wald statistic (always ≥ 0).
    """
    prev_sig = np.isfinite(prev_q) and prev_q < FDR_ALPHA
    new_sig = np.isfinite(new_q) and new_q < FDR_ALPHA
    opposite = (
        np.isfinite(prev_g)
        and np.isfinite(new_g)
        and prev_g != 0
        and new_g != 0
        and np.sign(prev_g) != np.sign(new_g)
    )
    if opposite:
        return "REVERSED_DIRECTION"
    if prev_sig and new_sig:
        return "ROBUST"
    if prev_sig and (not new_sig) and np.isfinite(new_p) and new_p < FDR_ALPHA:
        return "ATTENUATED_BUT_PRESENT"
    if prev_sig and not new_sig:
        return "NO_LONGER_SIGNIFICANT"
    if (not prev_sig) and new_sig:
        return "ROBUST"
    return "NO_LONGER_SIGNIFICANT"


def compare_with_previous(new: pd.DataFrame, previous_path: Path) -> pd.DataFrame:
    require_file(previous_path, "previous longitudinal results")
    prev = pd.read_csv(previous_path, sep="\t")
    require_columns(prev, ["IQM", "interaction", "interaction_p", "interaction_q"], "previous results")
    prev = prev.rename(
        columns={
            "IQM": "iqm",
            "interaction": "previous_interaction_estimate",
            "interaction_p": "previous_interaction_p",
            "interaction_q": "previous_interaction_q",
        }
    )
    now = new.rename(
        columns={
            "IQM": "iqm",
            "interaction": "session_level_interaction_estimate",
            "interaction_p": "session_level_interaction_p",
            "interaction_q": "session_level_interaction_q",
            "interaction_ci_low": "session_level_glaucoma_ci_low",
            "interaction_ci_high": "session_level_glaucoma_ci_high",
            "glaucoma_interaction": "glaucoma_interaction",
        }
    )
    merged = prev[
        ["iqm", "previous_interaction_estimate", "previous_interaction_p", "previous_interaction_q", "interaction_coefficients"]
    ].merge(
        now[
            [
                "iqm",
                "session_level_interaction_estimate",
                "session_level_interaction_p",
                "session_level_interaction_q",
                "session_level_glaucoma_ci_low",
                "session_level_glaucoma_ci_high",
                "glaucoma_interaction",
                "interaction_coefficients",
            ]
        ],
        on="iqm",
        how="outer",
        suffixes=("_prev", "_new"),
    )
    merged["delta_estimate"] = (
        merged["session_level_interaction_estimate"] - merged["previous_interaction_estimate"]
    )
    merged["delta_q"] = merged["session_level_interaction_q"] - merged["previous_interaction_q"]
    merged["previous_significant_fdr"] = merged["previous_interaction_q"] < FDR_ALPHA
    merged["session_level_significant_fdr"] = merged["session_level_interaction_q"] < FDR_ALPHA
    prev_parsed = merged["interaction_coefficients_prev"].map(
        lambda s: parse_named_coefficient(s, "Glaucoma")
    )
    merged["previous_glaucoma_interaction"] = prev_parsed.map(lambda d: d["estimate"])
    merged["previous_glaucoma_ci_low"] = prev_parsed.map(lambda d: d["ci_low"])
    merged["previous_glaucoma_ci_high"] = prev_parsed.map(lambda d: d["ci_high"])
    merged["rank_session_level"] = merged["session_level_interaction_q"].rank(method="min", ascending=True)
    merged["rank_previous"] = merged["previous_interaction_q"].rank(method="min", ascending=True)
    ordered = [
        "iqm",
        "previous_interaction_estimate",
        "previous_interaction_p",
        "previous_interaction_q",
        "session_level_interaction_estimate",
        "session_level_interaction_p",
        "session_level_interaction_q",
        "delta_estimate",
        "delta_q",
        "previous_significant_fdr",
        "session_level_significant_fdr",
        "previous_glaucoma_interaction",
        "previous_glaucoma_ci_low",
        "previous_glaucoma_ci_high",
        "glaucoma_interaction",
        "session_level_glaucoma_ci_low",
        "session_level_glaucoma_ci_high",
        "rank_previous",
        "rank_session_level",
    ]
    keep = [c for c in ordered if c in merged.columns]
    extra = [c for c in merged.columns if c not in keep]
    return merged[keep + extra].sort_values("iqm").reset_index(drop=True)


def sensitivity_both_sessions(session_df: pd.DataFrame, both_ids: set[str], iqms: list[str]) -> pd.DataFrame:
    sub = session_df.loc[session_df["subject_id"].isin(both_ids)].copy()
    rows = []
    for iqm in iqms:
        wide = (
            sub.pivot_table(index=["subject_id", "cohort"], columns="session", values=iqm, aggfunc="mean")
            .reset_index()
        )
        if "ses-01" not in wide.columns or "ses-02" not in wide.columns:
            continue
        wide["delta"] = wide["ses-02"] - wide["ses-01"]
        for cohort in EXPECTED_COHORTS:
            v = wide.loc[wide["cohort"] == cohort, "delta"].dropna()
            rows.append(
                {
                    "iqm": iqm,
                    "cohort": cohort,
                    "n_longitudinal_subjects": int(len(v)),
                    "mean_delta_ses02_minus_ses01": float(v.mean()) if len(v) else np.nan,
                    "sd_delta": float(v.std(ddof=1)) if len(v) > 1 else np.nan,
                }
            )
    return pd.DataFrame(rows)


def make_plots(session_df: pd.DataFrame, results: pd.DataFrame, dest_png: Path, dest_pdf: Path) -> list[str]:
    ranked = results.sort_values("interaction_q", na_position="last")
    iqms = ranked["IQM"].head(TOP_N_PLOT).tolist()
    fig, axes = plt.subplots(2, 3, figsize=(11.2, 7.2))
    axes = np.atleast_1d(axes).ravel()
    xmap = {"ses-01": 0, "ses-02": 1}
    both = session_df.groupby("subject_id")["session"].nunique()
    both_ids = set(both.loc[both == 2].index)
    for i, iqm in enumerate(iqms):
        ax = axes[i]
        q = float(ranked.loc[ranked["IQM"] == iqm, "interaction_q"].iloc[0])
        p = float(ranked.loc[ranked["IQM"] == iqm, "interaction_p"].iloc[0])
        for cohort in EXPECTED_COHORTS:
            color = COHORT_COLORS[cohort]
            cdat = session_df.loc[session_df["cohort"] == cohort, ["subject_id", "session", iqm]].copy()
            cdat[iqm] = to_numeric_iqm(cdat[iqm])
            n_long = cdat.loc[cdat["subject_id"].isin(both_ids), "subject_id"].nunique()
            alpha_line = 0.12 if n_long < 5 else 0.25
            for sid, g in cdat.groupby("subject_id"):
                if sid not in both_ids:
                    continue
                g = g.sort_values("session")
                ax.plot(
                    [xmap[s] for s in g["session"]],
                    g[iqm],
                    color=color,
                    alpha=alpha_line,
                    lw=0.8,
                )
            ys, yerr = [], []
            ns = []
            for ses in ("ses-01", "ses-02"):
                v = cdat.loc[cdat["session"] == ses, iqm].dropna()
                ns.append(len(v))
                ys.append(float(v.mean()) if len(v) else np.nan)
                if len(v) >= 2:
                    yerr.append(1.96 * float(v.std(ddof=1)) / math.sqrt(len(v)))
                else:
                    yerr.append(np.nan)
            label = f"{cohort} (n_ses={ns[0]}/{ns[1]})"
            ax.errorbar(
                [0, 1],
                ys,
                yerr=[0 if np.isnan(e) else e for e in yerr],
                color=color,
                lw=2.0 if n_long >= 5 else 1.2,
                marker="o",
                capsize=3,
                label=label,
            )
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["ses-01", "ses-02"])
        ax.set_title(f"{iqm}\ninteraction q={q:.3g}  p={p:.3g}", fontsize=9)
        ax.tick_params(labelsize=8)
        if i == 0:
            ax.legend(frameon=False, fontsize=6, loc="best")
    for j in range(i + 1, len(axes)):
        axes[j].axis("off")
    fig.suptitle(
        "Session-level T1w IQM trajectories (one FreeSurfer-selected run per session)\n"
        "Thin lines: subjects with both sessions. Bold: cohort mean ± 95% CI "
        "(CI omitted if n<2). Data_ON/Data_TON n_longitudinal is 1: not a population CI."
    )
    fig.subplots_adjust(left=0.07, right=0.99, top=0.84, bottom=0.08, wspace=0.32, hspace=0.45)
    fig.savefig(dest_png, dpi=120)
    fig.savefig(dest_pdf)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest_png)
    return iqms


def write_report(
    path: Path,
    *,
    schema: str,
    args: argparse.Namespace,
    hashes: dict[str, str],
    stats_info: dict[str, Any],
    match_summary: dict[str, Any],
    structure: dict[str, Any],
    iqm_used: list[str],
    iqm_dropped: list[str],
    results: pd.DataFrame,
    comparison: pd.DataFrame,
    robustness: dict[str, str],
    sensitivity: pd.DataFrame,
    plotted: list[str],
    n_session_rows: int,
) -> None:
    both = comparison.loc[
        comparison["previous_significant_fdr"] & comparison["session_level_significant_fdr"], "iqm"
    ].tolist()
    only_acq = comparison.loc[
        comparison["previous_significant_fdr"] & ~comparison["session_level_significant_fdr"], "iqm"
    ].tolist()
    only_ses = comparison.loc[
        ~comparison["previous_significant_fdr"] & comparison["session_level_significant_fdr"], "iqm"
    ].tolist()

    def focus_block(iqm: str) -> list[str]:
        row = comparison.loc[comparison["iqm"] == iqm]
        if row.empty:
            return [f"  {iqm}: not found"]
        r = row.iloc[0]
        ses_row = results.loc[results["IQM"] == iqm]
        ses_ci = ""
        if not ses_row.empty:
            s = ses_row.iloc[0]
            ses_ci = f" [{s.interaction_ci_low:.6g}, {s.interaction_ci_high:.6g}]"
        return [
            f"  {iqm} robustness class: {robustness.get(iqm, 'NA')}",
            "  Rule: REVERSED_DIRECTION if Glaucoma×session coefficient signs differ;",
            "        ROBUST if both FDR q<0.05 (same direction);",
            "        ATTENUATED_BUT_PRESENT if previous q<0.05, session q≥0.05, but session p<0.05;",
            "        NO_LONGER_SIGNIFICANT if previous q<0.05 and session p≥0.05.",
            "  Wald statistic is the 3-df cohort×session test (same as the previous script).",
            "  Named estimate below is the Glaucoma additional change vs Control (ses-02 − ses-01).",
            f"    acquisition-level Wald={r.previous_interaction_estimate:.6g} "
            f"p={r.previous_interaction_p:.6g} q={r.previous_interaction_q:.6g}",
            f"    acquisition-level Glaucoma coef={r.previous_glaucoma_interaction:.6g} "
            f"95% CI=[{r.previous_glaucoma_ci_low:.6g}, {r.previous_glaucoma_ci_high:.6g}]",
            f"    session-level Wald={r.session_level_interaction_estimate:.6g} "
            f"p={r.session_level_interaction_p:.6g} q={r.session_level_interaction_q:.6g}",
            f"    session-level Glaucoma coef={r.glaucoma_interaction:.6g} 95% CI={ses_ci.strip()}",
            "    A significant cohort×session term is a differential longitudinal",
            "    trajectory of the IQM, not evidence of image-quality deterioration.",
            "    rpve_csf / summary_csf_p05 can also track tissue-composition change;",
            "    anatomical interpretation is deferred to FreeSurfer.",
        ]

    n_int = int((results["interaction_q"] < FDR_ALPHA).sum())
    n_coh = int((results["cohort_q"] < FDR_ALPHA).sum())
    n_ses = int((results["session_q"] < FDR_ALPHA).sum())
    top = results.sort_values("interaction_q").iloc[0]
    sig_int = results.loc[results["interaction_q"] < FDR_ALPHA, "IQM"].tolist()
    sig_coh = results.loc[results["cohort_q"] < FDR_ALPHA, "IQM"].tolist()
    cell_txt = ", ".join(
        f"{k[0]} {k[1]}={v}" for k, v in sorted(structure["cell_counts"].items())
    )
    lines = [
        "MRIQC session-level longitudinal validation report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "1. PURPOSE",
        "  Repeat the MixedLM IQM ~ cohort * session + age + sex + (1|subject_id)",
        "  using exactly one FreeSurfer-selected T1w per subject × session.",
        "  Validation, not discovery. No averaging of IQMs within session.",
        "",
        "2. INPUT FILES",
        f"  MRIQC: {rel_to_study(args.clean_tsv, args.study_root)} sha256={hashes['clean']}",
        f"  FreeSurfer manifest: {rel_to_study(args.freesurfer_manifest, args.study_root)} sha256={hashes['fs']}",
        f"  previous longitudinal results: {rel_to_study(args.previous_results, args.study_root)} sha256={hashes['prev']}",
        f"  software: scipy {stats_info.get('scipy')}  statsmodels {stats_info.get('statsmodels')}",
        "",
        "3. INPUT SCHEMA",
        *[f"  {ln}" if ln else "" for ln in schema.splitlines()],
        "",
        "4. FREESURFER-TO-MRIQC MATCHING",
        "  Authoritative key: subject_id + session + normalized run from the manifest.",
        "  Confirmed with bids_name == stem(t1w_path). Ambiguous matches fail the run.",
        "  Lowest MRIQC run is used only when the FreeSurfer manifest selected it.",
        "",
        "5. SESSION-LEVEL DATASET CONSTRUCTION",
        f"  Final unique subject×session rows: {n_session_rows}",
        f"  IQMs used: {len(iqm_used)}  dropped zero-variance: {iqm_dropped}",
        "  Original IQM values preserved (no outlier removal, no aggregation).",
        "",
        "6. MATCHING AUDIT",
        f"  FreeSurfer sessions: {match_summary['fs_rows']} subjects={match_summary['fs_subjects']} "
        f"ses-01={match_summary['fs_ses01']} ses-02={match_summary['fs_ses02']}",
        f"  match_status: {match_summary['match_status_counts']}",
        f"  matched={match_summary['n_matched']} unmatched={match_summary['n_unmatched']} "
        f"ambiguous={match_summary['n_ambiguous']}",
        f"  sessions with multiple MRIQC T1w candidates: {match_summary['n_cells_with_multiple_t1w']}",
        "  sessions with missing IQMs: 0 (the script fails if any matched row has NA IQMs)",
        f"  MRIQC T1w acquisitions: {match_summary['n_mriqc_t1w_acquisitions']} "
        f"in {match_summary['n_mriqc_subject_session_cells']} subject×session cells",
        f"  acquisitions not selected (collapsed away): {match_summary['collapsed_acquisitions']}",
        "",
        "7. FINAL SESSION COUNTS",
        f"  rows={structure['n_sessions']} subjects={structure['n_subjects']} "
        f"ses-01={structure['n_ses01']} ses-02={structure['n_ses02']}",
        f"  cohort × session cells: {cell_txt}",
        "  (task mentioned ~132 sessions / 83 subjects / 82 ses-01 / 50 ses-02;",
        "  those figures are compared here, not hard-coded as filters)",
        "",
        "8. LONGITUDINAL SUBJECT STRUCTURE",
        f"  ses01_only={structure['n_ses01_only']} ses02_only={structure['n_ses02_only']} "
        f"both={structure['n_both']}",
    ]
    for row in structure["by_cohort"]:
        lines.append(
            f"  {row['cohort']}: subjects={row['n_subjects']} sessions={row['n_sessions']} "
            f"ses01_only={row['n_ses01_only']} ses02_only={row['n_ses02_only']} both={row['n_both']}"
        )
    lines.append(
        "  Data_ON and Data_TON longitudinal n remains 1 each; no population-level inference."
    )
    lines.extend(
        [
            "",
            "9. DUPLICATE CHECKS",
            "  unique(subject_id, session) == n_rows: True (otherwise the script fails)",
            "  unique(subject_id, session, run): True",
            "  unique(subject_id, session, bids_name): True",
            "",
            "10. MIXEDLM SPECIFICATION",
            "  IQM ~ C(cohort, Treatment(Control)) * C(session, Treatment(ses-01))",
            "       + age + C(sex) + (1|subject_id)   [statsmodels MixedLM, REML]",
            "  Includes cohort main effect, session main effect, and cohort:session.",
            "  FDR BH separately for 56 cohort tests, 56 session tests, 56 interactions.",
            "  Cohort and interaction p-values are 3-df Wald tests (same as acquisition-level).",
            "  cohort_effect / interaction_se columns store the Glaucoma named coefficient",
            "  (estimate, SE, 95% CI) for reporting; FDR remains on the Wald p-values.",
            "",
            "11. COHORT EFFECTS",
            f"  N FDR q<0.05: {n_coh} / 56   min q={results['cohort_q'].min():.6g}",
            f"  FDR hits: {sig_coh or 'none'}",
            "  Named estimate = Glaucoma vs Control at ses-01; FDR uses the 3-df Wald.",
            "  Acquisition-level cohort FDR was 0/56. The session-level count is reported",
            "  for completeness; this script is a unit-of-analysis check, not a discovery screen.",
            "",
            "12. SESSION EFFECTS",
            f"  N FDR q<0.05: {n_ses} / 56   min q={results['session_q'].min():.6g}",
            "",
            "13. COHORT × SESSION INTERACTIONS",
            f"  N FDR q<0.05: {n_int} / 56",
            f"  min q={results['interaction_q'].min():.6g}  top IQM={top['IQM']}",
            f"  FDR hits: {sig_int or 'none'}",
            "  Interaction = differential longitudinal trajectory of the IQM by cohort.",
            "  It is not a quality-deterioration claim.",
            "",
            "14. ACQUISITION-LEVEL VS SESSION-LEVEL",
            f"  significant in BOTH: {both or 'none'}",
            f"  significant ONLY acquisition-level: {only_acq or 'none'}",
            f"  significant ONLY session-level: {only_ses or 'none'}",
            "  Session-level-only FDR hits are listed for comparison only.",
            "  They are not treated as new discoveries.",
        ]
    )
    for iqm in FOCUS_IQMS:
        rnk = comparison.loc[comparison["iqm"] == iqm]
        if not rnk.empty:
            lines.append(
                f"  {iqm}: previous rank={int(rnk.iloc[0].rank_previous)} "
                f"session-level rank={int(rnk.iloc[0].rank_session_level)}"
            )
    lines.extend(["", "15. rpve_csf ROBUSTNESS"] + focus_block("rpve_csf"))
    lines.extend(["", "16. summary_csf_p05 ROBUSTNESS"] + focus_block("summary_csf_p05"))
    lines.extend(
        [
            "",
            "17. SENSITIVITY (descriptive; both-session subjects only; not the primary model)",
        ]
    )
    for iqm in FOCUS_IQMS:
        sub = sensitivity.loc[sensitivity["iqm"] == iqm]
        lines.append(f"  {iqm} mean Δ (ses-02 − ses-01) among subjects with both sessions:")
        for rec in sub.itertuples(index=False):
            lines.append(
                f"    {rec.cohort}: n={rec.n_longitudinal_subjects} "
                f"meanΔ={rec.mean_delta_ses02_minus_ses01:.6g} sd={rec.sd_delta:.6g}"
            )
    lines.extend(
        [
            "",
            "18. INTERPRETATION LIMITATIONS",
            "  Data_ON and Data_TON still have n_longitudinal=1; do not treat those",
            "  trajectories as population estimates.",
            "  Session-level selection follows the FreeSurfer T1w_MPR run, typically the",
            "  lowest remaining MPRAGE run, not WM-nulled.",
            "  Anatomical meaning of rpve_csf / summary_csf_p05 is not tested here.",
            "  The 3-df interaction Wald can be influenced by Data_ON/Data_TON n=1;",
            "  the Glaucoma named coefficient for summary_csf_p05 was already compatible",
            "  with zero at acquisition level.",
            "",
            "19. OUTPUT FILES",
            f"  {rel_to_study(args.session_tsv, args.study_root)}",
            "  qc_reports/mriqc_iqm_session_level_matching.tsv",
            "  qc_reports/mriqc_iqm_session_level_report.txt",
            "  qc_reports/mriqc_iqm/longitudinal_session_level_results.tsv",
            "  qc_reports/mriqc_iqm/longitudinal_session_vs_acquisition.tsv",
            "  qc_reports/mriqc_iqm/mixed_longitudinal_session_level_top_interactions.png/.pdf",
            f"  plotted IQMs: {plotted}",
            "  Previous longitudinal_results.tsv was not overwritten.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    LOGGER.info("Session-level T1w MRIQC longitudinal validation")

    stats = import_stats()
    if not stats["ok"]:
        fail(
            "Missing statistical dependencies: "
            + "; ".join(stats["missing"])
            + ". On Narval: module load scipy-stack/2025a. MixedLM was not reimplemented."
        )

    hashes = {
        "clean": file_sha256(args.clean_tsv),
        "fs": file_sha256(args.freesurfer_manifest),
        "prev": file_sha256(args.previous_results),
    }
    mriqc = load_mriqc(args.clean_tsv)
    manifest = load_freesurfer_manifest(args.freesurfer_manifest)
    schema = schema_summary(mriqc, manifest)
    print("INPUT SCHEMA")
    print(schema)
    print()

    t1 = mriqc.loc[mriqc["sequence_group"].astype(str) == "T1w"].copy()
    if t1.empty:
        fail("No sequence_group == T1w rows.")
    iqm_used, iqm_dropped = identify_iqms(mriqc, args.roles_tsv)

    audit = match_session_level_t1w(t1, manifest)
    args.qc_root.mkdir(parents=True, exist_ok=True)
    match_path = args.qc_root / "mriqc_iqm_session_level_matching.tsv"
    audit.to_csv(match_path, sep="\t", index=False)
    LOGGER.info("Wrote %s", match_path)
    match_summary = audit_matching(audit, manifest, t1)

    session_df = build_session_table(t1, audit, iqm_used)
    args.session_tsv.parent.mkdir(parents=True, exist_ok=True)
    session_df.to_csv(args.session_tsv, sep="\t", index=False)
    LOGGER.info("Wrote %s", args.session_tsv)
    duplicate_checks(session_df)

    structure = longitudinal_structure(session_df)
    n_long = structure["n_both"]
    results = fit_mixed_models(session_df, iqm_used, stats["smf"], stats["multipletests"], n_long)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.out_dir / "longitudinal_session_level_results.tsv", sep="\t", index=False, float_format="%.10g")

    comparison = compare_with_previous(results, args.previous_results)
    comparison.to_csv(
        args.out_dir / "longitudinal_session_vs_acquisition.tsv",
        sep="\t",
        index=False,
        float_format="%.10g",
    )
    LOGGER.info("Wrote comparison TSV")

    robustness = {}
    for iqm in FOCUS_IQMS:
        row = comparison.loc[comparison["iqm"] == iqm]
        if row.empty:
            robustness[iqm] = "NO_LONGER_SIGNIFICANT"
            continue
        r = row.iloc[0]
        robustness[iqm] = classify_robustness(
            float(r.previous_interaction_q),
            float(r.session_level_interaction_q),
            float(r.previous_glaucoma_interaction),
            float(r.glaucoma_interaction) if pd.notna(r.glaucoma_interaction) else float("nan"),
            float(r.session_level_interaction_p),
        )

    sensitivity = sensitivity_both_sessions(session_df, structure["both_ids"], list(FOCUS_IQMS))
    plotted = make_plots(
        session_df,
        results,
        args.out_dir / "mixed_longitudinal_session_level_top_interactions.png",
        args.out_dir / "mixed_longitudinal_session_level_top_interactions.pdf",
    )

    hashes_after = {
        "clean": file_sha256(args.clean_tsv),
        "prev": file_sha256(args.previous_results),
        "fs": file_sha256(args.freesurfer_manifest),
    }
    if hashes != hashes_after:
        fail("An input file changed during the run.")

    write_report(
        args.qc_root / "mriqc_iqm_session_level_report.txt",
        schema=schema,
        args=args,
        hashes=hashes,
        stats_info=stats,
        match_summary=match_summary,
        structure=structure,
        iqm_used=iqm_used,
        iqm_dropped=iqm_dropped,
        results=results,
        comparison=comparison,
        robustness=robustness,
        sensitivity=sensitivity,
        plotted=plotted,
        n_session_rows=len(session_df),
    )

    top = results.sort_values("interaction_q").iloc[0]
    rpve = comparison.loc[comparison["iqm"] == "rpve_csf"].iloc[0]
    csf = comparison.loc[comparison["iqm"] == "summary_csf_p05"].iloc[0]
    print()
    print("=" * 60)
    print("MRIQC SESSION-LEVEL LONGITUDINAL ANALYSIS")
    print("=" * 60)
    print()
    print(f"Expected FreeSurfer sessions: {match_summary['fs_rows']}")
    print(f"Matched MRIQC sessions: {match_summary['n_matched']}")
    print(f"Unmatched sessions: {match_summary['n_unmatched']}")
    print(f"Ambiguous sessions: {match_summary['n_ambiguous']}")
    print()
    print(f"Final unique subject×session rows: {len(session_df)}")
    print(f"Subjects: {structure['n_subjects']}")
    print(f"Longitudinal subjects: {structure['n_both']}")
    print()
    print(f"T1w acquisitions collapsed to session-level: {match_summary['collapsed_acquisitions']}")
    print()
    print(f"Interaction FDR < 0.05: {int((results.interaction_q < FDR_ALPHA).sum())} / 56")
    print(f"Minimum interaction q: {results.interaction_q.min():.6g}")
    print(f"Top IQM: {top['IQM']}")
    print()
    print("rpve_csf:")
    print(f"  acquisition-level q = {rpve.previous_interaction_q:.6g}")
    print(f"  session-level q     = {rpve.session_level_interaction_q:.6g}")
    print()
    print("summary_csf_p05:")
    print(f"  acquisition-level q = {csf.previous_interaction_q:.6g}")
    print(f"  session-level q     = {csf.session_level_interaction_q:.6g}")
    print()
    print("Robust interaction findings:")
    print(f"  rpve_csf: {robustness['rpve_csf']}")
    print(f"  summary_csf_p05: {robustness['summary_csf_p05']}")
    print()
    print("=" * 60)
    print("Session-level validation completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
