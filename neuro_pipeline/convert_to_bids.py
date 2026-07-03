#!/usr/bin/env python3
"""Convert staged DICOM to BIDS using dcm2niix."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.dicom_helpers import infer_bids_modality
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.extensions import PIPELINE_VERSION, build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)

BIDS_MODALITY_FOLDERS: frozenset[str] = frozenset({"anat", "func", "dwi", "fmap", "extra"})
CORE_BIDS_MODALITIES: frozenset[str] = frozenset({"anat", "func", "dwi"})
SESSION_LABEL_PATTERN = re.compile(r"^ses-\d{2}$")
NIFTI_SUFFIXES: tuple[str, ...] = (".nii.gz", ".nii")


def load_session_mapping(paths: ProjectPaths) -> pd.DataFrame:
    """Load session-level mapping produced by generate_mapping."""
    session_csv = paths.metadata / "session_mapping.csv"
    if not session_csv.is_file():
        raise FatalPipelineError(
            f"Session mapping not found: {session_csv}. Run generate_mapping.py first."
        )
    df = pd.read_csv(session_csv, dtype=str).fillna("")
    required = {
        "participant_id",
        "session_label",
        "modality",
        "series_description",
        "representative_dicom",
        "series_instance_uid",
        "series_number",
    }
    missing = required - set(df.columns)
    if missing:
        raise FatalPipelineError(f"Session mapping missing columns: {sorted(missing)}")
    return df


def resolve_staging_session_dir(
    staging_root: Path,
    raw_original: Path,
    participant_id: str,
    source_subject_path: str,
) -> Path:
    """Resolve the staged DICOM directory for a participant session."""
    subject_path = Path(source_subject_path)
    try:
        relative = subject_path.relative_to(raw_original)
    except ValueError:
        relative = Path(subject_path.name)
    staging_dir = staging_root / participant_id / relative
    if not staging_dir.is_dir():
        raise FatalPipelineError(
            f"Staged session directory not found: {staging_dir}"
        )
    return staging_dir


def resolve_staged_representative_dicom(
    staging_root: Path,
    raw_original: Path,
    participant_id: str,
    representative_dicom: str,
) -> Path:
    """Resolve the staged path for a representative DICOM file."""
    source_path = Path(representative_dicom)
    try:
        relative = source_path.relative_to(raw_original)
    except ValueError:
        relative = Path(source_path.name)
    staged_path = staging_root / participant_id / relative
    if not staged_path.is_file():
        raise FatalPipelineError(f"Staged DICOM not found: {staged_path}")
    return staged_path


def resolve_dcm2niix_binary(dcm2niix_path: str | None) -> str:
    """Resolve dcm2niix executable path."""
    if dcm2niix_path:
        resolved = Path(dcm2niix_path)
        if not resolved.is_file():
            raise FatalPipelineError(f"dcm2niix not found at: {resolved}")
        return str(resolved)
    found = shutil.which("dcm2niix")
    if not found:
        raise FatalPipelineError(
            "dcm2niix not found on PATH. Install dcm2niix or pass --dcm2niix-path."
        )
    return found


def get_dcm2niix_version(dcm2niix_bin: str) -> str:
    """Capture dcm2niix version string for provenance."""
    result = subprocess.run(
        [dcm2niix_bin, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    version = (result.stdout or result.stderr or "").strip()
    if not version:
        help_result = subprocess.run(
            [dcm2niix_bin, "-h"],
            capture_output=True,
            text=True,
            check=False,
        )
        version = (help_result.stdout or help_result.stderr or "").splitlines()[0].strip()
    return version or "unknown"


def write_dataset_description(paths: ProjectPaths) -> None:
    """Write BIDS dataset_description.json."""
    description = {
        "Name": "Neuro BIDS Pipeline Dataset",
        "BIDSVersion": "1.8.0",
        "DatasetType": "raw",
        "Authors": ["Neuro BIDS Pipeline"],
        "GeneratedBy": [
            {
                "Name": "neuro_pipeline",
                "Version": PIPELINE_VERSION,
                "Description": "DICOM to BIDS conversion",
            }
        ],
    }
    paths.raw_bids.mkdir(parents=True, exist_ok=True)
    paths.dataset_description_json.write_text(
        json.dumps(description, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_participants_tsv(mapping: pd.DataFrame, output_path: Path) -> None:
    """Write BIDS participants.tsv from mapping."""
    participants = (
        mapping[["participant_id", "cohort", "patient_sex"]]
        .drop_duplicates(subset=["participant_id"])
        .sort_values("participant_id", kind="mergesort")
        .rename(columns={"patient_sex": "sex"})
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    participants.to_csv(output_path, sep="\t", index=False)


def bids_output_dir(
    raw_bids: Path,
    participant_id: str,
    session_label: str,
    bids_modality: str,
) -> Path:
    """Return BIDS output directory for a session/modality."""
    if session_label:
        return raw_bids / participant_id / session_label / bids_modality
    return raw_bids / participant_id / bids_modality


def normalize_bids_modality(dicom_modality: str, series_description: str) -> str:
    """Map a series to a BIDS modality folder using infer_bids_modality only."""
    label = infer_bids_modality(dicom_modality, series_description)
    if label in BIDS_MODALITY_FOLDERS - {"extra"}:
        return label
    return "extra"


def derive_task_name(series_description: str) -> str:
    """Derive a BIDS task label from a series description."""
    description = series_description.lower()
    task_match = re.search(r"task[-_ ]?([a-z0-9]+)", description)
    if task_match:
        return task_match.group(1)
    if "rest" in description:
        return "rest"
    return "rest"


def derive_fmap_direction(series_description: str) -> str:
    """Derive a BIDS phase-encoding direction label for fieldmaps."""
    description = series_description.lower()
    if re.search(r"\bpa\b", description):
        return "PA"
    if re.search(r"\bap\b", description):
        return "AP"
    if re.search(r"\blr\b", description):
        return "LR"
    if re.search(r"\brl\b", description):
        return "RL"
    return "unknown"


def build_dcm2niix_filename(
    participant_id: str,
    session_label: str,
    bids_modality: str,
    run_index: int,
    series_description: str,
) -> str:
    """Build a BIDS-safe dcm2niix output filename stem."""
    run_tag = f"run-{run_index:02d}"
    if bids_modality == "anat":
        return f"{participant_id}_{session_label}_{run_tag}_T1w"
    if bids_modality == "func":
        task = derive_task_name(series_description)
        return f"{participant_id}_{session_label}_task-{task}_{run_tag}_bold"
    if bids_modality == "dwi":
        return f"{participant_id}_{session_label}_{run_tag}_dwi"
    if bids_modality == "fmap":
        direction = derive_fmap_direction(series_description)
        return f"{participant_id}_{session_label}_dir-{direction}_{run_tag}_epi"
    return f"{participant_id}_{session_label}_{run_tag}_extra"


def nifti_matches_stem(output_dir: Path, filename_stem: str) -> list[Path]:
    """Return NIfTI files matching a BIDS filename stem."""
    matches: list[Path] = []
    for suffix in NIFTI_SUFFIXES:
        candidate = output_dir / f"{filename_stem}{suffix}"
        if candidate.is_file():
            matches.append(candidate)
    return matches


def resolve_run_index_and_filename(
    output_dir: Path,
    participant_id: str,
    session_label: str,
    bids_modality: str,
    starting_run_index: int,
    series_description: str,
) -> tuple[int, str]:
    """Select a run index whose output files do not already exist."""
    run_index = starting_run_index
    while run_index <= 99:
        filename = build_dcm2niix_filename(
            participant_id,
            session_label,
            bids_modality,
            run_index,
            series_description,
        )
        if not nifti_matches_stem(output_dir, filename):
            return run_index, filename
        LOGGER.warning(
            "Output already exists for %s; incrementing run index",
            output_dir / filename,
        )
        run_index += 1
    raise FatalPipelineError(
        f"Exceeded maximum run index for {participant_id}/{session_label}/{bids_modality}"
    )


def run_dcm2niix(
    dcm2niix_bin: str,
    source_dir: Path,
    output_dir: Path,
    filename: str,
) -> subprocess.CompletedProcess[str]:
    """Invoke dcm2niix on a source DICOM directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        dcm2niix_bin,
        "-b",
        "y",
        "-ba",
        "n",
        "-z",
        "y",
        "-f",
        filename,
        "-o",
        str(output_dir),
        str(source_dir),
    ]
    LOGGER.debug("Running: %s", " ".join(command))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def dominant_bids_modality(group: pd.DataFrame) -> str:
    """Infer the primary BIDS modality label for a session group."""
    labels = [
        normalize_bids_modality(str(row["modality"]), str(row["series_description"]))
        for _, row in group.iterrows()
    ]
    non_extra = [label for label in labels if label != "extra"]
    if not non_extra:
        return "extra"
    return sorted(non_extra)[0]


