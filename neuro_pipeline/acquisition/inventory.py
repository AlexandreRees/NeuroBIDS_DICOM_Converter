#!/usr/bin/env python3
"""Read-only discovery of DICOM subjects, sessions, and series."""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from neuro_pipeline.config.constants import (
    INVENTORY_WARNING_SEVERITIES,
    REQUIRED_INVENTORY_METADATA,
)
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.dicom_helpers import (
    is_dicom_candidate,
    normalize_dicom_time,
    try_extract_dicom_metadata,
)
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.config.extensions import build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import COHORT_NAMES, ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)

# Backwards-compatible aliases for inventory metadata requirements.
REQUIRED_METADATA = REQUIRED_INVENTORY_METADATA
WARNING_SEVERITIES = INVENTORY_WARNING_SEVERITIES


@dataclass(frozen=True)
class InventoryWarning:
    """Structured inventory warning with type, severity, and context."""

    type: str
    severity: str
    context: str
    message: str

    def __post_init__(self) -> None:
        """Validate severity values."""
        if self.severity not in WARNING_SEVERITIES:
            raise ValueError(f"Invalid warning severity: {self.severity}")


@dataclass(frozen=True)
class SubjectIndex:
    """Filesystem index for one subject under a cohort."""

    cohort: str
    subject_label: str
    subject_path: Path
    dicom_files: tuple[Path, ...]


@dataclass(frozen=True)
class CorruptDicomRecord:
    """Tracking record for a corrupted DICOM file."""

    cohort: str
    subject_label: str
    subject_path: str
    dicom_path: str
    error: str


class MetadataCache:
    """Cache DICOM metadata reads and track per-file read failures."""

    def __init__(self) -> None:
        """Initialize an empty metadata cache."""
        self._store: dict[Path, dict[str, str] | None] = {}
        self._errors: dict[Path, str] = {}

    def get(self, path: Path) -> dict[str, str] | None:
        """Return cached metadata for *path*, reading from disk on first access."""
        resolved = path.resolve()
        if resolved not in self._store:
            metadata, error = try_extract_dicom_metadata(resolved)
            self._store[resolved] = metadata
            if error is not None:
                self._errors[resolved] = error
        return self._store[resolved]

    def get_error(self, path: Path) -> str | None:
        """Return the read error for *path* if metadata extraction failed."""
        self.get(path)
        return self._errors.get(path.resolve())

    @property
    def corrupt_paths(self) -> dict[Path, str]:
        """Return all paths that failed metadata extraction."""
        return dict(self._errors)


