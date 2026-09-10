#!/usr/bin/env python3
"""Physical-acquisition MRIQC IQM analysis: acquisition + cohort + demographics.

Fits MixedLM models on the 133-row physical-acquisition table (one
reconstruction per physical T1w scan). Does not rerun MRIQC or PCA,
does not modify previous analysis outputs, and does not use FreeSurfer.

On Narval:
  module load scipy-stack/2025a
  python code/mriqc_iqm_acquisition_physical_acq.py
"""

from __future__ import annotations

import argparse
import json
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
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import (  # noqa: E402
    EXPECTED_COHORTS,
    fail,
    read_json,
    require_columns,
    require_file,
    to_numeric_iqm,
)
from mriqc_iqm_cohort_analysis import FDR_ALPHA, fdr_bh, import_stats  # noqa: E402
from mriqc_iqm_pca import N_T1W_USABLE  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    FAMILY_COLORS,
    FAMILY_GROUP_ORDER,
    assert_unmodified,
    family_group,
    file_sha256,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.acquisition_cohort")

REF_COHORT = "Control"
REF_SESSION = "ses-01"
REF_SOFTWARE = "E11"
DOCUMENTED_MULTI_CELL = ("sub-043", "ses-02")
COLLINEAR_CORR = 0.99
MIN_MINORITY = 2
N_RETAINED_ROLES = 58

# Present in the physical table or attachable from the selected-row sidecar.
# NORM is inventoried but never used as an inferential predictor.
TABLE_ACQ_CANDIDATES = (
    "software_platform",
    "SoftwareVersions",
    "scanner",
    "ManufacturersModelName",
    "SAR",
    "TxRefAmp",
    "coil",
    "ProtocolName",
    "protocol_name",
    "RepetitionTime",
    "EchoTime",
    "InversionTime",
    "FlipAngle",
    "te_s",
    "tr_s",
    "ti_s",
    "flip_angle_deg",
    "SliceThickness",
    "spacing_x",
    "spacing_y",
    "spacing_z",
    "size_x",
    "size_y",
    "size_z",
    "voxel_size",
    "SeriesDescription",
    "ImageType",
    "NORM_status",
    "is_norm",
    "ShimSetting",
)