def validate_session_labels(session_mapping: pd.DataFrame) -> None:
    """Ensure session labels follow strict BIDS ses-XX formatting."""
    invalid = session_mapping[
        ~session_mapping["session_label"].map(lambda value: bool(SESSION_LABEL_PATTERN.match(value)))
    ]
    if not invalid.empty:
        labels = sorted(invalid["session_label"].unique())
        raise FatalPipelineError(
            f"Invalid session labels (expected ses-XX): {labels}"
        )


def validate_conversion_plan(planned_runs: list[dict[str, str]]) -> None:
    """Ensure no duplicate participant/session/modality/run combinations."""
    seen: set[tuple[str, str, str, str]] = set()
    duplicates: list[tuple[str, str, str, str]] = []
    for entry in planned_runs:
        key = (
            entry["participant_id"],
            entry["session_label"],
            entry["bids_modality"],
            entry["run_index"],
        )
        if key in seen:
            duplicates.append(key)
        seen.add(key)

    if duplicates:
        raise FatalPipelineError(
            "Duplicate participant/session/modality/run combinations detected: "
            f"{sorted(set(duplicates))}"
        )


def validate_bids_outputs(raw_bids: Path) -> None:
    """Verify BIDS structural and sidecar requirements after conversion."""
    subject_dirs = sorted(
        path for path in raw_bids.iterdir()
        if path.is_dir() and path.name.startswith("sub-")
    )
    if not subject_dirs:
        raise FatalPipelineError("BIDS validation failed: no subject directories found")

    for subject_dir in subject_dirs:
        relative_paths = [path.relative_to(subject_dir) for path in subject_dir.rglob("*") if path.is_file()]
        modality_folders = {
            part
            for rel_path in relative_paths
            for part in rel_path.parts
            if part in BIDS_MODALITY_FOLDERS
        }
        if not modality_folders & CORE_BIDS_MODALITIES:
            raise FatalPipelineError(
                f"BIDS validation failed: {subject_dir.name} has no anat, func, or dwi data"
            )

    nifti_files: list[Path] = []
    for subject_dir in subject_dirs:
        for path in subject_dir.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if name.endswith(".nii.gz") or name.endswith(".nii"):
                nifti_files.append(path)

    for nifti_path in sorted(nifti_files):
        if nifti_path.name.endswith(".nii.gz"):
            json_path = Path(str(nifti_path).replace(".nii.gz", ".json"))
        else:
            json_path = nifti_path.with_suffix(".json")
        if not json_path.is_file():
            raise FatalPipelineError(
                f"BIDS validation failed: missing JSON sidecar for {nifti_path}"
            )


