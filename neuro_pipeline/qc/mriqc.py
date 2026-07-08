#!/usr/bin/env python3
"""MRIQC IQM feature extraction — external CLI wrapper only.

This module treats MRIQC as an **external dependency**. It does not implement,
reimplement, or reproduce any MRIQC algorithm or IQM calculation.

Responsibilities are limited to:
    1. Invoking the official MRIQC BIDS App CLI via container subprocess
    2. Discovering and parsing official MRIQC report artifacts (JSON/HTML pairs)
    3. Exporting report payloads verbatim with dynamic key iteration

The parser never depends on a fixed list of IQM field names. Any key present
in an official MRIQC JSON report is exported automatically, including metrics
added in future MRIQC releases without code changes here.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from neuro_pipeline.config.mriqc_defaults import (
    DEFAULT_MRIQC_CONFIG,
    MRIQC_MODALITY_ORDER,
    MRIQC_MODALITY_SPECS,
    MRIQC_SKIP_JSON_NAMES,
    STRUCTURAL_SUFFIXES,
)
from neuro_pipeline.reporting.generator import write_json_report
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)

NIFTI_SUFFIXES = (".nii.gz", ".nii")
_MODALITY_FILENAME_PATTERNS = {
    modality: re.compile(spec["filename_pattern"], re.IGNORECASE)
    for modality, spec in MRIQC_MODALITY_SPECS.items()
}


@dataclass(frozen=True)
class BidsVolume:
    """A BIDS NIfTI eligible for MRIQC."""

    participant_id: str
    session_label: str
    modality: str
    suffix: str
    source_path: Path
    relative_path: Path


# Backward-compatible alias.
StructuralVolume = BidsVolume


@dataclass(frozen=True)
class MRIQCConfig:
    """Runtime configuration for MRIQC feature extraction."""

    run_mriqc: bool = True
    n_procs: int = 1
    memory_gb: int = 4
    container_runtime: str = "docker"
    container_path: str = "nipreps/mriqc:latest"
    temporary_directory: str | None = None
    output_directory: str | None = None


@dataclass
class MriqcExecutionRecord:
    """Result of one MRIQC container invocation."""

    participant_id: str
    modality: str
    exit_code: int
    execution_time_sec: float
    stdout: str
    stderr: str
    command: list[str]
    error: str | None = None


@dataclass
class SubjectMriqcExport:
    """Aggregated MRIQC outputs for one participant and modality."""

    participant_id: str
    modality: str
    acquisitions: list[dict[str, Any]] = field(default_factory=list)
    execution_records: list[dict[str, Any]] = field(default_factory=list)


def is_nifti(path: Path) -> bool:
    """Return True if *path* is a NIfTI file."""
    name = path.name.lower()
    return name.endswith(".nii.gz") or name.endswith(".nii")


def parse_bids_modality(filename: str) -> str | None:
    """Return MRIQC modality flag when *filename* matches a supported BIDS suffix."""
    for modality, pattern in _MODALITY_FILENAME_PATTERNS.items():
        if pattern.search(filename):
            return modality
    return None


def parse_structural_suffix(filename: str) -> str | None:
    """Return structural BIDS suffix (T1w/T2w) when present."""
    modality = parse_bids_modality(filename)
    if modality in STRUCTURAL_SUFFIXES:
        return modality
    return None


def parse_bids_ids(relative: Path) -> tuple[str, str]:
    """Extract participant and session labels from a BIDS relative path."""
    parts = relative.parts
    participant_id = parts[0] if parts else ""
    session_label = ""
    if len(parts) >= 2 and parts[1].startswith("ses-"):
        session_label = parts[1]
    return participant_id, session_label


def discover_bids_volumes(raw_bids: Path) -> list[BidsVolume]:
    """
    Discover MRIQC-eligible volumes under *raw_bids*.

    Modalities are detected independently (T1w, T2w, bold, dwi). Missing
    modalities are skipped without error.
    """
    volumes: list[BidsVolume] = []
    if not raw_bids.is_dir():
        return volumes

    for path in sorted(raw_bids.rglob("*")):
        if not path.is_file() or not is_nifti(path):
            continue
        modality = parse_bids_modality(path.name)
        if modality is None:
            continue
        spec = MRIQC_MODALITY_SPECS[modality]
        try:
            relative = path.relative_to(raw_bids)
        except ValueError:
            continue
        if spec["datatype"] not in relative.parts:
            continue
        participant_id, session_label = parse_bids_ids(relative)
        if not participant_id:
            continue
        volumes.append(
            BidsVolume(
                participant_id=participant_id,
                session_label=session_label,
                modality=modality,
                suffix=modality,
                source_path=path,
                relative_path=relative,
            )
        )
    return volumes


def discover_structural_volumes(raw_bids: Path) -> list[BidsVolume]:
    """Discover T1w and T2w structural volumes (backward-compatible helper)."""
    return [volume for volume in discover_bids_volumes(raw_bids) if volume.modality in STRUCTURAL_SUFFIXES]


def group_volumes_by_modality(
    volumes: list[BidsVolume],
) -> dict[str, dict[str, list[BidsVolume]]]:
    """Group discovered volumes by MRIQC modality and participant."""
    grouped: dict[str, dict[str, list[BidsVolume]]] = {}
    for volume in volumes:
        grouped.setdefault(volume.modality, {}).setdefault(volume.participant_id, []).append(volume)
    return grouped


def group_volumes_by_participant(
    volumes: list[BidsVolume],
) -> dict[str, list[BidsVolume]]:
    """Group volumes by BIDS participant identifier."""
    grouped: dict[str, list[BidsVolume]] = {}
    for volume in volumes:
        grouped.setdefault(volume.participant_id, []).append(volume)
    return grouped


def load_mriqc_config(paths: ProjectPaths) -> MRIQCConfig:
    """
    Load MRIQC configuration from defaults and optional project override file.

    Project override path: ``metadata/mriqc_config.json`` or ``metadata/mriqc_config.yaml``.
    """
    merged = dict(DEFAULT_MRIQC_CONFIG)
    json_override = paths.metadata / "mriqc_config.json"
    yaml_override = paths.mriqc_config_yaml
    if json_override.is_file():
        override = json.loads(json_override.read_text(encoding="utf-8"))
        if isinstance(override, dict):
            merged.update(override)
    elif yaml_override.is_file():
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to read metadata/mriqc_config.yaml. "
                "Install pyyaml or use metadata/mriqc_config.json instead."
            ) from exc
        with yaml_override.open(encoding="utf-8") as handle:
            override = yaml.safe_load(handle) or {}
        if isinstance(override, dict):
            merged.update(override)
    return MRIQCConfig(**{k: merged[k] for k in DEFAULT_MRIQC_CONFIG if k in merged})


def resolve_output_dir(paths: ProjectPaths, config: MRIQCConfig) -> Path:
    """Resolve MRIQC output directory from config or project defaults."""
    if config.output_directory:
        candidate = Path(config.output_directory)
        return candidate if candidate.is_absolute() else paths.root / candidate
    return paths.mriqc_output_dir


def resolve_work_dir(paths: ProjectPaths, config: MRIQCConfig) -> Path:
    """Resolve MRIQC temporary/work directory from config or project defaults."""
    if config.temporary_directory:
        candidate = Path(config.temporary_directory)
        return candidate if candidate.is_absolute() else paths.root / candidate
    return paths.mriqc_work_dir


def _container_executable(runtime: str) -> str:
    """Map configured runtime name to an executable on PATH."""
    normalized = runtime.lower()
    if normalized == "singularity":
        for name in ("apptainer", "singularity"):
            executable = shutil.which(name)
            if executable:
                return executable
        raise FileNotFoundError("Apptainer/Singularity executable not found on PATH")
    if normalized in {"apptainer", "docker"}:
        executable = shutil.which(normalized)
        if executable:
            return executable
        raise FileNotFoundError(f"{normalized} executable not found on PATH")
    raise ValueError(f"Unsupported container_runtime: {runtime}")


def build_mriqc_command(
    config: MRIQCConfig,
    *,
    bids_dir: Path,
    output_dir: Path,
    work_dir: Path,
    participant_label: str,
    modality: str,
) -> list[str]:
    """
    Build a container command for MRIQC participant-level execution.

    Uses the BIDS App interface with ``-m`` to restrict processing to one modality.
    """
    runtime = _container_executable(config.container_runtime)
    normalized = config.container_runtime.lower()
    bids_mount = f"{bids_dir.resolve()}:/data:ro"
    out_mount = f"{output_dir.resolve()}:/out"
    work_mount = f"{work_dir.resolve()}:/work"

    mriqc_args = [
        "/data",
        "/out",
        "participant",
        "--participant-label",
        participant_label.removeprefix("sub-"),
        "--no-sub",
        "-m",
        modality,
        "--n_procs",
        str(config.n_procs),
        "--mem-gb",
        str(config.memory_gb),
    ]

    if normalized == "docker":
        return [
            runtime,
            "run",
            "--rm",
            "-v",
            bids_mount,
            "-v",
            out_mount,
            "-v",
            work_mount,
            config.container_path,
            *mriqc_args,
        ]

    # Apptainer / Singularity
    image = config.container_path
    if image.startswith("docker://"):
        image_ref = image
    elif normalized == "singularity" and not Path(image).is_file():
        image_ref = f"docker://{image}"
    else:
        image_ref = image

    return [
        runtime,
        "run",
        "--cleanenv",
        "-B",
        bids_mount,
        "-B",
        out_mount,
        "-B",
        work_mount,
        image_ref,
        *mriqc_args,
    ]


def execute_mriqc(
    command: list[str],
    *,
    participant_id: str,
    modality: str,
    log_file: Path | None = None,
) -> MriqcExecutionRecord:
    """Run MRIQC via subprocess and capture stdout, stderr, timing, and exit code."""
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - started

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"\n=== {participant_id} [{modality}] ===\n")
            handle.write(f"command: {' '.join(command)}\n")
            handle.write(f"exit_code: {result.returncode}\n")
            handle.write(f"execution_time_sec: {elapsed:.3f}\n")
            handle.write("--- stdout ---\n")
            handle.write(result.stdout or "")
            handle.write("\n--- stderr ---\n")
            handle.write(result.stderr or "")
            handle.write("\n")

    error = None
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "MRIQC exited with non-zero status").strip()

    return MriqcExecutionRecord(
        participant_id=participant_id,
        modality=modality,
        exit_code=result.returncode,
        execution_time_sec=elapsed,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        command=command,
        error=error,
    )


def is_official_mriqc_report_json(json_path: Path) -> bool:
    """
    Return True when *json_path* is an official MRIQC report JSON artifact.

    MRIQC emits paired ``.json`` and ``.html`` reports for each run. We use
    that pairing to identify official outputs without hard-coding IQM names.
    """
    if json_path.name in MRIQC_SKIP_JSON_NAMES:
        return False
    if json_path.name.endswith("subject_qc.json"):
        return False
    return _matching_html_for_json(json_path) is not None


def discover_mriqc_json_outputs(output_dir: Path) -> list[Path]:
    """Find official MRIQC report JSON files under *output_dir*."""
    if not output_dir.is_dir():
        return []
    return sorted(
        path
        for path in output_dir.rglob("*.json")
        if is_official_mriqc_report_json(path)
    )


def load_mriqc_report_json(path: Path) -> dict[str, Any]:
    """Load an official MRIQC JSON report verbatim (no transformation)."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_mriqc_iqm_json(path: Path) -> dict[str, Any]:
    """Deprecated alias for :func:`load_mriqc_report_json`."""
    return load_mriqc_report_json(path)


