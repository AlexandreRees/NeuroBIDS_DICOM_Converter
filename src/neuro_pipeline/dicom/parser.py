"""DICOM folder scanner and series metadata extraction."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from pydicom import dcmread
from pydicom.errors import InvalidDicomError

from neuro_pipeline.dicom.format_support import (
    classify_sop_class,
    is_convertible_to_nifti,
)
from neuro_pipeline.dicom.sequence_classifier import SequenceClassifier
from neuro_pipeline.dicom.metadata import DicomMetadataExtractor
from neuro_pipeline.discovery.file_walk import iter_candidate_files
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.utils.exceptions import (
    InvalidDicomFolderError,
    PermissionDeniedError,
)
from neuro_pipeline.utils.filesystem import assert_non_empty_folder, ensure_readable_dir
from neuro_pipeline.utils.winpaths import safe_open_path

LOGGER = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class _SeriesKey:
    patient_id: str
    study_uid: str
    series_uid: str


class DicomParser:
    """Scan a folder tree and group files into DICOM series."""

    # Preferred suffixes for fast candidacy; proprietary extensions accepted via DICM magic.
    DICOM_SUFFIXES = {".dcm", ".ima", ".dicom", ""}

    def __init__(self, *, max_workers_hint: int = 1, use_scanner_profile: bool = True) -> None:
        self.max_workers_hint = max_workers_hint
        self.classifier = SequenceClassifier()
        self.metadata_extractor = DicomMetadataExtractor()
        self.use_scanner_profile = use_scanner_profile
        self.last_scanner_info = None

    def scan(
        self,
        folder: Path,
        *,
        progress: ProgressCallback | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> list[DicomSeries]:
        """Discover all DICOM series under ``folder``.

        Parameters
        ----------
        folder:
            Root directory selected by the user.
        progress:
            Optional callback receiving status strings.
        stop_check:
            Optional callable returning True when the scan should abort.
        """
        root = ensure_readable_dir(folder)
        assert_non_empty_folder(root)

        scanner_profile = None
        self.last_scanner_info = None
        if self.use_scanner_profile:
            try:
                from neuro_pipeline.scanner import AutoDetector

                info, scanner_profile = AutoDetector().detect(root)
                self.last_scanner_info = info
            except Exception as exc:  # noqa: BLE001 - never block scanning
                LOGGER.debug("Scanner auto-detect skipped: %s", exc)

        buckets: dict[_SeriesKey, list[Path]] = defaultdict(list)
        meta: dict[_SeriesKey, dict[str, object]] = {}
        scanned = 0
        dicom_hits = 0
        corrupt_files: list[Path] = []

        for path in self._iter_candidate_files(root):
            if stop_check and stop_check():
                break
            scanned += 1
            if progress and scanned % 50 == 0:
                progress(f"Scanning… {scanned} files ({dicom_hits} DICOM)")

            open_path = safe_open_path(path)
            try:
                ds = dcmread(open_path, stop_before_pixels=True, force=False)
            except InvalidDicomError:
                # Retry with force=True for implicit/nonstandard headers
                try:
                    ds = dcmread(open_path, stop_before_pixels=True, force=True)
                    if not hasattr(ds, "SOPClassUID") and not hasattr(ds, "SeriesInstanceUID"):
                        continue
                except Exception:
                    continue
            except PermissionError as exc:
                raise PermissionDeniedError(f"Permission denied reading: {path}") from exc
            except Exception as exc:  # noqa: BLE001 - collect and continue
                LOGGER.debug("Skipping unreadable file %s: %s", path, exc)
                corrupt_files.append(path)
                continue

            series_uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
            if not series_uid:
                continue

            patient_id = str(getattr(ds, "PatientID", "") or "Unknown")
            study_uid = str(getattr(ds, "StudyInstanceUID", "") or "")
            key = _SeriesKey(patient_id=patient_id, study_uid=study_uid, series_uid=series_uid)
            buckets[key].append(path)
            dicom_hits += 1

            if key not in meta:
                image_type = getattr(ds, "ImageType", None)
                if image_type is not None:
                    try:
                        image_type_val = [str(x) for x in image_type]
                    except TypeError:
                        image_type_val = [str(image_type)]
                else:
                    image_type_val = []
                diffusion_present = any(
                    hasattr(ds, tag)
                    and getattr(ds, tag) not in (None, "", [])
                    for tag in (
                        "DiffusionBValue",
                        "DiffusionGradientDirectionSequence",
                    )
                )
                sop_uid = str(getattr(ds, "SOPClassUID", "") or "")
                modality = str(getattr(ds, "Modality", "") or "")
                n_frames = _as_optional_int(getattr(ds, "NumberOfFrames", None))
                rows = _as_optional_int(getattr(ds, "Rows", None))
                cols = _as_optional_int(getattr(ds, "Columns", None))
                try:
                    ts_uid = str(
                        getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", "") or ""
                    )
                except Exception:  # noqa: BLE001
                    ts_uid = ""
                obj_class, convertibility = classify_sop_class(
                    sop_uid,
                    modality=modality,
                    number_of_frames=n_frames,
                    transfer_syntax_uid=ts_uid,
                    rows=rows,
                    columns=cols,
                )
                meta[key] = {
                    "patient_id": patient_id,
                    "study_description": str(getattr(ds, "StudyDescription", "") or ""),
                    "series_description": str(getattr(ds, "SeriesDescription", "") or ""),
                    "protocol_name": str(getattr(ds, "ProtocolName", "") or ""),
                    "series_number": _as_optional_int(getattr(ds, "SeriesNumber", None)),
                    "acquisition_number": _as_optional_int(getattr(ds, "AcquisitionNumber", None)),
                    "modality": modality,
                    "series_instance_uid": series_uid,
                    "image_type": image_type_val,
                    "diffusion_present": diffusion_present,
                    "source_dir": path.parent,
                    "sample_file": path,
                    "sop_class_uid": sop_uid,
                    "transfer_syntax_uid": ts_uid,
                    "number_of_frames": n_frames,
                    "dicom_object_class": obj_class.value,
                    "convertibility": convertibility.value,
                    "convertible_to_nifti": is_convertible_to_nifti(obj_class, convertibility),
                }

        if dicom_hits == 0:
            detail = ""
            if corrupt_files:
                detail = f"\n({len(corrupt_files)} unreadable file(s) encountered)"
            raise InvalidDicomFolderError(
                "No DICOM series were found in the selected folder." + detail
            )

        series_list: list[DicomSeries] = []
        for key, files in buckets.items():
            info = meta[key]
            sample = Path(str(info["sample_file"]))
            try:
                series_meta = self.metadata_extractor.extract_from_file(
                    sample, num_images=len(files), source_dir=info["source_dir"]
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("Metadata extract skipped: %s", exc)
                series_meta = None

            detailed = self.classifier.classify_detailed(
                series_meta,
                series_description=str(info["series_description"]),
                protocol_name=str(info["protocol_name"]),
                image_type=info.get("image_type"),  # type: ignore[arg-type]
                diffusion_present=bool(info.get("diffusion_present")),
                modality=str(info["modality"]),
                scanner_profile=scanner_profile,
            )
            seq_type = self.classifier.classify(
                series_description=str(info["series_description"]),
                protocol_name=str(info["protocol_name"]),
                image_type=info.get("image_type"),  # type: ignore[arg-type]
                diffusion_present=bool(info.get("diffusion_present")),
                modality=str(info["modality"]),
                scanner_profile=scanner_profile,
            )
            detection = getattr(self.classifier, "last_detection", None)
            item = DicomSeries(
                patient_id=str(info["patient_id"]),
                study_description=str(info["study_description"]),
                series_description=str(info["series_description"]),
                protocol_name=str(info["protocol_name"]),
                series_number=info["series_number"],  # type: ignore[arg-type]
                acquisition_number=info["acquisition_number"],  # type: ignore[arg-type]
                modality=str(info["modality"]),
                num_images=len(files),
                source_dir=Path(str(info["source_dir"])),
                sample_file=sample,
                status=SeriesStatus.PENDING,
                sequence_type=seq_type.value,
                series_instance_uid=str(info.get("series_instance_uid") or key.series_uid),
                study_instance_uid=str(key.study_uid or ""),
                fine_sequence_type=detailed.type.value,
                sequence_confidence=float(detailed.confidence),
                bids_suffix=str(getattr(detection, "suffix", "") or ""),
                detection_confidence=float(getattr(detection, "confidence", 0.0) or 0.0),
                detection_label=str(getattr(detection, "display_label", "") or ""),
                detection_plugin=str(getattr(detection, "plugin", "") or ""),
                requires_manual_mapping=bool(getattr(detection, "requires_manual_mapping", False)),
                sop_class_uid=str(info.get("sop_class_uid") or ""),
                transfer_syntax_uid=str(info.get("transfer_syntax_uid") or ""),
                number_of_frames=info.get("number_of_frames"),  # type: ignore[arg-type]
                dicom_object_class=str(info.get("dicom_object_class") or ""),
                convertibility=str(info.get("convertibility") or ""),
                convertible_to_nifti=bool(info.get("convertible_to_nifti", True)),
            )
            _warn_incomplete_series(item)
            series_list.append(item)

        series_list.sort(
            key=lambda s: (
                s.patient_id,
                s.series_number if s.series_number is not None else 10**9,
                s.series_description,
            )
        )
        if progress:
            progress(f"Found {len(series_list)} series in {dicom_hits} DICOM files")
        LOGGER.info("Scan complete: %s series from folder", len(series_list))
        LOGGER.debug("number_of_series_detected=%s", len(series_list))
        for idx, item in enumerate(series_list, start=1):
            LOGGER.debug(
                "detected[%s] name=%s path=%s modality=%s files=%s uid=%s",
                idx,
                item.display_name,
                item.source_dir.name,
                item.modality or "?",
                item.num_images,
                (item.series_instance_uid[:12] + "…") if item.series_instance_uid else "<missing>",
            )
        return series_list

    def _iter_candidate_files(self, root: Path) -> Iterable[Path]:
        # Same unlimited-depth walk as recursive discovery (Windows long-path safe).
        # Content validation happens at dcmread — do not gate on extensions alone.
        yield from iter_candidate_files(root)


def _as_optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _warn_incomplete_series(series: DicomSeries) -> None:
    """Log warnings for missing fields without dropping the series."""
    if not series.source_dir:
        LOGGER.warning("Series missing DICOM path: %s", series.display_name)
    if not series.series_instance_uid:
        LOGGER.warning("Series missing SeriesInstanceUID: %s", series.display_name)
    if not (series.series_description or series.protocol_name):
        LOGGER.warning("Series missing SeriesDescription/ProtocolName")
    if not series.modality:
        LOGGER.warning("Series missing Modality: %s", series.display_name)
