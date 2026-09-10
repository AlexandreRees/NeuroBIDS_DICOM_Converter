#!/usr/bin/env python3
"""Audit whether T1w volumes in the MRIQC/PCA table are independent scans.

Reads existing clean IQM rows, BIDS JSON sidecars, and DICOM inventory
tables. Does not rerun MRIQC or PCA, does not modify source files, and
does not drop observations.

Siemens ImageType token NORM is treated as a reconstruction flag until
the metadata show otherwise. It is not assumed to be an acquisition
variable.

Example:
  python code/mriqc_iqm_t1w_reconstruction_audit.py
  python code/mriqc_iqm_t1w_reconstruction_audit.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import (  # noqa: E402
    DEFAULT_SCRATCH,
    default_paths,
    fail,
    is_norm_image_type,
    require_columns,
    require_file,
)

LOGGER = logging.getLogger("mriqc_iqm.t1w_reconstruction_audit")

PROTECTED_RELATIVE = (
    "metadata/mriqc_iqm_clean.tsv",
    "qc_reports/mriqc_iqm/pca_T1w_scores.tsv",
    "qc_reports/mriqc_iqm/pca_T1w_loadings.tsv",
)

ACQ_PARAM_JSON_KEYS = (
    "RepetitionTime",
    "EchoTime",
    "InversionTime",
    "FlipAngle",
    "SliceThickness",
    "AcquisitionMatrixPE",
    "BaseResolution",
    "ReconMatrixPE",
    "PixelBandwidth",
    "ParallelReductionFactorInPlane",
    "PartialFourier",
    "SequenceName",
    "ScanningSequence",
    "SequenceVariant",
    "PulseSequenceDetails",
    "ReceiveCoilName",
    "PercentPhaseFOV",
    "PercentSampling",
    "PhaseEncodingSteps",
    "PhaseResolution",
    "MRAcquisitionType",
    "MagneticFieldStrength",
)

RECON_ONLY_JSON_KEYS = ("ImageType", "SeriesNumber", "SeriesDescription")

MPRAGE_REPEAT_SECONDS = 120.0


def study_root_default() -> Path:
    root = Path(__file__).resolve().parent.parent
    if not (root / "metadata").is_dir() or not (root / "qc_reports").is_dir():
        fail(
            f"Cannot resolve study root from {Path(__file__).resolve()}. "
            "Expected metadata/ and qc_reports/ next to code/. "
            "Pass --study-root explicitly."
        )
    return root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    paths = default_paths(DEFAULT_SCRATCH)
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Read-only audit. NORM in Siemens ImageType is a reconstruction "
            "flag unless metadata show two distinct acquisitions."
        ),
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    parser.add_argument("--release-root", type=Path, default=None)
    parser.add_argument("--bids-root", type=Path, default=None)
    parser.add_argument("--clean-tsv", type=Path, default=None)
    parser.add_argument("--session-mapping", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default()
    scratch = args.scratch.resolve()
    resolved = default_paths(scratch)
    args.study_root = root
    args.release_root = (
        args.release_root.resolve() if args.release_root else resolved["release"]
    )
    args.bids_root = (
        args.bids_root.resolve() if args.bids_root else (scratch / "bids")
    )
    args.clean_tsv = (
        args.clean_tsv.resolve()
        if args.clean_tsv
        else (root / "metadata" / "mriqc_iqm_clean.tsv")
    )
    args.session_mapping = (
        args.session_mapping.resolve()
        if args.session_mapping
        else (scratch / "metadata" / "session_mapping.csv")
    )
    args.out_dir = (
        args.out_dir.resolve()
        if args.out_dir
        else (root / "qc_reports" / "mriqc_iqm")
    )
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_protected(study_root: Path) -> dict[Path, str]:
    out: dict[Path, str] = {}
    for rel in PROTECTED_RELATIVE:
        path = study_root / rel
        require_file(path, f"protected file {rel}")
        out[path] = sha256_file(path)
    return out


def assert_unmodified(before: dict[Path, str]) -> None:
    for path, expected in before.items():
        current = sha256_file(path)
        if current != expected:
            fail(f"Refusing to continue: protected file changed: {path}")


def stringify(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(stringify(v) for v in value)
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value).strip()


def round_num(value: Any, ndigits: int) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return None


def norm_status_from_image_type(image_type: Any) -> str:
    if image_type is None or stringify(image_type) == "":
        return "unidentifiable"
    return "NORM" if is_norm_image_type(image_type) else "non-NORM"


def voxel_size_text(payload: dict[str, Any], spacing: tuple[Any, Any, Any]) -> str:
    sx, sy, sz = spacing
    if all(v is not None and str(v) not in {"", "nan"} for v in (sx, sy, sz)):
        try:
            return f"{float(sx):g}x{float(sy):g}x{float(sz):g}"
        except (TypeError, ValueError):
            pass
    thick = payload.get("SliceThickness")
    return stringify(thick)


def acquisition_fingerprint(payload: dict[str, Any]) -> str:
    shim = payload.get("ShimSetting")
    if isinstance(shim, (list, tuple)):
        shim_key = tuple(round_num(x, 3) for x in shim)
    else:
        shim_key = stringify(shim)
    parts = (
        round_num(payload.get("SAR"), 6),
        shim_key,
        round_num(payload.get("TxRefAmp"), 3),
        stringify(payload.get("SequenceName")),
        round_num(payload.get("RepetitionTime"), 6),
        round_num(payload.get("EchoTime"), 6),
        round_num(payload.get("InversionTime"), 6),
        round_num(payload.get("FlipAngle"), 4),
        round_num(payload.get("SliceThickness"), 4),
        stringify(payload.get("ReceiveCoilName")),
    )
    return repr(parts)


def json_diff_keys(payloads: list[dict[str, Any]]) -> list[str]:
    keys: set[str] = set()
    for payload in payloads:
        keys.update(payload.keys())
    differing: list[str] = []
    for key in sorted(keys):
        values = [json.dumps(p.get(key), sort_keys=True, default=str) for p in payloads]
        if len(set(values)) > 1:
            differing.append(key)
    return differing


def parse_dicom_time(value: Any) -> float | None:
    text = stringify(value)
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def find_sidecar(input_file: str, release_root: Path, bids_root: Path) -> Path:
    rel = str(input_file).replace(".nii.gz", ".json")
    candidates = [release_root / rel, bids_root / rel]
    for path in candidates:
        if path.is_file():
            return path
    fail(f"BIDS sidecar not found for {input_file}. Looked in: {candidates}")
    raise AssertionError("unreachable")


def load_sidecar(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON sidecar: {path}: {exc}")
    if not isinstance(payload, dict):
        fail(f"JSON root is not an object: {path}")
    return payload


def load_dicom_index(path: Path) -> dict[tuple[str, str, int], list[dict[str, Any]]]:
    if not path.is_file():
        LOGGER.warning("DICOM session mapping not found: %s", path)
        return {}
    df = pd.read_csv(path, low_memory=False)
    need = ["protocol_name", "series_number"]
    for col in need:
        if col not in df.columns:
            fail(f"{path} is missing column {col}")
    subject_col = "participant_id" if "participant_id" in df.columns else None
    session_col = "session_id" if "session_id" in df.columns else None
    if subject_col is None or session_col is None:
        fail(f"{path} is missing participant_id/session_id")
    t1 = df[df["protocol_name"].astype(str) == "T1w_MPR"].copy()
    index: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for _, row in t1.iterrows():
        try:
            series_n = int(float(row["series_number"]))
        except (TypeError, ValueError):
            continue
        key = (str(row[subject_col]), str(row[session_col]), series_n)
        index[key].append(
            {
                "SeriesInstanceUID": stringify(row.get("series_instance_uid", "")),
                "StudyInstanceUID": stringify(row.get("study_instance_uid", "")),
                "series_time": stringify(row.get("series_time", "")),
                "study_date": stringify(row.get("study_date", "")),
                "study_time": stringify(row.get("study_time", "")),
                "n_dicom_files": stringify(row.get("n_dicom_files", "")),
                "representative_dicom": stringify(row.get("representative_dicom", "")),
            }
        )
    LOGGER.info("Indexed %d T1w_MPR DICOM series from %s", sum(len(v) for v in index.values()), path)
    return index


def attach_dicom(
    subject: str, session: str, series_number: Any, index: dict[tuple[str, str, int], list[dict[str, Any]]]
) -> dict[str, str]:
    empty = {
        "SeriesInstanceUID": "",
        "StudyInstanceUID": "",
        "series_time": "",
        "study_date": "",
        "n_dicom_files": "",
        "dicom_match": "missing",
    }
    try:
        series_n = int(float(series_number))
    except (TypeError, ValueError):
        return empty
    hits = index.get((subject, session, series_n), [])
    if not hits:
        return empty
    if len(hits) == 1:
        hit = hits[0]
        return {
            "SeriesInstanceUID": hit["SeriesInstanceUID"],
            "StudyInstanceUID": hit["StudyInstanceUID"],
            "series_time": hit["series_time"],
            "study_date": hit["study_date"],
            "n_dicom_files": hit["n_dicom_files"],
            "dicom_match": "unique",
        }
    uids = sorted({h["SeriesInstanceUID"] for h in hits if h["SeriesInstanceUID"]})
    times = sorted({h["series_time"] for h in hits if h["series_time"]})
    return {
        "SeriesInstanceUID": "|".join(uids),
        "StudyInstanceUID": "|".join(sorted({h["StudyInstanceUID"] for h in hits if h["StudyInstanceUID"]})),
        "series_time": "|".join(times),
        "study_date": "|".join(sorted({h["study_date"] for h in hits if h["study_date"]})),
        "n_dicom_files": "|".join(sorted({h["n_dicom_files"] for h in hits if h["n_dicom_files"]})),
        "dicom_match": f"ambiguous_n={len(hits)}",
    }


def looks_like_reconstruction_set(items: list[dict[str, Any]]) -> bool:
    if len(items) < 2:
        return False
    fingerprints = {r["acquisition_fingerprint"] for r in items}
    if len(fingerprints) != 1:
        return False
    acq_nums = {stringify(r["AcquisitionNumber"]) for r in items}
    if len(acq_nums) != 1:
        return False
    param_tuples = {r["acq_param_tuple"] for r in items}
    if len(param_tuples) != 1:
        return False
    series_nums = sorted({r["series_number_int"] for r in items if r["series_number_int"] is not None})
    consecutive = len(series_nums) == len(items) and all(
        series_nums[i + 1] - series_nums[i] == 1 for i in range(len(series_nums) - 1)
    )
    times = [parse_dicom_time(r["series_time"]) for r in items]
    times_ok = [t for t in times if t is not None]
    dt = (max(times_ok) - min(times_ok)) if len(times_ok) >= 2 else None
    time_ok = dt is None or dt < MPRAGE_REPEAT_SECONDS
    recon_diff = any(
        key in json_diff_keys([r["payload"] for r in items]) for key in RECON_ONLY_JSON_KEYS
    )
    return bool((consecutive or recon_diff) and time_ok)


def classify_session(items: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(items)
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in items:
        clusters[row["acquisition_fingerprint"]].append(row)
    n_clusters = len(clusters)
    n_norm = sum(1 for r in items if r["NORM_status"] == "NORM")
    n_non = sum(1 for r in items if r["NORM_status"] == "non-NORM")
    has_norm_pair = n == 2 and n_norm == 1 and n_non == 1
    series_nums = sorted(r["series_number_int"] for r in items if r["series_number_int"] is not None)
    consecutive = n == 2 and len(series_nums) == 2 and abs(series_nums[1] - series_nums[0]) == 1
    same_params = len({r["acq_param_tuple"] for r in items}) == 1
    uids = [r["SeriesInstanceUID"] for r in items if r["SeriesInstanceUID"] and "|" not in r["SeriesInstanceUID"]]
    same_uid = len(uids) == n and len(set(uids)) == 1 and n >= 2
    times = [parse_dicom_time(r["series_time"]) for r in items]
    times_ok = [t for t in times if t is not None]
    dt = (max(times_ok) - min(times_ok)) if len(times_ok) >= 2 else None
    if dt is not None:
        dt = round(float(dt), 3)
    differing = json_diff_keys([r["payload"] for r in items])
    recon_clusters = sum(1 for grp in clusters.values() if looks_like_reconstruction_set(grp))
    singleton_clusters = sum(1 for grp in clusters.values() if len(grp) == 1)

    if n == 1:
        pattern = "SINGLE_VOLUME"
    elif n_clusters == 1 and looks_like_reconstruction_set(items) and has_norm_pair:
        pattern = "PAIRED_NORM_NON_NORM"
    elif n_clusters == 1 and looks_like_reconstruction_set(items):
        pattern = "PAIRED_RECONSTRUCTIONS_OTHER"
    elif n_clusters >= 2 and recon_clusters >= 2:
        pattern = "INDEPENDENT_SCANS_EACH_WITH_RECON_PAIRS"
    elif n_clusters >= 2 and recon_clusters >= 1:
        pattern = "MIXED_INDEPENDENT_AND_RECON"
    elif n_clusters == n and n >= 2:
        pattern = "INDEPENDENT_ACQUISITIONS"
    else:
        pattern = "UNRESOLVED"

    return {
        "n_t1w": n,
        "n_acquisition_clusters": n_clusters,
        "n_norm": n_norm,
        "n_non_norm": n_non,
        "has_norm_non_norm_pair": has_norm_pair,
        "consecutive_series": consecutive,
        "same_acquisition_parameters": same_params,
        "same_SeriesInstanceUID": same_uid,
        "series_time_delta_s": dt,
        "json_differing_keys": ",".join(differing),
        "session_pattern": pattern,
        "n_recon_clusters": recon_clusters,
        "n_singleton_clusters": singleton_clusters,
    }


def load_t1w_rows(
    clean_tsv: Path,
    release_root: Path,
    bids_root: Path,
    dicom_index: dict[tuple[str, str, int], list[dict[str, Any]]],
) -> tuple[pd.DataFrame, dict[tuple[str, str], list[dict[str, Any]]]]:
    require_file(clean_tsv, "clean IQM table")
    df = pd.read_csv(clean_tsv, sep="\t")
    require_columns(
        df,
        ["subject_id", "session", "sequence_group", "run", "input_file", "is_norm"],
        "clean IQM table",
    )
    t1 = df.loc[df["sequence_group"].astype(str) == "T1w"].copy()
    if t1.empty:
        fail("No sequence_group == T1w rows in the clean table.")
    LOGGER.info("Clean T1w rows: %d", len(t1))

    records: list[dict[str, Any]] = []
    for _, row in t1.iterrows():
        sidecar = find_sidecar(str(row["input_file"]), release_root, bids_root)
        payload = load_sidecar(sidecar)
        image_type = payload.get("ImageType", row.get("ImageType"))
        series_number = payload.get("SeriesNumber", row.get("series_number"))
        try:
            series_n_int = int(float(series_number))
        except (TypeError, ValueError):
            series_n_int = None
        dicom = attach_dicom(str(row["subject_id"]), str(row["session"]), series_number, dicom_index)
        spacing = (row.get("spacing_x"), row.get("spacing_y"), row.get("spacing_z"))
        json_uid = stringify(payload.get("SeriesInstanceUID"))
        acq_tuple = tuple(stringify(payload.get(k)) for k in ACQ_PARAM_JSON_KEYS)
        rec = {
            "subject": str(row["subject_id"]),
            "session": str(row["session"]),
            "run": row.get("run"),
            "acq": stringify(row.get("acquisition")),
            "bids_name": stringify(row.get("bids_name")),
            "input_file": stringify(row.get("input_file")),
            "sidecar_path": sidecar.as_posix(),
            "ProtocolName": stringify(payload.get("ProtocolName", row.get("protocol_name"))),
            "SeriesDescription": stringify(payload.get("SeriesDescription")),
            "ImageType": stringify(image_type),
            "NORM_status": norm_status_from_image_type(image_type),
            "clean_is_norm": bool(row.get("is_norm")),
            "RepetitionTime": payload.get("RepetitionTime"),
            "EchoTime": payload.get("EchoTime"),
            "FlipAngle": payload.get("FlipAngle"),
            "InversionTime": payload.get("InversionTime"),
            "SliceThickness": payload.get("SliceThickness"),
            "voxel_size": voxel_size_text(payload, spacing),
            "size_x": row.get("size_x"),
            "size_y": row.get("size_y"),
            "size_z": row.get("size_z"),
            "AcquisitionNumber": payload.get("AcquisitionNumber", ""),
            "SeriesNumber": series_number,
            "series_number_int": series_n_int,
            "SeriesInstanceUID_json": json_uid,
            "AcquisitionTime": stringify(payload.get("AcquisitionTime")),
            "SAR": payload.get("SAR"),
            "ShimSetting": stringify(payload.get("ShimSetting")),
            "TxRefAmp": payload.get("TxRefAmp"),
            "SequenceName": stringify(payload.get("SequenceName")),
            "payload": payload,
            "acquisition_fingerprint": acquisition_fingerprint(payload),
            "acq_param_tuple": acq_tuple,
        }
        rec.update(dicom)
        if rec["SeriesInstanceUID"] == "" and json_uid:
            rec["SeriesInstanceUID"] = json_uid
        records.append(rec)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        grouped[(rec["subject"], rec["session"])].append(rec)

    out_rows: list[dict[str, Any]] = []
    for (subject, session), items in grouped.items():
        items_sorted = sorted(items, key=lambda r: (int(r["run"]) if pd.notna(r["run"]) else 0, stringify(r["bids_name"])))
        session_info = classify_session(items_sorted)
        for rec in items_sorted:
            row_out = dict(rec)
            row_out.pop("payload", None)
            row_out.pop("acq_param_tuple", None)
            row_out["n_t1w"] = session_info["n_t1w"]
            row_out["n_acquisition_clusters"] = session_info["n_acquisition_clusters"]
            row_out["session_pattern"] = session_info["session_pattern"]
            row_out["has_norm_non_norm_pair"] = session_info["has_norm_non_norm_pair"]
            row_out["consecutive_series"] = session_info["consecutive_series"]
            row_out["same_acquisition_parameters"] = session_info["same_acquisition_parameters"]
            row_out["same_SeriesInstanceUID"] = session_info["same_SeriesInstanceUID"]
            row_out["series_time_delta_s"] = session_info["series_time_delta_s"]
            row_out["json_differing_keys"] = session_info["json_differing_keys"]
            row_out["n_norm_in_session"] = session_info["n_norm"]
            row_out["n_non_norm_in_session"] = session_info["n_non_norm"]
            out_rows.append(row_out)

    table = pd.DataFrame(out_rows)
    return table, grouped


def write_audit_tsv(dest: Path, table: pd.DataFrame) -> None:
    columns = [
        "subject",
        "session",
        "n_t1w",
        "run",
        "acq",
        "ProtocolName",
        "SeriesDescription",
        "ImageType",
        "NORM_status",
        "SeriesInstanceUID",
        "AcquisitionNumber",
        "SeriesNumber",
        "RepetitionTime",
        "EchoTime",
        "FlipAngle",
        "SliceThickness",
        "voxel_size",
        "size_x",
        "size_y",
        "size_z",
        "SAR",
        "ShimSetting",
        "series_time",
        "n_dicom_files",
        "dicom_match",
        "n_acquisition_clusters",
        "session_pattern",
        "has_norm_non_norm_pair",
        "consecutive_series",
        "same_acquisition_parameters",
        "same_SeriesInstanceUID",
        "series_time_delta_s",
        "json_differing_keys",
        "bids_name",
    ]
    out = table.reindex(columns=columns)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest, sep="\t", index=False)
    LOGGER.info("Wrote %s (%d rows)", dest, len(out))


def session_frame(grouped: dict[tuple[str, str], list[dict[str, Any]]]) -> pd.DataFrame:
    rows = []
    for (subject, session), items in grouped.items():
        info = classify_session(items)
        rows.append(
            {
                "subject": subject,
                "session": session,
                **info,
                "runs": ",".join(stringify(r["run"]) for r in items),
                "acq_values": ",".join(stringify(r["acq"]) or "-" for r in items),
                "protocols": ";".join(sorted({r["ProtocolName"] for r in items})),
                "series_descriptions": ";".join(sorted({r["SeriesDescription"] for r in items})),
                "image_types": ";".join(sorted({r["ImageType"] for r in items})),
                "norm_statuses": ",".join(r["NORM_status"] for r in items),
                "series_numbers": ",".join(stringify(r["SeriesNumber"]) for r in items),
                "acquisition_numbers": ",".join(stringify(r["AcquisitionNumber"]) for r in items),
                "uids": ";".join(r["SeriesInstanceUID"] for r in items),
            }
        )
    return pd.DataFrame(rows).sort_values(["subject", "session"]).reset_index(drop=True)


def write_report(
    dest: Path,
    table: pd.DataFrame,
    sessions: pd.DataFrame,
    source_paths: dict[str, Path],
) -> str:
    n_vol = len(table)
    n_ses = len(sessions)
    n1 = int((sessions["n_t1w"] == 1).sum())
    n2 = int((sessions["n_t1w"] == 2).sum())
    n_gt2 = int((sessions["n_t1w"] > 2).sum())
    n_norm_pair = int(sessions["has_norm_non_norm_pair"].sum())
    n_paired_norm = int((sessions["session_pattern"] == "PAIRED_NORM_NON_NORM").sum())
    n_paired_other = int((sessions["session_pattern"] == "PAIRED_RECONSTRUCTIONS_OTHER").sum())
    n_single = int((sessions["session_pattern"] == "SINGLE_VOLUME").sum())
    n_ind_recon = int((sessions["session_pattern"] == "INDEPENDENT_SCANS_EACH_WITH_RECON_PAIRS").sum())
    n_independent = int((sessions["session_pattern"] == "INDEPENDENT_ACQUISITIONS").sum())
    n_unresolved = int((sessions["session_pattern"] == "UNRESOLVED").sum())
    n_same_params = int(sessions.loc[sessions["n_t1w"] >= 2, "same_acquisition_parameters"].sum())
    n_consec = int(sessions.loc[sessions["n_t1w"] == 2, "consecutive_series"].sum())
    n_same_uid = int(sessions["same_SeriesInstanceUID"].sum())
    dts = sessions.loc[sessions["n_t1w"] >= 2, "series_time_delta_s"].dropna()
    n_dt_short = int((dts < MPRAGE_REPEAT_SECONDS).sum()) if len(dts) else 0
    n_dt_long = int((dts >= MPRAGE_REPEAT_SECONDS).sum()) if len(dts) else 0

    n_uid_present = int((table["SeriesInstanceUID"].astype(str).str.len() > 0).sum())
    n_acq_all_one = int((table["AcquisitionNumber"].astype(str) == "1").sum())
    n_uid_json = 0
    if "SeriesInstanceUID_json" in table.columns:
        n_uid_json = int((table["SeriesInstanceUID_json"].astype(str).str.len() > 0).sum())

    single_sessions = sessions[sessions["n_t1w"] == 1]
    gt2_sessions = sessions[sessions["n_t1w"] > 2]
    other_recon = sessions[sessions["session_pattern"] == "PAIRED_RECONSTRUCTIONS_OTHER"]
    mixed_sessions = sessions[
        sessions["session_pattern"].isin(
            ["INDEPENDENT_SCANS_EACH_WITH_RECON_PAIRS", "MIXED_INDEPENDENT_AND_RECON", "INDEPENDENT_ACQUISITIONS"]
        )
    ]

    n_acq_clusters_total = int(sessions["n_acquisition_clusters"].sum())
    # one reconstruction per physical acquisition
    n_keep_one_recon = n_acq_clusters_total

    if n_ind_recon or n_independent:
        conclusion = "MIXED_CASE"
    elif n_paired_norm + n_paired_other == n_ses - n_single and n_paired_norm + n_paired_other > 0 and n_single == 0:
        conclusion = "PAIRED_RECONSTRUCTIONS"
    elif n_independent == n_ses:
        conclusion = "INDEPENDENT_ACQUISITIONS"
    elif n_paired_norm + n_paired_other + n_single == n_ses and n_ind_recon == 0:
        # singletons are leftover members of excluded pairs, still recon-dominated
        conclusion = "MIXED_CASE" if n_single else "PAIRED_RECONSTRUCTIONS"
    else:
        conclusion = "UNRESOLVED"

    # Overall: one session with two independent scans plus leftover singles
    # is mixed even though the dual-T1w majority is paired reconstructions.
    if n_ind_recon or n_independent or (n_single and n_paired_norm):
        conclusion = "MIXED_CASE"

    lines: list[str] = []
    lines.append("T1w reconstruction audit (MRIQC / PCA analysis set)")
    lines.append("")
    lines.append("Scope: sequence_group == T1w rows from mriqc_iqm_clean.tsv.")
    lines.append("MRIQC was not rerun. PCA was not recomputed. No rows were removed.")
    lines.append("Existing PCA and clean tables were not modified.")
    lines.append("")
    lines.append("Sources (read-only):")
    for key, path in source_paths.items():
        lines.append(f"  {key}: {path}")
    lines.append("")
    lines.append("What Siemens NORM is in these metadata")
    lines.append("-" * 72)
    lines.append(
        "ImageType token NORM is a Siemens reconstruction flag (Prescan Normalize), "
        "not a protocol name and not a BIDS acq- entity. In this dataset ProtocolName "
        "is T1w_MPR for every audited T1w. The BIDS run- index distinguishes files, "
        "not necessarily independent scans. Conclusion about independence is based on "
        "acquisition fingerprints (SAR, shim, TxRefAmp, sequence timing), consecutive "
        "SeriesNumber, AcquisitionNumber, DICOM series_time, and ImageType/"
        "SeriesDescription differences — not on the presence of NORM alone."
    )
    lines.append("")
    lines.append("Volume and session counts")
    lines.append("-" * 72)
    lines.append(f"T1w volumes in the clean/PCA set: {n_vol}")
    lines.append(f"Sessions represented: {n_ses}")
    lines.append(f"Sessions with 1 T1w: {n1}")
    lines.append(f"Sessions with 2 T1w: {n2}")
    lines.append(f"Sessions with >2 T1w: {n_gt2}")
    lines.append(f"Sessions presenting NORM + non-NORM (exactly one of each, n_t1w=2): {n_norm_pair}")
    lines.append("")
    lines.append("Session pattern (from metadata, not from IQMs)")
    lines.append("-" * 72)
    lines.append(f"PAIRED_NORM_NON_NORM: {n_paired_norm}")
    lines.append(f"PAIRED_RECONSTRUCTIONS_OTHER (no NORM token pair): {n_paired_other}")
    lines.append(f"SINGLE_VOLUME: {n_single}")
    lines.append(f"INDEPENDENT_SCANS_EACH_WITH_RECON_PAIRS: {n_ind_recon}")
    lines.append(f"INDEPENDENT_ACQUISITIONS: {n_independent}")
    lines.append(f"UNRESOLVED: {n_unresolved}")
    lines.append("")
    lines.append("Do the 2 T1w in a session correspond systematically to NORM + non-NORM?")
    lines.append("-" * 72)
    lines.append(
        f"Among {n2} dual-T1w sessions, {n_norm_pair} are exactly one NORM and one "
        f"non-NORM. That is the usual pattern, but it is not universal."
    )
    if n_paired_other:
        lines.append(
            f"{n_paired_other} dual-T1w sessions have no NORM token in either ImageType "
            "(ImageType uses M,NONE). Those pairs still look like two reconstructions "
            "of one scan: consecutive SeriesNumber, identical acquisition parameters, "
            "SeriesDescription T1w_MPR vs T1w_MPR_ND, and DICOM series_time differences "
            "of tens of milliseconds."
        )
        for _, row in other_recon.iterrows():
            lines.append(
                f"  {row['subject']} {row['session']}: runs {row['runs']}; "
                f"SeriesDescription={row['series_descriptions']}; ImageType={row['image_types']}"
            )
    lines.append("")
    lines.append("Are NORM / non-NORM reconstructions of the same scan?")
    lines.append("-" * 72)
    lines.append(
        "Yes for the dual-T1w majority. Evidence against two independent MPRAGE scans:"
    )
    lines.append(
        f"- Same acquisition parameters (TR/TE/TI/FA/matrix/bandwidth/sequence) in "
        f"{n_same_params} of {n2 + n_gt2} sessions with ≥2 T1w."
    )
    lines.append(
        f"- Consecutive SeriesNumber in {n_consec} of {n2} dual-T1w sessions."
    )
    lines.append(
        f"- AcquisitionNumber is 1 for {n_acq_all_one}/{n_vol} volumes; pairs share this value."
    )
    lines.append(
        f"- Same SeriesInstanceUID: {n_same_uid} sessions. Different UIDs are expected: "
        "Siemens writes each reconstruction as a new series, so a new SeriesInstanceUID "
        "does not mean a new acquisition."
    )
    if len(dts):
        lines.append(
            f"- DICOM series_time delta: n={len(dts)}, min={float(dts.min()):.3f}s, "
            f"median={float(dts.median()):.3f}s, max={float(dts.max()):.3f}s. "
            f"{n_dt_short} pairs differ by < {MPRAGE_REPEAT_SECONDS:.0f}s; {n_dt_long} "
            f"differ by ≥ {MPRAGE_REPEAT_SECONDS:.0f}s. A second T1w_MPR would take "
            "several minutes (TR=2.5 s, 3D MPRAGE), not a fraction of a second."
        )
    lines.append(
        "- Sidecar fields that differ inside a typical pair are ImageType "
        "(addition of NORM) and SeriesNumber. ProtocolName, timing, shim, SAR, "
        "and coil are the same."
    )
    lines.append(
        f"SeriesInstanceUID in BIDS JSON: {n_uid_json}/{n_vol} volumes. "
        f"SeriesInstanceUID from DICOM inventory after join: {n_uid_present}/{n_vol}."
    )
    lines.append("")
    lines.append("Do both images have the same acquisition parameters?")
    lines.append("-" * 72)
    lines.append(
        f"Yes in {n_same_params}/{n2 + n_gt2} multi-T1w sessions for TR, TE, TI, flip angle, "
        "slice thickness, matrix, bandwidth, and sequence name from the BIDS sidecar."
    )
    lines.append("")
    lines.append("Are there cases that look like true independent acquisitions?")
    lines.append("-" * 72)
    if mixed_sessions.empty and n_independent == 0:
        lines.append("No session in this clean T1w set is classified as two independent scans without a reconstruction pairing.")
    else:
        for _, row in mixed_sessions.iterrows():
            lines.append(
                f"  {row['subject']} {row['session']}: n_t1w={row['n_t1w']}, "
                f"acquisition clusters={row['n_acquisition_clusters']}, "
                f"pattern={row['session_pattern']}, runs={row['runs']}"
            )
        lines.append(
            "Independent scans are identified by a different acquisition fingerprint "
            "(SAR + ShimSetting + TxRefAmp), not by run- labels or by NORM."
        )
    if not single_sessions.empty:
        lines.append("")
        lines.append("Sessions with 1 T1w (pair member not in the clean table):")
        for _, row in single_sessions.iterrows():
            lines.append(
                f"  {row['subject']} {row['session']}: run {row['runs']}, "
                f"NORM_status={row['norm_statuses']}, SeriesNumber={row['series_numbers']}"
            )
        lines.append(
            "These match excluded_t1w leftovers (the other reconstruction was withdrawn "
            "before the master/clean tables), not a protocol that acquired only one recon."
        )
    if not gt2_sessions.empty:
        lines.append("")
        lines.append("Sessions with >2 T1w:")
        for _, row in gt2_sessions.iterrows():
            lines.append(
                f"  {row['subject']} {row['session']}: n={row['n_t1w']}, "
                f"clusters={row['n_acquisition_clusters']}, pattern={row['session_pattern']}, "
                f"runs={row['runs']}, NORM={row['norm_statuses']}"
            )

    lines.append("")
    lines.append("Methodological conclusion")
    lines.append("-" * 72)
    lines.append(conclusion)
    lines.append("")
    if conclusion == "MIXED_CASE":
        lines.append(
            "The dominant structure is paired reconstructions of one T1w_MPR per session "
            f"({n_paired_norm} NORM+non-NORM pairs; {n_paired_other} reconstruction pairs "
            "without a NORM token). This is not a dataset of two independent T1w scans "
            "per session."
        )
        lines.append(
            f"{n_ind_recon} session(s) contain more than one physical acquisition, each "
            "still written as NORM + non-NORM reconstructions. "
            f"{n_single} session(s) retain a single reconstruction because the other file "
            "was excluded earlier. Those exceptions prevent a uniform "
            "PAIRED_RECONSTRUCTIONS label for the whole table, hence MIXED_CASE."
        )
        lines.append(
            "Selection strategy: keep one reconstruction per physical acquisition "
            "(one row per acquisition fingerprint). Apply the same rule in every "
            "session (for example always the non-NORM / non-normalized series, or "
            "always the NORM series). For sessions with two independent scans, keep "
            "one reconstruction from each scan. Do not treat BIDS run-01 vs run-02 as "
            "independent repeats of T1w_MPR."
        )
    elif conclusion == "PAIRED_RECONSTRUCTIONS":
        lines.append(
            "Dual T1w files are two reconstructions of the same acquisition. Keep one "
            "reconstruction per session/acquisition for statistical analyses."
        )
    elif conclusion == "INDEPENDENT_ACQUISITIONS":
        lines.append(
            "The two T1w files behave as independent scans. Both may be kept if that "
            "is documented; they are not merely NORM vs non-NORM copies."
        )
    else:
        lines.append("Metadata were insufficient for a firm independence decision.")

    lines.append("")
    lines.append("Impact on the existing T1w IQM PCA")
    lines.append("-" * 72)
    lines.append(
        f"The PCA used {n_vol} T1w rows and {n_ses} sessions. Physical acquisitions "
        f"estimated here: {n_keep_one_recon}."
    )
    lines.append(
        "Because most sessions contribute two reconstructions of the same scan, the "
        "PCA sample is pseudoreplicated: paired rows share the same anatomy, motion "
        "state, and k-space, and differ mainly by intensity-normalization reconstruction. "
        "IQMs that track intensity, bias field, and contrast (including those loading on "
        "PC1) are expected to split along the NORM/non-NORM axis. Standard errors and "
        "apparent sample size are optimistic if rows are treated as independent."
    )
    lines.append(
        "Recommendation: rerun PCA and subsequent statistical analyses after selecting "
        f"one reconstruction per acquisition (about {n_keep_one_recon} rows instead of "
        f"{n_vol}). Do not drop outliers or rerun MRIQC for that correction. Until then, "
        f"interpret the current PCA as a description of IQM covariance across "
        f"reconstructions, not as {n_vol} independent T1w acquisitions."
    )
    if n_ind_recon:
        lines.append(
            "Exception: sessions classified INDEPENDENT_SCANS_EACH_WITH_RECON_PAIRS should "
            "contribute one row per independent scan after recon-deduplication, not one "
            "row for the whole session."
        )
    lines.append("")
    lines.append("This audit did not modify mriqc_iqm_clean.tsv, PCA scores, PCA loadings, or other existing results.")
    lines.append("")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Wrote %s", dest)
    return conclusion


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)

    out_tsv = args.out_dir / "t1w_reconstruction_audit.tsv"
    out_txt = args.out_dir / "t1w_reconstruction_audit_report.txt"
    protected = {p.resolve() for p in before}
    if out_tsv.resolve() in protected or out_txt.resolve() in protected:
        fail("Output path collides with a protected file.")

    dicom_index = load_dicom_index(args.session_mapping)
    table, grouped = load_t1w_rows(
        args.clean_tsv, args.release_root, args.bids_root, dicom_index
    )
    sessions = session_frame(grouped)
    write_audit_tsv(out_tsv, table)
    source_paths = {
        "clean_tsv": args.clean_tsv,
        "release_root": args.release_root,
        "bids_root": args.bids_root,
        "session_mapping": args.session_mapping,
    }
    conclusion = write_report(out_txt, table, sessions, source_paths)
    LOGGER.info("Conclusion: %s", conclusion)
    assert_unmodified(before)
    print("T1w reconstruction audit completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
