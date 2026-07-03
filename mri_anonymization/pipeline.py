"""Core anonymization pipeline orchestration."""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from mri_anonymization.config import AnonymizationConfig
from mri_anonymization.date_shift import generate_date_shifts, write_date_shift_csv
from mri_anonymization.defacing import run_defacing
from mri_anonymization.dicom_anonymizer import is_dicom_file, process_dicom_file
from mri_anonymization.documentation import generate_anonymization_md, write_bids_root_files
from mri_anonymization.logging_utils import configure_logger, write_file_results
from mri_anonymization.metadata_anonymizer import (
    copy_binary_file,
    is_json_sidecar,
    is_nifti,
    is_tabular_metadata,
    process_json_file,
    process_tabular_file,
    process_text_file,
)
from mri_anonymization.models import AnonymizationState, FileResult, PipelineStats
from mri_anonymization.paths import AnonymizationPaths
from mri_anonymization.subject_id import (
    build_subject_mappings,
    discover_subjects,
    remap_path_component,
    write_subject_mapping_csv,
)
from mri_anonymization.validation import run_validation

LOGGER = logging.getLogger("mri_anonymization")


@dataclass(frozen=True)
class FileJob:
    """Work item for processing one input file."""

    source_path: Path
    destination_path: Path
    original_subject: str
    anonymized_subject: str
    shift_days: int
    preserve_patient_sex: bool
    subject_map: dict[str, str]


def _classify_file(path: Path) -> str:
    """Return a file type label for reporting."""
    if is_dicom_file(path):
        return "dicom"
    if is_json_sidecar(path):
        return "json"
    if is_tabular_metadata(path):
        return "tabular"
    if is_nifti(path):
        return "nifti"
    return "other"


def _process_file(job: FileJob) -> FileResult:
    """Process a single file; never raise to caller."""
    file_type = _classify_file(job.source_path)
    try:
        if file_type == "dicom":
            dicom_result = process_dicom_file(
                job.source_path,
                job.destination_path,
                job.anonymized_subject,
                job.shift_days,
                job.preserve_patient_sex,
            )
            if not dicom_result.success:
                return FileResult(
                    source_path=str(job.source_path),
                    output_path=str(job.destination_path),
                    subject_id=job.anonymized_subject,
                    file_type=file_type,
                    status="failed",
                    message=dicom_result.message,
                )
            if dicom_result.validation.warnings:
                return FileResult(
                    source_path=str(job.source_path),
                    output_path=str(job.destination_path),
                    subject_id=job.anonymized_subject,
                    file_type=file_type,
                    status="success",
                    message="; ".join(dicom_result.validation.warnings),
                )
        elif file_type == "json":
            process_json_file(
                job.source_path,
                job.destination_path,
                job.subject_map,
                job.shift_days,
            )
        elif file_type == "tabular":
            process_tabular_file(
                job.source_path,
                job.destination_path,
                job.subject_map,
                job.shift_days,
            )
        elif file_type == "nifti":
            copy_binary_file(job.source_path, job.destination_path)
        else:
            if job.destination_path.suffix.lower() in {".md", ".txt", ".tsv", ".csv"}:
                process_text_file(job.source_path, job.destination_path, job.subject_map)
            else:
                copy_binary_file(job.source_path, job.destination_path)
        return FileResult(
            source_path=str(job.source_path),
            output_path=str(job.destination_path),
            subject_id=job.anonymized_subject,
            file_type=file_type,
            status="success",
        )
    except Exception as exc:
        return FileResult(
            source_path=str(job.source_path),
            output_path=str(job.destination_path),
            subject_id=job.anonymized_subject,
            file_type=file_type,
            status="failed",
            message=str(exc),
        )


def _collect_jobs(
    input_dir: Path,
    public_dataset: Path,
    subject_map: dict[str, str],
    date_shifts: dict[str, int],
    preserve_patient_sex: bool,
) -> list[FileJob]:
    """Build processing jobs for every file under the input dataset."""
    jobs: list[FileJob] = []
    for source_path in sorted(input_dir.rglob("*")):
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(input_dir)
        if relative.parts and relative.parts[0] in subject_map:
            original_subject = relative.parts[0]
            anonymized_subject = subject_map[original_subject]
            shift_days = date_shifts[anonymized_subject]
            destination = public_dataset / remap_path_component(relative, subject_map)
            jobs.append(
                FileJob(
                    source_path=source_path,
                    destination_path=destination,
                    original_subject=original_subject,
                    anonymized_subject=anonymized_subject,
                    shift_days=shift_days,
                    preserve_patient_sex=preserve_patient_sex,
                    subject_map=subject_map,
                )
            )
        else:
            destination = public_dataset / relative
            jobs.append(
                FileJob(
                    source_path=source_path,
                    destination_path=destination,
                    original_subject="",
                    anonymized_subject="",
                    shift_days=0,
                    preserve_patient_sex=preserve_patient_sex,
                    subject_map=subject_map,
                )
            )
    return jobs