def discover_cohort_dirs(raw_original: Path) -> list[tuple[str, Path]]:
    """Discover cohort directories under raw_original.

    Known cohort names are prioritized; additional top-level folders are
    included in sorted order with a structured warning emitted by the caller.
    """
    if not raw_original.is_dir():
        raise FatalPipelineError(f"raw_original not found: {raw_original}")

    found: dict[str, Path] = {}
    for entry in sorted(raw_original.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            found[entry.name] = entry

    cohorts: list[tuple[str, Path]] = []
    for name in COHORT_NAMES:
        if name in found:
            cohorts.append((name, found.pop(name)))

    for name in sorted(found):
        cohorts.append((name, found[name]))

    if not cohorts:
        raise FatalPipelineError(f"No cohort directories found in {raw_original}")

    return cohorts


def index_cohort_filesystem(
    cohort: str,
    cohort_path: Path,
) -> tuple[list[SubjectIndex], list[InventoryWarning]]:
    """Phase 1: build cohort → subject → DICOM file hierarchy in one traversal."""
    subject_files: dict[str, list[Path]] = defaultdict(list)
    warnings: list[InventoryWarning] = []

    for path in sorted(cohort_path.rglob("*")):
        if not is_dicom_candidate(path):
            continue

        relative = path.relative_to(cohort_path)
        if len(relative.parts) == 1:
            warnings.append(
                InventoryWarning(
                    type="orphaned_dicom",
                    severity="warning",
                    context=str(path.resolve()),
                    message=(
                        "DICOM file at cohort root is not assigned to any subject; "
                        "skipped"
                    ),
                )
            )
            continue

        subject_files[relative.parts[0]].append(path)

    indexed_subjects: list[SubjectIndex] = []
    for subject_label in sorted(subject_files):
        files = tuple(sorted(subject_files[subject_label]))
        indexed_subjects.append(
            SubjectIndex(
                cohort=cohort,
                subject_label=subject_label,
                subject_path=(cohort_path / subject_label).resolve(),
                dicom_files=files,
            )
        )

    indexed_labels = set(subject_files)
    for child in sorted(cohort_path.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name not in indexed_labels:
            warnings.append(
                InventoryWarning(
                    type="empty_subject_folder",
                    severity="warning",
                    context=str(child.resolve()),
                    message="Subject folder contains no DICOM files",
                )
            )

    if not indexed_subjects and cohort_path.is_dir():
        has_children = any(
            child.is_dir() and not child.name.startswith(".")
            for child in cohort_path.iterdir()
        )
        if not has_children:
            warnings.append(
                InventoryWarning(
                    type="empty_cohort_folder",
                    severity="warning",
                    context=str(cohort_path.resolve()),
                    message="Cohort folder contains no subject directories",
                )
            )
        else:
            warnings.append(
                InventoryWarning(
                    type="no_subjects",
                    severity="warning",
                    context=str(cohort_path.resolve()),
                    message=f"Cohort '{cohort}' has no discoverable subjects with DICOM",
                )
            )

    return indexed_subjects, warnings


def build_session_cluster_key(
    metadata: dict[str, str],
    dicom_path: Path,
) -> tuple[int, str, str, str, str]:
    """Build a deterministic, sortable session cluster key for one DICOM file.

    Priority order:
    1. StudyDate + StudyTime/SeriesTime
    2. StudyDate + StudyInstanceUID
    3. StudyInstanceUID alone
    4. Parent-directory fallback clustering
    """
    study_date = metadata.get("study_date", "")
    study_time = normalize_dicom_time(
        metadata.get("study_time") or metadata.get("series_time", "")
    )
    study_uid = metadata.get("study_instance_uid", "")

    if study_date and study_time:
        return (0, study_date, study_time, study_uid, "")
    if study_date and study_uid:
        return (1, study_date, study_uid, "", "")
    if study_uid:
        return (2, study_uid, "", "", "")
    fallback_dir = dicom_path.parent.name
    return (3, fallback_dir, str(dicom_path.parent.resolve()), "", "")


def session_cluster_label(cluster_key: tuple[int, str, str, str, str]) -> str:
    """Render a stable string label for a session cluster key."""
    priority, first, second, third, fourth = cluster_key
    if priority == 0:
        return f"date_time:{first}|{second}|{third or 'no_uid'}"
    if priority == 1:
        return f"date_uid:{first}|{second}"
    if priority == 2:
        return f"uid:{first}"
    return f"dir:{first}|{second}"


def infer_sessions(
    subject: SubjectIndex,
    readable_files: list[tuple[Path, dict[str, str]]],
) -> tuple[list[tuple[str, str, list[tuple[Path, dict[str, str]]]]], list[InventoryWarning]]:
    """Group readable DICOM files into deterministic BIDS session buckets."""
    warnings: list[InventoryWarning] = []
    clusters: dict[tuple[int, str, str, str, str], list[tuple[Path, dict[str, str]]]] = (
        defaultdict(list)
    )

    for dicom_path, metadata in readable_files:
        cluster_key = build_session_cluster_key(metadata, dicom_path)
        clusters[cluster_key].append((dicom_path, metadata))

    sorted_clusters = sorted(clusters.items(), key=lambda item: item[0])
    session_count = len(sorted_clusters)

    if session_count > 2:
        warnings.append(
            InventoryWarning(
                type="session_count_high",
                severity="warning",
                context=str(subject.subject_path),
                message=(
                    f"Subject has {session_count} inferred sessions (>2); "
                    f"cluster keys: "
                    f"{[session_cluster_label(key) for key, _ in sorted_clusters]}"
                ),
            )
        )
    elif session_count == 1:
        warnings.append(
            InventoryWarning(
                type="session_count_low",
                severity="warning",
                context=str(subject.subject_path),
                message="Subject has only one inferred session (expected 1-2)",
            )
        )

    sessions: list[tuple[str, str, list[tuple[Path, dict[str, str]]]]] = []
    for session_index, (cluster_key, files) in enumerate(sorted_clusters, start=1):
        session_label = f"ses-{session_index:02d}"
        cluster_id = session_cluster_label(cluster_key)
        sessions.append((session_label, cluster_id, files))

    return sessions, warnings


def group_series(
    session_files: list[tuple[Path, dict[str, str]]],
) -> dict[str, list[tuple[Path, dict[str, str]]]]:
    """Group session files by SeriesInstanceUID with deterministic ordering."""
    series_map: dict[str, list[tuple[Path, dict[str, str]]]] = defaultdict(list)
    for dicom_path, metadata in session_files:
        series_uid = metadata.get("series_instance_uid") or "UNKNOWN_SERIES"
        series_map[series_uid].append((dicom_path, metadata))

    return dict(sorted(series_map.items()))


def collect_corrupt_records(
    subject: SubjectIndex,
    cache: MetadataCache,
) -> list[CorruptDicomRecord]:
    """Collect corrupted DICOM records for one subject."""
    records: list[CorruptDicomRecord] = []
    for dicom_path in subject.dicom_files:
        resolved = dicom_path.resolve()
        error = cache.get_error(resolved)
        if error is None:
            continue
        records.append(
            CorruptDicomRecord(
                cohort=subject.cohort,
                subject_label=subject.subject_label,
                subject_path=str(subject.subject_path),
                dicom_path=str(resolved),
                error=error,
            )
        )
    return records


def extract_subject_metadata(
    subject: SubjectIndex,
    cache: MetadataCache,
) -> tuple[list[tuple[Path, dict[str, str]]], list[CorruptDicomRecord], list[InventoryWarning]]:
    """Phase 2: read metadata once per file and partition readable vs corrupt."""
    warnings: list[InventoryWarning] = []
    readable: list[tuple[Path, dict[str, str]]] = []

    if not subject.dicom_files:
        warnings.append(
            InventoryWarning(
                type="empty_subject_folder",
                severity="warning",
                context=str(subject.subject_path),
                message="Subject folder contains no indexed DICOM files",
            )
        )
        return readable, [], warnings

    corrupt_records = collect_corrupt_records(subject, cache)
    for record in corrupt_records:
        warnings.append(
            InventoryWarning(
                type="corrupted_dicom",
                severity="error",
                context=record.dicom_path,
                message=record.error,
            )
        )

    for dicom_path in subject.dicom_files:
        metadata = cache.get(dicom_path)
        if metadata is not None:
            readable.append((dicom_path, metadata))

    return readable, corrupt_records, warnings


def build_series_records(
    subject: SubjectIndex,
    session_label: str,
    session_cluster_key: str,
    series_groups: dict[str, list[tuple[Path, dict[str, str]]]],
    warnings: list[InventoryWarning],
) -> list[dict[str, str]]:
    """Build inventory rows for all series in one session."""
    records: list[dict[str, str]] = []
    session_index = session_label.replace("ses-", "")

    for series_uid, series_files in series_groups.items():
        representative_path, representative_meta = series_files[0]

        for field in REQUIRED_METADATA:
            if not representative_meta.get(field):
                warnings.append(
                    InventoryWarning(
                        type="missing_metadata",
                        severity="warning",
                        context=str(representative_path.resolve()),
                        message=f"Missing metadata field '{field}'",
                    )
                )

        modality = representative_meta.get("modality", "")
        if modality.upper() in {"", "UNKNOWN"}:
            warnings.append(
                InventoryWarning(
                    type="unknown_modality",
                    severity="warning",
                    context=str(representative_path.resolve()),
                    message=f"Unknown modality for series {series_uid}",
                )
            )

        study_uid = representative_meta.get("study_instance_uid", "")
        records.append(
            {
                "cohort": subject.cohort,
                "source_subject_folder": subject.subject_label,
                "source_subject_path": str(subject.subject_path),
                "session_index": session_index,
                "session_label": session_label,
                "session_cluster_key": session_cluster_key,
                "study_instance_uid": study_uid,
                "series_instance_uid": series_uid,
                "series_description": representative_meta.get("series_description", ""),
                "modality": modality,
                "protocol_name": representative_meta.get("protocol_name", ""),
                "series_number": representative_meta.get("series_number", ""),
                "n_dicom_files": str(len(series_files)),
                "representative_dicom": str(representative_path.resolve()),
                "patient_id_raw": representative_meta.get("patient_id", ""),
                "patient_sex": representative_meta.get("patient_sex", ""),
                "study_date": representative_meta.get("study_date", ""),
                "study_time": representative_meta.get("study_time", ""),
                "series_time": representative_meta.get("series_time", ""),
            }
        )

    return records


def build_inventory_records(
    cohort: str,
    cohort_path: Path,
    cache: MetadataCache,
) -> tuple[list[dict[str, str]], list[InventoryWarning], list[CorruptDicomRecord]]:
    """Build inventory rows, warnings, and corrupt records for one cohort."""
    records: list[dict[str, str]] = []
    warnings: list[InventoryWarning] = []
    corrupt_records: list[CorruptDicomRecord] = []

    subjects, index_warnings = index_cohort_filesystem(cohort, cohort_path)
    warnings.extend(index_warnings)

    for subject in subjects:
        readable_files, subject_corrupt, subject_warnings = extract_subject_metadata(
            subject, cache
        )
        warnings.extend(subject_warnings)
        corrupt_records.extend(subject_corrupt)

        if not readable_files:
            continue

        sessions, session_warnings = infer_sessions(subject, readable_files)
        warnings.extend(session_warnings)

        for session_label, session_cluster_key, session_files in sessions:
            series_groups = group_series(session_files)
            records.extend(
                build_series_records(
                    subject,
                    session_label,
                    session_cluster_key,
                    series_groups,
                    warnings,
                )
            )

    return records, warnings, corrupt_records


def log_structured_warnings(
    logger: logging.Logger,
    warnings: list[InventoryWarning],
) -> None:
    """Log structured inventory warnings."""
    for warning in warnings:
        log_fn = logger.warning if warning.severity == "warning" else logger.error
        log_fn(
            "[%s|%s] %s — %s",
            warning.type,
            warning.severity,
            warning.context,
            warning.message,
        )


def write_warning_artifacts(
    warnings: list[InventoryWarning],
    warnings_csv: Path,
    warnings_log: Path,
) -> None:
    """Persist structured warnings to CSV and a human-readable log."""
    if not warnings:
        return

    deduped = list(
        {
            (warning.type, warning.severity, warning.context, warning.message): warning
            for warning in warnings
        }.values()
    )
    deduped.sort(key=lambda warning: (warning.severity, warning.type, warning.context))

    warning_rows = [
        {
            "type": warning.type,
            "severity": warning.severity,
            "context": warning.context,
            "message": warning.message,
        }
        for warning in deduped
    ]
    pd.DataFrame(warning_rows).to_csv(warnings_csv, index=False)

    log_lines = [
        f"{row['severity'].upper()} | {row['type']} | {row['context']} | {row['message']}"
        for row in warning_rows
    ]
    warnings_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")


def write_corrupt_artifacts(
    corrupt_records: list[CorruptDicomRecord],
    corrupt_csv: Path,
) -> None:
    """Persist per-subject corrupted DICOM tracking."""
    if not corrupt_records:
        return

    rows = [
        {
            "cohort": record.cohort,
            "subject_label": record.subject_label,
            "subject_path": record.subject_path,
            "dicom_path": record.dicom_path,
            "error": record.error,
        }
        for record in sorted(
            corrupt_records,
            key=lambda record: (
                record.cohort,
                record.subject_label,
                record.dicom_path,
            ),
        )
    ]
    pd.DataFrame(rows).to_csv(corrupt_csv, index=False)


def run_inventory(paths: ProjectPaths) -> pd.DataFrame:
    """Execute read-only inventory discovery and write outputs."""
    paths.ensure_metadata_dir()
    paths.validate_writable(paths.metadata)

    all_records: list[dict[str, str]] = []
    all_warnings: list[InventoryWarning] = []
    all_corrupt: list[CorruptDicomRecord] = []
    cache = MetadataCache()

    cohorts = discover_cohort_dirs(paths.raw_original)
    for cohort, cohort_path in cohorts:
        if cohort not in COHORT_NAMES:
            all_warnings.append(
                InventoryWarning(
                    type="unknown_cohort",
                    severity="warning",
                    context=str(cohort_path.resolve()),
                    message=f"Unknown cohort directory discovered: {cohort}",
                )
            )

        LOGGER.info("Scanning cohort '%s' at %s", cohort, cohort_path)
        records, warnings, corrupt_records = build_inventory_records(
            cohort, cohort_path, cache
        )
        all_records.extend(records)
        all_warnings.extend(warnings)
        all_corrupt.extend(corrupt_records)
        LOGGER.info(
            "Cohort '%s': %d series records, %d corrupt files",
            cohort,
            len(records),
            len(corrupt_records),
        )

    if all_corrupt:
        write_corrupt_artifacts(all_corrupt, paths.inventory_corrupt_csv)
        LOGGER.error(
            "Found %d corrupted DICOM file(s); see %s",
            len(all_corrupt),
            paths.inventory_corrupt_csv,
        )
        raise FatalPipelineError(
            f"Inventory encountered {len(all_corrupt)} corrupted DICOM file(s)"
        )

    if not all_records:
        raise FatalPipelineError(
            "Inventory found zero DICOM series. Cannot proceed."
        )

    df = pd.DataFrame(all_records)
    df = df.sort_values(
        by=[
            "cohort",
            "source_subject_folder",
            "session_index",
            "series_number",
            "series_instance_uid",
        ],
        kind="mergesort",
    ).reset_index(drop=True)

    df.to_csv(paths.inventory_csv, index=False)
    LOGGER.info("Wrote inventory: %s (%d rows)", paths.inventory_csv, len(df))

    if all_warnings:
        log_structured_warnings(LOGGER, all_warnings)
        write_warning_artifacts(
            all_warnings,
            paths.inventory_warnings_csv,
            paths.inventory_warnings,
        )
        LOGGER.info(
            "Wrote inventory warnings: %s, %s",
            paths.inventory_warnings_csv,
            paths.inventory_warnings,
        )

    manifest = build_manifest(
        paths.root,
        steps_completed=["inventory"],
        extra={
            "inventory_rows": len(df),
            "inventory_warnings": len(all_warnings),
            "inventory_corrupt_files": len(all_corrupt),
        },
    )
    write_manifest(paths.pipeline_manifest_json, manifest)

    return df


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Discover DICOM subjects, sessions, and series (read-only)."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for inventory discovery."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    log_file = paths.metadata / "inventory.log"
    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=log_file,
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting inventory (read-only) for %s", paths.root)
    try:
        run_inventory(paths)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("Inventory completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