NON_INFERENTIAL = frozenset(
    {
        "NORM_status",
        "is_norm",
        "ImageType",
        "SeriesDescription",
        "ShimSetting",
    }
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--study-root", type=Path, default=None)
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.phys = root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    args.roles = root / "metadata" / "mriqc_iqm_column_roles.tsv"
    args.orig_loadings = qc / "pca_T1w_loadings.tsv"
    args.release_root = root.parent / "release_dataset"
    args.bids_root = root.parent / "bids"
    args.out_dir = qc
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    LOGGER.addHandler(h)


def extra_protected(study_root: Path) -> dict[Path, str]:
    extra = [
        study_root / "qc_reports" / "mriqc_iqm" / "cohort_results.tsv",
        study_root / "qc_reports" / "mriqc_iqm" / "cohort_results_mixed.tsv",
        study_root / "qc_reports" / "mriqc_iqm" / "cohort_results_adjusted.tsv",
        study_root / "qc_reports" / "mriqc_iqm" / "cohort_results_raw.tsv",
    ]
    out: dict[Path, str] = {}
    for path in extra:
        if path.is_file():
            out[path] = file_sha256(path)
    return out


def sidecar_for(input_file: str, release_root: Path, bids_root: Path) -> Path:
    rel = str(input_file).replace(".nii.gz", ".json").replace(".nii", ".json")
    for root in (release_root, bids_root):
        path = root / rel
        if path.is_file():
            return path
    fail(f"BIDS sidecar not found for selected reconstruction {input_file}")
    raise AssertionError("unreachable")


def recode_software(series: pd.Series) -> pd.Series:
    out = series.astype(str)
    mapped = pd.Series(np.nan, index=series.index, dtype=object)
    mapped.loc[out.str.contains("XA30", na=False)] = "XA30"
    mapped.loc[out.str.contains(r"\bE11\b", na=False)] = "E11"
    return mapped


def attach_sidecar_fields(df: pd.DataFrame, release_root: Path, bids_root: Path) -> pd.DataFrame:
    """Attach SoftwareVersions/TxRefAmp for the 133 selected rows only."""
    require_columns(df, ["input_file", "bids_name"], "physical-acquisition table")
    versions: list[Any] = []
    tx: list[Any] = []
    model: list[Any] = []
    for rec in df.itertuples(index=False):
        payload = read_json(sidecar_for(str(rec.input_file), release_root, bids_root))
        versions.append(payload.get("SoftwareVersions"))
        versions_tx = payload.get("TxRefAmp")
        tx.append(np.nan if versions_tx in (None, "") else versions_tx)
        model.append(payload.get("ManufacturersModelName"))
    out = df.copy()
    out["SoftwareVersions"] = versions
    out["TxRefAmp"] = pd.to_numeric(tx, errors="coerce")
    out["ManufacturersModelName"] = model
    out["software_platform"] = recode_software(out["SoftwareVersions"])
    out["sar"] = pd.to_numeric(out["SAR"], errors="coerce")
    out["tx_ref_amp"] = out["TxRefAmp"]
    return out


def original_iqms(path: Path) -> list[str]:
    require_file(path, "original PCA loadings")
    df = pd.read_csv(path, sep="\t")
    if "iqm" not in df.columns:
        fail(f"{path} missing iqm column")
    iqms = df["iqm"].astype(str).tolist()
    if len(iqms) != N_T1W_USABLE:
        fail(f"Original PCA used {len(iqms)} IQMs, expected {N_T1W_USABLE}.")
    return iqms


def ordered_iqms(iqms: list[str]) -> list[str]:
    rank = {fam: i for i, fam in enumerate(FAMILY_GROUP_ORDER)}
    return sorted(iqms, key=lambda x: (rank.get(family_group(x), 99), x))


def validate_dataset(df: pd.DataFrame, iqms: list[str]) -> dict[str, Any]:
    notes: list[str] = []
    n = len(df)
    if n != EXPECTED_PHYSICAL_N:
        fail(
            f"Physical-acquisition table has {n} rows, expected {EXPECTED_PHYSICAL_N}. "
            "Rows were not dropped."
        )
    if df["physical_acquisition_id"].nunique(dropna=False) != n:
        fail("physical_acquisition_id is not unique.")
    extra = sorted(set(df["cohort"].astype(str)) - set(EXPECTED_COHORTS))
    if extra:
        fail(f"Unexpected cohort labels: {extra}")
    missing_c = [c for c in EXPECTED_COHORTS if c not in set(df["cohort"].astype(str))]
    if missing_c:
        fail(f"Cohorts absent: {missing_c}")
    for col in ("age", "sex", "session", "subject_id"):
        nmiss = int(df[col].isna().sum())
        if nmiss:
            fail(f"{col} has {nmiss} missing values. No silent dropping.")
    sex_levels = sorted(df["sex"].astype(str).unique())
    if set(sex_levels) - {"F", "M"}:
        fail(f"Unexpected sex values: {sex_levels}")
    ses_levels = sorted(df["session"].astype(str).unique())
    if set(ses_levels) - {"ses-01", "ses-02"}:
        fail(f"Unexpected session values: {ses_levels}")
    missing_iqm = [c for c in iqms if c not in df.columns]
    if missing_iqm:
        fail(f"Missing IQMs: {missing_iqm}")
    iqm_missing = {c: int(to_numeric_iqm(df[c]).isna().sum()) for c in iqms}
    if any(iqm_missing.values()):
        fail(f"Missing IQM values: { {k: v for k, v in iqm_missing.items() if v} }")
    ss = df.groupby(["subject_id", "session"], observed=False).size()
    multi = ss[ss > 1]
    unexpected = [k for k in multi.index.tolist() if k != DOCUMENTED_MULTI_CELL]
    if unexpected:
        fail(f"Unexpected subject/session cells with >1 physical acquisition: {unexpected}")
    if DOCUMENTED_MULTI_CELL not in multi.index:
        notes.append("Documented sub-043 ses-02 dual physical acquisition was not found.")
    elif int(multi.loc[DOCUMENTED_MULTI_CELL]) != 2:
        fail(
            f"{DOCUMENTED_MULTI_CELL} has {int(multi.loc[DOCUMENTED_MULTI_CELL])} "
            "physical acquisitions, expected 2."
        )
    n_subj_cohort = df.groupby("subject_id")["cohort"].nunique()
    if int((n_subj_cohort > 1).sum()):
        fail("At least one subject maps to more than one cohort.")
    return {
        "n_rows": n,
        "n_subjects": int(df["subject_id"].nunique()),
        "n_sessions": int(df.groupby(["subject_id", "session"], observed=False).ngroups),
        "n_unique_physical_ids": int(df["physical_acquisition_id"].nunique()),
        "documented_multi_cell": f"{DOCUMENTED_MULTI_CELL[0]} {DOCUMENTED_MULTI_CELL[1]}",
        "n_multi_cells": int(len(multi)),
        "cohorts": {c: int((df["cohort"] == c).sum()) for c in EXPECTED_COHORTS},
        "subjects_per_cohort": {
            c: int(df.loc[df["cohort"] == c, "subject_id"].nunique()) for c in EXPECTED_COHORTS
        },
        "age_available": True,
        "sex_available": True,
        "session_available": True,
        "n_iqms": len(iqms),
        "notes": notes,
    }


def effective_nunique(series: pd.Series) -> int:
    s = series.dropna()
    if s.empty:
        return 0
    num = pd.to_numeric(s, errors="coerce")
    if int(num.notna().sum()) == len(s):
        vals = np.asarray(num, dtype=float)
        if np.all(np.isfinite(vals)):
            uniq: list[float] = []
            for v in np.sort(vals):
                if not uniq or not math.isclose(v, uniq[-1], rel_tol=1e-6, abs_tol=1e-8):
                    uniq.append(float(v))
            return len(uniq)
    return int(s.astype(str).nunique())


def identical_partition(a: pd.Series, b: pd.Series) -> bool:
    work = pd.DataFrame({"a": a.astype(str), "b": b.astype(str)}).dropna()
    work = work.loc[~work["a"].isin(["nan", "None"]) & ~work["b"].isin(["nan", "None"])]
    if work.empty or effective_nunique(a) > 12 or effective_nunique(b) > 12:
        return False
    return int(work.groupby("a")["b"].nunique().max()) == 1 and int(
        work.groupby("b")["a"].nunique().max()
    ) == 1


def inventory_acquisition(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name in TABLE_ACQ_CANDIDATES:
        if name not in df.columns:
            rows.append(
                {
                    "parameter": name,
                    "present": False,
                    "kind": "",
                    "n_unique": 0,
                    "n_missing": len(df),
                    "missing_frac": 1.0,
                    "value_summary": "absent_from_table",
                    "inferential_status": "absent",
                }
            )
            continue
        series = df[name]
        n_missing = int(pd.isna(series).sum())
        n_unique = effective_nunique(series)
        numeric = pd.to_numeric(series, errors="coerce")
        is_num = int(numeric.notna().sum()) == int(series.notna().sum()) and n_unique > 0
        if is_num:
            kind = "numeric"
            nn = numeric.dropna()
            value_summary = f"min={float(nn.min()):.8g} max={float(nn.max()):.8g}"
        else:
            kind = "categorical"
            counts = series.dropna().astype(str).value_counts().head(8)
            value_summary = ", ".join(f"{k}={int(v)}" for k, v in counts.items())
        if name in NON_INFERENTIAL:
            status = "inventoried_not_modeled_NORM_or_identifier"
        elif n_unique <= 1:
            status = "constant"
        elif n_missing == len(df):
            status = "all_missing"
        else:
            status = "candidate"
        rows.append(
            {
                "parameter": name,
                "present": True,
                "kind": kind,
                "n_unique": n_unique,
                "n_missing": n_missing,
                "missing_frac": n_missing / len(df),
                "value_summary": value_summary,
                "inferential_status": status,
            }
        )
    return pd.DataFrame(rows)


def choose_inferential_variables(df: pd.DataFrame, inventory: pd.DataFrame) -> list[dict[str, Any]]:
    specs = [
        {
            "parameter": "software_platform",
            "model_col": "software_platform",
            "kind": "categorical",
            "reference": REF_SOFTWARE,
            "term_label": "software_platform[T.XA30]",
            "aliases": ["SoftwareVersions", "scanner", "ManufacturersModelName"],
            "exploratory": True,
            "exploratory_reason": "XA30 n=6; do not interpret as a causal scanner effect",
        },
        {
            "parameter": "SAR",
            "model_col": "sar",
            "kind": "numeric",
            "reference": "",
            "term_label": "SAR",
            "aliases": [],
            "exploratory": False,
            "exploratory_reason": "",
        },
        {
            "parameter": "TxRefAmp",
            "model_col": "tx_ref_amp",
            "kind": "numeric",
            "reference": "",
            "term_label": "TxRefAmp",
            "aliases": [],
            "exploratory": False,
            "exploratory_reason": "",
        },
    ]
    kept: list[dict[str, Any]] = []
    for spec in specs:
        col = spec["model_col"]
        series = df[col]
        n_unique = effective_nunique(series)
        n_missing = int(series.isna().sum())
        n_ok = int(series.notna().sum())
        if spec["kind"] == "categorical":
            minority = int(series.dropna().astype(str).value_counts().min()) if n_ok else 0
        else:
            minority = n_ok
        reason = ""
        usable = True
        if n_unique <= 1:
            usable = False
            reason = "constant"
        elif spec["kind"] == "categorical" and minority < MIN_MINORITY:
            usable = False
            reason = f"minority_n={minority}"
        elif n_ok < 20:
            usable = False
            reason = f"too_few_complete_cases n={n_ok}"
        spec.update(
            {
                "n_unique": n_unique,
                "n_missing": n_missing,
                "n_complete": n_ok,
                "minority_n": minority,
                "usable": usable,
                "skip_reason": reason,
            }
        )
        redundant = None
        if usable:
            for prev in kept:
                a = df[spec["model_col"]]
                b = df[prev["model_col"]]
                if spec["kind"] == "numeric" and prev["kind"] == "numeric":
                    aa = pd.to_numeric(a, errors="coerce")
                    bb = pd.to_numeric(b, errors="coerce")
                    mask = aa.notna() & bb.notna()
                    if int(mask.sum()) >= 8:
                        corr = float(np.corrcoef(aa.loc[mask], bb.loc[mask])[0, 1])
                        if math.isfinite(corr) and abs(corr) >= COLLINEAR_CORR:
                            redundant = prev["parameter"]
                if identical_partition(a, b):
                    redundant = prev["parameter"]
                if redundant:
                    break
        if redundant:
            spec["usable"] = False
            spec["skip_reason"] = f"collinear_with:{redundant}"
        if spec["usable"]:
            kept.append(spec)
        LOGGER.info(
            "Acquisition candidate %s usable=%s n_unique=%s missing=%s reason=%s",
            spec["parameter"],
            spec["usable"],
            n_unique,
            n_missing,
            spec["skip_reason"] or spec["exploratory_reason"] or "ok",
        )
    # Record collinearity of unused aliases in the inventory notes via stdout.
    if "software_platform" in df.columns and "scanner" in df.columns:
        if identical_partition(df["software_platform"], df["scanner"]):
            LOGGER.info(
                "software_platform is identical to scanner in this table; scanner is not modeled separately."
            )
    if "software_platform" in df.columns and "NORM_status" in df.columns:
        if identical_partition(df["software_platform"], df["NORM_status"]):
            LOGGER.info(
                "software_platform is aliased with NORM_status in this selected table "
                "(XA30 rows are the 6 non-NORM reconstructions). NORM is not modeled."
            )
    _ = inventory
    return kept


def demo_rhs() -> str:
    return f'C(session, Treatment("{REF_SESSION}")) + age + C(sex)'


def cohort_rhs() -> str:
    return f'C(cohort, Treatment("{REF_COHORT}")) + {demo_rhs()}'


def acquisition_term(spec: dict[str, Any]) -> str:
    col = spec["model_col"]
    if spec["kind"] == "numeric":
        return col
    ref = spec.get("reference") or REF_SOFTWARE
    return f'C({col}, Treatment("{ref}"))'


def empty_row(**kwargs: Any) -> dict[str, Any]:
    row = {
        "IQM": "",
        "IQM_family": "",
        "model": "",
        "predictor": "",
        "term": "",
        "coefficient": np.nan,
        "SE": np.nan,
        "statistic": np.nan,
        "p_value": np.nan,
        "q_value": np.nan,
        "CI_low": np.nan,
        "CI_high": np.nan,
        "std_coefficient": np.nan,
        "n_observations": np.nan,
        "n_subjects": np.nan,
        "converged": False,
        "status": "",
        "exclusion_reason": "",
        "fdr_family": "",
        "exploratory": False,
        "acquisition_variable": "",
    }
    row.update(kwargs)
    return row


def fit_mixed(
    df: pd.DataFrame,
    iqm: str,
    rhs: str,
    needed: list[str],
    stats: dict[str, Any],
) -> tuple[Any | None, pd.DataFrame, dict[str, Any]]:
    smf = stats["smf"]
    cols = list(dict.fromkeys(["subject_id", iqm, *needed]))
    work = df[cols].copy()
    work[iqm] = to_numeric_iqm(work[iqm])
    n_before = int(len(work))
    miss = work[cols].isna().any(axis=1)
    n_dropped = int(miss.sum())
    dropped_detail = ""
    if n_dropped:
        miss_cols = [c for c in cols if int(work.loc[miss, c].isna().sum())]
        dropped_detail = (
            f"excluded {n_dropped}/{n_before} rows with missing {miss_cols}; "
            "no other rows were removed"
        )
        LOGGER.info("%s %s", iqm, dropped_detail)
    work = work.loc[~miss].copy()
    meta = {
        "n_observations": int(len(work)),
        "n_subjects": int(work["subject_id"].nunique()),
        "exclusion_reason": dropped_detail,
        "n_before": n_before,
        "n_dropped": n_dropped,
        "iqm_sd": float(work[iqm].std(ddof=1)) if len(work) > 1 else float("nan"),
    }
    if len(work) < 8 or work["subject_id"].nunique() < 3:
        return None, work, {**meta, "status": "too_few_observations"}
    formula = f"{iqm} ~ {rhs}"
    md = smf.mixedlm(formula, data=work, groups=work["subject_id"])
    fit = None
    last_exc: Exception | None = None
    attempts = [
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
            LOGGER.debug("MixedLM %s optimizer %s failed: %s", iqm, kwargs, exc)
    if fit is None:
        return None, work, {**meta, "status": f"failed: {last_exc}"}
    meta["status"] = "ok" if bool(getattr(fit, "converged", False)) else "not_converged"
    meta["converged"] = bool(getattr(fit, "converged", False))
    return fit, work, meta


def std_from_coef(coef: float, se: float, ci_low: float, ci_high: float, scale: float) -> dict[str, float]:
    if not math.isfinite(scale) or scale == 0:
        return {"std": float("nan"), "std_se": float("nan"), "std_lo": float("nan"), "std_hi": float("nan")}
    return {
        "std": coef / scale,
        "std_se": se / scale,
        "std_lo": ci_low / scale,
        "std_hi": ci_high / scale,
    }


def extract_term(
    fit: Any,
    work: pd.DataFrame,
    meta: dict[str, Any],
    iqm: str,
    model: str,
    predictor: str,
    term_substr: str,
    fdr_family: str,
    acquisition_variable: str,
    exploratory: bool,
    numeric_predictor_col: str | None = None,
) -> dict[str, Any]:
    names = [n for n in fit.params.index if term_substr in str(n) and "Group Var" not in str(n)]
    if not names:
        return empty_row(
            IQM=iqm,
            IQM_family=family_group(iqm),
            model=model,
            predictor=predictor,
            n_observations=meta.get("n_observations"),
            n_subjects=meta.get("n_subjects"),
            converged=bool(meta.get("converged", False)),
            status=str(meta.get("status", "term_missing")),
            exclusion_reason=meta.get("exclusion_reason", ""),
            fdr_family=fdr_family,
            exploratory=exploratory,
            acquisition_variable=acquisition_variable,
        )
    name = names[0]
    ci = fit.conf_int()
    coef = float(fit.params[name])
    se = float(fit.bse[name])
    p = float(fit.pvalues[name]) if np.isfinite(fit.pvalues[name]) else float("nan")
    lo = float(ci.loc[name, 0])
    hi = float(ci.loc[name, 1])
    z = coef / se if math.isfinite(se) and se != 0 else float("nan")
    scale = float(meta.get("iqm_sd", np.nan))
    if numeric_predictor_col and numeric_predictor_col in work.columns:
        pred_sd = float(pd.to_numeric(work[numeric_predictor_col], errors="coerce").std(ddof=1))
        if math.isfinite(pred_sd) and math.isfinite(scale) and scale != 0:
            std = coef * pred_sd / scale
            std_se = se * pred_sd / scale
            std_lo = lo * pred_sd / scale
            std_hi = hi * pred_sd / scale
        else:
            std = std_se = std_lo = std_hi = float("nan")
    else:
        packed = std_from_coef(coef, se, lo, hi, scale)
        std, std_se, std_lo, std_hi = packed["std"], packed["std_se"], packed["std_lo"], packed["std_hi"]
    return empty_row(
        IQM=iqm,
        IQM_family=family_group(iqm),
        model=model,
        predictor=predictor,
        term=str(name),
        coefficient=coef,
        SE=se,
        statistic=z,
        p_value=p,
        CI_low=lo,
        CI_high=hi,
        std_coefficient=std,
        n_observations=meta.get("n_observations"),
        n_subjects=meta.get("n_subjects"),
        converged=bool(meta.get("converged", False)),
        status=str(meta.get("status", "")),
        exclusion_reason=meta.get("exclusion_reason", ""),
        fdr_family=fdr_family,
        exploratory=exploratory,
        acquisition_variable=acquisition_variable,
        std_SE=std_se,
        std_CI_low=std_lo,
        std_CI_high=std_hi,
    )


def apply_fdr_by_family(rows: list[dict[str, Any]], multipletests: Any) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["q_value"] = np.nan
    for fam, idx in df.groupby("fdr_family", dropna=False).groups.items():
        if not fam:
            continue
        pvals = df.loc[idx, "p_value"].tolist()
        q = fdr_bh(pvals, multipletests)
        df.loc[idx, "q_value"] = q
    return df


def classify_change(q_a: float, q_c: float, coef_a: float, coef_c: float) -> tuple[str, str]:
    a_sig = bool(np.isfinite(q_a) and q_a < FDR_ALPHA)
    c_sig = bool(np.isfinite(q_c) and q_c < FDR_ALPHA)
    if a_sig and c_sig:
        sig = "sig_to_sig"
        if math.isfinite(coef_a) and abs(coef_a) > 0 and abs(coef_c) < 0.8 * abs(coef_a):
            cls = "cohort association attenuated"
        else:
            cls = "cohort association retained"
    elif a_sig and not c_sig:
        sig = "sig_to_ns"
        cls = "cohort association lost"
    elif (not a_sig) and c_sig:
        sig = "ns_to_sig"
        cls = "cohort association newly apparent"
    else:
        sig = "ns_to_ns"
        cls = "neither"
    return cls, sig


def heatmap_matrix(
    results: pd.DataFrame,
    iqms: list[str],
    columns: list[tuple[str, str, str]],
    value: str = "std_coefficient",
) -> tuple[np.ndarray, np.ndarray]:
    """columns: list of (model, predictor, title)."""
    mat = np.full((len(iqms), len(columns)), np.nan)
    qmat = np.full((len(iqms), len(columns)), np.nan)
    lookup = {}
    for rec in results.itertuples(index=False):
        lookup[(rec.IQM, rec.model, rec.predictor)] = rec
    for i, iqm in enumerate(iqms):
        for j, (model, pred, _title) in enumerate(columns):
            rec = lookup.get((iqm, model, pred))
            if rec is None:
                continue
            mat[i, j] = float(getattr(rec, value))
            qmat[i, j] = float(rec.q_value)
    return mat, qmat


def save_heatmap(
    mat: np.ndarray,
    qmat: np.ndarray,
    row_labels: list[str],
    col_labels: list[str],
    title: str,
    cbar_label: str,
    dest: Path,
    families: list[str] | None = None,
) -> None:
    n_row, n_col = mat.shape
    fig_h = max(10.0, 0.28 * n_row + 2.2)
    fig_w = max(7.5, 1.6 * n_col + 4.5)
    finite = mat[np.isfinite(mat)]
    vmax = float(np.nanmax(np.abs(finite))) if finite.size else 1.0
    if vmax == 0:
        vmax = 1.0
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    im = ax.imshow(
        np.ma.masked_invalid(mat),
        cmap="RdBu_r",
        norm=TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax),
        aspect="auto",
    )
    ax.set_xticks(range(n_col), col_labels, rotation=25, ha="right")
    ax.set_yticks(range(n_row), row_labels, fontsize=7)
    ax.set_title(title)
    for i in range(n_row):
        for j in range(n_col):
            q = qmat[i, j]
            if np.isfinite(q) and q < FDR_ALPHA:
                ax.text(j, i, "*", ha="center", va="center", fontsize=8, color="black")
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label=cbar_label)
    if families:
        seen = set()
        handles = []
        for fam in FAMILY_GROUP_ORDER:
            if fam in families and fam not in seen:
                seen.add(fam)
                handles.append(
                    Line2D(
                        [0],
                        [0],
                        marker="s",
                        color="none",
                        markerfacecolor=FAMILY_COLORS.get(fam, "#BAB0AC"),
                        markersize=8,
                        label=fam,
                    )
                )
        # Colour y tick labels by family.
        for tick, fam in zip(ax.get_yticklabels(), families):
            tick.set_color(FAMILY_COLORS.get(fam, "#444444"))
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.22, 1.0), fontsize=8, frameon=False)
        fig.subplots_adjust(left=0.28, right=0.78, top=0.93, bottom=0.08)
    else:
        fig.tight_layout()
    fig.savefig(dest, dpi=160)
    plt.close(fig)