def _count_sessions(public_dataset: Path) -> int:
    """Count unique subject/session pairs in output."""
    sessions: set[tuple[str, str]] = set()
    for subject_dir in public_dataset.iterdir():
        if not subject_dir.is_dir() or not subject_dir.name.startswith("sub-"):
            continue
        for child in subject_dir.iterdir():
            if child.is_dir() and child.name.startswith("ses-"):
                sessions.add((subject_dir.name, child.name))
    return len(sessions)


class AnonymizationPipeline:
    """Production anonymization pipeline for public neuroimaging release."""

    def __init__(self, config: AnonymizationConfig) -> None:
        """Initialize pipeline with validated configuration."""
        config.validate()
        self.config = config
        self.paths = AnonymizationPaths(config.output_root)
        self.logger = configure_logger(self.paths.processing_log)

    def run(self) -> PipelineStats:
        """Execute the full anonymization workflow."""
        self.paths.ensure_directories()
        self.logger.info("Starting anonymization: input=%s", self.config.input_dir)

        original_subjects = discover_subjects(self.config.input_dir)
        mappings = build_subject_mappings(original_subjects, self.config.seed)
        subject_map = {
            mapping.original_subject_id: mapping.anonymized_subject_id
            for mapping in mappings
        }
        write_subject_mapping_csv(mappings, self.paths.subject_mapping_csv)

        anonymized_subjects = sorted(subject_map.values())
        shifts = generate_date_shifts(anonymized_subjects, self.config.seed)
        date_shift_map = {shift.subject: shift.shift_days for shift in shifts}
        write_date_shift_csv(shifts, self.paths.date_shift_csv)

        jobs = _collect_jobs(
            self.config.input_dir,
            self.paths.public_dataset,
            subject_map,
            date_shift_map,
            self.config.preserve_patient_sex,
        )

        results: list[FileResult] = []
        with ProcessPoolExecutor(max_workers=self.config.num_workers) as executor:
            futures = {executor.submit(_process_file, job): job for job in jobs}
            for future in tqdm(as_completed(futures), total=len(futures), desc="Anonymizing"):
                result = future.result()
                results.append(result)
                if result.status == "failed":
                    self.logger.warning("Failed %s: %s", result.source_path, result.message)

        stats = self._build_stats(results, subject_map)
        write_file_results(
            results,
            self.paths.anonymization_summary_csv,
            self.paths.skipped_files_csv,
            self.paths.failed_files_csv,
        )

        write_bids_root_files(
            self.paths.public_dataset,
            self.config.dataset_name,
            self.config.license_text,
        )

        if self.config.enable_defacing:
            defacing_report = run_defacing(self.paths.public_dataset, stats)
            defacing_report.to_csv(self.paths.defacing_report_csv, index=False)
        else:
            self.logger.info("Defacing disabled")

        validation = run_validation(
            self.paths.public_dataset,
            self.paths.private,
            subject_map,
            self.paths.validation_report_md,
        )

        generate_anonymization_md(
            self.paths.anonymization_md,
            stats,
            enable_defacing=self.config.enable_defacing,
            deterministic=self.config.deterministic,
            validation=validation,
        )

        self.logger.info(
            "Anonymization complete: %d success, %d failed, %d skipped",
            stats.n_files_processed,
            stats.n_files_failed,
            stats.n_files_skipped,
        )
        return stats

    def _build_stats(
        self,
        results: list[FileResult],
        subject_map: dict[str, str],
    ) -> PipelineStats:
        """Aggregate run statistics from file results."""
        stats = PipelineStats(n_subjects=len(subject_map))
        stats.n_sessions = _count_sessions(self.paths.public_dataset)

        for result in results:
            if result.status == "success":
                stats.n_files_processed += 1
            elif result.status == "failed":
                stats.n_files_failed += 1
                stats.warnings.append(f"Failed: {result.source_path} — {result.message}")
            else:
                stats.n_files_skipped += 1

            if result.file_type == "dicom":
                stats.n_dicom_files += 1
            elif result.file_type in {"json", "tabular"}:
                stats.n_metadata_files += 1
            elif result.file_type == "nifti":
                stats.n_nifti_files += 1

        return stats
