"""Verify DICOM → NIfTI spatial geometry preservation after conversion."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
import pydicom

from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.paths import ProjectPaths

LOGGER = logging.getLogger(__name__)

TOLERANCE_MM: float = 0.05
AFFINE_TOL: float = 1e-3

GEOMETRY_CSV_COLUMNS: tuple[str, ...] = (
    "participant",
    "session",
    "series_uid",
    "datatype",
    "status",
    "warning",
    "details",
)


@dataclass
class GeometryValidationRow:
    """One series geometry validation result."""

    participant: str
    session: str
    series_uid: str
    datatype: str
    status: str
    warning: str
    details: str

    def to_dict(self) -> dict[str, str]:
        return {
            "participant": self.participant,
            "session": self.session,
            "series_uid": self.series_uid,
            "datatype": self.datatype,
            "status": self.status,
            "warning": self.warning,
            "details": self.details,
        }


@dataclass
class GeometryValidationReport:
    """Aggregate geometry validation outcome."""

    passed: bool = True
    rows: list[GeometryValidationRow] = field(default_factory=list)

    def add_row(self, row: GeometryValidationRow) -> None:
        self.rows.append(row)
        if row.status == "error":
            self.passed = False

    @property
    def error_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "warning")


def _approx_equal(a: float, b: float, tol: float = TOLERANCE_MM) -> bool:
    return abs(a - b) <= tol


def _parse_float_list(value: object) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    text = str(value).strip("[]")
    if not text:
        return []
    return [float(part.strip()) for part in text.split(",") if part.strip()]


def _dicom_orientation_matrix(iop: list[float]) -> np.ndarray | None:
    if len(iop) != 6:
        return None
    row = np.array(iop[:3], dtype=float)
    col = np.array(iop[3:], dtype=float)
    if np.linalg.norm(row) == 0 or np.linalg.norm(col) == 0:
        return None
    row /= np.linalg.norm(row)
    col /= np.linalg.norm(col)
    slice_dir = np.cross(row, col)
    if np.linalg.norm(slice_dir) == 0:
        return None
    slice_dir /= np.linalg.norm(slice_dir)
    return np.column_stack([row, col, slice_dir])


def _nifti_orientation_matrix(affine: np.ndarray, zooms: tuple[float, ...]) -> np.ndarray | None:
    if affine.shape != (4, 4):
        return None
    rot = affine[:3, :3].copy()
    scales = np.array([zooms[0], zooms[1], zooms[2] if len(zooms) >= 3 else 1.0], dtype=float)
    for axis in range(3):
        norm = np.linalg.norm(rot[:, axis])
        if norm > 0:
            rot[:, axis] /= norm
        elif scales[axis] > 0:
            return None
    return rot


def _orientation_consistent(dicom_iop: list[float], affine: np.ndarray, zooms: tuple[float, ...]) -> bool:
    dicom_rot = _dicom_orientation_matrix(dicom_iop)
    nifti_rot = _nifti_orientation_matrix(affine, zooms)
    if dicom_rot is None or nifti_rot is None:
        return True
    diff = np.abs(np.abs(dicom_rot) - np.abs(nifti_rot))
    return bool(np.all(diff <= 0.15))


def _resolve_nifti_path(raw_bids: Path, expected_filename: str, output_dir: str) -> Path | None:
    if expected_filename:
        candidate = raw_bids / expected_filename
        if candidate.is_file():
            return candidate
    if output_dir:
        out = Path(output_dir)
        if out.is_dir():
            for suffix in (".nii.gz", ".nii"):
                matches = sorted(out.glob(f"*{suffix}"))
                if matches:
                    return matches[0]
    return None


def validate_series_geometry(
    *,
    participant: str,
    session: str,
    series_uid: str,
    datatype: str,
    source_dicom: Path,
    nifti_path: Path,
    dicom_slice_count: int | None = None,
) -> GeometryValidationRow:
    """Compare DICOM header geometry against converted NIfTI."""
    warnings: list[str] = []
    errors: list[str] = []
    details: dict[str, object] = {}

    try:
        dicom = pydicom.dcmread(str(source_dicom), stop_before_pixels=True, force=False)
    except (OSError, pydicom.errors.InvalidDicomError) as exc:
        return GeometryValidationRow(
            participant=participant,
            session=session,
            series_uid=series_uid,
            datatype=datatype,
            status="error",
            warning="",
            details=f"Cannot read DICOM: {exc}",
        )

    if not nifti_path.is_file():
        return GeometryValidationRow(
            participant=participant,
            session=session,
            series_uid=series_uid,
            datatype=datatype,
            status="error",
            warning="",
            details="Converted NIfTI missing",
        )

    image = nib.load(str(nifti_path))
    header = image.header
    affine = image.affine
    zooms = header.get_zooms()
    shape = image.shape

    iop = _parse_float_list(getattr(dicom, "ImageOrientationPatient", None))
    ipp = _parse_float_list(getattr(dicom, "ImagePositionPatient", None))
    pixel_spacing = _parse_float_list(getattr(dicom, "PixelSpacing", None))
    slice_thickness = float(getattr(dicom, "SliceThickness", 0) or 0)
    rows = int(getattr(dicom, "Rows", 0) or 0)
    columns = int(getattr(dicom, "Columns", 0) or 0)

    details.update(
        {
            "dicom_iop": iop,
            "dicom_ipp": ipp,
            "dicom_pixel_spacing": pixel_spacing,
            "dicom_slice_thickness": slice_thickness,
            "dicom_rows": rows,
            "dicom_columns": columns,
            "dicom_slice_count": dicom_slice_count,
            "nifti_shape": list(shape[:3]),
            "nifti_zooms": [float(z) for z in zooms[:3]],
            "nifti_qform_code": int(header["qform_code"]),
            "nifti_sform_code": int(header["sform_code"]),
        }
    )

    if rows and columns:
        if rows != shape[0] or columns != shape[1]:
            errors.append(
                f"Matrix mismatch DICOM ({rows}x{columns}) vs NIfTI ({shape[0]}x{shape[1]})"
            )

    if len(pixel_spacing) >= 2 and len(zooms) >= 2:
        if not _approx_equal(float(pixel_spacing[0]), float(zooms[0])):
            errors.append(f"Voxel X mismatch: DICOM {pixel_spacing[0]} vs NIfTI {zooms[0]}")
        if not _approx_equal(float(pixel_spacing[1]), float(zooms[1])):
            errors.append(f"Voxel Y mismatch: DICOM {pixel_spacing[1]} vs NIfTI {zooms[1]}")

    if slice_thickness and len(zooms) >= 3:
        if not _approx_equal(slice_thickness, float(zooms[2])):
            warnings.append(
                f"Slice thickness mismatch: DICOM {slice_thickness} vs NIfTI {zooms[2]}"
            )

    n_slices = dicom_slice_count
    if n_slices is None:
        n_slices = int(getattr(dicom, "NumberOfFrames", 0) or 0) or None
    if n_slices and len(shape) >= 3:
        nifti_slices = int(shape[2])
        if n_slices != nifti_slices and len(shape) == 3:
            errors.append(f"Slice count mismatch: DICOM {n_slices} vs NIfTI {nifti_slices}")

    if affine is None or not np.all(np.isfinite(affine)):
        errors.append("NIfTI affine is missing or non-finite")
    elif np.allclose(affine, np.eye(4), atol=1e-6):
        warnings.append("NIfTI affine is identity — verify qform/sform codes")

    qform = header.get_qform()
    sform = header.get_sform()
    q_code = int(header["qform_code"])
    s_code = int(header["sform_code"])
    if q_code == 0 and s_code == 0:
        errors.append("Both qform and sform codes are zero")
    elif q_code > 0 and s_code > 0 and not np.allclose(qform, sform, atol=AFFINE_TOL):
        warnings.append("qform and sform differ beyond tolerance")

    if iop and not _orientation_consistent(iop, affine, zooms):
        warnings.append("Orientation matrix differs between DICOM IOP and NIfTI affine")

    if not iop:
        warnings.append("ImageOrientationPatient missing in DICOM")
    if not ipp:
        warnings.append("ImagePositionPatient missing in DICOM")

    status = "pass"
    if errors:
        status = "error"
    elif warnings:
        status = "warning"

    return GeometryValidationRow(
        participant=participant,
        session=session,
        series_uid=series_uid,
        datatype=datatype,
        status=status,
        warning="; ".join(warnings),
        details=json.dumps(details, sort_keys=True),
    )


def _load_series_slice_counts(session_mapping: Path) -> dict[str, int]:
    if not session_mapping.is_file():
        return {}
    df = pd.read_csv(session_mapping, dtype=str).fillna("")
    counts: dict[str, int] = {}
    for _, row in df.iterrows():
        uid = str(row.get("series_instance_uid", "")).strip()
        raw_count = str(row.get("n_dicom_files", "")).strip()
        if uid and raw_count.isdigit():
            counts[uid] = int(raw_count)
    return counts


def run_geometry_validation(
    paths: ProjectPaths,
    *,
    fail_on_error: bool = False,
) -> GeometryValidationReport:
    """Validate geometry for all successfully converted series."""
    paths.ensure_derivatives_dir()
    paths.validate_writable(paths.derivatives / "validation")

    report = GeometryValidationReport()
    conversion = paths.conversion_report_csv
    if not conversion.is_file():
        LOGGER.warning("Conversion report missing; skipping geometry validation")
        pd.DataFrame(columns=list(GEOMETRY_CSV_COLUMNS)).to_csv(
            paths.geometry_validation_csv, index=False
        )
        return report

    df = pd.read_csv(conversion, dtype=str).fillna("")
    slice_counts = _load_series_slice_counts(paths.session_mapping_csv)

    for _, row in df.iterrows():
        if str(row.get("status", "")).strip() != "success":
            continue
        participant = str(row.get("participant_id", "")).strip()
        session = str(row.get("session_label", "")).strip()
        series_uid = str(row.get("series_instance_uid", "")).strip()
        datatype = str(row.get("bids_modality", "")).strip()
        source_dicom = Path(str(row.get("source_dicom", "")).strip())
        expected_filename = str(row.get("expected_filename", "")).strip()
        output_dir = str(row.get("bids_output_dir", "")).strip()
        nifti_path = _resolve_nifti_path(paths.raw_bids, expected_filename, output_dir)
        if nifti_path is None:
            report.add_row(
                GeometryValidationRow(
                    participant=participant,
                    session=session,
                    series_uid=series_uid,
                    datatype=datatype,
                    status="error",
                    warning="",
                    details="Could not locate converted NIfTI",
                )
            )
            continue

        result = validate_series_geometry(
            participant=participant,
            session=session,
            series_uid=series_uid,
            datatype=datatype,
            source_dicom=source_dicom,
            nifti_path=nifti_path,
            dicom_slice_count=slice_counts.get(series_uid),
        )
        report.add_row(result)

    pd.DataFrame([row.to_dict() for row in report.rows], columns=list(GEOMETRY_CSV_COLUMNS)).to_csv(
        paths.geometry_validation_csv,
        index=False,
    )
    LOGGER.info(
        "Geometry validation: passed=%s, errors=%d, warnings=%d, rows=%d",
        report.passed,
        report.error_count,
        report.warning_count,
        len(report.rows),
    )

    if fail_on_error and not report.passed:
        raise FatalPipelineError(
            f"Geometry validation reported {report.error_count} error(s); "
            f"see {paths.geometry_validation_csv}"
        )
    return report