def _matching_html_for_json(json_path: Path) -> Path | None:
    """Return sibling MRIQC HTML report path when present."""
    html_path = json_path.with_suffix(".html")
    if html_path.is_file():
        return html_path
    if json_path.name.endswith(".json"):
        alt = Path(str(json_path).replace(".json", ".html"))
        if alt.is_file():
            return alt
    return None


def _extract_software_version(iqm_payload: dict[str, Any]) -> str:
    """Read MRIQC software version from the provenance block when available."""
    provenance = iqm_payload.get("Provenance", iqm_payload.get("provenance", {}))
    if isinstance(provenance, dict):
        version = provenance.get("Version", provenance.get("version", ""))
        software = provenance.get("Software", provenance.get("software", "MRIQC"))
        if version:
            return f"{software} {version}"
    return str(iqm_payload.get("mriqc_version", "unknown"))


def _flatten_report_for_csv(report_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Serialize a MRIQC JSON report for CSV export.

    Iterates all top-level keys dynamically — no fixed IQM registry. Nested
    structures are JSON-encoded to preserve information without reinterpretation.
    """
    row: dict[str, Any] = {}
    for key, value in report_payload.items():
        if isinstance(value, (dict, list)):
            row[key] = json.dumps(value, sort_keys=True)
        else:
            row[key] = value
    return row


def copy_html_report(
    html_source: Path,
    destination_dir: Path,
    *,
    participant_id: str,
) -> Path:
    """Copy an MRIQC HTML report into the QC report bundle directory."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{participant_id}_{html_source.name}"
    shutil.copy2(html_source, destination)
    return destination


def export_subject_qc(
    export: SubjectMriqcExport,
    *,
    output_dir: Path,
    report_links_dir: Path,
) -> tuple[Path, Path]:
    """
    Write ``subject_qc.json`` and ``subject_qc.csv`` for one participant.

    JSON preserves full MRIQC payloads. CSV flattens top-level keys while
    retaining every field name from the MRIQC JSON outputs.
    """
    subject_dir = output_dir / export.participant_id
    subject_dir.mkdir(parents=True, exist_ok=True)
    json_path = subject_dir / "subject_qc.json"
    csv_path = subject_dir / "subject_qc.csv"

    payload = {
        "participant_id": export.participant_id,
        "modality": export.modality,
        "execution_records": export.execution_records,
        "acquisitions": export.acquisitions,
    }
    write_json_report(json_path, payload)

    csv_rows: list[dict[str, Any]] = []
    for acquisition in export.acquisitions:
        row = _flatten_report_for_csv(acquisition.get("mriqc_report", {}))
        row["participant_id"] = export.participant_id
        row["modality"] = export.modality
        row["source_image"] = acquisition.get("source_image", "")
        row["bids_relative_path"] = acquisition.get("bids_relative_path", "")
        row["suffix"] = acquisition.get("suffix", "")
        row["session_label"] = acquisition.get("session_label", "")
        row["mriqc_json_path"] = acquisition.get("mriqc_json_path", "")
        row["mriqc_html_path"] = acquisition.get("mriqc_html_path", "")
        row["linked_html_report"] = acquisition.get("linked_html_report", "")
        row["execution_time_sec"] = acquisition.get("execution_time_sec", "")
        row["software_version"] = acquisition.get("software_version", "")
        csv_rows.append(row)

    if csv_rows:
        fieldnames: list[str] = []
        for row in csv_rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)
    else:
        csv_path.write_text("participant_id\n", encoding="utf-8")

    return json_path, csv_path


