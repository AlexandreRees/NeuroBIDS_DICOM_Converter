"""dcm2niix-backed DICOM → NIfTI converter."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

from neuro_pipeline.logging.setup import get_conversion_logger
from neuro_pipeline.models import ConversionJob, ConversionOptions, ConversionResult, DicomSeries
from neuro_pipeline.utils.exceptions import (
    ConversionFailedError,
    Dcm2niixNotFoundError,
    OutputFolderError,
    PermissionDeniedError,
)
from neuro_pipeline.utils.filesystem import ensure_writable_dir, sanitize_filename
from neuro_pipeline.utils.naming import SmartFilenameEngine

LOGGER = logging.getLogger(__name__)
CONV_LOG = get_conversion_logger()

ProgressHook = Callable[[str], None]


class Converter:
    """Thin, testable wrapper around the ``dcm2niix`` CLI.

    The GUI must never call ``subprocess`` directly; it goes through this class
    (typically via a worker thread).
    """

    def __init__(
        self,
        dcm2niix_path: str | Path | None = None,
        naming_engine: SmartFilenameEngine | None = None,
    ) -> None:
        self._requested_path = str(dcm2niix_path or "").strip()
        self._executable: Path | None = None
        self.naming_engine = naming_engine or SmartFilenameEngine()

    def verify(self) -> Path:
        """Locate dcm2niix and raise a clear error if missing.

        When ``dcm2niix_path`` is an explicit non-empty / non-``auto`` value,
        only that path is accepted (no silent fallback). Missing / unusable
        explicit paths raise :class:`Dcm2niixNotFoundError`.

        Search order when ``dcm2niix_path`` is empty/``auto``:
        1. ``<exe_dir>/_internal/dcm2niix.exe`` (PyInstaller 6 onedir)
        2. ``resource_root()/dcm2niix.exe``
        3. ``<exe_dir>/dcm2niix.exe``
        4. ``<exe_dir>/bin/dcm2niix.exe``
        5. ``<exe_dir>/tools/dcm2niix.exe``
        6. ``project_root()`` locations (root / bin / tools)
        7–8. System ``PATH`` (``dcm2niix``, then ``dcm2niix.exe``)
        """
        if self._executable and self._executable.exists():
            return self._executable

        requested = self._requested_path
        auto = requested.lower() in {"", "auto"}

        # Explicit path: honor it strictly — never fall back to bundled / PATH.
        if requested and not auto:
            explicit = Path(requested)
            if explicit.exists():
                if os.access(explicit, os.X_OK | os.R_OK) or os.name == "nt":
                    self._executable = explicit.resolve()
                    LOGGER.info("Using dcm2niix (explicit path)")
                    return self._executable
            raise Dcm2niixNotFoundError(
                "dcm2niix was not found.\n\n"
                f"The configured path does not exist or is not usable:\n  {explicit}\n\n"
                "Recovery options:\n"
                "  • place dcm2niix.exe next to NeuroPipeline.exe (or in tools\\), or\n"
                "  • add dcm2niix to your PATH, or\n"
                "  • set dcm2niix_path in Settings / configs/default.yaml."
            )

        from neuro_pipeline.config.paths import is_frozen, project_root, resource_root

        candidates: list[Path] = []
        seen: set[Path] = set()

        def _add(path: Path) -> None:
            try:
                key = path.resolve() if path.exists() else path
            except OSError:
                key = path
            if key in seen:
                return
            seen.add(key)
            candidates.append(path)

        exe_dir = Path(sys.executable).resolve().parent
        root = project_root()
        res_root = resource_root()

        for path in (
            # 1. PyInstaller 6 onedir bundled location
            exe_dir / "_internal" / "dcm2niix.exe",
            # 2. resource_root (sys._MEIPASS when frozen)
            res_root / "dcm2niix.exe",
            # 3–5. Next to / under the application executable
            exe_dir / "dcm2niix.exe",
            exe_dir / "bin" / "dcm2niix.exe",
            exe_dir / "tools" / "dcm2niix.exe",
            # 6. Development / project locations
            root / "dcm2niix.exe",
            root / "bin" / "dcm2niix.exe",
            root / "tools" / "dcm2niix.exe",
        ):
            _add(path)

        # Preserve existing non-.exe / nested resource fallbacks (source & Linux).
        if not is_frozen():
            for path in (
                root / "dcm2niix",
                root / "bin" / "dcm2niix",
                root / "tools" / "dcm2niix",
            ):
                _add(path)
        _add(res_root / "bin" / "dcm2niix.exe")

        # 7–8: system PATH
        for name in ("dcm2niix", "dcm2niix.exe"):
            which = shutil.which(name)
            if which:
                _add(Path(which))

        for candidate in candidates:
            if candidate and candidate.exists() and os.access(candidate, os.X_OK | os.R_OK):
                self._executable = candidate.resolve()
                LOGGER.info("Using dcm2niix (resolved)")
                return self._executable

        # On Windows, .exe may not have Unix +x semantics; existence is enough.
        for candidate in candidates:
            if candidate and candidate.exists():
                self._executable = candidate.resolve()
                LOGGER.info("Using dcm2niix (resolved)")
                return self._executable

        raise Dcm2niixNotFoundError(
            "dcm2niix was not found.\n\n"
            "NeuroPipeline ships dcm2niix with the Windows build. If you see this "
            "message, the bundled binary is missing from the install folder.\n\n"
            "Recovery options:\n"
            "  • place dcm2niix.exe next to NeuroPipeline.exe (or in tools\\), or\n"
            "  • add dcm2niix to your PATH, or\n"
            "  • set dcm2niix_path in Settings / configs/default.yaml."
        )

    def build_command(
        self,
        *,
        input_dir: Path,
        output_dir: Path,
        options: ConversionOptions,
        filename_pattern: str = "%p_%s",
    ) -> list[str]:
        """Construct the dcm2niix argv list for a single series folder."""
        exe = str(self.verify())
        cmd = [exe, "-b", "y" if options.preserve_json else "n"]

        if options.compress:
            cmd.extend(["-z", "y"])
        else:
            cmd.extend(["-z", "n"])

        # Ignore derived images sparingly; keep defaults researcher-friendly
        cmd.extend(["-f", filename_pattern])
        cmd.extend(["-o", str(output_dir)])
        cmd.append(str(input_dir))
        return cmd

    def convert_series(
        self,
        job: ConversionJob,
        *,
        progress: ProgressHook | None = None,
    ) -> ConversionResult:
        """Convert one DICOM series and optionally apply smart renaming."""
        series = job.series
        start = time.perf_counter()
        command: list[str] = []

        try:
            # Soft-skip non-image DICOM (SR / SEG / PDF / waveform / spectroscopy…)
            if series.convertible_to_nifti is False or (
                series.dicom_object_class
                and series.convertibility
                in {"NOT_APPLICABLE", "UNSUPPORTED"}
            ):
                duration = time.perf_counter() - start
                reason = (
                    f"Skipped non-convertible DICOM object "
                    f"({series.dicom_object_class or 'unknown'}; "
                    f"{series.convertibility or 'n/a'}; "
                    f"SOP={series.sop_class_uid or '?'})."
                )
                CONV_LOG.info(
                    "SKIP series=%s reason=non_convertible class=%s",
                    series.display_name,
                    series.dicom_object_class or "?",
                )
                return ConversionResult(
                    series=series,
                    success=False,
                    command=[],
                    duration_seconds=duration,
                    error=reason,
                )

            out_dir = self._prepare_output_dir(job)
            filename_pattern = self._filename_pattern(series, job.options)
            command = self.build_command(
                input_dir=series.source_dir,
                output_dir=out_dir,
                options=job.options,
                filename_pattern=filename_pattern,
            )
            if progress:
                progress(f"Converting {series.display_name}")

            CONV_LOG.info(
                "START series=%s modality=%s tool=dcm2niix",
                series.display_name,
                series.modality or "MR",
            )

            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(out_dir),
            )
            duration = time.perf_counter() - start
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""

            if completed.returncode != 0:
                error = (
                    f"dcm2niix failed (exit {completed.returncode}) for "
                    f"{series.display_name}."
                )
                CONV_LOG.error(
                    "FAIL series=%s duration=%.2fs error=%s",
                    series.display_name,
                    duration,
                    error,
                )
                return ConversionResult(
                    series=series,
                    success=False,
                    command=command,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=duration,
                    error=error,
                )

            outputs = self._list_outputs(out_dir)
            if job.options.smart_naming and self.naming_engine:
                outputs = self._apply_smart_names(series, outputs)

            CONV_LOG.info(
                "OK series=%s duration=%.2fs outputs=%d",
                series.display_name,
                duration,
                len(outputs),
            )
            return ConversionResult(
                series=series,
                success=True,
                command=command,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                output_files=outputs,
            )
        except (Dcm2niixNotFoundError, PermissionDeniedError, OutputFolderError) as exc:
            duration = time.perf_counter() - start
            CONV_LOG.error(
                "FAIL series=%s duration=%.2fs error=%s",
                series.display_name,
                duration,
                type(exc).__name__,
            )
            return ConversionResult(
                series=series,
                success=False,
                command=command,
                duration_seconds=duration,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - never crash the worker
            duration = time.perf_counter() - start
            LOGGER.exception("Unexpected conversion failure")
            CONV_LOG.error(
                "FAIL series=%s duration=%.2fs error=%s",
                series.display_name,
                duration,
                type(exc).__name__,
            )
            return ConversionResult(
                series=series,
                success=False,
                command=command,
                duration_seconds=duration,
                error=f"Unexpected error: {exc}",
            )

    def convert_many(
        self,
        jobs: Sequence[ConversionJob],
        *,
        progress: ProgressHook | None = None,
        result_callback: Callable[[ConversionResult], None] | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> list[ConversionResult]:
        """Convert a sequence of jobs sequentially (GUI threads orchestrate)."""
        results: list[ConversionResult] = []
        for job in jobs:
            if stop_check and stop_check():
                break
            result = self.convert_series(job, progress=progress)
            results.append(result)
            if result_callback:
                result_callback(result)
            # Abort remaining series only when the binary itself is missing.
            if not result.success and "dcm2niix was not found" in (result.error or ""):
                raise ConversionFailedError(result.error)
        return results

    def _prepare_output_dir(self, job: ConversionJob) -> Path:
        base = ensure_writable_dir(job.output_dir, create=True)
        if job.options.one_folder_per_patient:
            patient = sanitize_filename(job.series.patient_id or "UnknownPatient")
            target = ensure_writable_dir(base / patient, create=True)
        else:
            target = base

        series_folder = sanitize_filename(job.series.display_name)
        final = target / series_folder
        if final.exists() and any(final.iterdir()):
            # Do not silently overwrite – create a unique sibling folder
            index = 1
            while True:
                candidate = target / f"{series_folder}_{index}"
                if not candidate.exists():
                    final = candidate
                    break
                index += 1
        return ensure_writable_dir(final, create=True)

    def _filename_pattern(self, series: DicomSeries, options: ConversionOptions) -> str:
        if options.smart_naming:
            smart = self.naming_engine.resolve(
                series.series_description,
                series.protocol_name,
            )
            series.smart_name = smart
            return smart
        # Keep patient/series clues from dcm2niix defaults
        return "%p_%s"

    def _list_outputs(self, folder: Path) -> list[Path]:
        allowed_suffixes = {".nii", ".json", ".bval", ".bvec"}
        outputs: list[Path] = []
        for path in folder.iterdir():
            if not path.is_file():
                continue
            if path.name.endswith(".nii.gz") or path.suffix.lower() in allowed_suffixes:
                outputs.append(path)
        return sorted(outputs)

    def _apply_smart_names(self, series: DicomSeries, outputs: list[Path]) -> list[Path]:
        """Ensure primary NIfTI/JSON stems use the smart name when possible."""
        smart = series.smart_name or self.naming_engine.resolve(
            series.series_description,
            series.protocol_name,
        )
        renamed: list[Path] = []
        for path in outputs:
            # Only rename simple stems produced with %f-like uniqueness
            if path.name.startswith(smart):
                renamed.append(path)
                continue
            # Leave multi-echo / multi-volume derivatives (_e1, _ph, etc.)
            stem = path.name
            if path.name.endswith(".nii.gz"):
                base, ext = path.name[: -len(".nii.gz")], ".nii.gz"
            else:
                base, ext = path.stem, path.suffix

            # Map first matching nii/json onto smart name if unique
            if ext in {".nii", ".gz", ".json"} or path.name.endswith(".nii.gz"):
                # Avoid clobbering distinct echo/phase outputs
                suffix_bits = ""
                for marker in ("_e", "_ph", "_real", "_imag", "_ADC", "_TRACEW"):
                    if marker.lower() in base.lower():
                        idx = base.lower().rfind(marker.lower())
                        suffix_bits = base[idx:]
                        break
                new_name = f"{smart}{suffix_bits}{ext if not path.name.endswith('.nii.gz') else '.nii.gz'}"
                if path.name.endswith(".nii.gz"):
                    new_name = f"{smart}{suffix_bits}.nii.gz"
                dest = path.with_name(new_name)
                if dest != path and not dest.exists():
                    path.rename(dest)
                    renamed.append(dest)
                else:
                    renamed.append(path)
            else:
                renamed.append(path)
        return renamed
