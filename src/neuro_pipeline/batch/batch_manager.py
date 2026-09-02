"""Batch conversion orchestration (uses existing ConversionManager unchanged)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

from neuro_pipeline.batch.batch_models import BatchJob, BatchJobStatus, BatchState, SeriesCheckpoint
from neuro_pipeline.batch.batch_queue import BatchQueue
from neuro_pipeline.batch.exceptions import BatchError, BatchPausedError
from neuro_pipeline.batch.input_analysis import InputAnalysis, sanitize_patient_id
from neuro_pipeline.batch import resume as resume_mod
from neuro_pipeline.converter.conversion_manager import ConversionManager, PipelineResult
from neuro_pipeline.dicom import DicomParser
from neuro_pipeline.models import ConversionOptions, DicomSeries, SeriesStatus
from neuro_pipeline.utils.exceptions import InvalidDicomFolderError

LOGGER = logging.getLogger(__name__)

ProgressHook = Callable[[BatchJob, str], None]
JobHook = Callable[[BatchJob], None]
StopCheck = Callable[[], bool]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BatchManager:
    """Discover subject folders and convert them with resume / checkpoint support.

    Important: this class never modifies the conversion engine internals. It only
    calls :class:`ConversionManager` as an external consumer.
    """

    def __init__(
        self,
        *,
        conversion_manager: ConversionManager | None = None,
        parser: DicomParser | None = None,
        output_layout: str = "bids",
    ) -> None:
        self.conversion_manager = conversion_manager or ConversionManager()
        self.parser = parser or DicomParser()
        self.output_layout = output_layout
        self.queue = BatchQueue()
        self._pause_requested = False

    def request_pause(self) -> None:
        self._pause_requested = True

    def clear_pause(self) -> None:
        self._pause_requested = False

    def discover_datasets(self, root: Path | str, *, output_root: Path | str) -> list[BatchJob]:
        """Discover subject source folders under ``root`` (any depth).

        Uses recursive DICOM discovery + tree partition so mixed layouts work::

            root/
              subject001/…
              group/
                subject002/visit01/raw/MR/DICOM/…

        Falls back to immediate child folders only when no DICOM is found
        (preserves previous empty-tree behaviour for UI scaffolding).
        """
        root_path = Path(root)
        out_root = Path(output_root)
        if not root_path.is_dir():
            raise BatchError(f"Input directory does not exist: {root_path}")

        jobs: list[BatchJob] = []
        try:
            from neuro_pipeline.discovery import DatasetDiscovery

            discovery = DatasetDiscovery(parser=self.parser).discover(
                root_path, mode="automatic"
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Recursive discovery failed during batch scan: %s", exc)
            discovery = None

        if discovery is not None and discovery.has_dicom and discovery.subjects:
            seen_keys: set[str] = set()
            for subject in discovery.subjects:
                folder = (
                    Path(subject.source_folder_path)
                    if subject.source_folder_path
                    else root_path
                )
                # Never drop subjects that share the root: key by folder path OR label.
                key = (
                    str(Path(subject.source_folder_path).resolve())
                    if subject.source_folder_path
                    else f"label:{subject.bids_subject}"
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                label = subject.source_folder or folder.name or subject.bids_subject
                job = BatchJob.create(folder, out_root, label=label)
                job.patient_id_filter = subject.bids_subject
                job.series_uids = list(subject.series_uids or [])
                job.source_folder_path = subject.source_folder_path or ""
                job.original_patient_id = subject.dicom_patient_id or ""
                job.series_count = len(subject.series_uids or [])
                jobs.append(job)
        else:
            children = sorted(
                [
                    p
                    for p in root_path.iterdir()
                    if p.is_dir() and not p.name.startswith(".")
                ]
            )
            if not children:
                jobs.append(BatchJob.create(root_path, out_root, label=root_path.name))
            else:
                for child in children:
                    jobs.append(BatchJob.create(child, out_root, label=child.name))

        self.queue.replace_all(jobs)
        return jobs

    def analyze_folder(
        self,
        folder: Path | str,
        *,
        discovery_mode: str = "automatic",
    ) -> InputAnalysis:
        """Scan ``folder`` and summarize subjects / studies via recursive discovery."""
        root = Path(folder)
        if not root.is_dir():
            raise BatchError(f"Input directory does not exist: {root}")
        try:
            from neuro_pipeline.discovery import DatasetDiscovery

            series, discovery = DatasetDiscovery(parser=self.parser).scan_series(
                root, mode=discovery_mode
            )
        except InvalidDicomFolderError:
            return InputAnalysis.empty(root, message="No DICOM files detected.")
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Input analysis failed: %s", exc)
            return InputAnalysis.empty(root, message="No DICOM files detected.")
        return InputAnalysis.from_discovery(series, discovery, folder=root)

    def plan_jobs(
        self,
        analysis: InputAnalysis,
        output_root: Path | str,
        *,
        subject_override: str = "",
        session_id: str = "",  # noqa: ARG002 - reserved for call-site options
    ) -> list[BatchJob]:
        """Create one job per reconstructed subject (PatientID or folder routing).

        Each job stores ``series_uids`` so conversion can filter without relying on
        raw DICOM PatientID equality after re-scan. When a subject has a dedicated
        source folder, that folder becomes ``input_path`` (narrower / faster scan).
        """
        out_root = Path(output_root)
        if not analysis.has_dicom:
            raise BatchError("No DICOM files detected.")

        override = (subject_override or "").strip()
        root = Path(analysis.folder)
        jobs: list[BatchJob] = []
        for summary in analysis.subjects:
            if override and analysis.number_of_subjects == 1:
                subject_label = override
            else:
                subject_label = summary.subject_label or sanitize_patient_id(summary.patient_id)

            if summary.source_folder_path:
                input_path = Path(summary.source_folder_path)
            else:
                input_path = root

            series_uids = list(summary.series_uids or [])
            if not series_uids:
                # Derive from analysis.series when discovery did not attach UIDs
                series_uids = [
                    s.series_instance_uid
                    for s in analysis.series
                    if s.series_instance_uid
                    and (
                        (s.patient_id or "").strip() == summary.patient_id
                        or sanitize_patient_id(s.patient_id or "") == subject_label
                    )
                ]

            job = BatchJob.create(
                input_path,
                out_root,
                label=summary.source_folder or f"Patient {summary.patient_id}",
            )
            job.subject_id = subject_label
            job.patient_id_filter = summary.patient_id
            job.series_uids = series_uids
            job.source_folder_path = summary.source_folder_path or ""
            job.original_patient_id = summary.original_patient_id or ""
            job.series_count = int(summary.series_count) or len(series_uids)
            jobs.append(job)
        self.queue.replace_all(jobs)
        return jobs

    def convert_folder(
        self,
        folder: Path | str,
        output_root: Path | str,
        *,
        options: ConversionOptions | None = None,
        subject_id: str = "",
        session_id: str = "",
        resume: bool = True,
        progress: ProgressHook | None = None,
        job_updated: JobHook | None = None,
        stop_check: StopCheck | None = None,
        analysis: InputAnalysis | None = None,
        conversion_plan=None,
    ) -> list[BatchJob]:
        """One-click conversion entry point.

        Automatically detects one or many subjects and creates internal batch
        jobs. The GUI never chooses Single vs Batch mode.
        """
        options = options or ConversionOptions()
        analysis = analysis or self.analyze_folder(folder)
        if not analysis.has_dicom:
            raise BatchError("No DICOM files detected.")

        self.plan_jobs(
            analysis,
            output_root,
            subject_override=subject_id,
            session_id=session_id,
        )
        # Force BIDS dataset export for the simplified one-click workflow.
        run_options = ConversionOptions(
            compress=options.compress,
            one_folder_per_patient=options.one_folder_per_patient,
            preserve_json=options.preserve_json,
            smart_naming=options.smart_naming,
            validate_output=options.validate_output,
            output_layout="bids",
            subject_id=(subject_id or options.subject_id or "").strip(),
            session_id=(session_id or options.session_id or "").strip(),
            study_mode=options.study_mode,
            session_queue=list(options.session_queue or []),
            export_profile=options.export_profile,
            threads=options.threads,
            dcm2niix_path=options.dcm2niix_path,
        )
        return self.run_all(
            options=run_options,
            resume=resume,
            progress=progress,
            job_updated=job_updated,
            stop_check=stop_check,
            conversion_plan=conversion_plan,
            preloaded_series=list(analysis.series),
        )

    def _job_state_root(self, job: BatchJob) -> Path:
        return Path(job.output_path) / ".batch" / job.job_id

    def find_resumable_jobs(self, jobs: Iterable[BatchJob] | None = None) -> list[BatchJob]:
        found: list[BatchJob] = []
        for job in jobs if jobs is not None else self.queue.all_jobs():
            if resume_mod.has_resumable_state(self._job_state_root(job)):
                found.append(job)
        return found

    def load_job_state(self, job: BatchJob) -> BatchState | None:
        return resume_mod.load_state(self._job_state_root(job))

    def run_all(
        self,
        *,
        options: ConversionOptions | None = None,
        resume: bool = True,
        progress: ProgressHook | None = None,
        job_updated: JobHook | None = None,
        stop_check: StopCheck | None = None,
        conversion_plan=None,
        preloaded_series: list[DicomSeries] | None = None,
    ) -> list[BatchJob]:
        """Run every queued / paused job sequentially."""
        self.clear_pause()
        options = options or ConversionOptions()
        results: list[BatchJob] = []
        for job in self.queue.all_jobs():
            if stop_check and stop_check():
                break
            if self._pause_requested:
                break
            if job.status == BatchJobStatus.COMPLETED:
                results.append(job)
                continue
            try:
                job_plan = conversion_plan
                if conversion_plan is not None and job.patient_id_filter:
                    job_plan = conversion_plan.filter_for_patient(job.patient_id_filter)
                job_series = None
                if preloaded_series is not None:
                    job_series = self._filter_series_for_job(job, preloaded_series)
                self.run_job(
                    job,
                    options=options,
                    resume=resume,
                    progress=progress,
                    job_updated=job_updated,
                    stop_check=stop_check,
                    conversion_plan=job_plan,
                    preloaded_series=job_series,
                )
            except BatchPausedError:
                job.status = BatchJobStatus.PAUSED
                job.finished = None
                if job_updated:
                    job_updated(job)
                results.append(job)
                break
            results.append(job)
        return results

    def run_job(
        self,
        job: BatchJob,
        *,
        options: ConversionOptions | None = None,
        resume: bool = True,
        progress: ProgressHook | None = None,
        job_updated: JobHook | None = None,
        stop_check: StopCheck | None = None,
        conversion_plan=None,
        preloaded_series: list[DicomSeries] | None = None,
    ) -> BatchJob:
        """Convert one dataset folder with optional resume + per-series skip."""
        options = options or ConversionOptions()
        # Per-job BIDS identity — never infer from folder name
        subject = (job.subject_id or options.subject_id or "").strip()
        if not subject:
            job.status = BatchJobStatus.FAILED
            job.error = "Subject ID is required for each batch job (do not use folder names)."
            job.finished = _utc_now()
            if job_updated:
                job_updated(job)
            return job
        # Force BIDS layout for batch BIDS dataset assembly
        options = ConversionOptions(
            compress=options.compress,
            one_folder_per_patient=options.one_folder_per_patient,
            preserve_json=options.preserve_json,
            smart_naming=options.smart_naming,
            validate_output=options.validate_output,
            output_layout="bids",
            subject_id=subject,
            session_id=options.session_id,
            study_mode=options.study_mode,
            session_queue=list(options.session_queue or []),
            export_profile=options.export_profile,
            threads=options.threads,
            dcm2niix_path=options.dcm2niix_path,
        )
        out = Path(job.output_path)
        out.mkdir(parents=True, exist_ok=True)
        # Per-job resume/checkpoint nest (shared BIDS dataset root is safe)
        state_root = self._job_state_root(job)
        state_root.mkdir(parents=True, exist_ok=True)

        job.status = BatchJobStatus.RUNNING
        job.started = job.started or _utc_now()
        job.finished = None
        job.error = None
        if job_updated:
            job_updated(job)

        try:
            if preloaded_series is not None:
                # Always re-apply identity filter (caller may pass a shared pool).
                series_list = self._filter_series_for_job(job, preloaded_series)
                if progress:
                    progress(job, f"Using {len(series_list)} pre-identified series…")
            else:
                if progress:
                    progress(job, "Scanning DICOM series…")
                series_list = self.parser.scan(Path(job.input_path))
                series_list = self._filter_series_for_job(job, series_list)

            if not series_list:
                job.status = BatchJobStatus.FAILED
                job.series_count = 0
                job.error = (
                    "No matching DICOM series for this subject after discovery filter. "
                    "Check PatientID / folder routing (possible silent miss)."
                )
                job.finished = _utc_now()
                resume_mod.write_state(
                    state_root,
                    BatchState(
                        job_id=job.job_id,
                        status=BatchJobStatus.FAILED,
                        total_series=0,
                        input_path=job.input_path,
                        output_path=job.output_path,
                    ),
                )
                if progress:
                    progress(job, job.error)
                if job_updated:
                    job_updated(job)
                return job

            job.series_count = len(series_list)

            completed_uids: set[str] = set()
            if resume:
                state = resume_mod.load_state(state_root)
                if state is not None:
                    completed_uids = set(state.completed_series_uids)

            to_convert: list[DicomSeries] = []
            skipped = 0
            for series in series_list:
                uid = series.series_instance_uid or series.display_name
                source_files = list(series.source_dir.glob("*"))
                source_hash = resume_mod.compute_source_hash(source_files)
                if uid in completed_uids or resume_mod.should_skip_series(
                    output_root=state_root,
                    series_uid=uid,
                    source_hash=source_hash,
                ):
                    series.status = SeriesStatus.SKIPPED
                    skipped += 1
                    continue
                to_convert.append(series)

            state = BatchState(
                job_id=job.job_id,
                status=BatchJobStatus.RUNNING,
                completed_series=skipped,
                total_series=job.series_count,
                input_path=job.input_path,
                output_path=job.output_path,
                completed_series_uids=sorted(completed_uids),
            )
            resume_mod.write_state(state_root, state)
            job.converted_count = skipped
            job.failed_count = 0
            if job_updated:
                job_updated(job)

            if not to_convert:
                if skipped > 0:
                    job.status = BatchJobStatus.COMPLETED
                    job.finished = _utc_now()
                    state.status = BatchJobStatus.COMPLETED
                    state.completed_series = job.series_count
                    resume_mod.write_state(state_root, state)
                    if progress:
                        progress(job, f"Nothing to convert (skipped {skipped} series).")
                    if job_updated:
                        job_updated(job)
                    return job
                job.status = BatchJobStatus.FAILED
                job.error = "No series left to convert after filtering."
                job.finished = _utc_now()
                state.status = BatchJobStatus.FAILED
                resume_mod.write_state(state_root, state)
                if job_updated:
                    job_updated(job)
                return job

            def _series_progress(msg: str) -> None:
                if progress:
                    progress(job, msg)

            def _stop() -> bool:
                if self._pause_requested:
                    return True
                if stop_check and stop_check():
                    return True
                return False

            def _on_result(result) -> None:  # noqa: ANN001
                uid = ""
                source_files: list[Path] = []
                if result.series is not None:
                    uid = result.series.series_instance_uid or result.series.display_name
                    source_files = list(result.series.source_dir.glob("*"))
                source_hash = resume_mod.compute_source_hash(source_files)
                out_files = [str(p) for p in (result.output_files or [])]
                relative: list[str] = []
                for p in out_files:
                    try:
                        relative.append(str(Path(p).resolve().relative_to(out.resolve())))
                    except Exception:
                        relative.append(Path(p).name)
                output_hash = resume_mod.compute_output_hash(
                    Path(p) for p in out_files if Path(p).exists()
                )
                status = "completed" if result.success else "failed"
                resume_mod.write_series_checkpoint(
                    state_root,
                    SeriesCheckpoint(
                        source_hash=source_hash,
                        output_hash=output_hash,
                        status=status,
                        series_uid=uid,
                        output_files=relative,
                    ),
                )
                if result.success:
                    job.converted_count += 1
                    if uid:
                        completed_uids.add(uid)
                else:
                    job.failed_count += 1
                state.completed_series = job.converted_count + job.failed_count
                state.completed_series_uids = sorted(completed_uids)
                state.status = BatchJobStatus.RUNNING
                resume_mod.write_state(state_root, state)
                if job_updated:
                    job_updated(job)

            pipeline: PipelineResult = self.conversion_manager.run(
                series_list=to_convert,
                input_folder=Path(job.input_path),
                output_dir=out,
                options=options,
                progress=_series_progress,
                result_callback=_on_result,
                stop_check=_stop,
                conversion_plan=conversion_plan,
            )

            if self._pause_requested or (stop_check and stop_check()):
                job.status = BatchJobStatus.PAUSED
                state.status = BatchJobStatus.PAUSED
                resume_mod.write_state(state_root, state)
                if job_updated:
                    job_updated(job)
                raise BatchPausedError(f"Batch job paused: {job.job_id}")

            # Never treat empty / all-failed conversion as success.
            newly_converted = max(0, job.converted_count - skipped)
            if newly_converted == 0 and job.failed_count > 0:
                job.status = BatchJobStatus.FAILED
                job.error = "All series failed conversion"
                state.status = BatchJobStatus.FAILED
            elif newly_converted == 0 and pipeline.converted == 0 and skipped == 0:
                job.status = BatchJobStatus.FAILED
                job.error = "Conversion produced no outputs"
                state.status = BatchJobStatus.FAILED
            elif pipeline.failed and not pipeline.converted and skipped == 0:
                job.status = BatchJobStatus.FAILED
                job.error = "All series failed conversion"
                state.status = BatchJobStatus.FAILED
            else:
                job.status = BatchJobStatus.COMPLETED
                state.status = BatchJobStatus.COMPLETED
                if job.failed_count:
                    job.error = (
                        f"Completed with {job.failed_count} failed series "
                        f"({newly_converted} converted)."
                    )
            job.finished = _utc_now()
            state.completed_series = job.converted_count + job.failed_count
            resume_mod.write_state(state_root, state)
            if job_updated:
                job_updated(job)
            return job

        except BatchPausedError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Batch job failed: %s", job.job_id)
            job.status = BatchJobStatus.FAILED
            job.error = str(exc)
            job.finished = _utc_now()
            try:
                resume_mod.write_state(
                    Path(job.output_path) / ".batch" / job.job_id,
                    BatchState(
                        job_id=job.job_id,
                        status=BatchJobStatus.FAILED,
                        completed_series=job.converted_count + job.failed_count,
                        total_series=job.series_count,
                        input_path=job.input_path,
                        output_path=job.output_path,
                    ),
                )
            except Exception:  # noqa: BLE001
                pass
            if job_updated:
                job_updated(job)
            return job

    @staticmethod
    def _filter_series_for_job(
        job: BatchJob, series_list: Sequence[DicomSeries]
    ) -> list[DicomSeries]:
        """Select series belonging to ``job`` without trusting raw PatientID alone.

        Priority:
          1. ``series_uids`` (authoritative when present)
          2. Discovery routing label / original DICOM PatientID / source folder
          3. If no identity filter is set, keep all series under the job input folder
        """
        items = list(series_list)
        if not items:
            return []

        uid_set = {u for u in (job.series_uids or []) if u}
        if uid_set:
            by_uid = [s for s in items if (s.series_instance_uid or "") in uid_set]
            if by_uid:
                return by_uid
            LOGGER.warning(
                "Job %s: series_uids filter matched 0/%s series",
                job.job_id,
                len(items),
            )

        # subject_id is a BIDS output label — not a DICOM PatientID filter.
        labels = {
            (job.patient_id_filter or "").strip(),
            sanitize_patient_id(job.patient_id_filter or ""),
            (job.original_patient_id or "").strip(),
            sanitize_patient_id(job.original_patient_id or ""),
        }
        labels.discard("")
        labels.discard("unknown")

        folder_hints = {
            (job.label or "").strip(),
            Path(job.source_folder_path).name if job.source_folder_path else "",
        }
        folder_hints.discard("")

        if labels or folder_hints:
            matched: list[DicomSeries] = []
            for series in items:
                pid = (series.patient_id or "").strip()
                dicom_pid = (series.dicom_patient_id or "").strip()
                src = (series.source_subject_folder or "").strip()
                if labels and (
                    pid in labels
                    or dicom_pid in labels
                    or sanitize_patient_id(pid) in labels
                    or sanitize_patient_id(dicom_pid) in labels
                ):
                    matched.append(series)
                    continue
                if folder_hints and src and src in folder_hints:
                    matched.append(series)
            if matched:
                return matched

        # Explicit identity filters were provided but matched nothing.
        if uid_set or labels:
            return []

        # Job is already scoped to a subject folder (or unfiltered single-folder batch).
        return items

    def export_report(self, path: Path | str) -> Path:
        """Write a simple Markdown batch summary report."""
        out = Path(path)
        lines = [
            "# Batch conversion report",
            "",
            f"Generated: {_utc_now()}",
            "",
            "| Subject | Status | Series | Converted | Failed | Error |",
            "|---------|--------|--------|-----------|--------|-------|",
        ]
        for job in self.queue.all_jobs():
            err = (job.error or "").replace("|", "/")
            lines.append(
                f"| {job.label} | {job.status.value} | {job.series_count} | "
                f"{job.converted_count} | {job.failed_count} | {err} |"
            )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out