def scatter_a_vs_c(
    comparison: pd.DataFrame,
    dest: Path,
) -> None:
    cohorts = ["Glaucoma", "Data_ON", "Data_TON"]
    fig, axes = plt.subplots(1, 3, figsize=(12.8, 4.4), sharex=False, sharey=False)
    for ax, cohort in zip(axes, cohorts):
        sub = comparison.loc[comparison["cohort"] == cohort]
        xcol = "std_coefficient_model_A" if "std_coefficient_model_A" in sub.columns else "coefficient_model_A"
        ycol = "std_coefficient_model_C" if "std_coefficient_model_C" in sub.columns else "coefficient_model_C"
        x = sub[xcol].to_numpy(dtype=float)
        y = sub[ycol].to_numpy(dtype=float)
        fams = sub["IQM_family"].tolist()
        colors = [FAMILY_COLORS.get(f, "#BAB0AC") for f in fams]
        ax.scatter(x, y, c=colors, s=28, alpha=0.9, edgecolors="none")
        finite = np.concatenate([x[np.isfinite(x)], y[np.isfinite(y)]]) if len(sub) else np.array([0.0])
        lim = float(np.nanmax(np.abs(finite))) if finite.size else 1.0
        lim = lim * 1.15 if lim else 1.0
        ax.plot([-lim, lim], [-lim, lim], color="#888888", lw=0.8, ls="--")
        ax.axhline(0, color="#bbbbbb", lw=0.6)
        ax.axvline(0, color="#bbbbbb", lw=0.6)
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_title(f"Control vs {cohort}")
        ax.set_xlabel("Model A standardized coefficient")
        ax.set_ylabel("Model C standardized coefficient")
        ax.set_aspect("equal", adjustable="box")
    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=FAMILY_COLORS[f],
            markersize=7,
            label=f,
        )
        for f in FAMILY_GROUP_ORDER
        if f in set(comparison["IQM_family"])
    ]
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=8, frameon=False)
    fig.suptitle(
        "Cohort coefficients before vs after software-platform adjustment\n"
        "(Model A vs Model C; identity line; not a quality grade)",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0.08, 1, 0.90))
    fig.savefig(dest, dpi=160)
    plt.close(fig)


