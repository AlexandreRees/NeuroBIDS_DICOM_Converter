#!/usr/bin/env python3
"""Integrate FreeSurfer 7.4.1 anatomy into the physical-acquisition MRIQC table.

Does not rebuild the MRIQC cohort, PCA, Elastic Net, IQM cleaning, or the
existing longitudinal MRIQC models. Does not read HCP-FS 6.0.1. Does not
modify study/metadata/mriqc_iqm_physical_acquisition.tsv.

On Narval, from study/:

  python3 code/mriqc_iqm_freesurfer_anatomical_adjustment.py
"""

from __future__ import annotations

import argparse
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

from extract_freesurfer_anatomy import (  # noqa: E402
    as_float,
    classify_status,
    freesurfer_version,
    is_fs_741,
    parse_measures,
    reject_forbidden_subjects_dir,
)
from mriqc_iqm_cohort_analysis import nakagawa_r2  # noqa: E402
from mriqc_iqm_lib import fail, require_file, to_numeric_iqm  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    FAMILY_COLORS,
    FAMILY_GROUP_ORDER,
    FDR_ALPHA,
    REF_COHORT,
    REF_SOFTWARE,
    assert_unmodified,
    family_group,
    file_sha256,
    load_physical_acquisition_table,
    load_t1w_iqm_names,
    snapshot_protected,
    study_root_default,
)
from mriqc_iqm_physical_acq_models import fdr_bh, import_stats, term_lookup, wald_terms  # noqa: E402

LOGGER = logging.getLogger("mriqc_iqm.freesurfer_anatomy_models")

REQUIRED_FS_VERSION = "7.4.1"
VIF_DROP_THRESHOLD = 5.0
CANONICAL_SHA256 = "be1d89fd0359fe86eb478fb9fda5a2e8fbd98e0c203229a81011792d00a2692a"
SUMMARY_SECTION_TITLE = "FreeSurfer anatomical adjustment"

# MRIQC IQM definitions (Esteban et al. 2017 / MRIQC anatomical QC), not observed r.
# TRUE if the IQM is computed from tissue segmentation, a brain mask, or GM/WM/CSF.
ANATOMY_SENSITIVE_BY_CONSTRUCTION: dict[str, bool] = {}
for _name in (
    "cjv",
    "cnr",
    "wm2max",
    "inu_med",
    "inu_range",
    "fber",
):
    ANATOMY_SENSITIVE_BY_CONSTRUCTION[_name] = True
for _prefix in ("snr_", "snrd_", "icvs_", "rpve_", "tpm_overlap_", "fwhm_"):
    ANATOMY_SENSITIVE_BY_CONSTRUCTION[_prefix] = True
for _tissue in ("csf", "gm", "wm"):
    ANATOMY_SENSITIVE_BY_CONSTRUCTION[f"summary_{_tissue}_"] = True

ANATOMY_SENSITIVE_FALSE_PREFIX = ("summary_bg_",)
ANATOMY_SENSITIVE_FALSE_EXACT = {"efc", "qi_1", "qi_2"}

ANATOMY_CANDIDATES = [
    "icv_etiv",
    "total_cortical_gm",
    "total_wm",
    "mean_cortical_thickness",
]
VOLUME_CANDIDATES = ["icv_etiv", "total_cortical_gm", "total_wm"]

VARIABLE_MAPPING = [
    {
        "requested": "ICV / estimated intracranial volume",
        "column": "icv_etiv",
        "freesurfer_source": "stats/aseg.stats # Measure EstimatedTotalIntraCranialVol, eTIV",
        "unit": "mm^3",
        "used_in_primary_model": "",
        "notes": "Atlas-scaled eTIV. Not BrainSegVol.",
    },
    {
        "requested": "BrainSegVol",
        "column": "brainseg_vol",
        "freesurfer_source": "stats/aseg.stats # Measure BrainSeg, BrainSegVol",
        "unit": "mm^3",
        "used_in_primary_model": "False",
        "notes": "Extracted; not a default co-entered size term with eTIV.",
    },
    {
        "requested": "total cortical GM",
        "column": "total_cortical_gm",
        "freesurfer_source": "stats/aseg.stats # Measure Cortex, CortexVol",
        "unit": "mm^3",
        "used_in_primary_model": "",
        "notes": "Cortical gray matter only (not TotalGrayVol, which includes subcortical GM).",
    },
    {
        "requested": "total WM",
        "column": "total_wm",
        "freesurfer_source": "stats/aseg.stats # Measure CerebralWhiteMatter, CerebralWhiteMatterVol",
        "unit": "mm^3",
        "used_in_primary_model": "",
        "notes": "Cerebral white-matter volume.",
    },
    {
        "requested": "total CSF",
        "column": "total_csf",
        "freesurfer_source": "stats/aseg.stats table, StructName=CSF, Volume_mm3 (SegId 24)",
        "unit": "mm^3",
        "used_in_primary_model": "False",
        "notes": "FreeSurfer CSF label (extra-axial CSF), not a whole-intracranial CSF compartment. VentricleChoroidVol exists but is ventricular+choroid, not substituted here.",
    },
    {
        "requested": "mean cortical thickness",
        "column": "mean_cortical_thickness",
        "freesurfer_source": "stats/lh.aparc.stats and rh.aparc.stats # Measure Cortex, MeanThickness",
        "unit": "mm",
        "used_in_primary_model": "",
        "notes": "Unweighted mean of the two hemisphere MeanThickness values.",
    },
    {
        "requested": "left hippocampal volume",
        "column": "left_hippocampal_volume",
        "freesurfer_source": "stats/aseg.stats table, StructName=Left-Hippocampus, Volume_mm3",
        "unit": "mm^3",
        "used_in_primary_model": "False",
        "notes": "Extracted; not entered in the primary anatomy set.",
    },
    {
        "requested": "right hippocampal volume",
        "column": "right_hippocampal_volume",
        "freesurfer_source": "stats/aseg.stats table, StructName=Right-Hippocampus, Volume_mm3",
        "unit": "mm^3",
        "used_in_primary_model": "False",
        "notes": "Extracted; not entered in the primary anatomy set.",
    },
]

ANATOMY_VALUE_COLUMNS = [
    "icv_etiv",
    "brainseg_vol",
    "total_cortical_gm",
    "total_wm",
    "total_csf",
    "mean_cortical_thickness",
    "left_hippocampal_volume",
    "right_hippocampal_volume",
]

