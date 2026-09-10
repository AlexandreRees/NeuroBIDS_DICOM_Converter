#!/usr/bin/env python3
"""Session-level T1w IQM sensitivity to BIDS/JSON acquisition parameters.

Uses the FreeSurfer-selected session-level T1w table (one run per
subject × session) plus packaged BIDS sidecars. Does not modify existing
files, does not rerun MRIQC or PCA, does not run FreeSurfer, and does
not remove outliers.

An association with an acquisition parameter is IQM sensitivity to that
acquisition/reconstruction characteristic, not a quality grade.

Requires scipy + statsmodels. On Narval:
  module load scipy-stack/2025a

Example:
  python code/mriqc_iqm_acquisition_analysis.py
  python code/mriqc_iqm_acquisition_analysis.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
import traceback
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import (  # noqa: E402
    fail,
    is_norm_image_type,
    read_json,
    require_columns,
    require_file,
    to_numeric_iqm,
)
from mriqc_iqm_session_level import (  # noqa: E402
    N_T1W_USABLE,
    build_session_table,
    identify_iqms,
    load_freesurfer_manifest,
    load_mriqc,
    match_session_level_t1w,
)

LOGGER = logging.getLogger("mriqc_iqm.acquisition")
FDR_ALPHA = 0.05
REF_SESSION = "ses-01"
REF_SOFTWARE = "E11"
MIN_MINORITY_MULTIVARIATE = 5
MAX_MISSING_FRAC_MULTIVARIATE = 0.10
COLLINEAR_CORR = 0.99
FLOAT_REL_TOL = 1e-6
FLOAT_ABS_TOL = 1e-8

# Sidecar / table fields that are identifiers, conversion artifacts, or
# scanner lock values rather than acquisition settings.
NON_ACQUISITION_KEYS = frozenset(
    {
        "AcquisitionNumber",
        "SeriesNumber",
        "SeriesDescription",
        "ConversionSoftware",
        "ConversionSoftwareVersion",
        "FileSize",
        "FileSizeUnits",
        "NumberOfVolumes",
        "InstitutionName",
        "InstitutionalDepartmentName",
        "StationName",
        "DeviceSerialNumber",
        "Modality",
        "BodyPartExamined",
        "PatientPosition",
        "ImagingFrequency",
        "ConsistencyInfo",
        "DwellTime",
        "AcquisitionDuration",
        "FrameOfReferenceUID",
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "SOPInstanceUID",
        "ImageOrientationPatientDICOM",
        "ShimSetting",
        "ImageType",
    }
)

# Always audit these if present (user-requested plus MRIQC bids_meta).
PRIORITY_FIELDS = (
    "ProtocolName",
    "RepetitionTime",
    "EchoTime",
    "InversionTime",
    "FlipAngle",
    "SliceThickness",
    "PixelBandwidth",
    "MagneticFieldStrength",
    "Manufacturer",
    "ManufacturersModelName",
    "SoftwareVersions",
    "ReceiveCoilName",
    "ReceiveCoilActiveElements",
    "CoilCombinationMethod",
    "ParallelReductionFactorInPlane",
    "PartialFourier",
    "AcquisitionMatrixPE",
    "BaseResolution",
    "ReconMatrixPE",
    "PercentPhaseFOV",
    "PercentSampling",
    "PhaseEncodingSteps",
    "PhaseResolution",
    "MatrixCoilMode",
    "MRAcquisitionType",
    "SequenceName",
    "SequenceVariant",
    "ScanningSequence",
    "ScanOptions",
    "PulseSequenceDetails",
    "NonlinearGradientCorrection",
    "SpoilingState",
    "RefLinesPE",
    "SAR",
    "TxRefAmp",
    "InPlanePhaseEncodingDirectionDICOM",
)

TABLE_ACQ_FIELDS = (
    "protocol_name",
    "te_s",
    "tr_s",
    "ti_s",
    "flip_angle_deg",
    "scanner",
    "coil",
    "is_norm",
    "spacing_x",
    "spacing_y",
    "spacing_z",
    "size_x",
    "size_y",
    "size_z",
)


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
    parser.add_argument("--session-tsv", type=Path, default=None)
    parser.add_argument("--clean-tsv", type=Path, default=None)
    parser.add_argument("--roles-tsv", type=Path, default=None)
    parser.add_argument("--freesurfer-manifest", type=Path, default=None)
    parser.add_argument("--release-root", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default()
    args.study_root = root
    args.session_tsv = (
        args.session_tsv.resolve()
        if args.session_tsv
        else root / "metadata" / "mriqc_iqm_session_t1w.tsv"
    )
    args.clean_tsv = (
        args.clean_tsv.resolve() if args.clean_tsv else root / "metadata" / "mriqc_iqm_clean.tsv"
    )
    args.roles_tsv = (
        args.roles_tsv.resolve()
        if args.roles_tsv
        else root / "metadata" / "mriqc_iqm_column_roles.tsv"
    )
    if args.freesurfer_manifest:
        args.freesurfer_manifest = args.freesurfer_manifest.resolve()
    else:
        local = root / "metadata" / "freesurfer_manifest.tsv"
        sibling = root.parent / "metadata" / "freesurfer_manifest.tsv"
        args.freesurfer_manifest = local if local.is_file() else sibling
    args.release_root = (
        args.release_root.resolve()
        if args.release_root
        else root.parent / "release_dataset"
    )
    args.out_dir = args.out_dir.resolve() if args.out_dir else root / "qc_reports" / "mriqc_iqm"
    args.results_tsv = args.out_dir / "acquisition_results.tsv"
    args.report_txt = args.out_dir / "acquisition_analysis_report.txt"
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


def sidecar_path(release_root: Path, input_file: str) -> Path:
    rel = str(input_file).replace(".nii.gz", ".json").replace(".nii", ".json")
    return release_root / rel


def scalarize(value: Any) -> Any:
    if value is None:
        return np.nan
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, bool):
        return bool(value)
    return value


def join_bids_metadata(session_df: pd.DataFrame, release_root: Path) -> pd.DataFrame:
    if not release_root.is_dir():
        fail(f"Release dataset root not found: {release_root}")
    require_columns(session_df, ["input_file", "bids_name"], "session-level table")
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    all_keys: set[str] = set()
    payloads: list[dict[str, Any]] = []
    for rec in session_df.itertuples(index=False):
        path = sidecar_path(release_root, rec.input_file)
        if not path.is_file():
            missing.append(str(rec.input_file))
            payloads.append({})
            continue
        payload = read_json(path)
        payloads.append(payload)
        all_keys.update(str(k) for k in payload.keys())
    if missing:
        fail(f"BIDS sidecars missing for {len(missing)} session-level rows, e.g. {missing[:5]}")
    extra_keys = [k for k in sorted(all_keys) if k not in PRIORITY_FIELDS]
    field_order = list(PRIORITY_FIELDS) + extra_keys
    for rec, payload in zip(session_df.itertuples(index=False), payloads):
        row: dict[str, Any] = {"bids_name": rec.bids_name, "input_file": rec.input_file}
        for key in field_order:
            row[key] = scalarize(payload.get(key))
        image_type = payload.get("ImageType")
        row["ImageType_str"] = (
            ",".join(str(x) for x in image_type)
            if isinstance(image_type, (list, tuple))
            else ("" if image_type is None else str(image_type))
        )
        row["reconstruction_NORM"] = bool(is_norm_image_type(image_type))
        rows.append(row)
    meta = pd.DataFrame(rows)
    merged = session_df.merge(meta, on=["bids_name", "input_file"], how="left", validate="one_to_one")
    if len(merged) != len(session_df):
        fail("Joining BIDS sidecars changed the session-level row count.")
    return merged


def effective_nunique(series: pd.Series) -> int:
    s = series.dropna()
    if s.empty:
        return 0
    num = pd.to_numeric(s, errors="coerce")
    if int(num.notna().sum()) == len(s) and pd.api.types.is_numeric_dtype(num):
        vals = num.to_numpy(dtype=float)
        if np.all(np.isfinite(vals)):
            span = float(np.nanmax(vals) - np.nanmin(vals))
            scale = max(abs(float(np.nanmedian(vals))), 1.0)
            if span <= max(FLOAT_ABS_TOL, FLOAT_REL_TOL * scale):
                return 1
            rounded = np.round(vals, 8)
            return int(len(np.unique(rounded)))
    return int(s.astype(str).nunique())


def as_numeric_or_none(series: pd.Series) -> pd.Series | None:
    num = pd.to_numeric(series, errors="coerce")
    n_ok = int(num.notna().sum())
    n_nonmiss = int(series.notna().sum())
    if n_nonmiss == 0:
        return None
    if n_ok == n_nonmiss:
        return num
    return None


def load_or_build_session_table(args: argparse.Namespace) -> tuple[pd.DataFrame, list[str], list[str], str]:
    clean = load_mriqc(args.clean_tsv)
    iqm_used, iqm_dropped = identify_iqms(clean, args.roles_tsv)
    source = ""
    if args.session_tsv.is_file():
        LOGGER.info("Loading existing session-level table: %s", args.session_tsv)
        df = pd.read_csv(args.session_tsv, sep="\t")
        source = f"on-disk {args.session_tsv}"
        require_columns(
            df,
            ["subject_id", "session", "run", "bids_name", "input_file", "age", "sex"] + iqm_used,
            "session-level T1w table",
        )
        if df.groupby(["subject_id", "session"]).ngroups != len(df):
            fail("Session-level table is not unique on subject_id × session.")
        if len(df) < 1:
            fail("Session-level table is empty.")
        missing_iqm = [c for c in iqm_used if c not in df.columns]
        if missing_iqm:
            fail(f"Session-level table missing IQMs: {missing_iqm}")
        LOGGER.info("Session-level rows: %d", len(df))
        return df, iqm_used, iqm_dropped, source
    LOGGER.warning(
        "Session-level TSV not found at %s; reconstructing in memory from "
        "FreeSurfer matching (table is not written).",
        args.session_tsv,
    )
    manifest = load_freesurfer_manifest(args.freesurfer_manifest)
    t1 = clean.loc[clean["sequence_group"].astype(str) == "T1w"].copy()
    if t1.empty:
        fail("No sequence_group == T1w rows in the clean table.")
    audit = match_session_level_t1w(t1, manifest)
    n_matched = int((audit["match_status"] == "MATCHED").sum())
    n_ambig = int((audit["match_status"] == "MULTIPLE_POSSIBLE_MATCHES").sum())
    n_mismatch = int((audit["match_status"] == "IDENTIFIER_MISMATCH").sum())
    if n_ambig or n_mismatch:
        fail(
            "Cannot reconstruct a unique session-level table "
            f"(ambiguous={n_ambig}, identifier_mismatch={n_mismatch})."
        )
    if n_matched == 0:
        fail("No MATCHED FreeSurfer–MRIQC sessions.")
    df = build_session_table(t1, audit, iqm_used)
    source = (
        f"in-memory reconstruction via mriqc_iqm_session_level matching "
        f"(manifest={args.freesurfer_manifest}; table not written)"
    )
    return df, iqm_used, iqm_dropped, source


def audit_parameters(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    voxel_x = pd.to_numeric(df.get("spacing_x"), errors="coerce")
    voxel_y = pd.to_numeric(df.get("spacing_y"), errors="coerce")
    voxel_z = pd.to_numeric(df.get("spacing_z"), errors="coerce")
    derived = {
        "voxel_size_x_mm": voxel_x,
        "voxel_size_y_mm": voxel_y,
        "voxel_size_z_mm": voxel_z,
        "voxel_volume_mm3": voxel_x * voxel_y * voxel_z,
        "reconstruction_NORM": df["reconstruction_NORM"]
        if "reconstruction_NORM" in df.columns
        else df.get("is_norm"),
        "software_platform": recode_software(df["SoftwareVersions"])
        if "SoftwareVersions" in df.columns
        else pd.Series(index=df.index, dtype=object),
    }
    candidates: list[tuple[str, str, pd.Series]] = []
    for col in PRIORITY_FIELDS:
        if col in df.columns:
            candidates.append((col, "bids_json", df[col]))
    for col in TABLE_ACQ_FIELDS:
        if col in df.columns:
            candidates.append((col, "session_table", df[col]))
    for col, series in derived.items():
        candidates.append((col, "derived", series))
    # Always audit ImageType string and skip-listed keys that exist, for completeness.
    for col in sorted(NON_ACQUISITION_KEYS):
        if col in df.columns:
            candidates.append((col, "present_not_an_acquisition_setting", df[col]))
    if "ImageType_str" in df.columns:
        candidates.append(("ImageType_str", "reconstruction", df["ImageType_str"]))

    for name, origin, series in candidates:
        n = int(len(series))
        n_missing = int(series.isna().sum()) if hasattr(series, "isna") else int(pd.isna(series).sum())
        n_unique = effective_nunique(series)
        numeric = as_numeric_or_none(series)
        kind = "numeric" if numeric is not None else "categorical"
        values = series.dropna()
        if kind == "numeric":
            sample = {
                "min": float(np.nanmin(numeric)) if n_unique else np.nan,
                "max": float(np.nanmax(numeric)) if n_unique else np.nan,
            }
            value_summary = (
                f"min={sample['min']:.8g} max={sample['max']:.8g}" if n_unique else "empty"
            )
        else:
            counts = values.astype(str).value_counts(dropna=False).head(8)
            value_summary = ", ".join(f"{k}={int(v)}" for k, v in counts.items())
        constant = n_unique <= 1
        skip_reason = ""
        if name in NON_ACQUISITION_KEYS or origin == "present_not_an_acquisition_setting":
            skip_reason = "not_an_acquisition_setting"
        elif constant:
            skip_reason = "constant"
        elif n_missing == n:
            skip_reason = "all_missing"
        rows.append(
            {
                "parameter": name,
                "origin": origin,
                "kind": kind,
                "n": n,
                "n_missing": n_missing,
                "missing_frac": n_missing / n if n else np.nan,
                "n_unique": n_unique,
                "constant": constant,
                "status": "constant" if constant else "variable",
                "skip_reason": skip_reason,
                "value_summary": value_summary,
            }
        )
    audit = pd.DataFrame(rows).drop_duplicates("parameter", keep="first")
    return audit.sort_values(["status", "parameter"], kind="mergesort").reset_index(drop=True)


def recode_software(series: pd.Series) -> pd.Series:
    out = series.astype(str)
    mapped = out.copy()
    mapped.loc[out.str.contains("XA30", na=False)] = "XA30"
    mapped.loc[out.str.contains(r"\bE11\b", na=False)] = "E11"
    mapped.loc[out.isin(["nan", "None", ""])] = np.nan
    return mapped


def minority_count(series: pd.Series) -> int:
    s = series.dropna()
    if s.empty:
        return 0
    return int(s.astype(str).value_counts().min())


def identical_partition(a: pd.Series, b: pd.Series) -> bool:
    """True when two low-cardinality labels encode the same groups."""
    if effective_nunique(a) > 12 or effective_nunique(b) > 12:
        return False
    work = pd.DataFrame({"a": a, "b": b}).dropna()
    if work.empty or len(work) < 4:
        return False
    return int(work.groupby("a")["b"].nunique().max()) == 1 and int(
        work.groupby("b")["a"].nunique().max()
    ) == 1


def prepare_predictors(df: pd.DataFrame, audit: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach model-ready columns and choose non-redundant testable parameters."""
    work = df.copy()
    work["software_platform"] = recode_software(work["SoftwareVersions"])
    work["reconstruction_NORM"] = np.where(
        work["reconstruction_NORM"].astype(bool), "NORM", "non_NORM"
    )
    work["sar"] = pd.to_numeric(work.get("SAR"), errors="coerce")
    work["tx_ref_amp"] = pd.to_numeric(work.get("TxRefAmp"), errors="coerce")
    work["voxel_size_mm"] = np.round(
        (
            pd.to_numeric(work["spacing_x"], errors="coerce")
            + pd.to_numeric(work["spacing_y"], errors="coerce")
            + pd.to_numeric(work["spacing_z"], errors="coerce")
        )
        / 3.0,
        3,
    )

    catalog = [
        {
            "parameter": "software_platform",
            "model_col": "software_platform",
            "kind": "categorical",
            "reference": REF_SOFTWARE,
            "aliases": [
                "SoftwareVersions",
                "ManufacturersModelName",
                "scanner",
                "PhaseEncodingSteps",
                "ReceiveCoilName",
                "coil",
            ],
        },
        {
            "parameter": "reconstruction_NORM",
            "model_col": "reconstruction_NORM",
            "kind": "categorical",
            "reference": "non_NORM",
            "aliases": ["is_norm"],
        },
        {
            "parameter": "SAR",
            "model_col": "sar",
            "kind": "numeric",
            "reference": "",
            "aliases": [],
        },
        {
            "parameter": "TxRefAmp",
            "model_col": "tx_ref_amp",
            "kind": "numeric",
            "reference": "",
            "aliases": [],
        },
        {
            "parameter": "ReceiveCoilActiveElements",
            "model_col": "ReceiveCoilActiveElements",
            "kind": "categorical",
            "reference": "",
            "aliases": [],
        },
        {
            "parameter": "ProtocolName",
            "model_col": "ProtocolName",
            "kind": "categorical",
            "reference": "",
            "aliases": ["protocol_name"],
        },
        {
            "parameter": "RepetitionTime",
            "model_col": "RepetitionTime",
            "kind": "numeric",
            "reference": "",
            "aliases": ["tr_s"],
        },
        {
            "parameter": "EchoTime",
            "model_col": "EchoTime",
            "kind": "numeric",
            "reference": "",
            "aliases": ["te_s"],
        },
        {
            "parameter": "FlipAngle",
            "model_col": "FlipAngle",
            "kind": "numeric",
            "reference": "",
            "aliases": ["flip_angle_deg"],
        },
        {
            "parameter": "SliceThickness",
            "model_col": "SliceThickness",
            "kind": "numeric",
            "reference": "",
            "aliases": [],
        },
        {
            "parameter": "voxel_size_mm",
            "model_col": "voxel_size_mm",
            "kind": "numeric",
            "reference": "",
            "aliases": ["spacing_x", "spacing_y", "spacing_z", "voxel_volume_mm3"],
        },
    ]

    known = {s["parameter"] for s in catalog}
    known.update(alias for spec in catalog for alias in spec["aliases"])
    known.update({"ImageType_str"})
    for rec in audit.itertuples(index=False):
        if rec.parameter in known:
            continue
        if rec.constant or rec.skip_reason:
            continue
        if rec.origin == "present_not_an_acquisition_setting":
            continue
        if rec.parameter not in work.columns:
            continue
        catalog.append(
            {
                "parameter": rec.parameter,
                "model_col": rec.parameter,
                "kind": rec.kind,
                "reference": "",
                "aliases": [],
            }
        )

    pred_rows = []
    usable: list[dict[str, Any]] = []
    for spec in catalog:
        col = spec["model_col"]
        if col not in work.columns:
            pred_rows.append({**spec, "n_unique": 0, "n_missing": len(work), "testable": False, "reason": "absent"})
            continue
        series = work[col]
        n_unique = effective_nunique(series)
        n_missing = int(series.isna().sum())
        n_min = minority_count(series) if spec["kind"] == "categorical" else int(series.notna().sum())
        reason = ""
        testable = True
        if n_unique <= 1:
            testable = False
            reason = "constant"
        elif spec["kind"] == "categorical" and n_min < 2:
            testable = False
            reason = f"minority_n={n_min}"
        if testable:
            usable.append(spec)
        pred_rows.append(
            {
                **spec,
                "n_unique": n_unique,
                "n_missing": n_missing,
                "minority_n": n_min,
                "testable": testable,
                "reason": reason,
            }
        )

    # Drop perfectly collinear duplicates among usable predictors.
    kept: list[dict[str, Any]] = []
    for spec in usable:
        series = work[spec["model_col"]]
        redundant = None
        for prev in kept:
            other = work[prev["model_col"]]
            if spec["kind"] == "numeric" and prev["kind"] == "numeric":
                a = pd.to_numeric(series, errors="coerce")
                b = pd.to_numeric(other, errors="coerce")
                mask = a.notna() & b.notna()
                if int(mask.sum()) >= 8:
                    corr = float(np.corrcoef(a.loc[mask], b.loc[mask])[0, 1])
                    if math.isfinite(corr) and abs(corr) >= COLLINEAR_CORR:
                        redundant = prev["parameter"]
                        break
            if identical_partition(series, other):
                redundant = prev["parameter"]
                break
        if redundant:
            for row in pred_rows:
                if row["parameter"] == spec["parameter"]:
                    row["testable"] = False
                    row["reason"] = f"collinear_with:{redundant}"
        else:
            kept.append(spec)

    pred_df = pd.DataFrame(pred_rows)
    return work, pred_df