def sample_size_block(df: pd.DataFrame) -> dict[str, Any]:
    n_per_subj = df.groupby("subject_id").size()
    return {
        "n_physical_acquisitions": int(len(df)),
        "n_subjects": int(df["subject_id"].nunique()),
        "n_repeated_subjects": int((n_per_subj > 1).sum()),
        "acquisitions_per_cohort": {c: int((df["cohort"] == c).sum()) for c in EXPECTED_COHORTS},
        "subjects_per_cohort": {
            c: int(df.loc[df["cohort"] == c, "subject_id"].nunique()) for c in EXPECTED_COHORTS
        },
        "n_E11": int((df["software_platform"] == "E11").sum()),
        "n_XA30": int((df["software_platform"] == "XA30").sum()),
        "SAR_n_missing": int(df["sar"].isna().sum()),
        "TxRefAmp_n_missing": int(df["tx_ref_amp"].isna().sum()),
        "session_counts": df["session"].astype(str).value_counts().to_dict(),
        "sex_counts": df["sex"].astype(str).value_counts().to_dict(),
    }


def fmt_p(x: float) -> str:
    if not np.isfinite(x):
        return "NA"
    if x == 0:
        return "0"
    if x < 1e-4:
        return f"{x:.3e}"
    return f"{x:.4g}"


