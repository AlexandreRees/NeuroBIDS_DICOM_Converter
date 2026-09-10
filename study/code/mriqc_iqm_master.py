#!/usr/bin/env python3
"""ÉTAPE 1 — Build the anatomical MRIQC IQM master dataframe.

One row per T1w / WM-nulled acquisition. Does not modify MRIQC originals,
does not re-run MRIQC, and does not include fMRI.

Example:
  python code/mriqc_iqm_master.py
  python code/mriqc_iqm_master.py --help
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import (
    DEFAULT_SCRATCH,
    EXPECTED_COHORTS,
    LOGGER,
    PROTOCOL_TO_SEQUENCE_GROUP,
    REQUIRED_METRICS_COLUMNS,
    bids_name_from_input,
    configure_logging,
    default_paths,
    fail,
    is_norm_image_type,
    normalize_cohort,
    normalize_run,
    parse_bids_stem,
    read_json,
    require_columns,
    require_file,
    sequence_group_from_protocol,
    sidecar_protocol,
)

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    paths = default_paths(DEFAULT_SCRATCH)
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Mapping assumptions are documented in mriqc_iqm_lib.py and written "
            "into the QC report. Unknown ProtocolName, ambiguous duplicate keys, "
            "or unpackaged/unlinked anatomical IQMs cause a hard failure."
        ),
    )
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH, help="Project scratch root.")
    parser.add_argument("--release-root", type=Path, default=None, help="BIDS release_dataset root.")
    parser.add_argument("--metrics", type=Path, default=None, help="Packaged MRIQC metrics CSV.")
    parser.add_argument("--mriqc-dir", type=Path, default=None, help="Native MRIQC JSON directory (read-only).")
    parser.add_argument("--study-root", type=Path, default=None, help="Output study directory.")
    parser.add_argument("--master-tsv", type=Path, default=None)
    parser.add_argument("--summary-json", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    resolved = default_paths(args.scratch)
    args.release_root = args.release_root or resolved["release"]
    args.metrics = args.metrics or resolved["metrics"]
    args.mriqc_dir = args.mriqc_dir or resolved["mriqc_derivatives"]
    args.study_root = args.study_root or resolved["study"]
    args.master_tsv = args.master_tsv or (args.study_root / "metadata" / "mriqc_iqm_master.tsv")
    args.summary_json = args.summary_json or (
        args.study_root / "metadata" / "mriqc_iqm_master_summary.json"
    )
    args.report = args.report or (args.study_root / "qc_reports" / "mriqc_iqm_master_report.txt")
    args.log_file = args.log_file or (args.study_root / "qc_reports" / "mriqc_iqm_master.log")
    args.excluded_t1w = args.release_root / "docs" / "quality_control" / "excluded_t1w.tsv"
    args.failures = args.release_root / "docs" / "quality_control" / "mriqc" / "mriqc_failures.csv"
    args.participants_release = args.release_root / "participants.tsv"
    args.participants_age = args.scratch / "metadata" / "participants.tsv"
    args.sessions = args.scratch / "metadata" / "sessions.tsv"
    args.session_summary = (
        args.release_root / "docs" / "dataset" / "participant_session_summary.tsv"
    )
    args.sequence_inventory = (
        args.release_root / "docs" / "inventory" / "sequence_inventory.csv"
    )
    return args


def load_table(path: Path, what: str, **kwargs: Any) -> pd.DataFrame:
    require_file(path, what)
    sep = kwargs.pop("sep", None)
    if sep is None:
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
    df = pd.read_csv(path, sep=sep, **kwargs)
    LOGGER.info("Loaded %s: %s (%d rows, %d cols)", what, path, len(df), df.shape[1])
    return df


def discover_packaged_t1w(release_root: Path) -> pd.DataFrame:
    rows = []
    for nii in sorted(release_root.glob("sub-*/ses-*/anat/*_T1w.nii.gz")):
        rel = nii.relative_to(release_root).as_posix()
        stem = nii.name.replace(".nii.gz", "")
        meta = parse_bids_stem(stem)
        if not meta["participant_id"] or not meta["session_id"]:
            fail(f"Cannot parse subject/session from packaged T1w: {rel}")
        if meta["suffix"] != "T1w":
            fail(f"Packaged file globbed as T1w but suffix parsed as {meta['suffix']!r}: {rel}")
        sidecar = nii.with_name(stem + ".json")
        protocol = sidecar_protocol(sidecar)
        payload = read_json(sidecar)
        rows.append(
            {
                "input_file": rel,
                "bids_name": stem,
                "subject_id": meta["participant_id"],
                "session": meta["session_id"],
                "run": normalize_run(meta["run"]),
                "acquisition": meta["acquisition"],
                "protocol_name": protocol,
                "sequence_group": sequence_group_from_protocol(protocol, sidecar),
                "sidecar_path": sidecar.relative_to(release_root).as_posix(),
                "ImageType": _image_type_str(payload.get("ImageType")),
                "is_norm": is_norm_image_type(payload.get("ImageType")),
                "te_s": payload.get("EchoTime"),
                "tr_s": payload.get("RepetitionTime"),
                "ti_s": payload.get("InversionTime"),
                "flip_angle_deg": payload.get("FlipAngle"),
                "scanner": payload.get("ManufacturersModelName"),
                "coil": payload.get("ReceiveCoilName"),
                "series_number": payload.get("SeriesNumber"),
            }
        )
    if not rows:
        fail(f"No packaged T1w NIfTI found under {release_root}")
    return pd.DataFrame(rows)


def _image_type_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(str(x) for x in value)
    return str(value)


def discover_mriqc_t1w_json(mriqc_dir: Path) -> list[Path]:
    if not mriqc_dir.is_dir():
        fail(f"MRIQC derivatives directory not found: {mriqc_dir}")
    return sorted(mriqc_dir.glob("sub-*/ses-*/anat/*_T1w.json"))


def excluded_stems(df: pd.DataFrame) -> set[str]:
    require_columns(df, ["filename"], "excluded_t1w")
    stems = set()
    for name in df["filename"].astype(str):
        stems.add(name.replace(".nii.gz", "").replace(".json", ""))
    return stems


def failure_t1w_files(df: pd.DataFrame) -> set[str]:
    require_columns(df, ["input_file"], "mriqc_failures")
    t1 = df[df["input_file"].astype(str).str.contains("_T1w", regex=False)].copy()
    return set(t1["input_file"].astype(str))


def inventory_protocol_table(inv: pd.DataFrame) -> pd.DataFrame:
    require_columns(
        inv,
        ["participant_id", "session_id", "protocol_name", "cohort"],
        "sequence_inventory",
    )
    inv = inv.copy()
    inv["cohort"] = inv["cohort"].map(normalize_cohort)
    inv["protocol_name"] = inv["protocol_name"].astype(str)
    named: dict[str, tuple[str, Any]] = {
        "inventory_n_series": ("protocol_name", "size"),
        "inventory_cohort": ("cohort", "first"),
    }
    if "n_dicom_files" in inv.columns:
        named["inventory_n_dicom"] = ("n_dicom_files", "sum")
    else:
        named["inventory_n_dicom"] = ("protocol_name", "size")
    if "exclusion_status" in inv.columns:
        named["inventory_exclusion_status"] = (
            "exclusion_status",
            lambda s: "|".join(sorted({str(x) for x in s.dropna()})),
        )
    grouped = (
        inv.groupby(["participant_id", "session_id", "protocol_name"], dropna=False)
        .agg(**named)
        .reset_index()
        .rename(
            columns={
                "participant_id": "subject_id",
                "session_id": "session",
            }
        )
    )
    return grouped


def participants_tables(release_path: Path, age_path: Path) -> pd.DataFrame:
    rel = load_table(release_path, "release participants")
    require_columns(rel, ["participant_id", "cohort", "sex"], "release participants")
    rel["cohort"] = rel["cohort"].map(normalize_cohort)
    age = load_table(age_path, "participants with age")
    require_columns(age, ["participant_id", "cohort", "sex", "age"], "participants with age")
    age["cohort"] = age["cohort"].map(normalize_cohort)
    merged = rel.merge(
        age,
        on="participant_id",
        how="outer",
        suffixes=("_release", "_age"),
        indicator=True,
    )
    mismatches = []
    if (merged["_merge"] != "both").any():
        extra = merged.loc[merged["_merge"] != "both", ["participant_id", "_merge"]]
        mismatches.append(f"participant table mismatch:\n{extra.to_string(index=False)}")
    cohort_mismatch = merged["cohort_release"] != merged["cohort_age"]
    sex_mismatch = merged["sex_release"].astype(str) != merged["sex_age"].astype(str)
    if cohort_mismatch.any() or sex_mismatch.any():
        bad = merged.loc[cohort_mismatch | sex_mismatch]
        mismatches.append(f"cohort/sex mismatch between participant tables:\n{bad.to_string(index=False)}")
    unknown = set(merged["cohort_age"].dropna()) - set(EXPECTED_COHORTS)
    if unknown:
        mismatches.append(f"unexpected cohort labels: {sorted(unknown)}")
    if mismatches:
        fail("Participant metadata is not consistent.\n" + "\n".join(mismatches))
    out = pd.DataFrame(
        {
            "subject_id": merged["participant_id"],
            "cohort": merged["cohort_age"],
            "sex": merged["sex_age"],
            "age": merged["age"],
        }
    )
    if out["age"].isna().any():
        missing = out.loc[out["age"].isna(), "subject_id"].tolist()
        LOGGER.warning("Age missing for %d subjects: %s", len(missing), missing)
    return out


def session_cohort_lookup(sessions: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    require_columns(sessions, ["participant_id", "session_id", "cohort"], "sessions.tsv")
    require_columns(
        summary,
        ["participant_id", "session_id", "cohort", "has_anat_T1w"],
        "participant_session_summary",
    )
    left = sessions.copy()
    left["cohort"] = left["cohort"].map(normalize_cohort)
    right = summary.copy()
    right["cohort"] = right["cohort"].map(normalize_cohort)
    merged = left.merge(
        right,
        on=["participant_id", "session_id"],
        how="outer",
        suffixes=("_sessions", "_summary"),
        indicator=True,
    )
    if (merged["_merge"] != "both").any():
        extra = merged.loc[merged["_merge"] != "both", ["participant_id", "session_id", "_merge"]]
        fail("Session inventory mismatch between sessions.tsv and participant_session_summary:\n"
             + extra.to_string(index=False))
    if (merged["cohort_sessions"] != merged["cohort_summary"]).any():
        bad = merged.loc[merged["cohort_sessions"] != merged["cohort_summary"]]
        fail("Cohort mismatch between sessions.tsv and participant_session_summary:\n"
             + bad.to_string(index=False))
    return pd.DataFrame(
        {
            "subject_id": merged["participant_id"],
            "session": merged["session_id"],
            "inventory_session_cohort": merged["cohort_sessions"],
            "has_anat_T1w": merged["has_anat_T1w"],
        }
    )


def filter_anatomical_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    require_columns(metrics, REQUIRED_METRICS_COLUMNS, "MRIQC metrics")
    anat = metrics.loc[metrics["suffix"] == "T1w"].copy()
    if anat.empty:
        fail("MRIQC metrics contain no suffix=T1w rows.")
    bad_mod = anat.loc[anat["modality"].astype(str) != "anat"]
    if not bad_mod.empty:
        fail(
            "T1w MRIQC rows with modality != anat:\n"
            + bad_mod[["participant_id", "session_id", "input_file", "modality"]].to_string(
                index=False
            )
        )
    bold_like = anat["input_file"].astype(str).str.contains("/func/", regex=False)
    if bold_like.any():
        fail("T1w-labelled MRIQC rows point at func/ files; refusing to mix fMRI IQMs.")
    return anat


def crosscheck_metrics_vs_filename(anat: pd.DataFrame) -> None:
    errors = []
    for idx, row in anat.iterrows():
        parsed = parse_bids_stem(bids_name_from_input(str(row["input_file"])))
        pid = str(row["participant_id"])
        ses = str(row["session_id"])
        if not parsed["participant_id"] or not parsed["session_id"]:
            errors.append(f"{row['input_file']}: cannot parse subject/session from filename")
            continue
        if parsed["participant_id"] != pid or parsed["session_id"] != ses:
            errors.append(
                f"{row['input_file']}: metrics ids {pid}/{ses} != filename "
                f"{parsed['participant_id']}/{parsed['session_id']}"
            )
        run_m = normalize_run(row["run"])
        run_f = normalize_run(parsed["run"])
        if run_m and run_f and run_m != run_f:
            errors.append(f"{row['input_file']}: run {run_m} != filename run {run_f}")
    if errors:
        preview = "\n".join(errors[:20])
        fail(f"{len(errors)} MRIQC rows fail subject/session/run filename checks:\n{preview}")


def build_master(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any], str]:
    metrics = load_table(args.metrics, "MRIQC metrics")
    anat_metrics = filter_anatomical_metrics(metrics)
    crosscheck_metrics_vs_filename(anat_metrics)

    packaged = discover_packaged_t1w(args.release_root)
    LOGGER.info("Packaged T1w NIfTI: %d", len(packaged))

    excluded = load_table(args.excluded_t1w, "excluded T1w")
    failures = load_table(args.failures, "MRIQC failures")
    excluded_set = excluded_stems(excluded)
    failed_files = failure_t1w_files(failures)

    participants = participants_tables(args.participants_release, args.participants_age)
    sessions = load_table(args.sessions, "sessions")
    summary = load_table(args.session_summary, "session summary")
    session_meta = session_cohort_lookup(sessions, summary)
    inventory = inventory_protocol_table(load_table(args.sequence_inventory, "sequence inventory"))

    metrics_files = set(anat_metrics["input_file"].astype(str))
    packaged_files = set(packaged["input_file"].astype(str))

    iqm_without_acquisition = sorted(metrics_files - packaged_files)
    packaged_without_iqm = sorted(packaged_files - metrics_files)
    known_failures = sorted(path for path in packaged_without_iqm if path in failed_files)
    unexpected_missing = sorted(path for path in packaged_without_iqm if path not in failed_files)

    json_paths = discover_mriqc_t1w_json(args.mriqc_dir)
    json_stems = {p.name.replace(".json", "") for p in json_paths}
    metrics_stems = {bids_name_from_input(x) for x in metrics_files}
    unmapped_json = sorted(json_stems - metrics_stems)
    unexpected_json = [s for s in unmapped_json if s not in excluded_set]
    documented_unmapped = [s for s in unmapped_json if s in excluded_set]

    errors: list[str] = []
    if iqm_without_acquisition:
        errors.append(
            "IQM rows without a packaged T1w acquisition:\n  " + "\n  ".join(iqm_without_acquisition)
        )
    if unexpected_missing:
        errors.append(
            "Packaged T1w acquisitions without MRIQC IQMs and not listed in mriqc_failures.csv:\n  "
            + "\n  ".join(unexpected_missing)
        )
    if unexpected_json:
        errors.append(
            "MRIQC JSON files not linked to a packaged acquisition and not in excluded_t1w.tsv:\n  "
            + "\n  ".join(unexpected_json)
        )

    anat_metrics = anat_metrics.copy()
    anat_metrics["bids_name"] = anat_metrics["input_file"].map(bids_name_from_input)
    anat_metrics["run"] = anat_metrics["run"].map(normalize_run)
    packaged["run"] = packaged["run"].map(normalize_run)

    overlap_drop = [
        "participant_id",
        "session_id",
        "task",
        "run",
        "suffix",
        "modality",
        "acquisition",
        "direction",
        "echo",
    ]
    metrics_join = anat_metrics.drop(
        columns=[c for c in overlap_drop if c in anat_metrics.columns]
    )
    master = packaged.merge(
        metrics_join,
        on=["input_file", "bids_name"],
        how="inner",
        indicator=True,
    )

    master = master.merge(participants, on="subject_id", how="left", indicator="part_merge")
    unmatched_people = master.loc[master["part_merge"] != "both", "subject_id"].unique().tolist()
    if unmatched_people:
        errors.append(f"Acquisitions whose subject_id is absent from participants tables: {unmatched_people}")

    master = master.merge(session_meta, on=["subject_id", "session"], how="left", indicator="ses_merge")
    unmatched_ses = master.loc[master["ses_merge"] != "both"]
    if not unmatched_ses.empty:
        errors.append(
            "Acquisitions without a session inventory row:\n"
            + unmatched_ses[["subject_id", "session", "input_file"]].to_string(index=False)
        )
    cohort_mismatch = master["cohort"].astype(str) != master["inventory_session_cohort"].astype(str)
    if cohort_mismatch.any():
        bad = master.loc[cohort_mismatch, ["subject_id", "session", "cohort", "inventory_session_cohort"]]
        errors.append("Cohort mismatch vs session inventory:\n" + bad.drop_duplicates().to_string(index=False))

    master = master.merge(
        inventory,
        on=["subject_id", "session", "protocol_name"],
        how="left",
        indicator="inv_merge",
    )
    unmapped_protocol = master.loc[master["inv_merge"] != "both"]
    if not unmapped_protocol.empty:
        errors.append(
            "Acquisitions whose ProtocolName is absent from sequence_inventory for that session:\n"
            + unmapped_protocol[["subject_id", "session", "protocol_name", "input_file"]].to_string(
                index=False
            )
        )
    inv_cohort_mismatch = (
        master["inventory_cohort"].notna()
        & (master["cohort"].astype(str) != master["inventory_cohort"].astype(str))
    )
    if inv_cohort_mismatch.any():
        bad = master.loc[
            inv_cohort_mismatch,
            ["subject_id", "session", "cohort", "inventory_cohort"],
        ].drop_duplicates()
        errors.append("Cohort mismatch vs sequence inventory:\n" + bad.to_string(index=False))

    key_cols = ["subject_id", "session", "sequence_group", "run"]
    dup_mask = master.duplicated(key_cols, keep=False)
    n_duplicated_mappings = int(dup_mask.sum())
    if dup_mask.any():
        errors.append(
            "Ambiguous duplicate subject/session/sequence_group/run rows "
            "(multiple runs of the same protocol are allowed only if run differs):\n"
            + master.loc[dup_mask, key_cols + ["input_file"]].to_string(index=False)
        )

    unknown_group = ~master["sequence_group"].isin(["T1w", "WMn"])
    if unknown_group.any():
        errors.append(
            "sequence_group outside {T1w, WMn}:\n"
            + master.loc[unknown_group, ["input_file", "protocol_name", "sequence_group"]].to_string(
                index=False
            )
        )

    if errors:
        fail("Master dataframe mapping checks failed.\n\n" + "\n\n".join(errors))

    # Drop merge indicators and redundant id columns; keep MRIQC IQMs + technical vars.
    drop_cols = [
        c
        for c in master.columns
        if c.endswith("_merge")
        or c.endswith("_metrics")
        or c in {"sidecar_path"}
    ]
    master = master.drop(columns=drop_cols, errors="ignore")

    master["modality"] = "anat"
    master["sequence"] = master["protocol_name"]
    master["mriqc_source_file"] = master["mriqc_output"].astype(str)
    master["mriqc_source_stem"] = master["bids_name"]
    master["filename"] = master["bids_name"].map(lambda s: f"{s}.nii.gz")
    master["mapping_ok"] = True
    master["mapping_notes"] = ""

    meta_front = [
        "subject_id",
        "session",
        "cohort",
        "sex",
        "age",
        "modality",
        "sequence",
        "sequence_group",
        "protocol_name",
        "acquisition",
        "run",
        "is_norm",
        "filename",
        "bids_name",
        "input_file",
        "mriqc_source_file",
        "mriqc_source_stem",
        "mriqc_version",
        "ImageType",
        "te_s",
        "tr_s",
        "ti_s",
        "flip_angle_deg",
        "scanner",
        "coil",
        "series_number",
        "inventory_n_series",
        "inventory_n_dicom",
        "inventory_cohort",
        "inventory_exclusion_status",
        "has_anat_T1w",
        "mapping_ok",
        "mapping_notes",
    ]
    skip_original_ids = {
        "participant_id",
        "session_id",
        "task",
        "suffix",
        "direction",
        "echo",
        "mriqc_output",
        "inventory_session_cohort",
    }
    remaining = [c for c in master.columns if c not in meta_front and c not in skip_original_ids]
    empty_dropped = [c for c in remaining if master[c].isna().all()]
    if empty_dropped:
        LOGGER.info(
            "Dropping %d all-missing columns from the anatomical master (BOLD/empty IQMs): %s",
            len(empty_dropped),
            empty_dropped,
        )
        remaining = [c for c in remaining if c not in empty_dropped]
    master = master[meta_front + remaining].copy()
    master = master.sort_values(["subject_id", "session", "sequence_group", "run"]).reset_index(drop=True)

    sessions_with_t1_false = session_meta.loc[
        ~session_meta["has_anat_T1w"].astype(str).str.lower().isin(["true", "1"]),
        ["subject_id", "session"],
    ]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scratch": str(args.scratch),
        "release_root": str(args.release_root),
        "metrics_file": str(args.metrics),
        "mriqc_dir": str(args.mriqc_dir),
        "n_rows": int(len(master)),
        "n_subjects": int(master["subject_id"].nunique()),
        "n_sessions": int(master.groupby(["subject_id", "session"]).ngroups),
        "n_t1w": int((master["sequence_group"] == "T1w").sum()),
        "n_wmn": int((master["sequence_group"] == "WMn").sum()),
        "n_by_cohort": {k: int(v) for k, v in master["cohort"].value_counts().sort_index().items()},
        "n_by_session": {k: int(v) for k, v in master["session"].value_counts().sort_index().items()},
        "n_by_sequence_group": {
            k: int(v) for k, v in master["sequence_group"].value_counts().sort_index().items()
        },
        "n_duplicated_mappings": n_duplicated_mappings,
        "n_unmapped_mriqc_files": len(unmapped_json),
        "documented_unmapped_mriqc_stems": documented_unmapped,
        "unexpected_unmapped_mriqc_stems": unexpected_json,
        "iqm_without_packaged_acquisition": iqm_without_acquisition,
        "packaged_without_iqm_known_failures": known_failures,
        "packaged_without_iqm_unexpected": unexpected_missing,
        "sessions_without_anat_t1w_inventory": sessions_with_t1_false.to_dict("records"),
        "missing_value_counts": {
            c: int(master[c].isna().sum())
            for c in meta_front
            if int(master[c].isna().sum()) > 0
        },
        "n_norm_reconstructions": int(master["is_norm"].sum()),
        "all_missing_columns_dropped": empty_dropped,
        "mapping_assumptions": [
            "Anatomical IQMs are suffix=T1w rows from the packaged MRIQC metrics table.",
            "sequence_group is ProtocolName from the BIDS sidecar, never inferred from run.",
            "T1w_MPR including NORM reconstructions are sequence_group=T1w.",
            "WMn_MPRAGE_sagittal is sequence_group=WMn.",
            "BOLD/fMRI IQMs are excluded.",
            "Uniqueness key is subject_id + session + sequence_group + run.",
            "Cohorts are normalized to Control, Glaucoma, Data_ON, Data_TON.",
            "Age is joined from metadata/participants.tsv.",
            "MRIQC originals are never modified.",
        ],
    }

    report = render_report(master, summary, known_failures, documented_unmapped, sessions_with_t1_false)
    return master, summary, report


def render_report(
    master: pd.DataFrame,
    summary: dict[str, Any],
    known_failures: list[str],
    documented_unmapped: list[str],
    sessions_without_t1: pd.DataFrame,
) -> str:
    missing_meta = []
    for col in ["subject_id", "session", "cohort", "sex", "age", "sequence_group", "run", "mriqc_source_file"]:
        n = int(master[col].isna().sum()) if col in master.columns else -1
        missing_meta.append(f"  {col}: {n}")

    iqm_na = []
    for col in master.columns:
        if col in {
            "subject_id",
            "session",
            "cohort",
            "sex",
            "age",
            "modality",
            "sequence",
            "sequence_group",
            "protocol_name",
            "acquisition",
            "run",
            "is_norm",
            "filename",
            "bids_name",
            "input_file",
            "mriqc_source_file",
            "mriqc_source_stem",
            "mriqc_version",
            "ImageType",
            "te_s",
            "tr_s",
            "ti_s",
            "flip_angle_deg",
            "scanner",
            "coil",
            "series_number",
            "inventory_n_series",
            "inventory_n_dicom",
            "inventory_cohort",
            "inventory_exclusion_status",
            "has_anat_T1w",
            "mapping_ok",
            "mapping_notes",
        }:
            continue
        n = int(master[col].isna().sum())
        if n:
            iqm_na.append(f"  {col}: {n} ({100.0 * n / len(master):.1f}%)")

    lines = [
        "MRIQC anatomical IQM master dataframe — QC report",
        f"generated_at: {summary['generated_at']}",
        "",
        "COUNTS",
        f"  n_rows (acquisitions): {summary['n_rows']}",
        f"  n_subjects: {summary['n_subjects']}",
        f"  n_sessions: {summary['n_sessions']}",
        f"  n_T1w: {summary['n_t1w']}",
        f"  n_WMn: {summary['n_wmn']}",
        f"  n_by_cohort: {summary['n_by_cohort']}",
        f"  n_by_session: {summary['n_by_session']}",
        f"  n_duplicated_mappings: {summary['n_duplicated_mappings']}",
        f"  n_unmapped_mriqc_files: {summary['n_unmapped_mriqc_files']}",
        "",
        "DUPLICATES",
        "  uniqueness key: subject_id, session, sequence_group, run",
        "  ambiguous duplicates: none (script would have failed)",
        "",
        "MISSING METADATA",
        *missing_meta,
        "",
        "MISSING / EMPTY IQM-LIKE COLUMNS (non-zero only)",
        *(iqm_na if iqm_na else ["  none"]),
        "",
        "ACQUISITIONS WITHOUT IQMs (documented MRIQC failures)",
        *([f"  {x}" for x in known_failures] if known_failures else ["  none"]),
        "",
        "MRIQC FILES NOT IN MASTER (withdrawn T1w listed in excluded_t1w.tsv)",
        *([f"  {x}" for x in documented_unmapped] if documented_unmapped else ["  none"]),
        "",
        "IQMs WITHOUT PACKAGED ACQUISITION",
        "  none (script would have failed)",
        "",
        "SESSIONS IN INVENTORY WITHOUT ANAT T1w (not treated as mapping failures)",
        *(
            [f"  {r.subject_id} {r.session}" for r in sessions_without_t1.itertuples(index=False)]
            if len(sessions_without_t1)
            else ["  none"]
        ),
        "",
        "MAPPING ASSUMPTIONS",
        *[f"  - {a}" for a in summary["mapping_assumptions"]],
        "",
        "SOURCES (read-only)",
        f"  metrics: {summary['metrics_file']}",
        f"  mriqc_dir: {summary['mriqc_dir']}",
        f"  release_root: {summary['release_root']}",
        "",
        "No original MRIQC files were modified.",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(master: pd.DataFrame, summary: dict[str, Any], report: str, args: argparse.Namespace) -> None:
    args.master_tsv.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    master.to_csv(args.master_tsv, sep="\t", index=False)
    args.summary_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(report, encoding="utf-8")
    LOGGER.info("Wrote %s", args.master_tsv)
    LOGGER.info("Wrote %s", args.summary_json)
    LOGGER.info("Wrote %s", args.report)


def print_summary(summary: dict[str, Any]) -> None:
    print()
    print("N subjects:", summary["n_subjects"])
    print("N sessions:", summary["n_sessions"])
    print("N T1w acquisitions:", summary["n_t1w"])
    print("N WM-nulled acquisitions:", summary["n_wmn"])
    print("N IQMs: (see étape 2)")
    print("N IQMs retained: (see étape 2)")
    print("N IQMs excluded: (see étape 2)")
    print("N missing values: (see étape 2)")
    print("N potential outliers: (see étape 2)")
    print("N unmapped MRIQC files:", summary["n_unmapped_mriqc_files"])
    print("N duplicated mappings:", summary["n_duplicated_mappings"])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(logging_level(args.verbose), args.log_file)
    LOGGER.info("Building anatomical MRIQC IQM master dataframe")
    master, summary, report = build_master(args)
    write_outputs(master, summary, report, args)
    print_summary(summary)
    return 0


def logging_level(verbose: bool) -> int:
    import logging

    return logging.DEBUG if verbose else logging.INFO


if __name__ == "__main__":
    sys.exit(main())