def select_multivariate(work: pd.DataFrame, pred_df: pd.DataFrame) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    complete_idx = pd.Series(True, index=work.index)
    for spec in pred_df.itertuples(index=False):
        if not bool(spec.testable):
            continue
        col = spec.model_col
        series = work[col]
        miss_frac = float(series.isna().mean())
        if miss_frac > MAX_MISSING_FRAC_MULTIVARIATE:
            continue
        if spec.kind == "categorical" and int(spec.minority_n) < MIN_MINORITY_MULTIVARIATE:
            continue
        trial_idx = complete_idx & series.notna()
        trial = series.loc[trial_idx]
        if effective_nunique(trial) <= 1:
            continue
        if spec.kind == "categorical" and minority_count(trial) < MIN_MINORITY_MULTIVARIATE:
            continue
        # Adding this column must not collapse an already selected variable.
        collapsed = False
        for prev in selected:
            prev_trial = work.loc[trial_idx, prev["model_col"]]
            if effective_nunique(prev_trial) <= 1:
                collapsed = True
                break
            if prev["kind"] == "categorical" and minority_count(prev_trial) < MIN_MINORITY_MULTIVARIATE:
                collapsed = True
                break
            if identical_partition(trial, prev_trial):
                collapsed = True
                break
        if collapsed:
            continue
        selected.append(
            {
                "parameter": spec.parameter,
                "model_col": spec.model_col,
                "kind": spec.kind,
                "reference": spec.reference,
            }
        )
        complete_idx = trial_idx
    return selected