def write_text(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def top_iqm_table(acq_rows: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for pred, sub in acq_rows.groupby("predictor", sort=False):
        ranked = sub.copy()
        ranked["_q"] = ranked["q_value"].fillna(1.0)
        ranked["_absstd"] = ranked["std_coefficient"].abs()
        ranked["_abscoef"] = ranked["coefficient"].abs()
        ranked = ranked.sort_values(["_q", "_absstd", "_abscoef"], ascending=[True, False, False])
        ranked["rank_within_predictor"] = np.arange(1, len(ranked) + 1)
        sig = ranked.loc[ranked["q_value"] < FDR_ALPHA]
        keep = sig if len(sig) else ranked.head(5)
        if len(sig) and len(sig) < 5:
            extra = ranked.loc[~ranked.index.isin(sig.index)].head(5 - len(sig))
            keep = pd.concat([keep, extra], axis=0)
        parts.append(keep)
    out = pd.concat(parts, ignore_index=True) if parts else acq_rows.iloc[0:0].copy()
    cols = [
        "predictor",
        "IQM",
        "IQM_family",
        "model",
        "coefficient",
        "std_coefficient",
        "SE",
        "statistic",
        "p_value",
        "q_value",
        "CI_low",
        "CI_high",
        "n_observations",
        "n_subjects",
        "converged",
        "exploratory",
        "rank_within_predictor",
        "exclusion_reason",
    ]
    return out[[c for c in cols if c in out.columns]]


def taxonomy(iqms: list[str], acq_b: pd.DataFrame, coh_a: pd.DataFrame, coh_c: pd.DataFrame) -> dict[str, list[str]]:
    acq_sig = set(acq_b.loc[acq_b["q_value"] < FDR_ALPHA, "IQM"].astype(str))
    coh_a_sig = set(coh_a.loc[coh_a["q_value"] < FDR_ALPHA, "IQM"].astype(str))
    coh_c_sig = set(coh_c.loc[coh_c["q_value"] < FDR_ALPHA, "IQM"].astype(str))
    neither = [i for i in iqms if i not in acq_sig and i not in coh_a_sig and i not in coh_c_sig]
    return {
        "acquisition_sensitive": ordered_iqms(sorted(acq_sig)),
        "cohort_associated_model_A": ordered_iqms(sorted(coh_a_sig)),
        "acquisition_adjusted_cohort_associated": ordered_iqms(sorted(coh_c_sig)),
        "neither": neither,
    }


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    print("Physical-acquisition MRIQC acquisition/cohort analysis")
    print("Input: study/metadata/mriqc_iqm_physical_acquisition.tsv")
    print("Unit of observation: physical acquisition")
    print("IQMs: 56")
    print("Anatomy: NOT INCLUDED")
    print("MRIQC rerun: NO")
    before = snapshot_protected(args.study_root)
    before.update(extra_protected(args.study_root))

    stats = import_stats()
    if not stats["ok"]:
        fail("scipy+statsmodels required: " + "; ".join(stats["missing"]))

    require_file(args.phys, "physical-acquisition table")
    phys = pd.read_csv(args.phys, sep="\t")
    require_columns(
        phys,
        [
            "physical_acquisition_id",
            "subject_id",
            "session",
            "cohort",
            "age",
            "sex",
            "input_file",
            "bids_name",
            "SAR",
        ],
        "physical-acquisition table",
    )
    LOGGER.info("Source table: %s  sha256=%s", args.phys, file_sha256(args.phys))

    iqms = original_iqms(args.orig_loadings)
    iqms = ordered_iqms(iqms)
    roles = pd.read_csv(args.roles, sep="\t")
    retained = roles.loc[roles["retained_for_statistics"].astype(bool), "column"].astype(str).tolist()
    if len(retained) != N_RETAINED_ROLES:
        fail(f"Expected {N_RETAINED_ROLES} retained IQM columns in roles TSV, found {len(retained)}.")
    dropped_zero = [c for c in retained if c not in iqms]
    LOGGER.info("Zero-variance IQMs excluded from the 56-model set: %s", dropped_zero)

    df = attach_sidecar_fields(phys, args.release_root, args.bids_root)
    df["cohort"] = pd.Categorical(df["cohort"].astype(str), categories=list(EXPECTED_COHORTS), ordered=False)
    df["session"] = pd.Categorical(df["session"].astype(str), categories=["ses-01", "ses-02"], ordered=False)
    df["sex"] = df["sex"].astype(str)
    df["age"] = pd.to_numeric(df["age"], errors="coerce")
    df["software_platform"] = pd.Categorical(
        df["software_platform"].astype(str), categories=["E11", "XA30"], ordered=False
    )

    validation = validate_dataset(df, iqms)
    LOGGER.info("Validation: %s", json.dumps(validation, default=str))
    inventory = inventory_acquisition(df)
    specs = choose_inferential_variables(df, inventory)
    sizes = sample_size_block(df)

    print()
    print("=== validation summary ===")
    print(f"n physical acquisitions: {validation['n_rows']}")
    print(f"unique physical_acquisition_id: {validation['n_unique_physical_ids']}")
    print(f"subjects: {validation['n_subjects']}  subject×session cells: {validation['n_sessions']}")
    print(f"documented extra cell: {validation['documented_multi_cell']}")
    print(f"cohorts (acquisitions): {validation['cohorts']}")
    print(f"cohorts (subjects): {validation['subjects_per_cohort']}")
    print("age/sex/session: complete")
    print(f"IQMs modeled: {len(iqms)}  (roles retained {len(retained)}; dropped {dropped_zero})")
    print(f"software_platform E11={sizes['n_E11']} XA30={sizes['n_XA30']}")
    print(f"SAR missing={sizes['SAR_n_missing']}  TxRefAmp missing={sizes['TxRefAmp_n_missing']}")
    print("NORM is not included as an inferential predictor.")
    print()
    print("Model A: IQM ~ cohort + age + sex + session + (1|subject_id)")
    print("Model B: IQM ~ acquisition_variable + age + sex + session + (1|subject_id)")
    print("Model C: IQM ~ cohort + acquisition_variable + age + sex + session + (1|subject_id)")
    print("FDR: Benjamini-Hochberg within each family of 56 IQM tests (alpha=0.05).")
    print("Acquisition variables modeled separately (not entered jointly).")

    rows: list[dict[str, Any]] = []
    LOGGER.info("Fitting Model A (cohort/demographic baseline)")
    for iqm in iqms:
        fit, work, meta = fit_mixed(df, iqm, cohort_rhs(), ["cohort", "age", "sex", "session"], stats)
        if fit is None:
            for pred, substr in (
                ("Glaucoma", "T.Glaucoma"),
                ("Data_ON", "T.Data_ON"),
                ("Data_TON", "T.Data_TON"),
            ):
                rows.append(
                    empty_row(
                        IQM=iqm,
                        IQM_family=family_group(iqm),
                        model="A_cohort_demographic",
                        predictor=pred,
                        n_observations=meta.get("n_observations"),
                        n_subjects=meta.get("n_subjects"),
                        status=str(meta.get("status")),
                        exclusion_reason=meta.get("exclusion_reason", ""),
                        fdr_family=f"model_A_{pred}",
                        acquisition_variable="",
                    )
                )
            continue
        for pred, substr in (
            ("Glaucoma", "T.Glaucoma"),
            ("Data_ON", "T.Data_ON"),
            ("Data_TON", "T.Data_TON"),
        ):
            rows.append(
                extract_term(
                    fit,
                    work,
                    meta,
                    iqm,
                    "A_cohort_demographic",
                    pred,
                    substr,
                    f"model_A_{pred}",
                    "",
                    False,
                )
            )

    for spec in specs:
        LOGGER.info("Fitting Model B for %s", spec["parameter"])
        rhs = f"{acquisition_term(spec)} + {demo_rhs()}"
        needed = [spec["model_col"], "age", "sex", "session"]
        numeric_col = spec["model_col"] if spec["kind"] == "numeric" else None
        pred_name = spec["term_label"]
        substr = "T.XA30" if spec["kind"] == "categorical" else spec["model_col"]
        for iqm in iqms:
            fit, work, meta = fit_mixed(df, iqm, rhs, needed, stats)
            if fit is None:
                rows.append(
                    empty_row(
                        IQM=iqm,
                        IQM_family=family_group(iqm),
                        model=f"B_acquisition_{spec['parameter']}",
                        predictor=pred_name,
                        n_observations=meta.get("n_observations"),
                        n_subjects=meta.get("n_subjects"),
                        status=str(meta.get("status")),
                        exclusion_reason=meta.get("exclusion_reason", ""),
                        fdr_family=f"model_B_{spec['parameter']}",
                        exploratory=spec["exploratory"],
                        acquisition_variable=spec["parameter"],
                    )
                )
                continue
            rows.append(
                extract_term(
                    fit,
                    work,
                    meta,
                    iqm,
                    f"B_acquisition_{spec['parameter']}",
                    pred_name,
                    substr,
                    f"model_B_{spec['parameter']}",
                    spec["parameter"],
                    spec["exploratory"],
                    numeric_predictor_col=numeric_col,
                )
            )

        LOGGER.info("Fitting Model C for %s", spec["parameter"])
        rhs_c = (
            f'C(cohort, Treatment("{REF_COHORT}")) + {acquisition_term(spec)} + {demo_rhs()}'
        )
        needed_c = ["cohort", spec["model_col"], "age", "sex", "session"]
        for iqm in iqms:
            fit, work, meta = fit_mixed(df, iqm, rhs_c, needed_c, stats)
            model_name = f"C_full_{spec['parameter']}"
            if fit is None:
                for pred, substr_c, fam in (
                    ("Glaucoma", "T.Glaucoma", f"model_C_{spec['parameter']}_Glaucoma"),
                    ("Data_ON", "T.Data_ON", f"model_C_{spec['parameter']}_Data_ON"),
                    ("Data_TON", "T.Data_TON", f"model_C_{spec['parameter']}_Data_TON"),
                    (pred_name, substr, f"model_C_{spec['parameter']}_acquisition"),
                ):
                    rows.append(
                        empty_row(
                            IQM=iqm,
                            IQM_family=family_group(iqm),
                            model=model_name,
                            predictor=pred,
                            n_observations=meta.get("n_observations"),
                            n_subjects=meta.get("n_subjects"),
                            status=str(meta.get("status")),
                            exclusion_reason=meta.get("exclusion_reason", ""),
                            fdr_family=fam,
                            exploratory=spec["exploratory"],
                            acquisition_variable=spec["parameter"],
                        )
                    )
                continue
            for pred, substr_c, fam, numcol in (
                ("Glaucoma", "T.Glaucoma", f"model_C_{spec['parameter']}_Glaucoma", None),
                ("Data_ON", "T.Data_ON", f"model_C_{spec['parameter']}_Data_ON", None),
                ("Data_TON", "T.Data_TON", f"model_C_{spec['parameter']}_Data_TON", None),
                (pred_name, substr, f"model_C_{spec['parameter']}_acquisition", numeric_col),
            ):
                rows.append(
                    extract_term(
                        fit,
                        work,
                        meta,
                        iqm,
                        model_name,
                        pred,
                        substr_c,
                        fam,
                        spec["parameter"],
                        spec["exploratory"] and pred == pred_name,
                        numeric_predictor_col=numcol,
                    )
                )

    results = apply_fdr_by_family(rows, stats["multipletests"])
    result_cols = [
        "IQM",
        "IQM_family",
        "model",
        "predictor",
        "term",
        "coefficient",
        "SE",
        "statistic",
        "p_value",
        "q_value",
        "CI_low",
        "CI_high",
        "std_coefficient",
        "n_observations",
        "n_subjects",
        "converged",
        "status",
        "exclusion_reason",
        "fdr_family",
        "exploratory",
        "acquisition_variable",
    ]
    results = results[[c for c in result_cols if c in results.columns]].sort_values(
        ["model", "predictor", "IQM"], kind="mergesort"
    )

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "acquisition_physical_acq_results.tsv"
    results.to_csv(results_path, sep="\t", index=False, float_format="%.10g")

    acq_b = results.loc[results["model"].str.startswith("B_acquisition_")].copy()
    top = top_iqm_table(acq_b)
    top_path = out_dir / "acquisition_physical_acq_top_iqms.tsv"
    top.to_csv(top_path, sep="\t", index=False, float_format="%.10g")

    primary_acq = "software_platform"
    coh_c = results.loc[
        (results["model"] == f"C_full_{primary_acq}")
        & (results["predictor"].isin(["Glaucoma", "Data_ON", "Data_TON"]))
    ].copy()
    coh_a = results.loc[
        (results["model"] == "A_cohort_demographic")
        & (results["predictor"].isin(["Glaucoma", "Data_ON", "Data_TON"]))
    ].copy()
    coh_c_path = out_dir / "cohort_acquisition_adjusted_results.tsv"
    coh_c.to_csv(coh_c_path, sep="\t", index=False, float_format="%.10g")

    # Model A vs primary Model C (software_platform: complete n=133).
    cmp_rows = []
    a_map = {(r.IQM, r.predictor): r for r in coh_a.itertuples(index=False)}
    c_map = {(r.IQM, r.predictor): r for r in coh_c.itertuples(index=False)}
    for iqm in iqms:
        for cohort in ("Glaucoma", "Data_ON", "Data_TON"):
            a = a_map.get((iqm, cohort))
            c = c_map.get((iqm, cohort))
            coef_a = float(a.coefficient) if a is not None else float("nan")
            coef_c = float(c.coefficient) if c is not None else float("nan")
            p_a = float(a.p_value) if a is not None else float("nan")
            p_c = float(c.p_value) if c is not None else float("nan")
            q_a = float(a.q_value) if a is not None else float("nan")
            q_c = float(c.q_value) if c is not None else float("nan")
            std_a = float(a.std_coefficient) if a is not None else float("nan")
            std_c = float(c.std_coefficient) if c is not None else float("nan")
            cls, sig = classify_change(q_a, q_c, coef_a, coef_c)
            cmp_rows.append(
                {
                    "IQM": iqm,
                    "IQM_family": family_group(iqm),
                    "cohort": cohort,
                    "acquisition_variable": primary_acq,
                    "coefficient_model_A": coef_a,
                    "p_model_A": p_a,
                    "q_model_A": q_a,
                    "coefficient_model_C": coef_c,
                    "p_model_C": p_c,
                    "q_model_C": q_c,
                    "std_coefficient_model_A": std_a,
                    "std_coefficient_model_C": std_c,
                    "effect_change": coef_c - coef_a if np.isfinite(coef_a) and np.isfinite(coef_c) else np.nan,
                    "significance_change": sig,
                    "classification": cls,
                    "n_observations_A": getattr(a, "n_observations", np.nan) if a is not None else np.nan,
                    "n_observations_C": getattr(c, "n_observations", np.nan) if c is not None else np.nan,
                }
            )
    comparison = pd.DataFrame(cmp_rows)
    cmp_path = out_dir / "cohort_acquisition_comparison.tsv"
    comparison.to_csv(cmp_path, sep="\t", index=False, float_format="%.10g")

    # Figures
    families = [family_group(i) for i in iqms]
    acq_cols = []
    acq_titles = []
    for spec in specs:
        acq_cols.append((f"B_acquisition_{spec['parameter']}", spec["term_label"], spec["parameter"]))
        acq_titles.append(spec["parameter"])
    mat, qmat = heatmap_matrix(results, iqms, acq_cols)
    fig1 = out_dir / "acquisition_physical_acq_heatmap.png"
    save_heatmap(
        mat,
        qmat,
        iqms,
        acq_titles,
        "Acquisition associations with MRIQC IQMs (Model B)\n"
        "* FDR q<0.05; colour = standardized coefficient (not a quality grade)",
        "standardized coefficient",
        fig1,
        families,
    )

    coh_cols = [
        ("C_full_software_platform", "Glaucoma", "Glaucoma"),
        ("C_full_software_platform", "Data_ON", "Data_ON"),
        ("C_full_software_platform", "Data_TON", "Data_TON"),
    ]
    mat_c, qmat_c = heatmap_matrix(results, iqms, coh_cols)
    fig2 = out_dir / "cohort_acquisition_adjusted_heatmap.png"
    save_heatmap(
        mat_c,
        qmat_c,
        iqms,
        ["Control vs Glaucoma", "Control vs Data_ON", "Control vs Data_TON"],
        "Cohort associations after software-platform + demographic adjustment (Model C)\n"
        "* FDR q<0.05; colour = standardized coefficient vs Control (not a quality grade)",
        "standardized coefficient",
        fig2,
        families,
    )

    fig3 = out_dir / "cohort_acquisition_comparison.png"
    scatter_a_vs_c(comparison, fig3)

    tax = taxonomy(iqms, acq_b, coh_a, coh_c)

    def n_sig(frame: pd.DataFrame, pred: str | None = None) -> int:
        sub = frame if pred is None else frame.loc[frame["predictor"] == pred]
        return int((sub["q_value"] < FDR_ALPHA).sum())

    acq_report = [
        "Physical-acquisition IQM acquisition-effect report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Input: study/metadata/mriqc_iqm_physical_acquisition.tsv",
        "Unit of observation: physical acquisition (one reconstruction per physical scan).",
        "NORM/non-NORM is not modeled: it is not an independent acquisition factor.",
        "Anatomy: not included. MRIQC was not rerun.",
        "",
        "SoftwareVersions and TxRefAmp were read from BIDS sidecars of the 133",
        "already-selected reconstructions. This does not reconstruct the 264-row table.",
        "",
        "Acquisition inventory:",
    ]
    for rec in inventory.itertuples(index=False):
        acq_report.append(
            f"  {rec.parameter}: present={rec.present} kind={rec.kind} unique={rec.n_unique} "
            f"missing={rec.n_missing} status={rec.inferential_status} {rec.value_summary}"
        )
    acq_report += [
        "",
        "Inferential acquisition variables (separate models; collinear aliases not co-entered):",
    ]
    for spec in specs:
        acq_report.append(
            f"  {spec['parameter']}: usable={spec['usable']} n_complete={spec['n_complete']} "
            f"missing={spec['n_missing']} minority={spec['minority_n']} "
            f"exploratory={spec['exploratory']} {spec['exploratory_reason'] or spec['skip_reason'] or 'ok'}"
        )
    acq_report += [
        "",
        "Collinearity notes:",
        "  software_platform == scanner == ManufacturersModelName partition.",
        "  In this selected table, XA30 is also aliased with non-NORM (6 rows).",
        "  SAR and TxRefAmp are correlated (r≈0.70) but not treated as interchangeable.",
        "  SAR and TxRefAmp are missing on the 6 XA30 rows, so those models use n=127 E11-only.",
        "",
        "FDR: BH within each Model B family of 56 IQM tests, alpha=0.05.",
        "",
        "Model B FDR-significant IQMs (q<0.05):",
    ]
    for spec in specs:
        n = n_sig(acq_b, spec["term_label"])
        acq_report.append(f"  {spec['parameter']}: {n}/56")
        sub = acq_b.loc[
            (acq_b["predictor"] == spec["term_label"]) & (acq_b["q_value"] < FDR_ALPHA)
        ].sort_values("q_value")
        for rec in sub.head(8).itertuples(index=False):
            acq_report.append(
                f"    {rec.IQM:20s} family={rec.IQM_family:24s} "
                f"coef={rec.coefficient:.4g} std={rec.std_coefficient:.4g} "
                f"p={fmt_p(rec.p_value)} q={fmt_p(rec.q_value)} n={int(rec.n_observations)}"
            )
    acq_report += [
        "",
        "software_platform XA30 (n=6) results are exploratory associations with",
        "acquisition/software platform, not causal scanner effects.",
        "",
        f"Wrote {results_path}",
        f"Wrote {top_path}",
        f"Wrote {fig1}",
    ]
    acq_report_path = out_dir / "acquisition_physical_acq_report.txt"
    write_text(acq_report_path, acq_report)

    coh_report = [
        "Cohort effects after acquisition adjustment (Model C, software_platform)",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Primary Model C:",
        "  IQM ~ cohort + software_platform + age + sex + session + (1|subject_id)",
        "Reference cohort: Control. Session reference: ses-01.",
        "FDR: BH within each Control-vs-cohort family of 56 IQM tests.",
        "",
        "This does not establish disease effects, image-quality grades, or anatomy.",
        "Residual cohort associations may still reflect anatomy, tissue composition,",
        "unmeasured technical factors, or biology–image interactions.",
        "",
        f"n observations={sizes['n_physical_acquisitions']}  n subjects={sizes['n_subjects']}",
        f"subjects per cohort: {sizes['subjects_per_cohort']}",
        f"acquisitions per cohort: {sizes['acquisitions_per_cohort']}",
        "Data_TON n=2 subjects; Data_ON is small; do not generalize those coefficients.",
        "",
        "FDR-significant cohort associations after software-platform adjustment:",
    ]
    for cohort in ("Glaucoma", "Data_ON", "Data_TON"):
        sub = coh_c.loc[coh_c["predictor"] == cohort]
        n = int((sub["q_value"] < FDR_ALPHA).sum())
        coh_report.append(f"  Control vs {cohort}: {n}/56")
        hits = sub.loc[sub["q_value"] < FDR_ALPHA].sort_values("q_value")
        for rec in hits.head(10).itertuples(index=False):
            coh_report.append(
                f"    {rec.IQM:20s} family={rec.IQM_family:24s} "
                f"coef={rec.coefficient:.4g} std={rec.std_coefficient:.4g} "
                f"p={fmt_p(rec.p_value)} q={fmt_p(rec.q_value)}"
            )
        if hits.empty:
            coh_report.append("    (none)")
    n_ret = int((comparison["classification"] == "cohort association retained").sum())
    n_att = int((comparison["classification"] == "cohort association attenuated").sum())
    n_lost = int((comparison["classification"] == "cohort association lost").sum())
    n_new = int((comparison["classification"] == "cohort association newly apparent").sum())
    coh_report += [
        "",
        "Model A vs Model C classification counts (3 cohort contrasts × 56 IQMs):",
        f"  retained={n_ret}  attenuated={n_att}  lost={n_lost}  newly apparent={n_new}",
        "  This is a descriptive comparison, not mediation or causality.",
        "",
        f"Wrote {coh_c_path}",
        f"Wrote {fig2}",
        f"Wrote {cmp_path}",
        f"Wrote {fig3}",
    ]
    coh_report_path = out_dir / "cohort_acquisition_adjusted_report.txt"
    write_text(coh_report_path, coh_report)

    final_report = [
        "Physical-acquisition MRIQC IQM acquisition/cohort analysis",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "1. Objective",
        "  Determine which of 56 MRIQC T1w IQMs associate with measurable",
        "  acquisition characteristics and which cohort associations remain",
        "  after acquisition, demographic, and repeated-subject adjustment.",
        "  Anatomy is not included. This is a baseline before FreeSurfer.",
        "",
        "2. Dataset",
        f"  {args.phys}",
        f"  sha256: {file_sha256(args.phys)}",
        f"  n={validation['n_rows']} physical acquisitions from {validation['n_subjects']} subjects.",
        "  The 264-row reconstruction table was not used as the analysis unit.",
        "  MRIQC, PCA, and previous cohort/longitudinal files were not modified.",
        "",
        "3. Unit of observation",
        "  One representative reconstruction per physical T1w acquisition.",
        f"  Unique physical_acquisition_id: {validation['n_unique_physical_ids']}.",
        "  Unique subject×session except the documented sub-043 ses-02 case",
        "  (two independent physical scans in one session).",
        "  Repeated measures are modeled with (1|subject_id), not as independent rows.",
        "",
        "4. Acquisition variables",
        "  Inventoried from the physical table plus sidecars of the selected 133 files.",
        f"  software_platform: E11 n={sizes['n_E11']}, XA30 n={sizes['n_XA30']} (exploratory).",
        "  Described as association with acquisition/software platform, not a causal scanner effect.",
        f"  SAR: n_missing={sizes['SAR_n_missing']} (the 6 XA30 rows). Modeled on n=127.",
        f"  TxRefAmp: n_missing={sizes['TxRefAmp_n_missing']} (the 6 XA30 rows). Modeled on n=127.",
        "  scanner / SoftwareVersions / ManufacturersModelName share the E11 vs XA30 partition",
        "  and are not entered together.",
        "  NORM/non-NORM is not an inferential predictor. In this selected table the 6 XA30",
        "  rows are exactly the 6 non-NORM reconstructions, so platform and NORM are aliased.",
        "  Protocol timing/geometry fields are constant (T1w_MPR 0.8 mm) and are not modeled.",
        "",
        "5. Statistical models",
        "  MixedLM, REML, random intercept (1|subject_id).",
        "  Model A: IQM ~ cohort + age + sex + session + (1|subject_id)",
        "  Model B: IQM ~ acquisition + age + sex + session + (1|subject_id)",
        "  Model C: IQM ~ cohort + acquisition + age + sex + session + (1|subject_id)",
        "  Acquisition variables are fit in separate B/C models (not a joint collinear block).",
        "  Session is categorical with reference ses-01. Cohort reference is Control.",
        "  Age is continuous. Sex is categorical.",
        "",
        "6. FDR correction",
        "  Benjamini–Hochberg, alpha=0.05, separately for each family of 56 IQM tests.",
        "  Families are defined by model × focal predictor (e.g. Model A Glaucoma,",
        "  Model B SAR, Model C software_platform Glaucoma).",
        "  Unrelated families are not pooled.",
        "",
        "7. Acquisition effects",
        *[
            f"  Model B {spec['parameter']}: {n_sig(acq_b, spec['term_label'])}/56 IQMs with q<0.05"
            for spec in specs
        ],
        "  See acquisition_physical_acq_report.txt and acquisition_physical_acq_top_iqms.tsv.",
        "  Standardized coefficients are used for ranking and heatmaps because IQMs have different scales.",
        "",
        "8. Cohort effects before acquisition adjustment",
        *[
            f"  Model A Control vs {c}: {n_sig(coh_a, c)}/56 IQMs with q<0.05"
            for c in ("Glaucoma", "Data_ON", "Data_TON")
        ],
        "",
        "9. Cohort effects after acquisition adjustment",
        "  Primary adjustment uses software_platform (complete n=133).",
        *[
            f"  Model C Control vs {c}: {n_sig(coh_c, c)}/56 IQMs with q<0.05"
            for c in ("Glaucoma", "Data_ON", "Data_TON")
        ],
        f"  A vs C (3×56 cells): retained={n_ret}, attenuated={n_att}, lost={n_lost}, newly apparent={n_new}.",
        "  Residual cohort coefficients are not interpreted as disease or biology.",
        "",
        "10. IQM-family interpretation",
        "  Taxonomy is descriptive, not biological.",
        f"  Acquisition-sensitive (Model B q<0.05, any modeled acquisition variable): {len(tax['acquisition_sensitive'])}",
        f"    {', '.join(tax['acquisition_sensitive']) or '(none)'}",
        f"  Cohort-associated after demographics (Model A q<0.05, any cohort): {len(tax['cohort_associated_model_A'])}",
        f"    {', '.join(tax['cohort_associated_model_A']) or '(none)'}",
        f"  Acquisition-adjusted cohort-associated (Model C software_platform q<0.05): {len(tax['acquisition_adjusted_cohort_associated'])}",
        f"    {', '.join(tax['acquisition_adjusted_cohort_associated']) or '(none)'}",
        f"  Neither in the current models: {len(tax['neither'])}",
        "",
        "11. Small-sample limitations",
        f"  total physical acquisitions={sizes['n_physical_acquisitions']}",
        f"  total subjects={sizes['n_subjects']}",
        f"  repeated subjects={sizes['n_repeated_subjects']}",
        f"  acquisitions per cohort={sizes['acquisitions_per_cohort']}",
        f"  subjects per cohort={sizes['subjects_per_cohort']}",
        f"  E11 n={sizes['n_E11']}  XA30 n={sizes['n_XA30']}",
        f"  SAR missing={sizes['SAR_n_missing']}  TxRefAmp missing={sizes['TxRefAmp_n_missing']}",
        "  XA30 n=6: exploratory; do not make strong claims.",
        "  Data_TON n=2 subjects: do not use as evidence for general cohort effects.",
        "  Data_ON is also small.",
        "  SAR/TxRefAmp models cannot estimate a platform contrast because XA30 rows are missing those fields.",
        "",
        "12. What can be concluded now",
        "  Whether measurable acquisition variables (software platform, SAR, TxRefAmp)",
        "  are associated with MRIQC IQMs after age, sex, session, and repeated-subject structure.",
        "  Whether cohort associations persist after those acquisition adjustments.",
        "  Which IQMs are robustly associated with acquisition characteristics (FDR q<0.05).",
        "",
        "13. What cannot yet be concluded",
        "  Whether residual cohort effects are anatomical.",
        "  Whether an IQM difference represents worse or better image quality.",
        "  Whether an IQM is caused by disease.",
        "  Causal relationships of any kind.",
        "  That a non-significant acquisition test means no acquisition effect.",
        "  cohort effect ≠ disease effect; IQM difference ≠ image-quality difference.",
        "",
        "14. Planned FreeSurfer/anatomy analysis",
        "  Planned anatomy-adjusted analysis",
        "  The current full non-anatomical model is",
        "    IQM ~ cohort + acquisition + age + sex + session + (1|subject_id).",
        "  After recon-all completes, anatomical variables can be added as",
        "    IQM ~ cohort + acquisition + anatomy + age + sex + session + (1|subject_id).",
        "  The purpose is to test whether residual cohort-associated IQM variation",
        "  is accounted for by anatomical variation. Candidate FreeSurfer variables",
        "  include intracranial volume, total GM/WM/CSF, hippocampal volume,",
        "  regional cortical volumes, and cortical thickness. Not all will necessarily",
        "  be used; selection will depend on completeness, collinearity, and a",
        "  pre-specified anatomical rationale. This script does not implement that model.",
        "",
        "15. Output files",
        f"  {results_path.name}",
        f"  {acq_report_path.name}",
        f"  {fig1.name}",
        f"  {top_path.name}",
        f"  {coh_c_path.name}",
        f"  {coh_report_path.name}",
        f"  {fig2.name}",
        f"  {cmp_path.name}",
        f"  {fig3.name}",
        f"  {out_dir / 'acquisition_cohort_physical_acq_report.txt'}",
        "",
        "scipy " + str(stats.get("scipy", "")) + "  statsmodels " + str(stats.get("statsmodels", "")),
    ]
    final_path = out_dir / "acquisition_cohort_physical_acq_report.txt"
    write_text(final_path, final_report)

    assert_unmodified(before)
    LOGGER.info("Protected previous analysis files unchanged.")
    print()
    print("Output locations:")
    for path in (
        results_path,
        acq_report_path,
        fig1,
        top_path,
        coh_c_path,
        coh_report_path,
        fig2,
        cmp_path,
        fig3,
        final_path,
    ):
        print(f"  {path}")
    print("Physical-acquisition IQM acquisition/cohort analysis completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