def collect_subject_exports(
    participant_id: str,
    modality: str,
    volumes: list[BidsVolume],
    json_outputs: list[Path],
    execution_record: MriqcExecutionRecord | None,
    *,
    report_links_dir: Path,
) -> SubjectMriqcExport:
    """
    Match MRIQC JSON outputs to discovered volumes for one subject and modality.

    All keys from official MRIQC JSON reports are preserved verbatim.
    """
    export = SubjectMriqcExport(participant_id=participant_id, modality=modality)
    if execution_record is not None:
        export.execution_records.append(
            {
                "participant_id": execution_record.participant_id,
                "modality": execution_record.modality,
                "exit_code": execution_record.exit_code,
                "execution_time_sec": execution_record.execution_time_sec,
                "command": execution_record.command,
                "error": execution_record.error,
            }
        )

    volume_lookup = {volume.source_path.name: volume for volume in volumes}
    matched_json: set[Path] = set()

    for json_path in json_outputs:
        if participant_id not in json_path.parts:
            continue
        report_payload = load_mriqc_report_json(json_path)
        bids_name = report_payload.get("bids_name", {})
        suffix = ""
        session_label = ""
        if isinstance(bids_name, dict):
            suffix = str(bids_name.get("suffix", ""))
            session_label = str(bids_name.get("session", ""))

        source_name = json_path.name.replace(".json", ".nii.gz")
        volume = volume_lookup.get(source_name)
        if volume is None and suffix:
            for candidate in volumes:
                if candidate.suffix.lower() == suffix.lower():
                    volume = candidate
                    break

        html_source = _matching_html_for_json(json_path)
        linked_html = ""
        if html_source is not None:
            linked = copy_html_report(html_source, report_links_dir, participant_id=participant_id)
            linked_html = str(linked)

        acquisition = {
            "source_image": str(volume.source_path) if volume else "",
            "bids_relative_path": str(volume.relative_path) if volume else "",
            "suffix": volume.suffix if volume else suffix,
            "session_label": volume.session_label if volume else session_label,
            "mriqc_json_path": str(json_path.resolve()),
            "mriqc_html_path": str(html_source.resolve()) if html_source else "",
            "linked_html_report": linked_html,
            "execution_time_sec": execution_record.execution_time_sec if execution_record else None,
            "software_version": _extract_software_version(report_payload),
            "mriqc_report": report_payload,
            "iqms": report_payload,
        }
        export.acquisitions.append(acquisition)
        matched_json.add(json_path)

    # Volumes without MRIQC JSON still appear with empty iqms for traceability.
    for volume in volumes:
        already = any(
            acq.get("bids_relative_path") == str(volume.relative_path)
            for acq in export.acquisitions
        )
        if already:
            continue
        export.acquisitions.append(
            {
                "source_image": str(volume.source_path),
                "bids_relative_path": str(volume.relative_path),
                "suffix": volume.suffix,
                "session_label": volume.session_label,
                "mriqc_json_path": "",
                "mriqc_html_path": "",
                "linked_html_report": "",
                "execution_time_sec": execution_record.execution_time_sec if execution_record else None,
                "software_version": "",
                "iqms": {},
                "mriqc_report": {},
            }
        )

    return export