def convert_sessions(
    session_mapping: pd.DataFrame,
    paths: ProjectPaths,
    dcm2niix_bin: str,
) -> pd.DataFrame:
    """Convert each series to BIDS with run-safe naming and per-series isolation."""
    records: list[dict[str, str]] = []

    validate_session_labels(session_mapping)

    ordered = session_mapping.sort_values(
        by=[
            "participant_id",
            "session_label",
            "series_number",
            "series_instance_uid",
        ],
        kind="mergesort",
    ).reset_index(drop=True)

    run_counters: dict[tuple[str, str, str], int] = defaultdict(int)
    planned_runs: list[dict[str, str]] = []

    for _, row in ordered.iterrows():
        participant_id = str(row["participant_id"])
        session_label = str(row["session_label"])
        series_description = str(row["series_description"])
        bids_modality = normalize_bids_modality(
            str(row["modality"]),
            series_description,
        )
        modality_key = (participant_id, session_label, bids_modality)
        run_counters[modality_key] += 1
        planned_runs.append(
            {
                "participant_id": participant_id,
                "session_label": session_label,
                "bids_modality": bids_modality,
                "run_index": f"{run_counters[modality_key]:02d}",
            }
        )

    validate_conversion_plan(planned_runs)

    run_counters = defaultdict(int)
    for _, row in ordered.iterrows():
        participant_id = str(row["participant_id"])
        session_label = str(row["session_label"])
        series_description = str(row["series_description"])
        series_instance_uid = str(row["series_instance_uid"])
        bids_modality = normalize_bids_modality(
            str(row["modality"]),
            series_description,
        )

        if bids_modality == "extra":
            LOGGER.warning(
                "Series mapped to extra/ for %s %s (%s)",
                participant_id,
                session_label,
                series_instance_uid,
            )

        modality_key = (participant_id, session_label, bids_modality)
        run_counters[modality_key] += 1
        starting_run_index = run_counters[modality_key]

        output_dir = bids_output_dir(
            paths.raw_bids,
            participant_id,
            session_label,
            bids_modality,
        )

        run_index, filename = resolve_run_index_and_filename(
            output_dir,
            participant_id,
            session_label,
            bids_modality,
            starting_run_index,
            series_description,
        )
        if run_index != starting_run_index:
            run_counters[modality_key] = run_index

        staged_dicom = resolve_staged_representative_dicom(
            paths.staging,
            paths.raw_original,
            participant_id,
            str(row["representative_dicom"]),
        )
        source_input = staged_dicom

        if nifti_matches_stem(output_dir, filename):
            LOGGER.warning(
                "Skipping conversion; BIDS output already exists: %s",
                output_dir / filename,
            )
            records.append(
                {
                    "participant_id": participant_id,
                    "session_label": session_label,
                    "series_instance_uid": series_instance_uid,
                    "dicom_modality": str(row["modality"]),
                    "bids_modality": bids_modality,
                    "run_index": f"{run_index:02d}",
                    "expected_filename": filename,
                    "source_staging_dicom": str(staged_dicom.resolve()),
                    "bids_output_dir": str(output_dir.resolve()),
                    "n_converted_files": "0",
                    "dcm2niix_returncode": "",
                    "status": "skipped",
                    "dcm2niix_stdout": "",
                    "dcm2niix_stderr": "output already exists",
                }
            )
            continue

        result = run_dcm2niix(dcm2niix_bin, source_input, output_dir, filename)
        status = "success" if result.returncode == 0 else "failed"

        log_stem = f"{participant_id}_{session_label}_{series_instance_uid}_{run_index:02d}"
        log_path = paths.conversion_logs_dir / f"{log_stem}.log"
        paths.conversion_logs_dir.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"command: dcm2niix\nreturncode: {result.returncode}\n\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}\n",
            encoding="utf-8",
        )

        if status == "failed":
            LOGGER.error(
                "dcm2niix failed for %s %s series %s (code %d)\nstdout:\n%s\nstderr:\n%s",
                participant_id,
                session_label,
                series_instance_uid,
                result.returncode,
                result.stdout,
                result.stderr,
            )
        else:
            LOGGER.info(
                "Converted %s %s (%s run-%02d): %s",
                participant_id,
                session_label,
                bids_modality,
                run_index,
                filename,
            )

        nii_files = nifti_matches_stem(output_dir, filename)
        records.append(
            {
                "participant_id": participant_id,
                "session_label": session_label,
                "series_instance_uid": series_instance_uid,
                "dicom_modality": str(row["modality"]),
                "bids_modality": bids_modality,
                "run_index": f"{run_index:02d}",
                "expected_filename": filename,
                "source_staging_dicom": str(staged_dicom.resolve()),
                "bids_output_dir": str(output_dir.resolve()),
                "n_converted_files": str(len(nii_files)),
                "dcm2niix_returncode": str(result.returncode),
                "status": status,
                "dcm2niix_stdout": result.stdout,
                "dcm2niix_stderr": result.stderr,
            }
        )

    return pd.DataFrame(records).sort_values(
        by=["participant_id", "session_label", "bids_modality", "run_index"],
        kind="mergesort",
    )


