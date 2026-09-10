#!/usr/bin/env python3
"""Shared constants and helpers for anatomical MRIQC IQM steps 1–2.

Mapping assumptions (documented for the methods paper, not silent defaults):

1. Anatomical MRIQC IQMs live in the packaged table
   ``release_dataset/docs/quality_control/mriqc/mriqc_metrics.csv``.
   Native JSON under ``derivatives/mriqc/`` is read-only and used only
   for traceability / unmapped-file checks. MRIQC is never re-run.
2. Both T1w MPRAGE and WM-nulled share the BIDS suffix ``T1w``.
   ``sequence_group`` is taken from the BIDS sidecar ``ProtocolName``:
   ``T1w_MPR`` → ``T1w``; ``WMn_MPRAGE_sagittal`` → ``WMn``.
   Run number is never used as a protocol proxy.
3. Siemens ``ImageType`` containing ``NORM`` is a reconstruction flag
   of the same ``T1w_MPR`` protocol, not a third sequence group.
4. fMRI / BOLD IQM columns are excluded from this anatomical stage.
5. Duplicate runs of the same protocol in one session are distinct
   acquisitions. The uniqueness key is
   ``(subject_id, session, sequence_group, run)``.
6. Cohort labels are normalized to Control / Glaucoma / Data_ON / Data_TON.
   Age is joined from ``metadata/participants.tsv`` (not in the release
   participants table).
7. Extra MRIQC JSON for T1w volumes listed in ``excluded_t1w.tsv`` are
   reported as unmapped and are not rows of the master table.
8. Packaged T1w NIfTI without IQMs must appear in ``mriqc_failures.csv``.
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

LOGGER = logging.getLogger("mriqc_iqm")

PROTOCOL_TO_SEQUENCE_GROUP = {
    "T1w_MPR": "T1w",
    "WMn_MPRAGE_sagittal": "WMn",
}
SEQUENCE_GROUP_LABEL = {"T1w": "T1w MPRAGE", "WMn": "WM-nulled"}
EXPECTED_SEQUENCE_GROUPS = ("T1w", "WMn")
EXPECTED_COHORTS = ("Control", "Glaucoma", "Data_ON", "Data_TON")
COHORT_ALIASES = {
    "DataON": "Data_ON",
    "Data_ON": "Data_ON",
    "DataTON": "Data_TON",
    "Data_TON": "Data_TON",
    "Control": "Control",
    "Glaucoma": "Glaucoma",
}

# Same stem parser as release_dataset/docs/quality_control/build_release_qc_package.py
BIDS_SUFFIX_MODALITY = (("T1w", "anat"), ("T2w", "anat"), ("bold", "func"), ("dwi", "dwi"))

IDENTIFIER_COLUMNS = frozenset(
    {
        "participant_id",
        "session_id",
        "subject_id",
        "session",
        "task",
        "run",
        "suffix",
        "modality",
        "acquisition",
        "direction",
        "echo",
        "input_file",
        "mriqc_output",
        "mriqc_source_file",
        "mriqc_source_stem",
        "mriqc_version",
        "bids_name",
        "filename",
        "sequence",
        "sequence_group",
        "protocol_name",
        "cohort",
        "sex",
        "age",
        "is_norm",
        "ImageType",
        "image_type",
        "scanner",
        "coil",
        "series_number",
        "inventory_n_series",
        "inventory_n_dicom",
        "inventory_cohort",
        "inventory_session_cohort",
        "inventory_exclusion_status",
        "has_anat_T1w",
        "mapping_ok",
        "mapping_notes",
        "EchoTime",
        "RepetitionTime",
        "InversionTime",
        "FlipAngle",
        "ManufacturersModelName",
        "ReceiveCoilName",
        "SeriesNumber",
        "te_s",
        "tr_s",
        "ti_s",
        "flip_angle_deg",
    }
)

TECHNICAL_EXACT = frozenset(
    {
        "size_x",
        "size_y",
        "size_z",
        "size_t",
        "spacing_x",
        "spacing_y",
        "spacing_z",
        "spacing_tr",
        "dummy_trs",
        "summary_bg_n",
        "summary_csf_n",
        "summary_gm_n",
        "summary_wm_n",
        "summary_fg_n",
    }
)
TECHNICAL_PREFIXES = ("size_", "spacing_")

BOLD_EXACT = frozenset(
    {
        "aor",
        "aqi",
        "dummy_trs",
        "dvars_nstd",
        "dvars_std",
        "dvars_vstd",
        "fd_mean",
        "fd_num",
        "fd_perc",
        "gcor",
        "gsr_x",
        "gsr_y",
        "snr",
        "tsnr",
        "size_t",
        "spacing_tr",
    }
)
BOLD_PREFIXES = ("dvars_", "fd_", "gsr_", "summary_fg_")

REQUIRED_METRICS_COLUMNS = (
    "participant_id",
    "session_id",
    "run",
    "suffix",
    "modality",
    "input_file",
    "mriqc_output",
    "mriqc_version",
)

MAIN_IQMS_FOR_PLOTS = (
    "cjv",
    "cnr",
    "efc",
    "fber",
    "fwhm_avg",
    "inu_med",
    "inu_range",
    "qi_2",
    "snr_total",
    "snrd_total",
    "wm2max",
    "rpve_wm",
)

NEAR_ZERO_REL_SD = 1e-8
IQR_K = 1.5
ROBUST_Z_THRESH = 3.5
DEFAULT_SCRATCH = Path("/lustre07/scratch/alexrees")


def configure_logging(level: int = logging.INFO, log_file: Path | None = None) -> None:
    LOGGER.setLevel(level)
    LOGGER.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    LOGGER.addHandler(stream)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        LOGGER.addHandler(fh)


def fail(message: str) -> None:
    LOGGER.error(message)
    raise SystemExit(f"ERROR: {message}")


def require_file(path: Path, what: str) -> Path:
    if not path.is_file():
        fail(f"{what} not found: {path}")
    return path


def require_columns(df: pd.DataFrame, columns: Iterable[str], what: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        fail(f"{what} is missing required columns: {missing}")


def normalize_cohort(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    return COHORT_ALIASES.get(text, text)


def normalize_run(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none"}:
        return ""
    if text.startswith("run-"):
        text = text[4:]
    try:
        return f"{int(text):02d}"
    except ValueError:
        return text.zfill(2) if text.isdigit() else text


def parse_bids_stem(stem: str) -> dict[str, str]:
    """BIDS filename entities. Logic aligned with build_release_qc_package.parse_bids_stem."""
    out = {
        "participant_id": "",
        "session_id": "",
        "task": "",
        "run": "",
        "suffix": "",
        "modality": "",
        "acquisition": "",
        "direction": "",
        "echo": "",
    }
    m = re.search(r"(sub-[A-Za-z0-9]+)", stem)
    if m:
        out["participant_id"] = m.group(1)
    m = re.search(r"(ses-[A-Za-z0-9]+)", stem)
    if m:
        out["session_id"] = m.group(1)
    m = re.search(r"task-([A-Za-z0-9]+)", stem)
    if m:
        out["task"] = m.group(1)
    m = re.search(r"run-([0-9]+)", stem)
    if m:
        out["run"] = m.group(1)
    m = re.search(r"acq-([A-Za-z0-9]+)", stem)
    if m:
        out["acquisition"] = m.group(1)
    m = re.search(r"dir-([A-Za-z0-9]+)", stem)
    if m:
        out["direction"] = m.group(1)
    m = re.search(r"echo-([0-9]+)", stem)
    if m:
        out["echo"] = m.group(1)
    for suf, mod in BIDS_SUFFIX_MODALITY:
        if stem.endswith(f"_{suf}") or f"_{suf}_" in stem:
            out["suffix"] = suf
            out["modality"] = mod
            break
    return out


def bids_name_from_input(input_file: str) -> str:
    name = Path(str(input_file)).name
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")]
    return Path(name).stem


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON (read-only check): {path}: {exc}")
    if not isinstance(payload, dict):
        fail(f"JSON root is not an object: {path}")
    return payload


def sidecar_protocol(sidecar: Path) -> str:
    if not sidecar.is_file():
        fail(f"BIDS sidecar missing for ProtocolName mapping: {sidecar}")
    proto = read_json(sidecar).get("ProtocolName")
    if proto is None or str(proto).strip() == "":
        fail(f"ProtocolName missing in sidecar: {sidecar}")
    return str(proto).strip()


def sequence_group_from_protocol(protocol: str, sidecar: Path) -> str:
    group = PROTOCOL_TO_SEQUENCE_GROUP.get(protocol)
    if group is None:
        fail(
            "Unknown anatomical ProtocolName "
            f"{protocol!r} in {sidecar}. Expected one of "
            f"{sorted(PROTOCOL_TO_SEQUENCE_GROUP)}."
        )
    return group


def is_norm_image_type(image_type: Any) -> bool:
    if image_type is None:
        return False
    if isinstance(image_type, str):
        tokens = [t.strip() for t in image_type.replace("[", "").replace("]", "").split(",")]
    elif isinstance(image_type, (list, tuple)):
        tokens = [str(t).strip() for t in image_type]
    else:
        tokens = [str(image_type)]
    return "NORM" in {t.strip("'\" ") for t in tokens}


def iqm_family(name: str) -> str:
    if name in {"cjv", "cnr"}:
        return "contrast"
    if name == "efc":
        return "entropy"
    if name == "fber":
        return "energy"
    if name == "wm2max":
        return "intensity_ratio"
    prefixes = (
        ("fwhm_", "smoothness"),
        ("icvs_", "tissue_fraction"),
        ("inu_", "bias_field"),
        ("qi_", "artifact"),
        ("rpve_", "partial_volume"),
        ("snrd_", "snr_dietrich"),
        ("snr_", "snr"),
        ("tpm_overlap_", "template_overlap"),
        ("summary_", "intensity_summary"),
    )
    for prefix, family in prefixes:
        if name.startswith(prefix):
            return family
    return "other"


def is_technical_column(name: str) -> bool:
    if name in TECHNICAL_EXACT:
        return True
    return name.startswith(TECHNICAL_PREFIXES)


def is_bold_column(name: str) -> bool:
    if name in BOLD_EXACT:
        return True
    return any(name.startswith(p) for p in BOLD_PREFIXES)


def is_identifier_column(name: str) -> bool:
    return name in IDENTIFIER_COLUMNS


def classify_column(name: str) -> str:
    if is_identifier_column(name) or name in {"notes"}:
        return "metadata"
    if is_bold_column(name):
        return "bold_excluded"
    if is_technical_column(name):
        return "technical"
    return "iqm"


def analytic_iqm_columns(df: pd.DataFrame) -> list[str]:
    cols: list[str] = []
    for name in df.columns:
        if classify_column(name) != "iqm":
            continue
        series = df[name]
        if pd.api.types.is_bool_dtype(series):
            continue
        if not pd.api.types.is_numeric_dtype(series):
            continue
        cols.append(name)
    return cols


def technical_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if classify_column(c) == "technical"]


def to_numeric_iqm(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    return out.replace([np.inf, -np.inf], np.nan)


def robust_z(values: pd.Series) -> pd.Series:
    x = to_numeric_iqm(values)
    med = x.median(skipna=True)
    mad = (x - med).abs().median(skipna=True)
    if pd.isna(mad) or mad == 0:
        q1 = x.quantile(0.25)
        q3 = x.quantile(0.75)
        iqr = q3 - q1
        scale = iqr / 1.349 if pd.notna(iqr) and iqr > 0 else np.nan
        if pd.isna(scale) or scale == 0:
            return pd.Series(np.nan, index=x.index)
        return 0.6745 * (x - med) / scale
    return 0.6745 * (x - med) / mad


def iqr_outlier_mask(values: pd.Series, k: float = IQR_K) -> pd.Series:
    x = to_numeric_iqm(values)
    q1 = x.quantile(0.25)
    q3 = x.quantile(0.75)
    iqr = q3 - q1
    if pd.isna(iqr) or iqr == 0:
        return pd.Series(False, index=x.index)
    lo = q1 - k * iqr
    hi = q3 + k * iqr
    return x.notna() & ((x < lo) | (x > hi))


def default_paths(scratch: Path) -> dict[str, Path]:
    release = scratch / "release_dataset"
    study = scratch / "study"
    return {
        "scratch": scratch,
        "release": release,
        "study": study,
        "metrics": release / "docs" / "quality_control" / "mriqc" / "mriqc_metrics.csv",
        "excluded_t1w": release / "docs" / "quality_control" / "excluded_t1w.tsv",
        "failures": release / "docs" / "quality_control" / "mriqc" / "mriqc_failures.csv",
        "participants_release": release / "participants.tsv",
        "participants_age": scratch / "metadata" / "participants.tsv",
        "sessions": scratch / "metadata" / "sessions.tsv",
        "session_summary": release / "docs" / "dataset" / "participant_session_summary.tsv",
        "sequence_inventory": release / "docs" / "inventory" / "sequence_inventory.csv",
        "mriqc_derivatives": scratch / "derivatives" / "mriqc",
        "mriqc_derivatives_release": release / "derivatives" / "mriqc",
        "master_tsv": study / "metadata" / "mriqc_iqm_master.tsv",
        "master_json": study / "metadata" / "mriqc_iqm_master_summary.json",
        "master_report": study / "qc_reports" / "mriqc_iqm_master_report.txt",
        "clean_tsv": study / "metadata" / "mriqc_iqm_clean.tsv",
        "figures": study / "qc_reports" / "mriqc_iqm",
    }