def build_mriqc_summary_rows(exports: list[SubjectMriqcExport]) -> list[dict[str, Any]]:
    """Build tabular rows for the aggregated HTML report (dynamic keys, no interpretation)."""
    rows: list[dict[str, Any]] = []
    for export in exports:
        for acquisition in export.acquisitions:
            report_payload = acquisition.get("mriqc_report", acquisition.get("iqms", {}))
            if not isinstance(report_payload, dict) or not report_payload:
                continue
            row = {
                "modality": export.modality,
                "participant_id": export.participant_id,
                "session_label": acquisition.get("session_label", ""),
                "suffix": acquisition.get("suffix", ""),
                "source_image": acquisition.get("source_image", ""),
                "software_version": acquisition.get("software_version", ""),
                "execution_time_sec": acquisition.get("execution_time_sec", ""),
                "mriqc_html_report": acquisition.get("linked_html_report")
                or acquisition.get("mriqc_html_path", ""),
            }
            for key, value in report_payload.items():
                if isinstance(value, (dict, list)):
                    row[key] = json.dumps(value, sort_keys=True)
                else:
                    row[key] = value
            rows.append(row)
    return rows


def _empty_modality_summary(modality: str, output_dir: Path, work_dir: Path) -> dict[str, Any]:
    """Initialize per-modality summary counters."""
    return {
        "modality": modality,
        "volumes_discovered": 0,
        "participants_discovered": 0,
        "participants_processed": 0,
        "participants_failed": 0,
        "exports": [],
        "failures": [],
        "output_directory": str(output_dir.resolve()),
        "temporary_directory": str(work_dir.resolve()),
        "mriqc_report_rows": [],
    }


