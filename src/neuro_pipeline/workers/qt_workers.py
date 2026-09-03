"""Background workers that keep the Qt UI responsive."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from neuro_pipeline.converter import ConversionManager
from neuro_pipeline.models import (
    ConversionOptions,
    ConversionResult,
    DicomSeries,
    ProgressInfo,
    SeriesStatus,
)
from neuro_pipeline.utils.naming import SmartFilenameEngine

LOGGER = logging.getLogger(__name__)


class ScanWorker(QObject):
    """Scan a DICOM folder on a background thread via DatasetDiscovery."""

    progress = Signal(str)
    finished = Signal(list)
    discovery_finished = Signal(object)  # DiscoveryResult
    failed = Signal(str)
    scanner_detected = Signal(object)

    def __init__(
        self,
        folder: Path,
        *,
        discovery_mode: str = "automatic",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.folder = folder
        self.discovery_mode = discovery_mode or "automatic"
        self._stop = False
        self.discovery_result = None

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            from neuro_pipeline.discovery import DatasetDiscovery

            discovery = DatasetDiscovery()
            series, result = discovery.scan_series(
                self.folder,
                mode=self.discovery_mode,
                progress=lambda msg: self.progress.emit(msg),
                stop_check=lambda: self._stop,
            )
            self.discovery_result = result
            if discovery.parser.last_scanner_info is not None:
                self.scanner_detected.emit(discovery.parser.last_scanner_info)
            if not self._stop:
                self.discovery_finished.emit(result)
                self.finished.emit(series)
        except Exception as exc:  # noqa: BLE001 - surface to GUI
            self.failed.emit(str(exc))


class BatchWorker(QObject):
    """Run BatchManager jobs on a background thread."""

    progress = Signal(str)
    job_updated = Signal(object)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        manager,
        *,
        options: ConversionOptions | None = None,
        resume: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.options = options or ConversionOptions()
        self.resume = resume
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        try:
            self.manager.request_pause()
        except Exception:  # noqa: BLE001
            pass

    def run(self) -> None:
        try:
            jobs = self.manager.run_all(
                options=self.options,
                resume=self.resume,
                progress=lambda job, msg: self.progress.emit(f"{job.label}: {msg}"),
                job_updated=lambda job: self.job_updated.emit(job),
                stop_check=lambda: self._stop,
            )
            self.finished.emit(jobs)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class FolderConvertWorker(QObject):
    """One-click folder conversion: auto-detect subjects and convert all."""

    progress = Signal(str)
    job_updated = Signal(object)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        folder: Path,
        output_dir: Path,
        *,
        options: ConversionOptions | None = None,
        subject_id: str = "",
        session_id: str = "",
        analysis=None,
        conversion_plan=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.folder = Path(folder)
        self.output_dir = Path(output_dir)
        self.options = options or ConversionOptions()
        self.subject_id = (subject_id or "").strip()
        self.session_id = (session_id or "").strip()
        self.analysis = analysis
        self.conversion_plan = conversion_plan
        self._manager = None
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        if self._manager is not None:
            try:
                self._manager.request_pause()
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> None:
        try:
            from neuro_pipeline.batch import BatchManager

            self._manager = BatchManager(
                conversion_manager=ConversionManager(
                    dcm2niix_path=self.options.dcm2niix_path,
                )
            )
            jobs = self._manager.convert_folder(
                self.folder,
                self.output_dir,
                options=self.options,
                subject_id=self.subject_id,
                session_id=self.session_id,
                analysis=self.analysis,
                conversion_plan=self.conversion_plan,
                progress=lambda job, msg: self.progress.emit(f"{job.label}: {msg}"),
                job_updated=lambda job: self.job_updated.emit(job),
                stop_check=lambda: self._stop,
            )
            self.finished.emit(jobs)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class InventoryWorker(QObject):
    """Build DICOM inventory workbook/CSV on a background thread (no conversion)."""

    progress = Signal(str)
    finished = Signal(object)  # InventoryResult
    failed = Signal(str)

    def __init__(
        self,
        folder: Path,
        output_dir: Path,
        *,
        series_list: list[DicomSeries] | None = None,
        subject_id: str = "",
        session_id: str = "",
        naming_engine: SmartFilenameEngine | None = None,
        write_csv: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.folder = Path(folder)
        self.output_dir = Path(output_dir)
        self.series_list = list(series_list) if series_list is not None else None
        self.subject_id = (subject_id or "").strip()
        self.session_id = (session_id or "").strip()
        self.naming_engine = naming_engine or SmartFilenameEngine()
        self.write_csv = write_csv
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            from neuro_pipeline.inventory import InventoryManager

            manager = InventoryManager(naming_engine=self.naming_engine)
            result = manager.run(
                self.folder,
                self.output_dir,
                series_list=self.series_list,
                subject_override=self.subject_id,
                session_override=self.session_id,
                write_csv=self.write_csv,
                progress=lambda msg: self.progress.emit(msg),
                stop_check=lambda: self._stop,
            )
            if not self._stop:
                self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface to GUI
            self.failed.emit(str(exc))


class ConversionWorker(QObject):
    """Convert all detected series, then validate and write the HTML report."""

    progress = Signal(object)  # ProgressInfo
    series_updated = Signal(object)  # DicomSeries
    result = Signal(object)  # ConversionResult
    finished = Signal(object)  # PipelineResult
    failed = Signal(str)

    def __init__(
        self,
        series_list: list[DicomSeries],
        input_folder: Path,
        output_dir: Path,
        options: ConversionOptions,
        naming_engine: SmartFilenameEngine,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        # Copy immediately so a later GUI clear cannot empty this list.
        self.series_list = list(series_list)
        self.input_folder = input_folder
        self.output_dir = output_dir
        self.options = options
        self.naming_engine = naming_engine
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        series_list = list(self.series_list)
        LOGGER.debug("ConversionWorker received series_count=%s", len(series_list))
        for item in series_list:
            LOGGER.debug(
                "worker series name=%s path=%s modality=%s",
                item.display_name,
                item.source_dir.name,
                item.modality or "?",
            )

        manager = ConversionManager(
            dcm2niix_path=self.options.dcm2niix_path,
            naming_engine=self.naming_engine,
        )
        total = len(series_list)
        durations: list[float] = []
        completed_index = {"value": 0}

        def on_progress(message: str) -> None:
            index = completed_index["value"]
            remaining = max(total - index, 0)
            avg = sum(durations) / len(durations) if durations else None
            eta = avg * remaining if avg is not None else None
            current = series_list[index].display_name if index < total else ""
            self.progress.emit(
                ProgressInfo(
                    current_series=current,
                    converted=index,
                    remaining=remaining,
                    total=total,
                    percent=(index / total) * 100 if total else 0.0,
                    estimated_seconds_remaining=eta,
                    message=message,
                )
            )

        def on_result(outcome: ConversionResult) -> None:
            durations.append(outcome.duration_seconds)
            completed_index["value"] += 1
            series = outcome.series
            series.status = SeriesStatus.DONE if outcome.success else SeriesStatus.FAILED
            series.message = outcome.error
            self.series_updated.emit(series)
            self.result.emit(outcome)
            index = completed_index["value"]
            remaining = max(total - index, 0)
            avg = sum(durations) / len(durations) if durations else None
            self.progress.emit(
                ProgressInfo(
                    current_series=series.display_name,
                    converted=index,
                    remaining=remaining,
                    total=total,
                    percent=(index / total) * 100 if total else 0.0,
                    estimated_seconds_remaining=(avg * remaining) if avg is not None else None,
                    message=f"Series completed {index}/{total}: {series.display_name}",
                )
            )

        try:
            pipeline = manager.run(
                series_list=series_list,
                input_folder=self.input_folder,
                output_dir=self.output_dir,
                options=self.options,
                progress=on_progress,
                result_callback=on_result,
                stop_check=lambda: self._stop,
            )
            overall = pipeline.validation.overall_status.value
            self.progress.emit(
                ProgressInfo(
                    current_series="",
                    converted=pipeline.converted,
                    remaining=0,
                    total=total,
                    percent=100.0 if total else 0.0,
                    estimated_seconds_remaining=0.0,
                    message=f"Conversion completed — validation {overall}",
                )
            )
            self.finished.emit(pipeline)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class CopilotWorker(QObject):
    """Run :class:`CopilotAgent.handle` off the Qt GUI thread."""

    started = Signal()
    response_ready = Signal(object)  # CopilotTurnResult
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        agent: object,
        request: str,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._agent = agent
        self._request = request
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        self.started.emit()
        try:
            if self._stop:
                return
            result = self._agent.handle(self._request)
            if not self._stop:
                self.response_ready.emit(result)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("CopilotWorker failed")
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class LLMConnectionTestWorker(QObject):
    """Probe LLM provider connectivity off the GUI thread."""

    finished_result = Signal(object)  # ConnectionProbeResult
    failed = Signal(str)
    finished = Signal()

    def __init__(self, config: object, *, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config

    def run(self) -> None:
        try:
            from neuro_pipeline.neurobids.copilot.llm.connection import probe_llm_connection

            result = probe_llm_connection(self._config)  # type: ignore[arg-type]
            self.finished_result.emit(result)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("LLM connection test failed")
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


def start_worker(worker: QObject, *, slot_name: str = "run") -> QThread:
    """Move ``worker`` onto a new ``QThread`` and start it."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(getattr(worker, slot_name))
    return thread
