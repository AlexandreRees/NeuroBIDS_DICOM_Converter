#!/usr/bin/env python3
"""Shared helpers for the physical-acquisition MRIQC reanalysis branch.

Selection of which reconstruction to keep never inspects IQM values.
Existing clean/PCA/cohort/longitudinal files are read-only.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from mriqc_iqm_lib import fail, require_file

LOGGER = logging.getLogger("mriqc_iqm.physical_acq")

PROTECTED_RELATIVE = (
    "metadata/mriqc_iqm_clean.tsv",
    "qc_reports/mriqc_iqm/pca_T1w_scores.tsv",
    "qc_reports/mriqc_iqm/pca_T1w_loadings.tsv",
    "qc_reports/mriqc_iqm/pca_T1w_variance.tsv",
    "qc_reports/mriqc_iqm/pca_cohort_results.tsv",
    "qc_reports/mriqc_iqm/longitudinal_results.tsv",
    "qc_reports/mriqc_iqm/t1w_reconstruction_audit.tsv",
)

EXPECTED_PHYSICAL_N = 133
N_T1W_USABLE = 56
REF_COHORT = "Control"
REF_SOFTWARE = "E11"
FDR_ALPHA = 0.05
SCANNER_TO_SOFTWARE = {
    "Prisma": "E11",
    "MAGNETOM Prisma": "XA30",
}
# Conventional MRIQC anatomical quality metrics (user examples: SNR, CNR,
# FBER, EFC, FWHM, CJV) mapped onto the existing family taxonomy.
CORE_QUALITY_FAMILIES = (
    "signal / SNR",
    "contrast",
    "entropy / information",
    "smoothness / sharpness",
)
# Segmentation / partial-volume / tissue-distribution families.
TISSUE_SENSITIVE_FAMILIES = (
    "morphology / tissue",
    "intensity",
)
FAMILY_GROUP_ORDER = [
    "signal / SNR",
    "contrast",
    "intensity",
    "homogeneity / bias field",
    "artifact",
    "entropy / information",
    "morphology / tissue",
    "smoothness / sharpness",
    "other",
]
FAMILY_COLORS = {
    "signal / SNR": "#4C78A8",
    "contrast": "#F58518",
    "intensity": "#54A24B",
    "homogeneity / bias field": "#E45756",
    "artifact": "#B279A2",
    "entropy / information": "#72B7B2",
    "morphology / tissue": "#FF9DA6",
    "smoothness / sharpness": "#9D755D",
    "other": "#BAB0AC",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_protected(study_root: Path) -> dict[Path, str]:
    out: dict[Path, str] = {}
    for rel in PROTECTED_RELATIVE:
        path = study_root / rel
        if not path.is_file():
            LOGGER.warning("Protected file not found (skipped): %s", path)
            continue
        out[path] = file_sha256(path)
    return out


def assert_unmodified(before: dict[Path, str]) -> None:
    for path, expected in before.items():
        current = file_sha256(path)
        if current != expected:
            fail(f"Protected file changed during the run: {path}")


def family_group(iqm: str) -> str:
    if iqm.startswith("snrd_") or iqm.startswith("snr_"):
        return "signal / SNR"
    if iqm in {"cjv", "cnr"}:
        return "contrast"
    if iqm.startswith("inu_"):
        return "homogeneity / bias field"
    if iqm.startswith("qi_"):
        return "artifact"
    if iqm in {"efc", "fber"}:
        return "entropy / information"
    if iqm.startswith("fwhm_"):
        return "smoothness / sharpness"
    if iqm.startswith(("icvs_", "rpve_", "tpm_overlap_")):
        return "morphology / tissue"
    if iqm.startswith("summary_") or iqm == "wm2max":
        return "intensity"
    return "other"


def is_core_quality(iqm: str) -> bool:
    return family_group(iqm) in CORE_QUALITY_FAMILIES


def is_tissue_sensitive(iqm: str) -> bool:
    return family_group(iqm) in TISSUE_SENSITIVE_FAMILIES


def iqm_subsets(iqms: Iterable[str]) -> dict[str, list[str]]:
    names = [str(x) for x in iqms]
    return {
        "FULL_56": list(names),
        "CORE_QUALITY": [n for n in names if is_core_quality(n)],
        "TISSUE_SENSITIVE": [n for n in names if is_tissue_sensitive(n)],
    }


def software_platform_from_scanner(series: pd.Series) -> pd.Series:
    mapped = series.astype(str).str.strip().map(SCANNER_TO_SOFTWARE)
    unknown = series.loc[mapped.isna() & series.notna()]
    if len(unknown):
        fail(f"Unmapped scanner values for software_platform: {sorted(set(unknown.astype(str)))}")
    return mapped


def load_t1w_iqm_names(loadings_path: Path) -> list[str]:
    require_file(loadings_path, "T1w IQM loadings table")
    df = pd.read_csv(loadings_path, sep="\t")
    if "iqm" not in df.columns:
        fail(f"{loadings_path} is missing column iqm.")
    names = df["iqm"].astype(str).tolist()
    if len(names) != N_T1W_USABLE:
        fail(f"Expected {N_T1W_USABLE} IQMs in {loadings_path}, found {len(names)}.")
    return names


def load_physical_acquisition_table(path: Path, iqm_names: Iterable[str]) -> pd.DataFrame:
    require_file(path, "physical-acquisition IQM table")
    df = pd.read_csv(path, sep="\t")
    if len(df) != EXPECTED_PHYSICAL_N:
        fail(f"Expected {EXPECTED_PHYSICAL_N} physical-acquisition rows, found {len(df)}.")
    need = ["subject_id", "session", "cohort", "age", "sex", "scanner"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        fail(f"Physical-acquisition table missing columns: {missing}")
    iqms = list(iqm_names)
    missing_iqm = [c for c in iqms if c not in df.columns]
    if missing_iqm:
        fail(f"Physical-acquisition table missing IQMs: {missing_iqm}")
    out = df.copy()
    out["software_platform"] = software_platform_from_scanner(out["scanner"])
    out["cohort"] = out["cohort"].astype(str)
    out["session"] = out["session"].astype(str)
    out["sex"] = out["sex"].astype(str)
    out["age"] = pd.to_numeric(out["age"], errors="coerce")
    if out["age"].isna().any() or out["software_platform"].isna().any():
        fail("Missing age or software_platform after loading the physical-acquisition table.")
    extra = sorted(set(out["cohort"]) - {"Control", "Glaucoma", "Data_ON", "Data_TON"})
    if extra:
        fail(f"Unexpected cohorts: {extra}")
    return out


def fingerprint(row: pd.Series) -> tuple[Any, str]:
    """Acquisition identity from sidecar/DICOM, never from IQMs."""
    try:
        sar_f = float(row["SAR"])
        sar = None if sar_f != sar_f else round(sar_f, 6)
    except (TypeError, ValueError):
        sar = None
    shim = str(row.get("ShimSetting") or "").strip()
    if shim.lower() in {"", "nan", "none"}:
        shim = ""
    return (sar, shim)


def _sort_recon_priority(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["_series"] = pd.to_numeric(out.get("SeriesNumber"), errors="coerce")
    out["_run"] = pd.to_numeric(out.get("run"), errors="coerce")
    return out.sort_values(["_series", "_run"], ascending=[False, False], kind="mergesort")


def select_reconstruction(cluster: pd.DataFrame) -> tuple[pd.Series, str]:
    """Deterministic reconstruction pick. Does not look at IQM values."""
    if cluster.empty:
        fail("Empty reconstruction cluster.")
    work = cluster.copy()
    work["NORM_status"] = work["NORM_status"].astype(str)
    work["SeriesDescription"] = work["SeriesDescription"].astype(str)

    if (work["NORM_status"] == "NORM").any():
        chosen = work.loc[work["NORM_status"] == "NORM"]
        rule = "prefer_NORM"
    elif set(work["SeriesDescription"]) >= {"T1w_MPR", "T1w_MPR_ND"}:
        chosen = work.loc[work["SeriesDescription"] == "T1w_MPR"]
        rule = "prefer_SeriesDescription_T1w_MPR_over_T1w_MPR_ND"
    else:
        chosen = work
        rule = "prefer_higher_SeriesNumber_then_run"

    chosen = _sort_recon_priority(chosen)
    if len(chosen) > 1:
        if rule == "prefer_NORM":
            rule = "prefer_NORM_then_higher_SeriesNumber_then_run"
        elif rule.startswith("prefer_SeriesDescription"):
            rule = rule + "_then_higher_SeriesNumber_then_run"
        chosen = chosen.iloc[[0]]
    return chosen.iloc[0], rule


def study_root_default(script_path: Path) -> Path:
    root = script_path.resolve().parent.parent
    if not (root / "metadata").is_dir() or not (root / "qc_reports").is_dir():
        fail(
            f"Cannot resolve study root from {script_path}. "
            "Pass --study-root explicitly."
        )
    return root