def term_name(spec: dict[str, Any]) -> str:
    col = spec["model_col"]
    if spec["kind"] != "categorical":
        return col
    if spec["parameter"] == "software_platform":
        return f'C({col}, Treatment("{REF_SOFTWARE}"))'
    if spec["parameter"] == "reconstruction_NORM":
        return f'C({col}, Treatment("non_NORM"))'
    ref = spec.get("reference", "")
    if ref == "" or ref is False:
        return f"C({col})"
    return f"C({col}, Treatment({repr(ref)}))"


def predictor_terms(fit: Any, spec: dict[str, Any]) -> list[str]:
    col = spec["model_col"]
    names = []
    for name in fit.params.index:
        if name == "Intercept":
            continue
        if spec["kind"] == "numeric" and name == col:
            names.append(name)
        elif spec["kind"] == "categorical" and (
            name == col or name.startswith(f"C({col}") or name.startswith(f"{col}[")
        ):
            names.append(name)
    return names


def empty_row(iqm: str, parameter: str, analysis: str, **extra: Any) -> dict[str, Any]:
    row = {
        "IQM": iqm,
        "parameter": parameter,
        "analysis": analysis,
        "estimate": np.nan,
        "p": np.nan,
        "q": np.nan,
        "N": np.nan,
        "se": np.nan,
        "ci_low": np.nan,
        "ci_high": np.nan,
        "spearman_rho": np.nan,
        "method": "",
        "status": "not_tested",
        "note": "",
    }
    row.update(extra)
    return row