def run_conversion(
    paths: ProjectPaths,
    dcm2niix_path: str | None,
) -> pd.DataFrame:
    """Execute DICOM-to-BIDS conversion."""
    paths.ensure_metadata_dir()
    paths.ensure_derivatives_dir()
    paths.validate_writable(paths.raw_bids)
    paths.validate_writable(paths.derivatives)

    dcm2niix_bin = resolve_dcm2niix_binary(dcm2niix_path)
    dcm2niix_version = get_dcm2niix_version(dcm2niix_bin)
    LOGGER.info("dcm2niix version: %s", dcm2niix_version)
    session_mapping = load_session_mapping(paths)

    write_dataset_description(paths)
    write_participants_tsv(session_mapping, paths.participants_tsv)

    report = convert_sessions(session_mapping, paths, dcm2niix_bin)

    success_count = int((report["status"] == "success").sum()) if not report.empty else 0
    failed_count = int((report["status"] == "failed").sum()) if not report.empty else 0

    if success_count == 0:
        raise FatalPipelineError("Conversion produced zero successful outputs")

    validate_bids_outputs(paths.raw_bids)

    report.to_csv(paths.conversion_report_csv, index=False)
    LOGGER.info(
        "Wrote conversion report: %s (%d rows, %d success, %d failed)",
        paths.conversion_report_csv,
        len(report),
        success_count,
        failed_count,
    )

    if failed_count > 0:
        raise FatalPipelineError(
            f"Conversion failed for {failed_count} series; see {paths.conversion_report_csv}"
        )

    manifest = build_manifest(
        paths.root,
        steps_completed=[
            "inventory",
            "generate_mapping",
            "deidentify_dicom",
            "convert_to_bids",
        ],
        extra={
            "converted_sessions": success_count,
            "conversion_failed": failed_count,
            "dcm2niix_version": dcm2niix_version,
        },
    )
    write_manifest(paths.pipeline_manifest_json, manifest)

    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Convert staged DICOM to BIDS using dcm2niix."
    )
    parser.add_argument(
        "--dcm2niix-path",
        type=str,
        default=None,
        help="Path to dcm2niix executable (default: search PATH).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for BIDS conversion."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    log_file = paths.metadata / "convert_to_bids.log"
    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=log_file,
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting BIDS conversion for %s", paths.root)
    try:
        run_conversion(paths, args.dcm2niix_path)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("BIDS conversion completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
