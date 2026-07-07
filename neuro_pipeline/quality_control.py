#!/usr/bin/env python3
"""Generate publication-grade quality-control reports for the BIDS dataset."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import nibabel as nib
import pandas as pd

from neuro_pipeline.raw_bids_guard import assert_raw_bids_immutable
from neuro_pipeline.reports.generator import write_html_report, write_json_report
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.extensions import build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.pipeline_steps import RESEARCH_STEP_NAMES
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

RESEARCH_STEPS_THROUGH_QC: list[str] = list(
    RESEARCH_STEP_NAMES[: RESEARCH_STEP_NAMES.index("quality_control") + 1]
)

LOGGER = logging.getLogger(__name__)

NIFTI_SUFFIXES: tuple[str, ...] = (".nii", ".nii.gz")
MIN_VOLUME_SIZE_MB: float = 0.1


def is_nifti(path: Path) -> bool:
    """Return True if path is a NIfTI file."""
    name = path.name.lower()
    return name.endswith(".nii.gz") or name.endswith(".nii")


def load_participant_mapping(mapping_csv: Path) -> pd.DataFrame:
    """Load participant mapping for cohort labels."""
    if not mapping_csv.is_file():
        raise FatalPipelineError(
            f"Participant mapping not found: {mapping_csv}"
        )
    return pd.read_csv(mapping_csv, dtype=str).fillna("")


def load_nifti(path: Path) -> nib.spatialimages.SpatialImage | None:
    """Load a NIfTI volume, returning None if the header cannot be read."""
    try:
        return nib.load(str(path))
    except Exception as exc:
        LOGGER.warning("Failed to load NIfTI header for %s: %s", path, exc)
        return None


def json_sidecar_path(nifti_path: Path) -> Path:
    """Return the expected BIDS JSON sidecar path for a NIfTI file."""
    if nifti_path.name.endswith(".nii.gz"):
        return Path(str(nifti_path).replace(".nii.gz", ".json"))
    return nifti_path.with_suffix(".json")


def parse_bids_relative_path(relative: Path) -> tuple[str, str, str]:
    """Extract participant, session, and modality from a BIDS relative path."""
    parts = relative.parts
    participant_id = parts[0] if parts else ""
    session_label = ""
    modality = ""

    if len(parts) >= 2 and parts[1].startswith("ses-"):
        session_label = parts[1]
        modality = parts[2] if len(parts) >= 3 else ""
    elif len(parts) >= 2:
        modality = parts[1]

    return participant_id, session_label, modality


def scan_bids_volumes(raw_bids: Path) -> list[dict[str, str | float | bool | tuple[int, ...]]]:
    """Scan raw_bids for NIfTI files and collect QC metrics."""
    records: list[dict[str, str | float | bool | tuple[int, ...]]] = []
    if not raw_bids.is_dir():
        raise FatalPipelineError(f"BIDS dataset not found: {raw_bids}")

    for nifti_path in sorted(raw_bids.rglob("*")):
        if not nifti_path.is_file() or not is_nifti(nifti_path):
            continue

        relative = nifti_path.relative_to(raw_bids)
        participant_id, session_label, modality = parse_bids_relative_path(relative)

        image = load_nifti(nifti_path)
        header_ok = image is not None
        shape: tuple[int, ...] = tuple(image.shape) if image is not None else ()
        affine_ok = bool(image is not None and image.affine is not None)

        sidecar = json_sidecar_path(nifti_path)
        has_json = sidecar.is_file()
        size_bytes = nifti_path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)

        records.append(
            {
                "participant_id": participant_id,
                "session_label": session_label,
                "modality": modality,
                "filename": nifti_path.name,
                "relative_path": str(relative),
                "header_ok": header_ok,
                "affine_ok": affine_ok,
                "shape": str(shape),
                "size_bytes": size_bytes,
                "size_mb": size_mb,
                "has_json_sidecar": has_json,
            }
        )

    return records


def build_qc(detail: pd.DataFrame) -> pd.DataFrame:
    """Assign pass/warn/fail status and notes to scanned volumes."""
    df = detail.copy()
    statuses: list[str] = []
    notes_list: list[str] = []

    for _, row in df.iterrows():
        notes: list[str] = []
        status = "pass"

        if not row["header_ok"]:
            status = "fail"
            notes.append("invalid_header")
        elif not row["affine_ok"]:
            status = "fail"
            notes.append("missing_affine")
        elif float(row["size_bytes"]) == 0:
            status = "fail"
            notes.append("empty_nifti")
        else:
            if not row["has_json_sidecar"]:
                status = "warn"
                notes.append("missing_json_sidecar")
            if float(row["size_mb"]) < MIN_VOLUME_SIZE_MB:
                status = "warn" if status == "pass" else status
                notes.append("suspiciously_small")

        statuses.append(status)
        notes_list.append(";".join(notes))

    df["status"] = statuses
    df["notes"] = notes_list
    return df


def build_summary(detail: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-participant/session QC summary."""
    cohort_lookup = (
        mapping[["participant_id", "cohort"]]
        .drop_duplicates(subset=["participant_id"])
        .set_index("participant_id")["cohort"]
    )

    df = detail.copy()
    df["cohort"] = df["participant_id"].map(cohort_lookup).fillna("UNKNOWN")

    summary = (
        df.groupby(["participant_id", "cohort", "session_label"], sort=True)
        .agg(
            n_volumes=("filename", "count"),
            n_fail=("status", lambda series: int((series == "fail").sum())),
            n_warn=("status", lambda series: int((series == "warn").sum())),
            n_pass=("status", lambda series: int((series == "pass").sum())),
            n_header_fail=("header_ok", lambda series: int((~series.astype(bool)).sum())),
            n_missing_json=("has_json_sidecar", lambda series: int((~series.astype(bool)).sum())),
            total_bytes=("size_bytes", lambda series: int(pd.to_numeric(series).sum())),
            mean_size_mb=("size_mb", lambda series: float(pd.to_numeric(series).mean())),
        )
        .reset_index()
        .sort_values(["cohort", "participant_id", "session_label"], kind="mergesort")
    )
    return summary