def run_mriqc(
    paths: ProjectPaths,
    *,
    config: MRIQCConfig | None = None,
    execute_fn=execute_mriqc,
) -> dict[str, Any]:
    """
    Run MRIQC feature extraction per detected modality (T1w, T2w, bold, dwi).

    Each modality is processed independently with separate output folders.
    Failures in one modality or participant do not stop other runs.
    """
    paths.ensure_metadata_dir()
    config = config or load_mriqc_config(paths)
    output_dir = resolve_output_dir(paths, config)
    work_dir = resolve_work_dir(paths, config)

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "run_mriqc": config.run_mriqc,
        "modalities_detected": [],
        "volumes_discovered": 0,
        "participants_discovered": 0,
        "participants_processed": 0,
        "participants_failed": 0,
        "structural_volumes_discovered": 0,
        "modality_summaries": {},
        "mriqc_report_rows_by_modality": {},
        "exports": [],
        "failures": [],
        "config": asdict(config),
        "output_directory": str(output_dir.resolve()),
        "temporary_directory": str(work_dir.resolve()),
    }

    if not config.run_mriqc:
        LOGGER.info("MRIQC disabled by configuration (run_mriqc=false)")
        write_json_report(paths.mriqc_run_summary_json, summary)
        return summary

    if not paths.raw_bids.is_dir():
        message = f"BIDS dataset not found: {paths.raw_bids}"
        LOGGER.error(message)
        summary["failures"].append({"error": message})
        write_json_report(paths.mriqc_run_summary_json, summary)
        return summary

    volumes = discover_bids_volumes(paths.raw_bids)
    grouped_by_modality = group_volumes_by_modality(volumes)
    summary["volumes_discovered"] = len(volumes)
    summary["structural_volumes_discovered"] = sum(
        1 for volume in volumes if volume.modality in STRUCTURAL_SUFFIXES
    )
    summary["modalities_detected"] = [
        modality for modality in MRIQC_MODALITY_ORDER if modality in grouped_by_modality
    ]

    if not grouped_by_modality:
        LOGGER.info("No MRIQC-eligible modalities discovered under raw_bids/")
        write_json_report(paths.mriqc_run_summary_json, summary)
        return summary

    all_exports: list[SubjectMriqcExport] = []

    for modality in MRIQC_MODALITY_ORDER:
        participants = grouped_by_modality.get(modality)
        if not participants:
            continue

        modality_output = output_dir / modality
        modality_work = work_dir / modality
        modality_report_links = paths.mriqc_modality_report_links_dir(modality)
        modality_output.mkdir(parents=True, exist_ok=True)
        modality_work.mkdir(parents=True, exist_ok=True)
        modality_report_links.mkdir(parents=True, exist_ok=True)

        modality_summary = _empty_modality_summary(modality, modality_output, modality_work)
        modality_summary["volumes_discovered"] = sum(len(vols) for vols in participants.values())
        modality_summary["participants_discovered"] = len(participants)
        modality_exports: list[SubjectMriqcExport] = []

        LOGGER.info(
            "Running MRIQC for modality %s (%d participant(s), %d volume(s))",
            modality,
            modality_summary["participants_discovered"],
            modality_summary["volumes_discovered"],
        )

        for participant_id in sorted(participants):
            subject_volumes = participants[participant_id]
            LOGGER.info(
                "MRIQC %s / %s (%d volume(s))",
                modality,
                participant_id,
                len(subject_volumes),
            )
            execution_record: MriqcExecutionRecord | None = None
            try:
                command = build_mriqc_command(
                    config,
                    bids_dir=paths.raw_bids,
                    output_dir=modality_output,
                    work_dir=modality_work,
                    participant_label=participant_id,
                    modality=modality,
                )
                execution_record = execute_fn(
                    command,
                    participant_id=participant_id,
                    modality=modality,
                    log_file=paths.mriqc_log,
                )
                if execution_record.exit_code != 0:
                    modality_summary["participants_failed"] += 1
                    failure = {
                        "modality": modality,
                        "participant_id": participant_id,
                        "error": execution_record.error,
                        "exit_code": execution_record.exit_code,
                    }
                    modality_summary["failures"].append(failure)
                    summary["failures"].append(failure)
                    summary["participants_failed"] += 1
                    LOGGER.error(
                        "MRIQC failed for %s / %s (exit %d): %s",
                        modality,
                        participant_id,
                        execution_record.exit_code,
                        execution_record.error,
                    )
                else:
                    modality_summary["participants_processed"] += 1
                    summary["participants_processed"] += 1
            except Exception as exc:  # noqa: BLE001 — continue pipeline on MRIQC errors
                modality_summary["participants_failed"] += 1
                summary["participants_failed"] += 1
                failure = {
                    "modality": modality,
                    "participant_id": participant_id,
                    "error": str(exc),
                    "exit_code": -1,
                }
                modality_summary["failures"].append(failure)
                summary["failures"].append(failure)
                LOGGER.exception("MRIQC execution error for %s / %s", modality, participant_id)

            json_outputs = discover_mriqc_json_outputs(modality_output)
            export = collect_subject_exports(
                participant_id,
                modality,
                subject_volumes,
                json_outputs,
                execution_record,
                report_links_dir=modality_report_links,
            )
            json_path, csv_path = export_subject_qc(
                export,
                output_dir=modality_output,
                report_links_dir=modality_report_links,
            )
            modality_exports.append(export)
            all_exports.append(export)
            export_record = {
                "modality": modality,
                "participant_id": participant_id,
                "subject_qc_json": str(json_path.resolve()),
                "subject_qc_csv": str(csv_path.resolve()),
                "n_acquisitions": len(export.acquisitions),
            }
            modality_summary["exports"].append(export_record)
            summary["exports"].append(export_record)

        modality_summary["mriqc_report_rows"] = build_mriqc_summary_rows(modality_exports)
        summary["modality_summaries"][modality] = modality_summary
        summary["mriqc_report_rows_by_modality"][modality] = modality_summary["mriqc_report_rows"]

    summary["participants_discovered"] = len(
        {volume.participant_id for volume in volumes}
    )
    summary["mriqc_report_rows"] = build_mriqc_summary_rows(all_exports)
    write_json_report(paths.mriqc_run_summary_json, summary)

    try:
        from neuro_pipeline.reporting.pipeline_qc_summary import generate_pipeline_qc_summary_html

        generate_pipeline_qc_summary_html(paths)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Could not refresh pipeline QC summary after MRIQC: %s", exc)

    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Extract MRIQC Image Quality Metrics per detected modality."
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="Load configuration and discover inputs without executing MRIQC.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for MRIQC feature extraction."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.mriqc_log,
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting MRIQC feature extraction for %s", paths.root)
    config = load_mriqc_config(paths)
    if args.no_run:
        config = MRIQCConfig(**{**asdict(config), "run_mriqc": False})

    run_mriqc(paths, config=config)
    LOGGER.info("MRIQC feature extraction finished (non-fatal errors logged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