EXTRA_PROTECTED_RELATIVE = (
    "metadata/mriqc_iqm_physical_acquisition.tsv",
    "qc_reports/mriqc_iqm/iqm_family_robustness_results.tsv",
    "qc_reports/mriqc_iqm/iqm_variance_explained_physical_acq.tsv",
    "qc_reports/mriqc_iqm/elastic_net_subject_grouped_results.tsv",
    "qc_reports/mriqc_iqm/longitudinal_physical_acq_results.tsv",
    "qc_reports/mriqc_iqm/pca_physical_acq_loadings.tsv",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--subjects-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args(argv)
    study_root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    project_root = args.project_root.resolve() if args.project_root else study_root.parent
    args.study_root = study_root
    args.project_root = project_root
    args.subjects_dir = (
        args.subjects_dir.resolve()
        if args.subjects_dir
        else project_root / "derivatives" / "freesurfer"
    )
    args.manifest = (
        args.manifest.resolve()
        if args.manifest
        else project_root / "metadata" / "freesurfer_manifest.tsv"
    )
    qc = study_root / "qc_reports" / "mriqc_iqm"
    args.phys = study_root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    args.loadings = qc / "pca_physical_acq_loadings.tsv"
    args.out_audit = qc / "freesurfer_integration_audit.tsv"
    args.out_summary = study_root / "metadata" / "freesurfer_anatomical_summary.tsv"
    args.out_qc = qc / "freesurfer_qc_summary.tsv"
    args.out_join = study_root / "metadata" / "mriqc_iqm_physical_acquisition_freesurfer.tsv"
    args.out_mapping = qc / "freesurfer_anatomical_variable_mapping.tsv"
    args.out_models = qc / "anatomical_adjustment_models.tsv"
    args.out_cohort = qc / "cohort_effect_anatomical_adjustment.tsv"
    args.out_var = qc / "anatomical_variance_decomposition.tsv"
    args.out_long = qc / "longitudinal_anatomical_adjustment.tsv"
    args.fig_a = qc / "figure_anatomical_variance.pdf"
    args.fig_b = qc / "figure_cohort_anatomical_adjustment.pdf"
    args.fig_c = qc / "figure_iqm_predictor_heatmap.pdf"
    args.out_md = qc / "FREESURFER_INTEGRATION_SUMMARY.md"
    args.out_txt = qc / "robustness_variance_elastic_net_summary.txt"
    args.qc_dir = qc
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    LOGGER.addHandler(handler)


def snapshot_all(study_root: Path) -> dict[Path, str]:
    before = snapshot_protected(study_root)
    for rel in EXTRA_PROTECTED_RELATIVE:
        path = study_root / rel
        require_file(path, "protected table")
        before[path] = file_sha256(path)
    return before


def anatomy_sensitive(iqm: str) -> bool:
    if iqm in ANATOMY_SENSITIVE_FALSE_EXACT:
        return False
    if any(iqm.startswith(p) for p in ANATOMY_SENSITIVE_FALSE_PREFIX):
        return False
    if iqm in ANATOMY_SENSITIVE_BY_CONSTRUCTION:
        return bool(ANATOMY_SENSITIVE_BY_CONSTRUCTION[iqm])
    if any(iqm.startswith(p) for p, flag in ANATOMY_SENSITIVE_BY_CONSTRUCTION.items() if flag and p.endswith("_")):
        return True
    return False


def bool_str(flag: bool) -> str:
    return "TRUE" if flag else "FALSE"


def parse_aseg_struct_volumes(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    if not path.is_file():
        return out
    headers: list[str] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# ColHeaders"):
            headers = line.split()[2:]
            continue
        if not line or line.startswith("#") or headers is None:
            continue
        cols = line.split()
        if "StructName" not in headers or "Volume_mm3" not in headers:
            continue
        i_name = headers.index("StructName")
        i_vol = headers.index("Volume_mm3")
        if len(cols) <= max(i_name, i_vol):
            continue
        value = as_float(cols[i_vol])
        if value is not None:
            out[cols[i_name]] = value
    return out


def extract_primary_anatomy(subj: Path) -> dict[str, float | None]:
    values: dict[str, float | None] = {name: None for name in ANATOMY_VALUE_COLUMNS}
    aseg_path = subj / "stats" / "aseg.stats"
    lh_path = subj / "stats" / "lh.aparc.stats"
    rh_path = subj / "stats" / "rh.aparc.stats"
    aseg = parse_measures(aseg_path)
    structs = parse_aseg_struct_volumes(aseg_path)
    lh_meas = parse_measures(lh_path)
    rh_meas = parse_measures(rh_path)

    values["icv_etiv"] = as_float(aseg.get("eTIV") or aseg.get("EstimatedTotalIntraCranialVol"))
    values["brainseg_vol"] = as_float(aseg.get("BrainSegVol") or aseg.get("BrainSeg"))
    values["total_cortical_gm"] = as_float(aseg.get("CortexVol") or aseg.get("Cortex"))
    values["total_wm"] = as_float(aseg.get("CerebralWhiteMatterVol") or aseg.get("CerebralWhiteMatter"))
    values["total_csf"] = structs.get("CSF")
    values["left_hippocampal_volume"] = structs.get("Left-Hippocampus")
    values["right_hippocampal_volume"] = structs.get("Right-Hippocampus")

    lh_thick = as_float(lh_meas.get("lhMeanThickness") or lh_meas.get("MeanThickness"))
    rh_thick = as_float(rh_meas.get("rhMeanThickness") or rh_meas.get("MeanThickness"))
    if lh_thick is not None and rh_thick is not None:
        values["mean_cortical_thickness"] = (lh_thick + rh_thick) / 2.0
    return values


def load_manifest(path: Path) -> pd.DataFrame:
    require_file(path, "FreeSurfer manifest")
    man = pd.read_csv(path, sep="\t")
    need = {"subject_id", "session", "freesurfer_id"}
    missing = need - set(man.columns)
    if missing:
        fail(f"FreeSurfer manifest missing columns: {sorted(missing)}")
    man["subject_id"] = man["subject_id"].astype(str).str.strip()
    man["session"] = man["session"].astype(str).str.strip()
    man["freesurfer_id"] = man["freesurfer_id"].astype(str).str.strip()
    dups = man.duplicated(["subject_id", "session"], keep=False)
    if dups.any():
        fail(f"Duplicate subject/session in FreeSurfer manifest: {man.loc[dups, ['subject_id','session']]}")
    return man


def fmt_num(value: float | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return ""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def audit_and_extract(
    mriqc: pd.DataFrame,
    manifest: pd.DataFrame,
    subjects_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    iqm_keys = mriqc[["subject_id", "session"]].drop_duplicates().copy()
    iqm_keys["subject_id"] = iqm_keys["subject_id"].astype(str)
    iqm_keys["session"] = iqm_keys["session"].astype(str)
    man = manifest.set_index(["subject_id", "session"], drop=False)
    audit_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    for rec in iqm_keys.itertuples(index=False):
        subject, session = str(rec.subject_id), str(rec.session)
        key = (subject, session)
        row_a: dict[str, Any] = {
            "subject": subject,
            "session": session,
            "freesurfer_found": "FALSE",
            "aseg_found": "FALSE",
            "lh_aparc_found": "FALSE",
            "rh_aparc_found": "FALSE",
            "status": "MISSING_FREESURFER",
            "reason": "subject/session absent from the FreeSurfer 7.4.1 manifest and SUBJECTS_DIR",
        }
        row_s: dict[str, Any] = {
            "subject": subject,
            "subject_id": subject,
            "session": session,
            "freesurfer_id": "",
            "freesurfer_version": "",
            "processing_status": "NOT_STARTED",
            "FS_success": "FALSE",
            **{name: "" for name in ANATOMY_VALUE_COLUMNS},
        }
        if key not in man.index:
            audit_rows.append(row_a)
            summary_rows.append(row_s)
            continue
        fs_id = str(man.loc[key, "freesurfer_id"])
        subj = subjects_dir / fs_id
        version = freesurfer_version(subj)
        status = classify_status(subj)
        aseg_ok = (subj / "stats" / "aseg.stats").is_file()
        lh_ok = (subj / "stats" / "lh.aparc.stats").is_file()
        rh_ok = (subj / "stats" / "rh.aparc.stats").is_file()
        wmparc_ok = (subj / "stats" / "wmparc.stats").is_file()
        found = subj.is_dir()
        version_ok = is_fs_741(version)
        reasons: list[str] = []
        if not found:
            reasons.append(f"SUBJECTS_DIR folder missing: {fs_id}")
        if not version_ok:
            reasons.append(f"build stamp is not {REQUIRED_FS_VERSION}: {version or 'empty'}")
        if status != "COMPLETED":
            reasons.append(f"recon-all status={status}")
        if not aseg_ok:
            reasons.append("aseg.stats missing")
        if not lh_ok:
            reasons.append("lh.aparc.stats missing")
        if not rh_ok:
            reasons.append("rh.aparc.stats missing")
        if not wmparc_ok:
            reasons.append("wmparc.stats missing (optional)")
        fs_success = found and status == "COMPLETED" and version_ok and aseg_ok and lh_ok and rh_ok
        if fs_success:
            audit_status = "OK"
            reason = "FreeSurfer 7.4.1 recon-all complete; aseg and aparc present"
            if not wmparc_ok:
                reason += "; wmparc.stats absent"
        elif found and status == "COMPLETED" and version_ok:
            audit_status = "INCOMPLETE_STATS"
            reason = "; ".join(reasons) if reasons else "stats incomplete"
        elif found:
            audit_status = status if status in {"FAILED", "RUNNING/UNKNOWN"} else "FAILED"
            reason = "; ".join(reasons) if reasons else status
        else:
            audit_status = "MISSING_FREESURFER"
            reason = "; ".join(reasons)
        row_a.update(
            {
                "freesurfer_found": bool_str(found),
                "aseg_found": bool_str(aseg_ok),
                "lh_aparc_found": bool_str(lh_ok),
                "rh_aparc_found": bool_str(rh_ok),
                "status": audit_status,
                "reason": reason,
            }
        )
        row_s.update(
            {
                "freesurfer_id": fs_id,
                "freesurfer_version": version,
                "processing_status": status,
                "FS_success": bool_str(fs_success),
            }
        )
        if fs_success:
            anatomy = extract_primary_anatomy(subj)
            for name, value in anatomy.items():
                row_s[name] = fmt_num(value) if value is not None else ""
        audit_rows.append(row_a)
        summary_rows.append(row_s)

    audit = pd.DataFrame(audit_rows)
    summary = pd.DataFrame(summary_rows)
    return audit, summary


def qc_summary(summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add_check(item: str, n: Any, note: str = "", **kwargs: Any) -> None:
        rec = {
            "row_type": "check",
            "item": item,
            "n": n,
            "n_missing": "",
            "n_invalid": "",
            "n_outlier_iqr": "",
            "min": "",
            "p05": "",
            "median": "",
            "p95": "",
            "max": "",
            "note": note,
        }
        rec.update(kwargs)
        rows.append(rec)

    n_sessions = len(summary)
    n_subjects = int(summary["subject_id"].nunique())
    n_dups = int(summary.duplicated(["subject_id", "session"]).sum())
    n_ok = int((summary["FS_success"] == "TRUE").sum())
    add_check("n_subject_session_rows", n_sessions, "one FreeSurfer recon-all per MRIQC subject×session")
    add_check("n_subjects", n_subjects)
    add_check("n_duplicate_subject_session", n_dups, "must be 0 in the anatomy table")
    add_check("n_FS_success", n_ok)
    add_check("n_without_complete_freesurfer", n_sessions - n_ok)

    numeric = summary.copy()
    for col in ANATOMY_VALUE_COLUMNS:
        numeric[col] = pd.to_numeric(numeric[col], errors="coerce")

    rules = {
        "icv_etiv": ("ICV > 0", lambda s: s <= 0),
        "brainseg_vol": ("BrainSegVol > 0", lambda s: s <= 0),
        "total_cortical_gm": ("GM > 0", lambda s: s <= 0),
        "total_wm": ("WM > 0", lambda s: s <= 0),
        "total_csf": ("CSF >= 0", lambda s: s < 0),
        "mean_cortical_thickness": ("cortical thickness > 0", lambda s: s <= 0),
        "left_hippocampal_volume": ("left hippocampus > 0", lambda s: s <= 0),
        "right_hippocampal_volume": ("right hippocampus > 0", lambda s: s <= 0),
    }
    for col, (rule, invalid_fn) in rules.items():
        series = numeric[col]
        n_miss = int(series.isna().sum())
        valid = series.dropna()
        n_invalid = int(invalid_fn(valid).sum()) if len(valid) else 0
        if len(valid) >= 4:
            q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
            iqr = q3 - q1
            n_out = int(((valid < q1 - 1.5 * iqr) | (valid > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0
        else:
            n_out = 0
        rows.append(
            {
                "row_type": "variable",
                "item": col,
                "n": int(valid.shape[0]),
                "n_missing": n_miss,
                "n_invalid": n_invalid,
                "n_outlier_iqr": n_out,
                "min": fmt_num(float(valid.min()) if len(valid) else None),
                "p05": fmt_num(float(valid.quantile(0.05)) if len(valid) else None),
                "median": fmt_num(float(valid.median()) if len(valid) else None),
                "p95": fmt_num(float(valid.quantile(0.95)) if len(valid) else None),
                "max": fmt_num(float(valid.max()) if len(valid) else None),
                "note": f"{rule}; IQR outliers documented, not dropped",
            }
        )
        bad = numeric.loc[series.notna() & invalid_fn(series), ["subject_id", "session", col]]
        for rec in bad.itertuples(index=False):
            rows.append(
                {
                    "row_type": "impossible_value",
                    "item": f"{rec.subject_id}/{rec.session}/{col}",
                    "n": 1,
                    "n_missing": 0,
                    "n_invalid": 1,
                    "n_outlier_iqr": "",
                    "min": fmt_num(float(getattr(rec, col))),
                    "p05": "",
                    "median": "",
                    "p95": "",
                    "max": "",
                    "note": rule,
                }
            )
    missing_sessions = summary.loc[summary["FS_success"] != "TRUE", ["subject_id", "session", "processing_status"]]
    for rec in missing_sessions.itertuples(index=False):
        rows.append(
            {
                "row_type": "missing_freesurfer",
                "item": f"{rec.subject_id}/{rec.session}",
                "n": 1,
                "n_missing": 1,
                "n_invalid": "",
                "n_outlier_iqr": "",
                "min": "",
                "p05": "",
                "median": "",
                "p95": "",
                "max": "",
                "note": rec.processing_status,
            }
        )
    return pd.DataFrame(rows)


def left_join_mriqc(mriqc: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    n_before = len(mriqc)
    if n_before != EXPECTED_PHYSICAL_N:
        fail(f"STOP: MRIQC table has {n_before} rows, expected {EXPECTED_PHYSICAL_N}.")
    fs = summary.copy()
    for col in ANATOMY_VALUE_COLUMNS:
        fs[col] = pd.to_numeric(fs[col], errors="coerce")
    fs_cols = [
        "subject_id",
        "session",
        "freesurfer_id",
        "freesurfer_version",
        "processing_status",
        "FS_success",
        *ANATOMY_VALUE_COLUMNS,
    ]
    merged = mriqc.merge(fs[fs_cols], on=["subject_id", "session"], how="left", validate="m:1")
    if len(merged) != EXPECTED_PHYSICAL_N:
        fail(
            f"STOP: JOIN changed the row count ({n_before} → {len(merged)}). "
            "The canonical physical-acquisition table was not modified."
        )
    extra = merged.duplicated(["physical_acquisition_id"]).sum() if "physical_acquisition_id" in merged.columns else 0
    if extra:
        fail(f"STOP: JOIN created duplicate physical_acquisition_id rows ({extra}).")
    return merged


def design_vif(df: pd.DataFrame, columns: list[str]) -> dict[str, float]:
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    import statsmodels.api as sm

    work = df[columns].astype(float).dropna()
    if work.empty or work.shape[1] < 1:
        return {c: float("nan") for c in columns}
    x = sm.add_constant(work, has_constant="add")
    out: dict[str, float] = {}
    names = list(x.columns)
    for i, name in enumerate(names):
        if name == "const":
            continue
        try:
            out[name] = float(variance_inflation_factor(x.to_numpy(dtype=float), i))
        except Exception:
            out[name] = float("nan")
    return out


def select_anatomy_terms(df: pd.DataFrame) -> tuple[list[str], dict[str, float], list[str]]:
    work = df.dropna(subset=ANATOMY_CANDIDATES + ["age"]).copy()
    selected = list(ANATOMY_CANDIDATES)
    dropped: list[str] = []
    vif = design_vif(work, selected + ["age"])
    anatomy_vif = {k: vif.get(k, float("nan")) for k in selected}

    def max_vol_vif(current: list[str], current_vif: dict[str, float]) -> tuple[str | None, float]:
        vols = [c for c in current if c in VOLUME_CANDIDATES]
        if not vols:
            return None, float("nan")
        name = max(vols, key=lambda c: current_vif.get(c, 0.0) if math.isfinite(current_vif.get(c, float("nan"))) else -1)
        return name, float(current_vif.get(name, float("nan")))

    while selected:
        finite_vals = [v for v in anatomy_vif.values() if math.isfinite(v)]
        if not finite_vals or max(finite_vals) <= VIF_DROP_THRESHOLD:
            break
        drop_name, drop_vif = max_vol_vif(selected, anatomy_vif)
        if drop_name is None or not math.isfinite(drop_vif) or drop_vif <= VIF_DROP_THRESHOLD:
            break
        selected.remove(drop_name)
        dropped.append(f"{drop_name} (VIF={drop_vif:.2f})")
        vif = design_vif(work, selected + ["age"])
        anatomy_vif = {k: vif.get(k, float("nan")) for k in selected}
    return selected, {**anatomy_vif, **{k: vif.get(k, float("nan")) for k in ["age"] if k in vif}}, dropped


def ols_fit(df: pd.DataFrame, formula: str, stats: dict[str, Any]) -> Any | None:
    smf = stats["smf"]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return smf.ols(formula, data=df).fit()
    except Exception as exc:
        LOGGER.warning("OLS failed (%s): %s", formula, exc)
        return None


def ols_term_rows(
    fit: Any,
    iqm: str,
    model: str,
    n_obs: int,
    n_subj: int,
    selected_anatomy: list[str],
    vif_map: dict[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ci = fit.conf_int()
    r2 = float(fit.rsquared)
    r2_adj = float(fit.rsquared_adj)
    for name in fit.params.index:
        if name == "Intercept":
            continue
        rows.append(
            {
                "iqm": iqm,
                "family_group": family_group(iqm),
                "model": model,
                "n_obs": n_obs,
                "n_subjects": n_subj,
                "r2": r2,
                "r2_adj": r2_adj,
                "term": name,
                "beta": float(fit.params[name]),
                "se": float(fit.bse[name]),
                "p": float(fit.pvalues[name]),
                "ci_low": float(ci.loc[name, 0]),
                "ci_high": float(ci.loc[name, 1]),
                "vif": vif_map.get(name, float("nan")),
                "anatomy_sensitive_by_construction": bool_str(anatomy_sensitive(iqm)),
                "selected_anatomy": "+".join(selected_anatomy),
            }
        )
    return rows


def exog_vif_from_fit(fit: Any) -> dict[str, float]:
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    exog = np.asarray(fit.model.exog, dtype=float)
    names = list(fit.model.exog_names)
    out: dict[str, float] = {}
    for i, name in enumerate(names):
        if name == "Intercept":
            continue
        try:
            out[name] = float(variance_inflation_factor(exog, i))
        except Exception:
            out[name] = float("nan")
    return out


def incremental_r2(df: pd.DataFrame, iqm: str, full_rhs: str, reduced_rhs: str, stats: dict[str, Any]) -> float:
    full = ols_fit(df, f'Q("{iqm}") ~ {full_rhs}', stats)
    reduced = ols_fit(df, f'Q("{iqm}") ~ {reduced_rhs}', stats)
    if full is None or reduced is None:
        return float("nan")
    return float(full.rsquared) - float(reduced.rsquared)


def classify_variance(r2_a: float, delta: float, r2_c: float) -> str:
    if not math.isfinite(r2_c) or r2_c < 0.10:
        if math.isfinite(delta) and delta >= 0.10:
            return "anatomy-associated"
        if math.isfinite(r2_a) and r2_a >= 0.10:
            return "acquisition-associated"
        return "low-explained-variance"
    if math.isfinite(r2_a) and r2_a >= 0.05 and math.isfinite(delta) and delta >= 0.05:
        return "mixed"
    if math.isfinite(delta) and delta >= 0.10 and (not math.isfinite(r2_a) or delta >= r2_a):
        return "anatomy-associated"
    if math.isfinite(r2_a) and r2_a >= 0.10 and (not math.isfinite(delta) or delta < 0.05):
        return "acquisition-associated"
    if math.isfinite(r2_a) and r2_a >= 0.05 and math.isfinite(delta) and delta >= 0.05:
        return "mixed"
    return "low-explained-variance"


def classify_cohort_shift(
    beta_before: float,
    beta_after: float,
    q_before: float,
    q_after: float,
    attenuation: float,
) -> str:
    sig_b = math.isfinite(q_before) and q_before < FDR_ALPHA
    sig_a = math.isfinite(q_after) and q_after < FDR_ALPHA
    if (not sig_b) and sig_a:
        return "appearing_after_adjustment"
    if math.isfinite(beta_before) and math.isfinite(beta_after) and beta_before * beta_after < 0 and (sig_b or sig_a):
        return "sign_reversed"
    if sig_b and (not sig_a):
        return "attenuated_lost_fdr"
    if sig_b and sig_a and math.isfinite(attenuation) and abs(attenuation) < 0.70:
        return "attenuated_persistent_fdr"
    if sig_b and sig_a:
        return "persistent"
    return "not_fdr_significant"


def fit_mixed_anatomy(
    df: pd.DataFrame,
    iqm: str,
    rhs: str,
    extra_cols: list[str],
    stats: dict[str, Any],
) -> dict[str, Any]:
    smf = stats["smf"]
    needed = ["subject_id", iqm, "cohort", "age", "sex", "session", *extra_cols]
    work = df[needed].copy()
    work[iqm] = to_numeric_iqm(work[iqm])
    work = work.dropna()
    n_obs = int(len(work))
    n_subj = int(work["subject_id"].nunique())
    empty = {
        "iqm": iqm,
        "n_obs": n_obs,
        "n_subjects": n_subj,
        "status": "failed",
        "converged": False,
        "r2_marginal": float("nan"),
        "r2_conditional": float("nan"),
        "cohort_p": float("nan"),
        "glaucoma_coef": float("nan"),
        "glaucoma_p": float("nan"),
        "glaucoma_se": float("nan"),
        "glaucoma_ci_low": float("nan"),
        "glaucoma_ci_high": float("nan"),
        "session_p": float("nan"),
        "interaction_tested": "FALSE",
        "interaction_p": float("nan"),
        "formula": f'Q("{iqm}") ~ {rhs}',
        "anatomy_sensitive_by_construction": bool_str(anatomy_sensitive(iqm)),
    }
    if n_obs < 10 or n_subj < 5:
        empty["status"] = "too_few_rows"
        return empty
    formula = f'Q("{iqm}") ~ {rhs}'
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
        if fit is None:
            raise last_exc if last_exc is not None else RuntimeError("MixedLM produced no fit")
        converged = bool(getattr(fit, "converged", False))
        try:
            re = fit.random_effects
            blup = work["subject_id"].map(lambda s: float(np.asarray(re[s]).reshape(-1)[0]))
            fe_fitted = np.asarray(fit.fittedvalues) - blup.to_numpy(dtype=float)
            r2m, r2c = nakagawa_r2(fit, fe_fitted)
        except Exception:
            r2m, r2c = float("nan"), float("nan")
        _, _, _, c_p = wald_terms(fit, "C(cohort")
        _, _, _, s_p = wald_terms(fit, "C(session")
        glau = term_lookup(fit, "T.Glaucoma")
        empty.update(
            {
                "status": "ok" if converged else "not_converged",
                "converged": converged,
                "r2_marginal": r2m,
                "r2_conditional": r2c,
                "cohort_p": c_p,
                "glaucoma_coef": glau["coef"],
                "glaucoma_p": glau["p"],
                "glaucoma_se": glau["se"],
                "glaucoma_ci_low": glau["ci_low"],
                "glaucoma_ci_high": glau["ci_high"],
                "session_p": s_p,
            }
        )
        return empty
    except Exception as exc:
        LOGGER.warning("mixed %s failed: %s", iqm, exc)
        LOGGER.debug(traceback.format_exc())
        empty["status"] = f"failed: {exc}"
        return empty


def plot_figure_a(var_df: pd.DataFrame, dest: Path) -> None:
    work = var_df.sort_values("delta_R2_anatomy", ascending=False).copy()
    fig, ax = plt.subplots(figsize=(16.0, 6.2))
    x = np.arange(len(work))
    w = 0.40
    ax.bar(x - w / 2, work["R2_A"], width=w, color="#4C78A8", label="R² acquisition (Model A)", zorder=3)
    ax.bar(x + w / 2, work["delta_R2_anatomy"], width=w, color="#54A24B", label="ΔR² anatomy (C−B)", zorder=3)
    ax.set_xticks(x, work["iqm"], rotation=90, fontsize=7)
    ax.set_ylabel("R² / ΔR² (OLS, complete-case anatomy)")
    ax.set_xlabel("IQM")
    ax.set_title("Acquisition vs anatomy explained variance (model-explained, not causal)")
    ax.legend(frameon=False, loc="upper right")
    ax.axhline(0, color="#444444", lw=0.6)
    fig.tight_layout()
    fig.savefig(dest)
    plt.close(fig)


def plot_figure_b(cohort_df: pd.DataFrame, dest: Path) -> None:
    work = cohort_df.copy()
    if "beta_before_std" not in work.columns:
        work["beta_before_std"] = work["beta_before"]
        work["beta_after_std"] = work["beta_after"]
    fig, ax = plt.subplots(figsize=(6.8, 6.6))
    colors = {True: "#E45756", False: "#4C78A8"}
    sensitive = work["anatomy_sensitive_by_construction"].astype(str).str.upper().eq("TRUE")
    for flag, sub in work.groupby(sensitive):
        ax.scatter(
            sub["beta_before_std"],
            sub["beta_after_std"],
            s=42,
            c=colors[bool(flag)],
            label="anatomy-sensitive by construction" if flag else "not tissue/mask IQM by definition",
            edgecolors="white",
            linewidths=0.4,
            zorder=3,
        )
    vals = pd.concat([work["beta_before_std"], work["beta_after_std"]], ignore_index=True)
    finite = vals[np.isfinite(vals.to_numpy(dtype=float))]
    lim = float(np.nanmax(np.abs(finite))) * 1.12 if len(finite) else 1.0
    ax.plot([-lim, lim], [-lim, lim], color="#888888", lw=0.8, ls="--", label="no change")
    ax.axhline(0, color="#bbbbbb", lw=0.6)
    ax.axvline(0, color="#bbbbbb", lw=0.6)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_xlabel("Glaucoma vs Control β / SD(IQM) before anatomy")
    ax.set_ylabel("Glaucoma vs Control β / SD(IQM) after anatomy")
    ax.set_title("Cohort effect before vs after anatomical adjustment")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    labeled = work.loc[
        work["cohort_shift_class"].isin(
            {"persistent", "attenuated_lost_fdr", "attenuated_persistent_fdr", "appearing_after_adjustment"}
        )
    ]
    for rec in labeled.itertuples(index=False):
        ax.annotate(
            rec.iqm,
            (rec.beta_before_std, rec.beta_after_std),
            fontsize=6,
            xytext=(3, 3),
            textcoords="offset points",
        )
    fig.tight_layout()
    fig.savefig(dest)
    plt.close(fig)


def plot_figure_c(heat: pd.DataFrame, dest: Path) -> None:
    order = sorted(heat["iqm"].tolist(), key=lambda x: (FAMILY_GROUP_ORDER.index(family_group(x)), x))
    cols = ["R2_Acquisition", "R2_AgeSex", "R2_Anatomy", "R2_Cohort"]
    mat = heat.set_index("iqm").loc[order, cols].to_numpy(dtype=float)
    fig_h = max(10.0, 0.22 * len(order) + 1.8)
    fig, ax = plt.subplots(figsize=(6.4, fig_h))
    vmax = max(0.25, float(np.nanmax(np.abs(mat))))
    im = ax.imshow(mat, cmap="viridis", vmin=0.0, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(cols)), ["Acquisition", "Age/Sex", "Anatomy", "Cohort"], fontsize=8)
    ax.set_yticks(range(len(order)), [f"{n}  [{family_group(n)}]" for n in order], fontsize=7)
    ax.set_title("Incremental R² by predictor family (OLS; not causal)")
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            val = mat[i, j]
            if np.isfinite(val):
                ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=6, color="white" if val > 0.45 * vmax else "black")
    fig.colorbar(im, ax=ax, fraction=0.04, pad=0.04, label="incremental R²")
    fig.subplots_adjust(left=0.46, right=0.96, top=0.96, bottom=0.04)
    fig.savefig(dest)
    plt.close(fig)


def append_summary_txt(path: Path, block: str) -> None:
    require_file(path, "robustness summary")
    text = path.read_text(encoding="utf-8")
    marker = f"\n10. {SUMMARY_SECTION_TITLE}\n"
    alt = f"\n{SUMMARY_SECTION_TITLE}\n"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    elif "\n10. " in text and SUMMARY_SECTION_TITLE in text:
        idx = text.find("\n10. ")
        text = text[:idx].rstrip() + "\n"
    text = text.rstrip() + "\n" + block
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def run_models(
    joined: pd.DataFrame,
    iqms: list[str],
    selected_anatomy: list[str],
    dropped_anatomy: list[str],
    stats: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    work = joined.copy()
    work["subject_id"] = work["subject_id"].astype(str)
    work["session"] = work["session"].astype(str)
    work["cohort"] = work["cohort"].astype(str)
    work["sex"] = work["sex"].astype(str)
    for col in iqms + selected_anatomy + ["age"]:
        work[col] = to_numeric_iqm(work[col]) if col in iqms else pd.to_numeric(work[col], errors="coerce")

    model_df = work.dropna(subset=selected_anatomy + ["age", "sex", "software_platform", "cohort"]).copy()
    n_model = len(model_df)
    n_subj = int(model_df["subject_id"].nunique())
    LOGGER.info("Complete-case modelling n_obs=%s n_subjects=%s anatomy=%s", n_model, n_subj, selected_anatomy)
    if n_model != EXPECTED_PHYSICAL_N:
        LOGGER.info("Complete-case n differs from 133 because of missing FreeSurfer anatomy.")

    acq = f'C(software_platform, Treatment("{REF_SOFTWARE}"))'
    cov = "age + C(sex)"
    anatomy_rhs = " + ".join(selected_anatomy)
    rhs_a = f"{acq} + {cov}"
    rhs_b = f"{rhs_a} + {anatomy_rhs}"
    rhs_m1 = f'C(cohort, Treatment("{REF_COHORT}")) + {rhs_a}'
    rhs_m2 = f'C(cohort, Treatment("{REF_COHORT}")) + {rhs_b}'
    rhs_var_a = acq
    rhs_var_b = rhs_a
    rhs_var_c = rhs_b
    rhs_agesex = cov
    rhs_cohort_inc = rhs_m2

    model_rows: list[dict[str, Any]] = []
    cohort_rows: list[dict[str, Any]] = []
    var_rows: list[dict[str, Any]] = []
    heat_rows: list[dict[str, Any]] = []
    long_rows: list[dict[str, Any]] = []

    both = model_df.groupby(["cohort", "subject_id"])["session"].nunique().reset_index()
    n_long = both.loc[both["session"] >= 2].groupby("cohort").size().to_dict()
    LOGGER.info("Longitudinal subjects in complete-case data: %s", n_long)
    interaction_ok = int(n_long.get("Control", 0)) >= 10 and int(n_long.get("Glaucoma", 0)) >= 10
    mixed_rhs = f'C(cohort, Treatment("{REF_COHORT}")) + C(session) + age + C(sex) + {anatomy_rhs}'

    for iqm in iqms:
        sub = model_df.dropna(subset=[iqm]).copy()
        n_obs = len(sub)
        n_s = int(sub["subject_id"].nunique())
        fit_a = ols_fit(sub, f'Q("{iqm}") ~ {rhs_a}', stats)
        fit_b = ols_fit(sub, f'Q("{iqm}") ~ {rhs_b}', stats)
        fit_m1 = ols_fit(sub, f'Q("{iqm}") ~ {rhs_m1}', stats)
        fit_m2 = ols_fit(sub, f'Q("{iqm}") ~ {rhs_m2}', stats)
        fit_va = ols_fit(sub, f'Q("{iqm}") ~ {rhs_var_a}', stats)
        fit_vb = ols_fit(sub, f'Q("{iqm}") ~ {rhs_var_b}', stats)
        fit_vc = ols_fit(sub, f'Q("{iqm}") ~ {rhs_var_c}', stats)

        vif_a = exog_vif_from_fit(fit_a) if fit_a is not None else {}
        vif_b = exog_vif_from_fit(fit_b) if fit_b is not None else {}
        if fit_a is not None:
            model_rows.extend(ols_term_rows(fit_a, iqm, "A_acquisition_age_sex", n_obs, n_s, selected_anatomy, vif_a))
        if fit_b is not None:
            model_rows.extend(ols_term_rows(fit_b, iqm, "B_acquisition_age_sex_anatomy", n_obs, n_s, selected_anatomy, vif_b))

        def glau_pack(fit: Any | None) -> dict[str, float]:
            out = {k: float("nan") for k in ("beta", "se", "p", "ci_low", "ci_high", "r2")}
            if fit is None:
                return out
            names = [n for n in fit.params.index if "T.Glaucoma" in str(n)]
            if not names:
                out["r2"] = float(fit.rsquared)
                return out
            name = names[0]
            ci = fit.conf_int()
            out.update(
                {
                    "beta": float(fit.params[name]),
                    "se": float(fit.bse[name]),
                    "p": float(fit.pvalues[name]),
                    "ci_low": float(ci.loc[name, 0]),
                    "ci_high": float(ci.loc[name, 1]),
                    "r2": float(fit.rsquared),
                }
            )
            return out

        before = glau_pack(fit_m1)
        after = glau_pack(fit_m2)
        att = (
            after["beta"] / before["beta"]
            if math.isfinite(before["beta"]) and math.isfinite(after["beta"]) and before["beta"] != 0
            else float("nan")
        )
        iqm_sd = float(sub[iqm].std(ddof=1)) if n_obs > 1 else float("nan")
        std_before = before["beta"] / iqm_sd if math.isfinite(iqm_sd) and iqm_sd > 0 else float("nan")
        std_after = after["beta"] / iqm_sd if math.isfinite(iqm_sd) and iqm_sd > 0 else float("nan")
        cohort_rows.append(
            {
                "iqm": iqm,
                "family_group": family_group(iqm),
                "n_obs": n_obs,
                "n_subjects": n_s,
                "iqm_sd": iqm_sd,
                "beta_before": before["beta"],
                "beta_before_std": std_before,
                "se_before": before["se"],
                "p_before": before["p"],
                "ci_low_before": before["ci_low"],
                "ci_high_before": before["ci_high"],
                "r2_before": before["r2"],
                "beta_after": after["beta"],
                "beta_after_std": std_after,
                "se_after": after["se"],
                "p_after": after["p"],
                "ci_low_after": after["ci_low"],
                "ci_high_after": after["ci_high"],
                "r2_after": after["r2"],
                "effect_attenuation": att,
                "anatomy_sensitive_by_construction": bool_str(anatomy_sensitive(iqm)),
                "selected_anatomy": "+".join(selected_anatomy),
            }
        )

        r2_a = float(fit_va.rsquared) if fit_va is not None else float("nan")
        r2_b = float(fit_vb.rsquared) if fit_vb is not None else float("nan")
        r2_c = float(fit_vc.rsquared) if fit_vc is not None else float("nan")
        delta = r2_c - r2_b if math.isfinite(r2_c) and math.isfinite(r2_b) else float("nan")
        var_rows.append(
            {
                "iqm": iqm,
                "family_group": family_group(iqm),
                "n_obs": n_obs,
                "R2_A": r2_a,
                "R2_B": r2_b,
                "R2_C": r2_c,
                "delta_R2_anatomy": delta,
                "variance_class": classify_variance(r2_a, delta, r2_c),
                "anatomy_sensitive_by_construction": bool_str(anatomy_sensitive(iqm)),
                "selected_anatomy": "+".join(selected_anatomy),
            }
        )
        r2_acq_u = incremental_r2(sub, iqm, rhs_a, rhs_agesex, stats)
        r2_demo_u = incremental_r2(sub, iqm, rhs_a, rhs_var_a, stats)
        r2_anat_u = delta
        r2_coh_u = incremental_r2(sub, iqm, rhs_cohort_inc, rhs_b, stats)
        heat_rows.append(
            {
                "iqm": iqm,
                "R2_Acquisition": r2_acq_u,
                "R2_AgeSex": r2_demo_u,
                "R2_Anatomy": r2_anat_u,
                "R2_Cohort": r2_coh_u,
            }
        )

        mixed = fit_mixed_anatomy(sub, iqm, mixed_rhs, selected_anatomy, stats)
        mixed["interaction_tested"] = "TRUE" if interaction_ok else "FALSE"
        mixed["interaction_reason"] = (
            "Control and Glaucoma each have ≥10 longitudinal subjects"
            if interaction_ok
            else (
                f"not tested: longitudinal n by cohort={n_long}; "
                "Data_ON and Data_TON are too small; Glaucoma returners < 10"
            )
        )
        mixed["n_longitudinal_control"] = int(n_long.get("Control", 0))
        mixed["n_longitudinal_glaucoma"] = int(n_long.get("Glaucoma", 0))
        mixed["n_longitudinal_data_on"] = int(n_long.get("Data_ON", 0))
        mixed["n_longitudinal_data_ton"] = int(n_long.get("Data_TON", 0))
        mixed["selected_anatomy"] = "+".join(selected_anatomy)
        long_rows.append(mixed)

    models = pd.DataFrame(model_rows)
    cohort = pd.DataFrame(cohort_rows)
    var_df = pd.DataFrame(var_rows)
    heat = pd.DataFrame(heat_rows)
    long_df = pd.DataFrame(long_rows)

    mt = stats["multipletests"]
    if not models.empty:
        models["fdr_q"] = np.nan
        for (model_name, term), idx in models.groupby(["model", "term"]).groups.items():
            pvals = models.loc[idx, "p"].tolist()
            models.loc[idx, "fdr_q"] = fdr_bh(pvals, mt)
    if not cohort.empty:
        cohort["q_before"] = fdr_bh(cohort["p_before"].tolist(), mt)
        cohort["q_after"] = fdr_bh(cohort["p_after"].tolist(), mt)
        cohort["cohort_shift_class"] = [
            classify_cohort_shift(b, a, qb, qa, att)
            for b, a, qb, qa, att in zip(
                cohort["beta_before"],
                cohort["beta_after"],
                cohort["q_before"],
                cohort["q_after"],
                cohort["effect_attenuation"],
            )
        ]
    if not long_df.empty:
        long_df["cohort_q"] = fdr_bh(long_df["cohort_p"].tolist(), mt)
        long_df["glaucoma_q"] = fdr_bh(long_df["glaucoma_p"].tolist(), mt)

    extra = {
        "n_model_obs": n_model,
        "n_model_subjects": n_subj,
        "n_long": n_long,
        "dropped_anatomy": dropped_anatomy,
        "interaction_ok": interaction_ok,
    }
    return {
        "models": models,
        "cohort": cohort,
        "var": var_df,
        "heat": heat,
        "long": long_df,
        "extra": extra,  # type: ignore[dict-item]
    }


def write_markdown(
    path: Path,
    counts: dict[str, Any],
    selected_anatomy: list[str],
    dropped_anatomy: list[str],
    var_df: pd.DataFrame,
    cohort: pd.DataFrame,
    joined: pd.DataFrame,
) -> None:
    n_fs = int((joined["FS_success"] == "TRUE").sum())
    n_missing = int((joined["FS_success"] != "TRUE").sum())
    miss_rate = {
        col: float(joined[col].isna().mean()) for col in ANATOMY_VALUE_COLUMNS if col in joined.columns
    }
    anatomy_assoc = var_df.loc[var_df["variance_class"] == "anatomy-associated", "iqm"].tolist()
    acq_assoc = var_df.loc[var_df["variance_class"] == "acquisition-associated", "iqm"].tolist()
    mixed = var_df.loc[var_df["variance_class"] == "mixed", "iqm"].tolist()
    low = var_df.loc[var_df["variance_class"] == "low-explained-variance", "iqm"].tolist()
    top_anat = var_df.sort_values("delta_R2_anatomy", ascending=False).head(8)
    top_acq = var_df.sort_values("R2_A", ascending=False).head(8)
    att = cohort.loc[cohort["cohort_shift_class"].isin(["attenuated_lost_fdr", "attenuated_persistent_fdr"]), "iqm"].tolist()
    pers = cohort.loc[cohort["cohort_shift_class"] == "persistent", "iqm"].tolist()
    appear = cohort.loc[cohort["cohort_shift_class"] == "appearing_after_adjustment", "iqm"].tolist()
    lines = [
        "# FreeSurfer anatomical integration",
        "",
        f"generated_utc: {datetime.now(timezone.utc).isoformat()}",
        "FreeSurfer version: 7.4.1 (fs_t1w_mpr / derivatives/freesurfer).",
        "HCP-FS 6.0.1 was not used.",
        "Canonical MRIQC table was not modified.",
        "",
        "## Counts before models",
        f"- N MRIQC physical acquisitions: {counts['n_mriqc']}",
        f"- N MRIQC subjects: {counts['n_mriqc_subjects']}",
        f"- N MRIQC subject×session cells: {counts['n_mriqc_sessions']}",
        f"- N FreeSurfer subject×session rows: {counts['n_fs_rows']}",
        f"- N FreeSurfer complete (aseg+aparc, 7.4.1): {counts['n_fs_success']}",
        f"- N subject×session matches MRIQC∩manifest: {counts['n_matches']}",
        f"- Duplicate physical_acquisition_id after JOIN: {counts['n_dup_phys']}",
        f"- JOIN rows: {counts['n_join']} (must be 133)",
        f"- JOIN rows with FreeSurfer anatomy: {n_fs} (131 complete sessions; sub-043 ses-02 has 2 physical acquisitions)",
        f"- JOIN rows without FreeSurfer: {n_missing} (sub-019 ses-01 recon-all failed)",
        "",
        "## Anatomical variables",
        "Primary candidates: ICV (eTIV), total cortical GM (CortexVol), total WM",
        "(CerebralWhiteMatterVol), mean cortical thickness.",
        f"Selected after VIF (threshold {VIF_DROP_THRESHOLD:g}): {', '.join(selected_anatomy) if selected_anatomy else 'none'}",
        f"Dropped for collinearity: {', '.join(dropped_anatomy) if dropped_anatomy else 'none'}",
        "Hippocampal volumes and FreeSurfer CSF (SegId 24) were extracted and not",
        "entered in the primary model.",
        "",
        "Missingness on the 133-row JOIN:",
    ]
    for col, rate in miss_rate.items():
        lines.append(f"- {col}: {rate:.3f}")
    lines += [
        "",
        "## Variance classes (OLS R²; not causal, not 'pure biology')",
        f"- anatomy-associated: {len(anatomy_assoc)}  {', '.join(anatomy_assoc) if anatomy_assoc else 'none'}",
        f"- acquisition-associated: {len(acq_assoc)}  {', '.join(acq_assoc) if acq_assoc else 'none'}",
        f"- mixed: {len(mixed)}  {', '.join(mixed) if mixed else 'none'}",
        f"- low-explained-variance: {len(low)}",
        "",
        "Largest ΔR² anatomy:",
    ]
    for rec in top_anat.itertuples(index=False):
        lines.append(f"- {rec.iqm}: ΔR²={rec.delta_R2_anatomy:.3f}  R2_A={rec.R2_A:.3f}  class={rec.variance_class}")
    lines.append("")
    lines.append("Largest R² acquisition (Model A):")
    for rec in top_acq.itertuples(index=False):
        lines.append(f"- {rec.iqm}: R2_A={rec.R2_A:.3f}  ΔR² anatomy={rec.delta_R2_anatomy:.3f}")
    lines += [
        "",
        "## Cohort association (Glaucoma vs Control)",
        "Wording: the cohort association was attenuated after anatomical adjustment.",
        "Do not read this as 'biology caused the IQM difference'.",
        f"- persistent after anatomy (FDR): {', '.join(pers) if pers else 'none'}",
        f"- attenuated after anatomy: {', '.join(att) if att else 'none'}",
        f"- appearing after anatomy: {', '.join(appear) if appear else 'none'}",
        "",
        "## Circularity",
        "IQM whose MRIQC definition uses tissue segmentation, a brain mask, or",
        "GM/WM/CSF estimates are flagged anatomy_sensitive_by_construction=TRUE.",
        "rpve_*, icvs_* and tissue intensity summaries are anatomy-sensitive by",
        "construction; their ΔR² is not independent biological evidence.",
        "",
        "## Limitations",
        "- FreeSurfer-derived anatomy is not an independent ground truth of biology.",
        "- Some MRIQC IQMs are themselves dependent on tissue segmentation/brain masks.",
        "- Cohorts are unbalanced.",
        "- Data_ON and Data_TON are small.",
        "- Scanner platform effect E11 vs XA30 is based on only n=6 XA30 acquisitions.",
        "- Cross-sectional anatomical adjustment cannot establish causality.",
        "- Missing FreeSurfer outputs reduce the analytical sample if applicable.",
        "- OLS R² ignores repeated sessions within subject; MixedLM is a sensitivity check only.",
        "",
        "## Files",
        "- study/qc_reports/mriqc_iqm/freesurfer_integration_audit.tsv",
        "- study/metadata/freesurfer_anatomical_summary.tsv",
        "- study/qc_reports/mriqc_iqm/freesurfer_qc_summary.tsv",
        "- study/metadata/mriqc_iqm_physical_acquisition_freesurfer.tsv",
        "- study/qc_reports/mriqc_iqm/anatomical_adjustment_models.tsv",
        "- study/qc_reports/mriqc_iqm/cohort_effect_anatomical_adjustment.tsv",
        "- study/qc_reports/mriqc_iqm/anatomical_variance_decomposition.tsv",
        "- study/qc_reports/mriqc_iqm/longitudinal_anatomical_adjustment.tsv",
        "- study/qc_reports/mriqc_iqm/figure_anatomical_variance.pdf",
        "- study/qc_reports/mriqc_iqm/figure_cohort_anatomical_adjustment.pdf",
        "- study/qc_reports/mriqc_iqm/figure_iqm_predictor_heatmap.pdf",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def txt_block(counts: dict[str, Any], selected: list[str], dropped: list[str], var_df: pd.DataFrame, cohort: pd.DataFrame) -> str:
    anatomy_assoc = var_df.loc[var_df["variance_class"] == "anatomy-associated", "iqm"].tolist()
    acq_assoc = var_df.loc[var_df["variance_class"] == "acquisition-associated", "iqm"].tolist()
    att = cohort.loc[cohort["cohort_shift_class"].isin(["attenuated_lost_fdr", "attenuated_persistent_fdr"]), "iqm"].tolist()
    pers = cohort.loc[cohort["cohort_shift_class"] == "persistent", "iqm"].tolist()
    top_anat = ", ".join(
        f"{r.iqm} (ΔR²={r.delta_R2_anatomy:.3f})"
        for r in var_df.sort_values("delta_R2_anatomy", ascending=False).head(5).itertuples(index=False)
    )
    top_acq = ", ".join(
        f"{r.iqm} (R2_A={r.R2_A:.3f})"
        for r in var_df.sort_values("R2_A", ascending=False).head(5).itertuples(index=False)
    )
    return f"""
10. {SUMMARY_SECTION_TITLE}
  N MRIQC physical acquisitions: {counts['n_mriqc']}
  N JOIN rows with FreeSurfer anatomy: {counts['n_join_fs']} (131 complete sessions + extra physical acq)
  N MRIQC rows without FreeSurfer: {counts['n_join_missing_fs']} (sub-019 ses-01)
  IQMs analysed: 56 T1w IQMs retained in the physical-acquisition robustness set.
  Anatomical variables extracted: eTIV, BrainSegVol, CortexVol, CerebralWhiteMatterVol,
    aseg CSF (SegId 24), mean cortical thickness, left/right hippocampus.
  Primary model anatomy after VIF: {', '.join(selected) if selected else 'none'}
  Dropped for collinearity: {', '.join(dropped) if dropped else 'none'}
  Most anatomy-associated (ΔR²): {top_anat}
  Most acquisition-associated (R² Model A): {top_acq}
  Variance class anatomy-associated: {', '.join(anatomy_assoc) if anatomy_assoc else 'none'}
  Variance class acquisition-associated: {', '.join(acq_assoc) if acq_assoc else 'none'}
  Cohort effects attenuated after anatomy: {', '.join(att) if att else 'none'}
  Cohort effects persisting after anatomy: {', '.join(pers) if pers else 'none'}
  Limitations: FreeSurfer anatomy is not independent biological ground truth;
    some IQMs are anatomy-sensitive by construction; cohorts unbalanced;
    Data_ON/Data_TON small; XA30 n=6; no causality; missing FS reduces n if present.
""".rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    before = snapshot_all(args.study_root)
    canonical = args.study_root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    sha = file_sha256(canonical)
    if sha != CANONICAL_SHA256:
        fail(f"Canonical MRIQC table hash changed: {sha} (expected {CANONICAL_SHA256})")
    reject_forbidden_subjects_dir(args.subjects_dir)
    require_file(args.subjects_dir / "dataset_description.json", "FreeSurfer dataset_description")

    stats = import_stats()
    if not stats["ok"]:
        fail("scipy+statsmodels required: " + "; ".join(stats["missing"]))

    iqms = load_t1w_iqm_names(args.loadings)
    mriqc = load_physical_acquisition_table(args.phys, iqms)
    manifest = load_manifest(args.manifest)

    n_mriqc = len(mriqc)
    n_mriqc_subjects = int(mriqc["subject_id"].nunique())
    n_mriqc_sessions = int(mriqc.groupby(["subject_id", "session"]).ngroups)
    print(f"1. N MRIQC rows: {n_mriqc}")
    print(f"   N MRIQC subjects: {n_mriqc_subjects}")
    print(f"   N MRIQC subject×session: {n_mriqc_sessions}")

    audit, summary = audit_and_extract(mriqc, manifest, args.subjects_dir)
    n_fs_rows = len(summary)
    n_fs_success = int((summary["FS_success"] == "TRUE").sum())
    n_matches = int(len(set(zip(mriqc["subject_id"], mriqc["session"])) & set(zip(summary["subject_id"], summary["session"]))))
    print(f"2. N FreeSurfer subject×session rows: {n_fs_rows}")
    print(f"   N FreeSurfer complete: {n_fs_success}")
    print(f"3. N subject/session correspondences: {n_matches}")
    n_dup_fs = int(summary.duplicated(["subject_id", "session"]).sum())
    print(f"4. Duplicate subject/session in anatomy table: {n_dup_fs}")
    if n_dup_fs:
        fail("STOP: duplicate subject/session in FreeSurfer anatomy table.")

    args.out_audit.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(args.out_audit, sep="\t", index=False)
    summary.to_csv(args.out_summary, sep="\t", index=False)
    qc = qc_summary(summary)
    qc.to_csv(args.out_qc, sep="\t", index=False)
    mapping = pd.DataFrame(VARIABLE_MAPPING)
    mapping.to_csv(args.out_mapping, sep="\t", index=False)

    joined = left_join_mriqc(mriqc, summary)
    n_join = len(joined)
    n_join_fs = int((joined["FS_success"] == "TRUE").sum())
    n_join_missing = n_join - n_join_fs
    n_dup_phys = int(joined.duplicated(["physical_acquisition_id"]).sum())
    print(f"5. N JOIN rows: {n_join}")
    print(f"   N with FreeSurfer: {n_join_fs}")
    print(f"   N without FreeSurfer: {n_join_missing}")
    print(f"   Duplicate physical_acquisition_id: {n_dup_phys}")
    if n_join != EXPECTED_PHYSICAL_N:
        fail("STOP: JOIN row count is not 133.")
    joined.to_csv(args.out_join, sep="\t", index=False)

    selected, vif_sel, dropped = select_anatomy_terms(joined)
    LOGGER.info("Selected anatomy %s  VIF=%s  dropped=%s", selected, vif_sel, dropped)
    if not selected:
        fail("No anatomical variables remained after VIF filtering.")
    mapping["used_in_primary_model"] = [
        "TRUE" if row.column in selected else "FALSE" for row in mapping.itertuples(index=False)
    ]
    mapping.to_csv(args.out_mapping, sep="\t", index=False)

    results = run_models(joined, iqms, selected, dropped, stats)
    results["models"].to_csv(args.out_models, sep="\t", index=False)
    results["cohort"].to_csv(args.out_cohort, sep="\t", index=False)
    results["var"].to_csv(args.out_var, sep="\t", index=False)
    results["long"].to_csv(args.out_long, sep="\t", index=False)

    plot_figure_a(results["var"], args.fig_a)
    plot_figure_b(results["cohort"], args.fig_b)
    plot_figure_c(results["heat"], args.fig_c)

    counts = {
        "n_mriqc": n_mriqc,
        "n_mriqc_subjects": n_mriqc_subjects,
        "n_mriqc_sessions": n_mriqc_sessions,
        "n_fs_rows": n_fs_rows,
        "n_fs_success": n_fs_success,
        "n_matches": n_matches,
        "n_dup_phys": n_dup_phys,
        "n_join": n_join,
        "n_join_fs": n_join_fs,
        "n_join_missing_fs": n_join_missing,
    }
    write_markdown(args.out_md, counts, selected, dropped, results["var"], results["cohort"], joined)
    append_summary_txt(args.out_txt, txt_block(counts, selected, dropped, results["var"], results["cohort"]))

    assert_unmodified(before)
    if file_sha256(canonical) != CANONICAL_SHA256:
        fail("Canonical MRIQC table was modified; this is not allowed.")

    print(f"Wrote {args.out_audit}")
    print(f"Wrote {args.out_summary}")
    print(f"Wrote {args.out_qc}")
    print(f"Wrote {args.out_join}")
    print(f"Wrote {args.out_models}")
    print(f"Wrote {args.out_cohort}")
    print(f"Wrote {args.out_var}")
    print(f"Wrote {args.out_long}")
    print(f"Wrote {args.fig_a}")
    print(f"Wrote {args.fig_b}")
    print(f"Wrote {args.fig_c}")
    print(f"Wrote {args.out_md}")
    print(f"Updated {args.out_txt} (appended section only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