def coef_stats(fit: Any, term: str) -> dict[str, float]:
    empty = {k: float("nan") for k in ("estimate", "se", "ci_low", "ci_high", "p")}
    if term not in fit.params.index:
        return empty
    ci = fit.conf_int().loc[term]
    return {
        "estimate": float(fit.params[term]),
        "se": float(fit.bse[term]),
        "ci_low": float(ci.iloc[0]),
        "ci_high": float(ci.iloc[1]),
        "p": float(fit.pvalues[term]) if np.isfinite(fit.pvalues[term]) else float("nan"),
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


def fit_ols(formula: str, data: pd.DataFrame, smf: Any) -> Any:
    return smf.ols(formula, data=data).fit()


def fit_mixed(formula: str, data: pd.DataFrame, smf: Any) -> Any:
    md = smf.mixedlm(formula, data=data, groups=data["subject_id"])
    fit = None
    last_exc: Exception | None = None
    for kwargs in (
        {"reml": True, "maxiter": 300},
        {"method": "nm", "reml": True, "maxiter": 400},
        {"method": "powell", "reml": True, "maxiter": 400},
    ):
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
    return fit


def spearman_rho(x: pd.Series, y: pd.Series) -> float:
    a = pd.to_numeric(x, errors="coerce")
    b = pd.to_numeric(y, errors="coerce")
    mask = a.notna() & b.notna()
    if int(mask.sum()) < 5:
        return float("nan")
    return float(a.loc[mask].corr(b.loc[mask], method="spearman"))


def univariate_one(
    work: pd.DataFrame,
    iqm: str,
    spec: dict[str, Any],
    smf: Any,
) -> dict[str, Any]:
    col = spec["model_col"]
    cols = ["subject_id", iqm, col]
    data = work[cols].copy()
    data[iqm] = to_numeric_iqm(data[iqm])
    data = data.dropna(subset=[iqm, col])
    n = int(len(data))
    note = ""
    if spec["kind"] == "categorical" and minority_count(data[col]) < MIN_MINORITY_MULTIVARIATE:
        note = f"sparse_minority_n={minority_count(data[col])}"
    rhs = term_name(spec)
    formula = f"{iqm} ~ {rhs}"
    base = empty_row(iqm, spec["parameter"], "univariate", N=n, note=note, method="OLS")
    try:
        fit = fit_ols(formula, data, smf)
        if spec["kind"] == "numeric":
            blk = coef_stats(fit, col)
            rho = spearman_rho(data[col], data[iqm])
            base.update(
                {
                    "estimate": blk["estimate"],
                    "se": blk["se"],
                    "ci_low": blk["ci_low"],
                    "ci_high": blk["ci_high"],
                    "p": blk["p"],
                    "spearman_rho": rho,
                    "status": "ok",
                }
            )
            return base
        terms = [name for name in fit.params.index if name != "Intercept"]
        if len(terms) == 1:
            blk = coef_stats(fit, terms[0])
            base.update(
                {
                    "estimate": blk["estimate"],
                    "se": blk["se"],
                    "ci_low": blk["ci_low"],
                    "ci_high": blk["ci_high"],
                    "p": blk["p"],
                    "status": "ok",
                    "note": note or terms[0],
                }
            )
            return base
        stat, p, df_w = wald_terms(fit, terms)
        base.update(
            {
                "estimate": stat,
                "p": p,
                "status": "ok",
                "note": (note + " " if note else "") + f"wald_df={df_w} terms={terms}",
            }
        )
        return base
    except Exception as exc:
        LOGGER.warning("univariate %s %s failed: %s", iqm, spec["parameter"], exc)
        base["status"] = f"failed: {exc}"
        return base


def multivariate_one(
    work: pd.DataFrame,
    iqm: str,
    selected: list[dict[str, Any]],
    smf: Any,
) -> list[dict[str, Any]]:
    cols = ["subject_id", "session", "age", "sex", iqm] + [s["model_col"] for s in selected]
    data = work[cols].copy()
    data[iqm] = to_numeric_iqm(data[iqm])
    data = data.dropna(subset=[iqm, "subject_id", "session", "age", "sex"] + [s["model_col"] for s in selected])
    n = int(len(data))
    acq_rhs = " + ".join(term_name(s) for s in selected)
    formula = (
        f"{iqm} ~ {acq_rhs} + C(session, Treatment(\"{REF_SESSION}\")) + age + C(sex)"
    )
    rows = []
    try:
        n_subj = int(data["subject_id"].nunique())
        use_mixed = n_subj < n and n_subj >= 5
        if use_mixed:
            fit = fit_mixed(formula, data, smf)
            method = "MixedLM"
            converged = bool(getattr(fit, "converged", False))
            status = "ok" if converged else "not_converged"
        else:
            fit = fit_ols(formula, data, smf)
            method = "OLS"
            status = "ok"
        acq_terms = []
        for spec in selected:
            names = predictor_terms(fit, spec)
            acq_terms.extend(names)
            if spec["kind"] == "numeric" or len(names) == 1:
                term = names[0] if names else spec["model_col"]
                blk = coef_stats(fit, term)
                rows.append(
                    empty_row(
                        iqm,
                        spec["parameter"],
                        "multivariate",
                        estimate=blk["estimate"],
                        se=blk["se"],
                        ci_low=blk["ci_low"],
                        ci_high=blk["ci_high"],
                        p=blk["p"],
                        N=n,
                        method=method,
                        status=status,
                        note=term,
                    )
                )
            else:
                stat, p, df_w = wald_terms(fit, names)
                rows.append(
                    empty_row(
                        iqm,
                        spec["parameter"],
                        "multivariate",
                        estimate=stat,
                        p=p,
                        N=n,
                        method=method,
                        status=status,
                        note=f"wald_df={df_w}",
                    )
                )
        stat, p, df_w = wald_terms(fit, acq_terms)
        rows.append(
            empty_row(
                iqm,
                "acquisition_block",
                "multivariate",
                estimate=stat,
                p=p,
                N=n,
                method=method,
                status=status,
                note=f"wald_df={df_w} terms={acq_terms}",
            )
        )
        return rows
    except Exception as exc:
        LOGGER.warning("multivariate %s failed: %s", iqm, exc)
        LOGGER.debug(traceback.format_exc())
        return [
            empty_row(
                iqm,
                spec["parameter"],
                "multivariate",
                N=n,
                status=f"failed: {exc}",
            )
            for spec in selected
        ] + [
            empty_row(
                iqm,
                "acquisition_block",
                "multivariate",
                N=n,
                status=f"failed: {exc}",
            )
        ]


def apply_fdr(results: pd.DataFrame, multipletests: Any) -> pd.DataFrame:
    out = results.copy()
    out["q"] = np.nan
    for (analysis, parameter), idx in out.groupby(["analysis", "parameter"]).groups.items():
        p = pd.to_numeric(out.loc[idx, "p"], errors="coerce")
        ok = p.notna() & np.isfinite(p.to_numpy(dtype=float))
        if int(ok.sum()) == 0:
            continue
        _, adj, _, _ = multipletests(
            p.loc[ok].to_numpy(dtype=float), alpha=FDR_ALPHA, method="fdr_bh"
        )
        out.loc[p.loc[ok].index, "q"] = adj
    return out


def write_report(
    path: Path,
    *,
    args: argparse.Namespace,
    hashes: dict[str, str],
    stats_info: dict[str, Any],
    session_source: str,
    n_rows: int,
    n_subjects: int,
    iqm_used: list[str],
    iqm_dropped: list[str],
    audit: pd.DataFrame,
    pred_df: pd.DataFrame,
    selected: list[dict[str, Any]],
    results: pd.DataFrame,
    formula: str,
) -> None:
    lines = [
        "T1w IQM acquisition-parameter analysis report",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "1. PURPOSE",
        "  Quantify how the 56 session-level T1w MRIQC IQMs associate with",
        "  available BIDS/JSON acquisition metadata.",
        "  An association means IQM sensitivity to an acquisition or",
        "  reconstruction characteristic. It is not a quality grade and is",
        "  not an anatomical or biological interpretation.",
        "",
        "2. MRIQC METADATA RATIONALE",
        "  MRIQC's anatomical IQM workflow includes an explicit metadata",
        "  step that copies BIDS sidecar fields into the IQM JSON",
        "  (bids_meta). Voxel size from the image header also enters",
        "  spatial IQMs (for example FWHM in millimetres). Jointly auditing",
        "  acquisition metadata with IQMs is therefore part of the IQM",
        "  measurement model, not a post-hoc covariate hunt.",
        "",
        "3. INPUTS (read-only)",
        f"  session table: {session_source}",
        f"  clean TSV: {args.clean_tsv}",
        f"  roles TSV: {args.roles_tsv}",
        f"  BIDS JSON root: {args.release_root}",
        f"  clean sha256: {hashes.get('clean', '')}",
        f"  session sha256: {hashes.get('session', 'not on disk')}",
        f"  scipy {stats_info.get('scipy')}  statsmodels {stats_info.get('statsmodels')}",
        "  MRIQC / PCA / FreeSurfer were not rerun. Outliers were not removed.",
        "",
        "4. SESSION-LEVEL DATASET",
        f"  rows (subject × session): {n_rows}",
        f"  subjects: {n_subjects}",
        f"  IQMs used: {len(iqm_used)}  dropped zero-variance: {iqm_dropped}",
        "  Unit of analysis: one FreeSurfer-selected T1w_MPR per session.",
        "",
        "5. ACQUISITION PARAMETER AUDIT",
        "  parameter  origin  kind  n_unique  n_missing  status  values",
    ]
    for rec in audit.itertuples(index=False):
        lines.append(
            f"  {rec.parameter:32s} {rec.origin:18s} {rec.kind:12s} "
            f"unique={int(rec.n_unique):4d} missing={int(rec.n_missing):3d} "
            f"{rec.status:9s} {rec.value_summary}"
        )
    n_const = int(audit["constant"].sum())
    n_var = int((~audit["constant"]).sum())
    lines.extend(
        [
            "",
            f"  n_parameters_audited={len(audit)}  constant={n_const}  variable={n_var}",
            "",
            "6. TESTABLE PARAMETERS AND REDUNDANCY",
        ]
    )
    for rec in pred_df.itertuples(index=False):
        lines.append(
            f"  {rec.parameter}: testable={rec.testable} unique={rec.n_unique} "
            f"missing={rec.n_missing} minority={getattr(rec, 'minority_n', '')} "
            f"reason={rec.reason or 'ok'} aliases={rec.aliases}"
        )
    if selected:
        sel = ", ".join(s["parameter"] for s in selected)
    else:
        sel = "none (no non-redundant, sufficiently populated acquisition term)"
    lines.extend(
        [
            "",
            "7. MODELS",
            "  Univariate (per testable parameter): OLS  IQM ~ parameter",
            "  Numeric univariate also records Spearman rho (descriptive; FDR uses OLS p).",
            "  Multivariate, when possible:",
            f"    {formula}",
            "    MixedLM random intercept (1|subject_id) when subjects contribute",
            "    both sessions; OLS otherwise. Age/sex/session are covariates,",
            "    not acquisition parameters.",
            f"  Multivariate acquisition terms: {sel}",
            "  Perfectly collinear aliases are represented by one term.",
            "  A parameter is omitted from the multivariate model if adding it",
            "  makes a previously selected term constant in complete cases,",
            "  if missingness exceeds 10%, or if the minority class has n<5.",
            "",
            "8. FDR",
            "  Benjamini–Hochberg is applied separately to the 56 IQM tests",
            "  within each (analysis, parameter) family.",
            f"  alpha={FDR_ALPHA}",
            "",
            "9. RESULTS BY ANALYSIS",
        ]
    )
    for (analysis, parameter), sub in results.groupby(["analysis", "parameter"], sort=True):
        n_ok = int((sub["status"].astype(str) == "ok").sum() + (sub["status"].astype(str) == "not_converged").sum())
        n_fdr = int((pd.to_numeric(sub["q"], errors="coerce") < FDR_ALPHA).sum())
        finite_q = pd.to_numeric(sub["q"], errors="coerce")
        min_q = float(finite_q.min()) if finite_q.notna().any() else float("nan")
        top = sub.sort_values("q", na_position="last").iloc[0]
        lines.append(
            f"  {analysis} / {parameter}: tested={n_ok}/56  FDR q<{FDR_ALPHA}: {n_fdr}  "
            f"min q={min_q:.6g}  top IQM={top['IQM']}"
        )
    lines.extend(["", "10. IQMs MOST STRONGLY ASSOCIATED WITH ACQUISITION PARAMETERS"])
    display = results.loc[results["parameter"] != "acquisition_block"].copy()
    sig = display.loc[pd.to_numeric(display["q"], errors="coerce") < FDR_ALPHA].copy()
    if sig.empty:
        lines.append("  None at FDR q < 0.05.")
    else:
        lines.append(
            f"  {len(sig)} IQM×parameter rows with FDR q < {FDR_ALPHA} "
            "(acquisition_block omitted here when it duplicates a single term)."
        )
        sig = sig.sort_values(["analysis", "q", "IQM"])
        for analysis, sub in sig.groupby("analysis", sort=True):
            lines.append(f"  {analysis}:")
            shown = 0
            for rec in sub.itertuples(index=False):
                if shown >= 15:
                    n_more = int(len(sub) - shown)
                    lines.append(f"    ... {n_more} additional FDR-significant rows in the TSV")
                    break
                lines.append(
                    f"    {rec.parameter:22s} {rec.IQM:20s} "
                    f"estimate={rec.estimate:.6g} p={rec.p:.6g} q={rec.q:.6g} N={int(rec.N)}"
                )
                shown += 1
    lines.append("")
    lines.append("  Smallest q per analysis/parameter (whether or not FDR-significant):")
    ranked_groups = display.groupby(["analysis", "parameter"], sort=True)
    for (analysis, parameter), sub in ranked_groups:
        rec = sub.sort_values("q", na_position="last").iloc[0]
        qv = rec.q if pd.notna(rec.q) else float("nan")
        lines.append(
            f"    {analysis:13s} {parameter:22s} top={rec.IQM:20s} q={qv:.6g}"
        )
    lines.extend(
        [
            "",
            "11. INTERPRETATION LIMITATIONS",
            "  Protocol contrast settings (ProtocolName, TR, TE, TI, flip angle,",
            "  slice thickness, voxel size, field strength) are constant in this",
            "  FreeSurfer-selected T1w_MPR session-level table. They cannot be",
            "  statistically tested here; constancy is itself the finding.",
            "  Siemens reconstruction flag NORM is present on only two sessions;",
            "  univariate tests are reported but are not a basis for inference.",
            "  Software platform E11 vs XA30 is collinear with scanner label",
            "  (Prisma vs MAGNETOM Prisma), PhaseEncodingSteps 299 vs 300,",
            "  ImageType ND vs NONE, and missing coil metadata. One term",
            "  represents that cluster.",
            "  SAR and TxRefAmp are scan-instance RF metadata in bids_meta, not",
            "  operator-chosen protocol fields; they are missing on XA30 rows,",
            "  so they cannot enter the same complete-case model as software.",
            "  No anatomical, tissue, or disease interpretation is made.",
            "  FreeSurfer morphometry is reserved for a later step.",
            "",
            "12. OUTPUT FILES",
            f"  {args.results_tsv}",
            f"  {path}",
            "  Columns: IQM, parameter, estimate (effect), p, q, N",
            "  plus analysis, se, CI, Spearman rho (numeric univariate), method, status.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    LOGGER.info("T1w IQM acquisition-parameter analysis")

    stats = import_stats()
    if not stats["ok"]:
        fail(
            "Missing statistical dependencies: "
            + "; ".join(stats["missing"])
            + ". On Narval: module load scipy-stack/2025a. Models were not reimplemented."
        )

    hashes: dict[str, str] = {"clean": file_sha256(args.clean_tsv)}
    if args.session_tsv.is_file():
        hashes["session"] = file_sha256(args.session_tsv)

    session_df, iqm_used, iqm_dropped, session_source = load_or_build_session_table(args)
    if len(iqm_used) != N_T1W_USABLE:
        fail(f"Expected {N_T1W_USABLE} T1w IQMs, found {len(iqm_used)}.")
    if session_df.groupby(["subject_id", "session"]).ngroups != len(session_df):
        fail("n_unique(subject_id, session) != n_rows")

    work_raw = join_bids_metadata(session_df, args.release_root)
    audit = audit_parameters(work_raw)
    work, pred_df = prepare_predictors(work_raw, audit)
    selected = select_multivariate(work, pred_df)
    LOGGER.info("Testable parameters: %s", pred_df.loc[pred_df.testable, "parameter"].tolist())
    LOGGER.info("Multivariate acquisition terms: %s", [s["parameter"] for s in selected])

    rows: list[dict[str, Any]] = []
    testable_specs = [
        {
            "parameter": rec.parameter,
            "model_col": rec.model_col,
            "kind": rec.kind,
            "reference": rec.reference,
        }
        for rec in pred_df.itertuples(index=False)
        if bool(rec.testable)
    ]
    LOGGER.info("Univariate OLS for %d IQMs × %d parameters", len(iqm_used), len(testable_specs))
    for i, iqm in enumerate(iqm_used, start=1):
        if i == 1 or i % 10 == 0:
            LOGGER.info("  univariate %d/%d %s", i, len(iqm_used), iqm)
        for spec in testable_specs:
            rows.append(univariate_one(work, iqm, spec, stats["smf"]))

    if selected:
        acq_rhs = " + ".join(term_name(s) for s in selected)
        formula = (
            f"IQM ~ {acq_rhs} + C(session, Treatment(\"{REF_SESSION}\")) + age + C(sex)"
            " + (1|subject_id)"
        )
        LOGGER.info("Multivariate models for %d IQMs", len(iqm_used))
        for i, iqm in enumerate(iqm_used, start=1):
            if i == 1 or i % 10 == 0:
                LOGGER.info("  multivariate %d/%d %s", i, len(iqm_used), iqm)
            rows.extend(multivariate_one(work, iqm, selected, stats["smf"]))
    else:
        formula = "not fitted (no eligible acquisition parameter)"
        LOGGER.warning("Multivariate model not fitted: no eligible acquisition parameter.")

    results = pd.DataFrame(rows)
    results = apply_fdr(results, stats["multipletests"])
    col_order = [
        "IQM",
        "parameter",
        "estimate",
        "p",
        "q",
        "N",
        "analysis",
        "se",
        "ci_low",
        "ci_high",
        "spearman_rho",
        "method",
        "status",
        "note",
    ]
    results = results[col_order].sort_values(["analysis", "parameter", "IQM"]).reset_index(drop=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.results_tsv, sep="\t", index=False, float_format="%.10g")
    LOGGER.info("Wrote %s", args.results_tsv)

    hashes_after = {"clean": file_sha256(args.clean_tsv)}
    if args.session_tsv.is_file():
        hashes_after["session"] = file_sha256(args.session_tsv)
    if hashes.get("clean") != hashes_after.get("clean"):
        fail("Clean IQM table changed during the run.")
    if "session" in hashes and hashes["session"] != hashes_after.get("session"):
        fail("Session-level table changed during the run.")

    write_report(
        args.report_txt,
        args=args,
        hashes=hashes,
        stats_info=stats,
        session_source=session_source,
        n_rows=len(work),
        n_subjects=int(work["subject_id"].nunique()),
        iqm_used=iqm_used,
        iqm_dropped=iqm_dropped,
        audit=audit,
        pred_df=pred_df,
        selected=selected,
        results=results,
        formula=formula,
    )

    def count_fdr(analysis: str, parameter: str) -> tuple[int, float, str]:
        sub = results.loc[(results["analysis"] == analysis) & (results["parameter"] == parameter)]
        if sub.empty:
            return 0, float("nan"), ""
        n = int((pd.to_numeric(sub["q"], errors="coerce") < FDR_ALPHA).sum())
        q = pd.to_numeric(sub["q"], errors="coerce")
        top = sub.sort_values("q", na_position="last").iloc[0]
        return n, float(q.min()) if q.notna().any() else float("nan"), str(top["IQM"])

    print()
    print("=" * 60)
    print("MRIQC T1w IQM ACQUISITION-PARAMETER ANALYSIS")
    print("=" * 60)
    print()
    print(f"Session-level rows: {len(work)}")
    print(f"Subjects: {work['subject_id'].nunique()}")
    print(f"IQMs: {len(iqm_used)}")
    print(f"Session table source: {session_source}")
    print()
    print("Acquisition audit:")
    print(f"  parameters audited: {len(audit)}")
    print(f"  constant: {int(audit['constant'].sum())}")
    print(f"  variable: {int((~audit['constant']).sum())}")
    print(f"  univariate parameters: {[s['parameter'] for s in testable_specs]}")
    print(f"  multivariate parameters: {[s['parameter'] for s in selected]}")
    print()
    print("FDR q<0.05 (56 IQMs per analysis):")
    for analysis, parameter in results.groupby(["analysis", "parameter"]).groups:
        n, qmin, top = count_fdr(analysis, parameter)
        print(f"  {analysis:13s} {parameter:22s}  {n}/56  min q={qmin:.6g}  top={top}")
    print()
    print("Association with an acquisition parameter is IQM sensitivity")
    print("to acquisition/reconstruction characteristics, not image-quality")
    print("better/worse, and not an anatomical finding.")
    print()
    print("=" * 60)
    print("Acquisition analysis completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
