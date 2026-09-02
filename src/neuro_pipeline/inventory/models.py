"""DICOM inventory models (series rows + protocol completeness)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SERIES_INVENTORY_COLUMNS: tuple[str, ...] = (
    "Dataset Root",
    "Subject",
    "Session",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SeriesNumber",
    "AcquisitionNumber",
    "SeriesDescription",
    "ProtocolName",
    "SequenceName",
    "SequenceVariant",
    "ScanningSequence",
    "ImageType",
    "Modality",
    "Manufacturer",
    "ManufacturerModelName",
    "MagneticFieldStrength",
    "StationName",
    "InstitutionName",
    "BodyPartExamined",
    "PatientPosition",
    "Rows",
    "Columns",
    "NumberOfSlices",
    "NumberOfImages",
    "PixelSpacing",
    "SliceThickness",
    "SpacingBetweenSlices",
    "EchoTime",
    "RepetitionTime",
    "InversionTime",
    "FlipAngle",
    "Bandwidth",
    "PhaseEncodingDirection",
    "PhaseEncodingPolarity",
    "MultibandFactor",
    "ReceiveCoilName",
    "TransmitCoilName",
    "Detected Acquisition Type",
    "Naming Rule Applied",
    "Source Subject Folder",
    "Detection Method",
    "Original PatientID",
    "Expected BIDS Datatype",
    "Expected BIDS Suffix",
    "Planned Run Number",
    "Planned Filename",
    "Conversion Status",
    "Warnings",
)


PROTOCOL_ACQUISITIONS: tuple[str, ...] = (
    "T1w",
    "FLAIR",
    "REST_AP",
    "REST_PA",
    "MOVIE_1",
    "MOVIE_2",
    "MOVIE_3",
    "MOVIE_4",
    "DWI",
    "SBRef",
    "FieldMap_AP",
    "FieldMap_PA",
)


PROTOCOL_COLUMNS: tuple[str, ...] = ("Subject", "Session", *PROTOCOL_ACQUISITIONS, "Complete Protocol")


@dataclass(slots=True)
class SeriesInventoryRow:
    """One inventory row (one DICOM series)."""

    values: dict[str, Any] = field(default_factory=dict)

    def as_ordered(self) -> dict[str, Any]:
        return {col: self.values.get(col, "") for col in SERIES_INVENTORY_COLUMNS}


@dataclass(slots=True)
class ProtocolCompletenessRow:
    """One subject/session protocol completeness row."""

    subject: str
    session: str
    flags: dict[str, bool] = field(default_factory=dict)
    complete: bool = False

    def as_ordered(self) -> dict[str, Any]:
        out: dict[str, Any] = {"Subject": self.subject, "Session": self.session or ""}
        for key in PROTOCOL_ACQUISITIONS:
            out[key] = "✓" if self.flags.get(key) else "✗"
        out["Complete Protocol"] = "TRUE" if self.complete else "FALSE"
        return out


@dataclass(slots=True)
class InventoryResult:
    """Full inventory tables + export paths."""

    series_rows: list[SeriesInventoryRow] = field(default_factory=list)
    protocol_rows: list[ProtocolCompletenessRow] = field(default_factory=list)
    xlsx_path: str = ""
    csv_path: str = ""
    n_series: int = 0
    n_subjects: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_series": self.n_series,
            "n_subjects": self.n_subjects,
            "xlsx_path": self.xlsx_path,
            "csv_path": self.csv_path,
            "series_rows": [r.as_ordered() for r in self.series_rows],
            "protocol_rows": [r.as_ordered() for r in self.protocol_rows],
        }
