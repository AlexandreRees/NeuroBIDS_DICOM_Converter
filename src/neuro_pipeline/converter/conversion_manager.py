"""Conversion orchestration: DICOM → dcm2niix → BIDS → validation → report.

QC / blocking metadata validation are intentionally not part of this pipeline.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from neuro_pipeline.bids import BIDSExporter, BidsExportResult
from neuro_pipeline.bids.validator import BIDSValidationResult, BIDSValidator
from neuro_pipeline.converter.dcm2niix import Converter
from neuro_pipeline.logging.privacy import session_log_message
from neuro_pipeline.logging.setup import get_conversion_logger
from neuro_pipeline.models import ConversionJob, ConversionOptions, ConversionResult, DicomSeries
from neuro_pipeline.provenance import ProvenanceRecorder
from neuro_pipeline.reports import BidsValidationReportWriter
from neuro_pipeline.utils.exceptions import (
    MissingDcm2niixError,
    NeuroPipelineError,
    OutputFolderError,
    PermissionDeniedError,
)
from neuro_pipeline.utils.filesystem import ensure_writable_dir
from neuro_pipeline.utils.naming import SmartFilenameEngine
from neuro_pipeline.validation.report_generator import ReportContext, ReportGenerator
from neuro_pipeline.validation.models import ValidationSummary

LOGGER = logging.getLogger(__name__)
CONV_LOG = get_conversion_logger()

ProgressHook = Callable[[str], None]
ResultHook = Callable[[ConversionResult], None]
StopCheck = Callable[[], bool]


@dataclass(slots=True)
class PipelineResult:
    """Full pipeline outcome for one conversion session."""

    conversion_results: list[ConversionResult] = field(default_factory=list)
    validation: ValidationSummary = field(default_factory=ValidationSummary)
    report_path: Path | None = None
    input_folder: Path | None = None
    output_folder: Path | None = None
    bids_export: BidsExportResult | None = None
    bids_validation: BIDSValidationResult | None = None
    bids_validation_report: Path | None = None
    provenance_path: Path | None = None
    conversion_errors_path: Path | None = None
    plan_validation_ok: bool | None = None
    plan_validation_summary: str = ""

    @property
    def converted(self) -> int:
        return sum(1 for r in self.conversion_results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.conversion_results if not r.success)

    @property
    def conversion_success(self) -> bool:
        """True when every attempted DICOM→NIfTI conversion succeeded."""
        return bool(self.conversion_results) and self.failed == 0


class ConversionManager:
    """DICOM → dcm2niix → (optional BIDS) → BIDS validation → provenance → report."""

    def __init__(
        self,
        *,
        dcm2niix_path: str | Path | None = None,
        naming_engine: SmartFilenameEngine | None = None,
        min_free_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        self.converter = Converter(
            dcm2niix_path=dcm2niix_path,
            naming_engine=naming_engine,
        )
        self.min_free_bytes = min_free_bytes

    def prepare(self, output_dir: Path) -> Path:
        """Pre-flight checks before conversion starts."""
        try:
            self.converter.verify()
        except Exception as exc:
            from neuro_pipeline.utils.exceptions import Dcm2niixNotFoundError

            if isinstance(exc, Dcm2niixNotFoundError):
                raise MissingDcm2niixError(str(exc)) from exc
            raise

        try:
            out = ensure_writable_dir(output_dir, create=True)
        except PermissionDeniedError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OutputFolderError(f"Cannot use output folder: {output_dir}") from exc

        usage = shutil.disk_usage(out)
        if usage.free < self.min_free_bytes:
            mb = self.min_free_bytes // (1024 * 1024)
            raise OutputFolderError(
                "Insufficient disk space for conversion.\n"
                f"Need at least ~{mb} MB free "
                f"(available: {usage.free // (1024 * 1024)} MB)."
            )
        CONV_LOG.info("Pre-flight OK: dcm2niix ready, output writable, disk space OK")
        return out

    def run(
        self,
        *,
        series_list: Sequence[DicomSeries],
        input_folder: Path,
        output_dir: Path,
        options: ConversionOptions,
        progress: ProgressHook | None = None,
        result_callback: ResultHook | None = None,
        stop_check: StopCheck | None = None,
        conversion_plan: object | None = None,
    ) -> PipelineResult:
        """Execute: conversion → BIDS export → BIDS validation → provenance → report.

        Parameters
        ----------
        conversion_plan:
            Optional validated :class:`~neuro_pipeline.bids.conversion_plan.BIDSConversionPlan`.
            When provided, only included series are converted and BIDS naming follows the plan.
            The DICOM input tree is never modified.
        """
        from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan

        series_list = list(series_list)
        plan: BIDSConversionPlan | None = None
        plan_validation_ok: bool | None = None
        plan_validation_summary = ""
        if conversion_plan is not None:
            if not isinstance(conversion_plan, BIDSConversionPlan):
                raise NeuroPipelineError("conversion_plan must be a BIDSConversionPlan.")
            plan = conversion_plan
            # Ensure every included series has a NIfTI filename before convert
            plan.refresh_filenames(seed_existing_from_output=True)
            validation = plan.validate()
            plan_validation_ok = validation.ok
            plan_validation_summary = validation.summary()
            if not validation.ok:
                CONV_LOG.warning(
                    "BIDS conversion plan validation reported errors. "
                    "NIfTI conversion will continue.\n%s",
                    validation.summary(),
                )
            elif validation.warnings:
                CONV_LOG.info(
                    "BIDS conversion plan validation warnings:\n%s",
                    validation.summary(),
                )
            series_list = plan.included_series(series_list)

        out = self.prepare(output_dir)
        bids_mode = str(options.output_layout or "nifti").strip().lower() == "bids"

        if bids_mode:
            subject = (options.subject_id or "").strip()
            if not subject and plan is None:
                raise NeuroPipelineError(
                    "Subject ID is required for BIDS export.\n"
                    "Enter a BIDS-safe label (e.g. 001 → sub-001)."
                )
            if not subject and plan is not None:
                # Prefer first included plan subject for options / reports
                for item in plan.items:
                    if item.include_in_conversion and item.subject:
                        options.subject_id = item.subject
                        break

        convert_root = ensure_writable_dir(out / "_staging", create=True) if bids_mode else out

        CONV_LOG.info(
            session_log_message(
                input_folder=input_folder,
                output_folder=out,
                n_series=len(series_list),
                status="started",
            )
        )

        provenance = ProvenanceRecorder()
        if progress:
            progress("Hashing input DICOM folder (read-only)…")
        input_hash = provenance.hash_input(input_folder)

        results: list[ConversionResult] = []
        for series in series_list:
            if stop_check and stop_check():
                break
            job = ConversionJob(series=series, output_dir=convert_root, options=options)
            outcome = self.converter.convert_series(job, progress=progress)
            results.append(outcome)
            if result_callback:
                result_callback(outcome)
            if not outcome.success and "dcm2niix was not found" in (outcome.error or ""):
                break

        errors_path = _write_conversion_errors(out, results)

        bids_export: BidsExportResult | None = None
        if bids_mode:
            if progress:
                progress("Exporting BIDS dataset…")
            session_ids = _resolve_session_queue(options)
            if len(session_ids) <= 1:
                sess = session_ids[0] if session_ids else (options.session_id or None)
                bids_export = BIDSExporter(
                    out,
                    subject_id=options.subject_id,
                    session_id=sess,
                    conversion_plan=plan,
                ).export(results, conversion_plan=plan)
            else:
                for sess in session_ids:
                    bids_export = BIDSExporter(
                        out,
                        subject_id=options.subject_id,
                        session_id=sess,
                        conversion_plan=plan,
                    ).export(results, conversion_plan=plan)
            CONV_LOG.info(
                "BIDS export: exported=%s skipped=%s",
                bids_export.exported if bids_export else 0,
                bids_export.skipped if bids_export else 0,
            )

        bids_validation: BIDSValidationResult | None = None
        bids_validation_report: Path | None = None
        if bids_mode:
            if progress:
                progress("Running BIDS validation…")
            bids_validation = BIDSValidator().validate(out)
            bids_validation_report = BidsValidationReportWriter(out).write(bids_validation)
            CONV_LOG.info("BIDS validation: %s", bids_validation.status.value)

        if progress:
            progress("Writing conversion provenance…")
        try:
            dcm2niix_ref = ""
            try:
                dcm2niix_ref = str(self.converter.verify())
            except Exception:  # noqa: BLE001
                dcm2niix_ref = ""
            provenance_path = provenance.write(
                dataset_or_output_root=out,
                input_path=input_folder,
                input_hash=input_hash,
                dcm2niix_version=dcm2niix_ref,
                parameters={
                    "output_layout": options.output_layout,
                    "compress": options.compress,
                    "preserve_json": options.preserve_json,
                    "subject_id": options.subject_id,
                    "session_id": options.session_id,
                    "conversion_plan": bool(plan),
                },
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Provenance recording failed: %s", exc)
            provenance_path = None

        if progress:
            progress("Writing conversion_report.html…")
        report_path = ReportGenerator(out).write(
            ReportContext(
                input_folder=Path(input_folder),
                output_folder=out,
                conversion_results=results,
                validation=ValidationSummary(),
                series_detected=len(series_list),
                subject_id=options.subject_id or "",
                session_id=options.session_id or "",
                bids_validation_status=(
                    bids_validation.status.value if bids_validation else ""
                ),
            )
        )

        status = "failed" if any(not r.success for r in results) else "completed"
        # BIDS validation FAIL is diagnostic only — session status tracks NIfTI results.
        CONV_LOG.info(
            session_log_message(
                input_folder=input_folder,
                output_folder=out,
                n_series=len(series_list),
                status=status,
            )
        )
        if plan_validation_ok is not None:
            CONV_LOG.info(
                "Plan validation: %s | NIfTI conversion: %s",
                "OK" if plan_validation_ok else "FAILED",
                "SUCCESS" if not any(not r.success for r in results) else "FAILED",
            )
        return PipelineResult(
            conversion_results=results,
            validation=ValidationSummary(),
            report_path=report_path,
            input_folder=Path(input_folder),
            output_folder=out,
            bids_export=bids_export,
            bids_validation=bids_validation,
            bids_validation_report=bids_validation_report,
            provenance_path=provenance_path,
            conversion_errors_path=errors_path,
            plan_validation_ok=plan_validation_ok,
            plan_validation_summary=plan_validation_summary,
        )


def _write_conversion_errors(
    output_dir: Path, results: Sequence[ConversionResult]
) -> Path | None:
    """Persist dcm2niix failures as ``conversion_errors.json`` (never crashes)."""
    errors: list[dict[str, Any]] = []
    for result in results:
        if result.success:
            continue
        errors.append(
            {
                "series": result.series.display_name,
                "exit_code": _exit_code_from_error(result),
                "message": result.error or "conversion failed",
                "stdout": (result.stdout or "")[:4000],
                "stderr": (result.stderr or "")[:4000],
            }
        )
    path = Path(output_dir) / "conversion_errors.json"
    try:
        path.write_text(json.dumps(errors, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Could not write conversion_errors.json: %s", exc)
        return None


def _exit_code_from_error(result: ConversionResult) -> str:
    err = result.error or ""
    # "dcm2niix failed (exit N)"
    import re

    match = re.search(r"exit\s+(\d+)", err, flags=re.I)
    return match.group(1) if match else ""


def _resolve_session_queue(options: ConversionOptions) -> list[str]:
    queue = [str(s).strip() for s in (options.session_queue or []) if str(s).strip()]
    if queue:
        seen: set[str] = set()
        out: list[str] = []
        for item in queue:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out
    if options.session_id and str(options.session_id).strip():
        return [str(options.session_id).strip()]
    return []
