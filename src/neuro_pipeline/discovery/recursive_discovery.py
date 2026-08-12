"""Unlimited-depth recursive DICOM file discovery (metadata only)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from pydicom.errors import InvalidDicomError

from neuro_pipeline.discovery.file_walk import iter_candidate_files
from neuro_pipeline.discovery.models import DicomFileRecord
from neuro_pipeline.utils.winpaths import safe_open_path

LOGGER = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]
StopCheck = Callable[[], bool]


class RecursiveDicomScanner:
    """Walk an input tree of any depth and collect DICOM header records.

    Does not load pixel data. Does not modify files. Discovery does not depend
    on file extensions (extensionless DICOM is supported).
    """

    def scan(
        self,
        root_path: Path | str,
        *,
        progress: ProgressCallback | None = None,
        stop_check: StopCheck | None = None,
    ) -> list[DicomFileRecord]:
        root = Path(root_path)
        if not root.is_dir():
            raise FileNotFoundError(f"Input folder does not exist: {root}")

        records: list[DicomFileRecord] = []
        scanned = 0
        hits = 0

        for path in iter_candidate_files(root):
            if stop_check and stop_check():
                break

            scanned += 1
            if progress and scanned % 250 == 0:
                progress(f"Recursive discovery… {scanned} files ({hits} DICOM)")

            record = self._try_read(path)
            if record is None:
                continue
            records.append(record)
            hits += 1

        if progress:
            progress(f"Recursive discovery complete: {hits} DICOM files")
        LOGGER.info("RecursiveDicomScanner: %s DICOM files under %s", hits, root)
        return records

    def _try_read(self, path: Path) -> DicomFileRecord | None:
        open_path = safe_open_path(path)
        try:
            from pydicom import dcmread

            ds = dcmread(open_path, stop_before_pixels=True, force=False)
        except InvalidDicomError:
            try:
                from pydicom import dcmread

                ds = dcmread(open_path, stop_before_pixels=True, force=True)
                if not hasattr(ds, "SOPClassUID") and not hasattr(ds, "SeriesInstanceUID"):
                    return None
            except Exception:  # noqa: BLE001
                return None
        except PermissionError:
            LOGGER.debug("Permission denied: %s", path)
            return None
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Skip %s: %s", path, exc)
            return None

        series_uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
        if not series_uid:
            return None

        return DicomFileRecord(
            filepath=path,
            parent_folder=path.parent,
            series_instance_uid=series_uid,
            study_instance_uid=str(getattr(ds, "StudyInstanceUID", "") or ""),
            patient_id=str(getattr(ds, "PatientID", "") or ""),
            patient_name=str(getattr(ds, "PatientName", "") or ""),
            study_date=str(getattr(ds, "StudyDate", "") or ""),
            series_description=str(getattr(ds, "SeriesDescription", "") or ""),
            protocol_name=str(getattr(ds, "ProtocolName", "") or ""),
            series_number=_optional_int(getattr(ds, "SeriesNumber", None)),
            acquisition_number=_optional_int(getattr(ds, "AcquisitionNumber", None)),
            modality=str(getattr(ds, "Modality", "") or ""),
            study_description=str(getattr(ds, "StudyDescription", "") or ""),
        )


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