def compare_expected_subjects(
    mapping: pd.DataFrame,
    detail: pd.DataFrame,
) -> list[str]:
    """Return warnings for mapped subjects missing from BIDS output."""
    expected = set(mapping["participant_id"].unique())
    found = set(detail["participant_id"].unique())
    missing = sorted(expected - found)
    warnings: list[str] = []
    for participant_id in missing:
        warnings.append(
            f"Mapped participant missing from BIDS output: {participant_id}"
        )
    return warnings


def run_qc(paths: ProjectPaths) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Execute QC scanning and write reports."""
    paths.ensure_metadata_dir()
    paths.ensure_derivatives_dir()
    paths.validate_writable(paths.metadata)
    paths.validate_writable(paths.derivatives / "qc")

    if not paths.raw_bids.is_dir():
        raise FatalPipelineError(f"BIDS dataset not found: {paths.raw_bids}")

    assert_raw_bids_immutable(paths)

    mapping = load_participant_mapping(paths.participant_mapping_csv)
    detail = pd.DataFrame(scan_bids_volumes(paths.raw_bids))

    if detail.empty:
        raise FatalPipelineError("QC found zero NIfTI volumes in raw_bids/")

    detail = build_qc(detail)
    summary = build_summary(detail, mapping)

    missing_warnings = compare_expected_subjects(mapping, detail)
    for message in missing_warnings:
        LOGGER.warning(message)

    detail.to_csv(paths.qc_detail_csv, index=False)
    summary.to_csv(paths.qc_summary_csv, index=False)
    LOGGER.info("Wrote QC detail: %s (%d rows)", paths.qc_detail_csv, len(detail))
    LOGGER.info("Wrote QC summary: %s (%d rows)", paths.qc_summary_csv, len(summary))

    fail_count = int((detail["status"] == "fail").sum())
    warn_count = int((detail["status"] == "warn").sum())
    pass_count = int((detail["status"] == "pass").sum())
    LOGGER.info(
        "QC results: %d pass, %d warn, %d fail across %d volumes",
        pass_count,
        warn_count,
        fail_count,
        len(detail),
    )

    if fail_count > 0:
        raise FatalPipelineError(f"QC reported {fail_count} failed volume(s)")

    qc_json = paths.derivatives / "qc" / "qc_report.json"
    qc_html = paths.derivatives / "qc" / "qc_report.html"
    report_payload = {
        "volumes": len(detail),
        "pass": pass_count,
        "warn": warn_count,
        "fail": fail_count,
        "missing_subject_warnings": missing_warnings,
    }
    write_json_report(qc_json, report_payload)
    write_html_report(
        qc_html,
        title="Neuro BIDS QC Report",
        summary=report_payload,
        sections=[
            ("Volume Detail", detail.head(500).to_dict(orient="records")),
            ("Session Summary", summary.to_dict(orient="records")),
        ],
    )
    LOGGER.info("Wrote QC reports: %s, %s", qc_json, qc_html)

    from neuro_pipeline.reports.pipeline_qc_summary import generate_pipeline_qc_summary_html
    from neuro_pipeline.utils.execution_context import ExecutionContext

    context = ExecutionContext.capture(project_root=paths.root)
    context.write_json(paths.metadata / "quality_control_context.json")
    generate_pipeline_qc_summary_html(paths)

    manifest = build_manifest(
        paths.root,
        steps_completed=RESEARCH_STEPS_THROUGH_QC,
        execution_context=context,
        project_paths=paths,
        extra={
            "qc_volumes": len(detail),
            "qc_pass": pass_count,
            "qc_warnings": warn_count,
            "qc_failures": fail_count,
            "qc_missing_subjects": len(missing_warnings),
        },
    )
    write_manifest(paths.pipeline_manifest_json, manifest)

    return summary, detail


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Generate QC reports for the BIDS dataset."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for quality control."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    log_file = paths.metadata / "quality_control.log"
    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=log_file,
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting QC for %s", paths.root)
    try:
        run_qc(paths)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("QC completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
