"""InventoryManager — DICOM inventory via existing discovery / naming pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from neuro_pipeline.batch.input_analysis import sanitize_patient_id
from neuro_pipeline.bids.subject_manager import SubjectManager
from neuro_pipeline.dicom import DicomMetadataExtractor, DicomParser
from neuro_pipeline.inventory.csv_exporter import export_inventory_csv
from neuro_pipeline.inventory.excel_exporter import export_inventory_xlsx
from neuro_pipeline.inventory.extra_tags import read_optional_tags
from neuro_pipeline.inventory.models import (
    SERIES_INVENTORY_COLUMNS,
    InventoryResult,
    SeriesInventoryRow,
)
from neuro_pipeline.inventory.protocol_completeness import build_protocol_rows
from neuro_pipeline.models import DicomSeries
from neuro_pipeline.utils.naming import SmartFilenameEngine

LOGGER = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]
StopCheck = Callable[[], bool]

# Map inventory column → DicomSeriesMetadata attribute (parser-synced fields).
_META_COLUMN_ATTR: dict[str, str] = {
    "StudyInstanceUID": "study_instance_uid",
    "SeriesInstanceUID": "series_instance_uid",
    "SeriesNumber": "series_number",
    "SeriesDescription": "series_description",
    "ProtocolName": "protocol_name",
    "ImageType": "image_type",
    "Modality": "modality",
    "Manufacturer": "manufacturer",
    "ManufacturerModelName": "manufacturer_model_name",
    "MagneticFieldStrength": "magnetic_field_strength",
    "Rows": "rows",
    "Columns": "columns",
    "NumberOfImages": "num_images",
    "PixelSpacing": "pixel_spacing",
    "SliceThickness": "slice_thickness",
    "EchoTime": "echo_time",
    "RepetitionTime": "repetition_time",
    "FlipAngle": "flip_angle",
}

# Map inventory column → optional sample-file tags (not on DicomSeriesMetadata today).
_OPTIONAL_COLUMN_TAG: dict[str, str] = {
    "SequenceName": "SequenceName",
    "SequenceVariant": "SequenceVariant",
    "ScanningSequence": "ScanningSequence",
    "AcquisitionNumber": "AcquisitionNumber",
    "InversionTime": "InversionTime",
    "Bandwidth": "PixelBandwidth",
    "PhaseEncodingDirection": "PhaseEncodingDirection",
    "SpacingBetweenSlices": "SpacingBetweenSlices",
    "StationName": "StationName",
    "InstitutionName": "InstitutionName",
    "BodyPartExamined": "BodyPartExamined",
    "PatientPosition": "PatientPosition",
    "ReceiveCoilName": "ReceiveCoilName",
    "TransmitCoilName": "TransmitCoilName",
    "MultibandFactor": "MultibandFactor",
}


class InventoryManager:
    """Scan / enrich series and export inventory workbooks without converting."""

    def __init__(
        self,
        *,
        parser: DicomParser | None = None,
        metadata_extractor: DicomMetadataExtractor | None = None,
        naming_engine: SmartFilenameEngine | None = None,
    ) -> None:
        self.parser = parser or DicomParser()
        self.metadata_extractor = metadata_extractor or DicomMetadataExtractor()
        self.naming_engine = naming_engine or SmartFilenameEngine()
        self._subjects = SubjectManager()

    def scan(
        self,
        folder: Path | str,
        *,
        progress: ProgressCallback | None = None,
        stop_check: StopCheck | None = None,
        discovery_mode: str = "automatic",
    ) -> list[DicomSeries]:
        """Discover series via recursive discovery + existing parser routing."""
        from neuro_pipeline.discovery import DatasetDiscovery

        series, _discovery = DatasetDiscovery(parser=self.parser).scan_series(
            Path(folder),
            mode=discovery_mode,
            progress=progress,
            stop_check=stop_check,
        )
        for item in series:
            if not item.smart_name:
                item.smart_name = self.naming_engine.resolve(
                    item.series_description,
                    item.protocol_name,
                )
        return series

    def build(
        self,
        series_list: list[DicomSeries],
        *,
        dataset_root: Path | str = "",
        subject_override: str = "",
        session_override: str = "",
        progress: ProgressCallback | None = None,
        stop_check: StopCheck | None = None,
    ) -> InventoryResult:
        """Build inventory tables from already-discovered ``DicomSeries`` objects."""
        from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan

        dataset_root = str(dataset_root or "")
        subject_override = (subject_override or "").strip()
        session_label = self._session_label(session_override)
        unique_patients = {s.patient_id for s in series_list}
        apply_subject_override = bool(subject_override) and len(unique_patients) <= 1

        if progress:
            progress("Building BIDS conversion plan…")
        plan = BIDSConversionPlan.from_series(
            series_list,
            dataset_root=dataset_root,
            subject_override=subject_override,
            session_override=session_override,
        )
        planned_by_uid = {item.source_series_uid: item for item in plan.items}

        ordered = sorted(
            series_list,
            key=lambda s: (
                s.patient_id or "",
                s.series_number if s.series_number is not None else 10**9,
                s.series_description or "",
                s.series_instance_uid or "",
            ),
        )

        series_rows: list[SeriesInventoryRow] = []
        total = len(ordered)
        for idx, series in enumerate(ordered):
            if stop_check and stop_check():
                break
            if progress:
                progress(f"Collecting metadata… {idx + 1}/{total}: {series.display_name}")
            subject = (
                subject_override
                if apply_subject_override
                else sanitize_patient_id(series.patient_id)
            )
            try:
                subject = self._subjects.validate_subject_id(subject)
            except ValueError:
                subject = sanitize_patient_id(series.patient_id)

            uid = series.series_instance_uid or series.display_name
            planned_item = planned_by_uid.get(uid)
            if planned_item is not None:
                datatype = planned_item.datatype
                suffix = planned_item.suffix
                run = planned_item.run
                filename = planned_item.intended_filename
                naming_rule = planned_item.naming_rule_applied
                subject = planned_item.subject or subject
                session_out = planned_item.session or (session_label or "")
            else:
                datatype = suffix = run = filename = naming_rule = ""
                session_out = session_label or ""

            values = self._row_values(
                series,
                dataset_root=dataset_root,
                subject=subject,
                session=session_out,
                datatype=datatype,
                suffix=suffix,
                run=run,
                filename=filename,
                naming_rule=naming_rule,
            )
            series_rows.append(SeriesInventoryRow(values=values))

        protocol_rows = build_protocol_rows(
            ordered,
            subject_override=subject_override if apply_subject_override else "",
            session_override=session_label or "",
        )

        return InventoryResult(
            series_rows=series_rows,
            protocol_rows=protocol_rows,
            n_series=len(series_rows),
            n_subjects=len({r.subject for r in protocol_rows}),
        )

    def run(
        self,
        folder: Path | str,
        output_dir: Path | str,
        *,
        series_list: list[DicomSeries] | None = None,
        subject_override: str = "",
        session_override: str = "",
        write_csv: bool = True,
        progress: ProgressCallback | None = None,
        stop_check: StopCheck | None = None,
    ) -> InventoryResult:
        """Scan (unless ``series_list`` given), build tables, export xlsx (+ csv)."""
        root = Path(folder)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if series_list is None:
            if progress:
                progress("Scanning DICOM datasets…")
            series_list = self.scan(root, progress=progress, stop_check=stop_check)
        else:
            for item in series_list:
                if not item.smart_name:
                    item.smart_name = self.naming_engine.resolve(
                        item.series_description,
                        item.protocol_name,
                    )

        if stop_check and stop_check():
            return InventoryResult()

        result = self.build(
            series_list,
            dataset_root=root,
            subject_override=subject_override,
            session_override=session_override,
            progress=progress,
            stop_check=stop_check,
        )

        if stop_check and stop_check():
            return result

        if progress:
            progress("Writing Excel inventory…")
        xlsx = out_dir / "dicom_inventory.xlsx"
        export_inventory_xlsx(result, xlsx, dataset_root=str(root))
        result.xlsx_path = str(xlsx)

        if write_csv:
            if progress:
                progress("Writing CSV inventory…")
            csv_path = out_dir / "dicom_inventory.csv"
            export_inventory_csv(result, csv_path, include_protocol=True)
            result.csv_path = str(csv_path)

        if progress:
            progress(
                f"Inventory complete — {result.n_series} series, "
                f"{result.n_subjects} subject(s)."
            )
        LOGGER.info(
            "Inventory written xlsx=%s csv=%s series=%s",
            result.xlsx_path,
            result.csv_path,
            result.n_series,
        )
        return result

    def _session_label(self, session_override: str) -> str | None:
        raw = (session_override or "").strip()
        if not raw:
            return None
        try:
            return self._subjects.validate_session_id(raw)
        except ValueError:
            return raw.removeprefix("ses-").strip() or None

    def _row_values(
        self,
        series: DicomSeries,
        *,
        dataset_root: str,
        subject: str,
        session: str,
        datatype: str,
        suffix: str,
        run: str,
        filename: str,
        naming_rule: str = "",
    ) -> dict[str, Any]:
        meta = self.metadata_extractor.extract_from_file(
            series.sample_file,
            num_images=series.num_images,
            source_dir=series.source_dir,
        )
        optional = read_optional_tags(series.sample_file)

        values: dict[str, Any] = {col: "" for col in SERIES_INVENTORY_COLUMNS}
        values["Dataset Root"] = dataset_root
        values["Subject"] = subject
        values["Session"] = session or ""

        # Prefer live series fields, then extractor metadata (future-safe attribute map).
        values["StudyInstanceUID"] = series.study_instance_uid or getattr(
            meta, "study_instance_uid", ""
        )
        values["SeriesInstanceUID"] = series.series_instance_uid or getattr(
            meta, "series_instance_uid", ""
        )
        values["SeriesNumber"] = (
            series.series_number
            if series.series_number is not None
            else getattr(meta, "series_number", None)
        )
        values["AcquisitionNumber"] = series.acquisition_number
        values["SeriesDescription"] = series.series_description or meta.series_description
        values["ProtocolName"] = series.protocol_name or meta.protocol_name
        values["Modality"] = series.modality or meta.modality
        values["NumberOfImages"] = series.num_images or meta.num_images
        values["NumberOfSlices"] = series.num_images or meta.num_images

        for column, attr in _META_COLUMN_ATTR.items():
            if values.get(column) not in (None, ""):
                continue
            raw = getattr(meta, attr, None)
            values[column] = _format_meta_value(raw)

        for column, tag in _OPTIONAL_COLUMN_TAG.items():
            if values.get(column) not in (None, ""):
                continue
            if tag in optional:
                values[column] = optional[tag]

        # PhaseEncodingPolarity — only when a polarity-like token is present (no invention).
        pe = str(values.get("PhaseEncodingDirection") or "")
        if pe.upper() in {"+", "-", "POS", "NEG", "POSITIVE", "NEGATIVE"}:
            values["PhaseEncodingPolarity"] = pe
        elif "InPlanePhaseEncodingDirectionDICOM" in optional:
            # j / i / ROW / COL are axes, not polarity — leave polarity empty.
            pass

        acq_type = (
            series.fine_sequence_type
            or series.detection_label
            or series.sequence_type
            or "unknown"
        )
        values["Detected Acquisition Type"] = acq_type
        values["Naming Rule Applied"] = naming_rule
        values["Source Subject Folder"] = getattr(series, "source_subject_folder", "") or ""
        values["Detection Method"] = getattr(series, "subject_detection_method", "") or ""
        values["Original PatientID"] = getattr(series, "dicom_patient_id", "") or ""
        values["Expected BIDS Datatype"] = datatype
        values["Expected BIDS Suffix"] = suffix
        values["Planned Run Number"] = run
        values["Planned Filename"] = filename
        values["Conversion Status"] = series.status.value if series.status else "Pending"
        values["Warnings"] = _warnings_for(series)

        # Future-compat: fold any extra metadata keys that match inventory columns.
        dump = _meta_dump(meta)
        for column in values:
            if values[column] not in (None, ""):
                continue
            snake = column.lower().replace(" ", "_")
            if snake in dump and dump[snake] not in (None, "", []):
                values[column] = _format_meta_value(dump[snake])

        return values


def _meta_dump(meta: Any) -> dict[str, Any]:
    if hasattr(meta, "model_dump"):
        try:
            return dict(meta.model_dump())
        except Exception:  # noqa: BLE001
            pass
    return {k: getattr(meta, k) for k in dir(meta) if not k.startswith("_")}


def _format_meta_value(raw: Any) -> Any:
    if raw is None:
        return ""
    if isinstance(raw, (list, tuple)):
        return "\\".join(str(x) for x in raw)
    return raw


def _warnings_for(series: DicomSeries) -> str:
    parts: list[str] = []
    if series.message:
        parts.append(series.message)
    if series.requires_manual_mapping:
        parts.append("requires_manual_mapping")
    if series.sequence_confidence and series.sequence_confidence < 0.5:
        parts.append(f"low_confidence={series.sequence_confidence:.2f}")
    if (series.sequence_type or "").lower() == "unknown":
        parts.append("unknown_sequence_type")
    return "; ".join(parts)
