"""Audit DICOM → BIDS conversion for information preservation."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import nibabel as nib
import pydicom

from neuro_pipeline.config.defaults import (
    CONVERSION_AUDIT_TOLERANCE_MM,
    CONVERSION_AUDIT_TOLERANCE_SEC,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class ConversionAuditResult:
    """Outcome of one series conversion audit."""

    participant_id: str
    session_label: str
    series_instance_uid: str
    source_dicom: str
    nifti_path: str
    passed: bool
    checks: list[dict[str, object]]
    errors: list[str]
    warnings: list[str]


def _read_dicom_field(dataset: pydicom.dataset.Dataset, tag: tuple[int, int]) -> str:
    element = dataset.get(tag)
    if element is None or element.value is None:
        return ""
    return str(element.value).strip()


def _approx_equal(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def audit_series_conversion(
    *,
    participant_id: str,
    session_label: str,
    series_instance_uid: str,
    source_dicom: Path,
    nifti_path: Path,
) -> ConversionAuditResult:
    """Compare DICOM source metadata against converted NIfTI + JSON sidecar."""
    checks: list[dict[str, object]] = []
    errors: list[str] = []
    warnings: list[str] = []

    sidecar_path = (
        Path(str(nifti_path).replace(".nii.gz", ".json"))
        if nifti_path.name.endswith(".nii.gz")
        else nifti_path.with_suffix(".json")
    )

    try:
        dicom = pydicom.dcmread(str(source_dicom), stop_before_pixels=True, force=False)
    except (OSError, pydicom.errors.InvalidDicomError) as exc:
        return ConversionAuditResult(
            participant_id=participant_id,
            session_label=session_label,
            series_instance_uid=series_instance_uid,
            source_dicom=str(source_dicom),
            nifti_path=str(nifti_path),
            passed=False,
            checks=checks,
            errors=[f"Cannot read DICOM: {exc}"],
            warnings=warnings,
        )

    if not nifti_path.is_file():
        return ConversionAuditResult(
            participant_id=participant_id,
            session_label=session_label,
            series_instance_uid=series_instance_uid,
            source_dicom=str(source_dicom),
            nifti_path=str(nifti_path),
            passed=False,
            checks=checks,
            errors=["Converted NIfTI missing"],
            warnings=warnings,
        )

    image = nib.load(str(nifti_path))
    header = image.header
    zooms = header.get_zooms()
    voxel_size = [float(zooms[i]) for i in range(min(3, len(zooms)))]
    n_volumes = 1
    if len(image.shape) == 4:
        n_volumes = int(image.shape[3])

    dicom_rows = int(getattr(dicom, "Rows", 0) or 0)
    dicom_cols = int(getattr(dicom, "Columns", 0) or 0)
    slice_thickness = float(getattr(dicom, "SliceThickness", 0) or 0)
    pixel_spacing = getattr(dicom, "PixelSpacing", None)
    dicom_voxel_x = float(pixel_spacing[0]) if pixel_spacing else 0.0
    dicom_voxel_y = float(pixel_spacing[1]) if pixel_spacing else 0.0

    checks.append(
        {
            "name": "matrix_dimensions",
            "dicom_rows": dicom_rows,
            "dicom_columns": dicom_cols,
            "nifti_shape": list(image.shape[:3]),
            "passed": dicom_rows == image.shape[0] and dicom_cols == image.shape[1],
        }
    )
    if dicom_rows and dicom_cols:
        if dicom_rows != image.shape[0] or dicom_cols != image.shape[1]:
            errors.append(
                f"Matrix mismatch DICOM ({dicom_rows}x{dicom_cols}) "
                f"vs NIfTI ({image.shape[0]}x{image.shape[1]})"
            )

    if slice_thickness and len(voxel_size) >= 3:
        slice_ok = _approx_equal(slice_thickness, voxel_size[2], CONVERSION_AUDIT_TOLERANCE_MM)
        checks.append(
            {
                "name": "slice_thickness",
                "dicom_mm": slice_thickness,
                "nifti_mm": voxel_size[2],
                "passed": slice_ok,
            }
        )
        if not slice_ok:
            errors.append(
                f"Slice thickness mismatch: DICOM {slice_thickness} vs NIfTI {voxel_size[2]}"
            )

    if dicom_voxel_x and dicom_voxel_y and len(voxel_size) >= 2:
        xy_ok = (
            _approx_equal(dicom_voxel_x, voxel_size[0], CONVERSION_AUDIT_TOLERANCE_MM)
            and _approx_equal(dicom_voxel_y, voxel_size[1], CONVERSION_AUDIT_TOLERANCE_MM)
        )
        checks.append(
            {
                "name": "pixel_spacing",
                "dicom_mm": [dicom_voxel_x, dicom_voxel_y],
                "nifti_mm": voxel_size[:2],
                "passed": xy_ok,
            }
        )
        if not xy_ok:
            errors.append("In-plane voxel size mismatch between DICOM and NIfTI")

    orientation = _read_dicom_field(dicom, (0x0020, 0x0037))
    checks.append({"name": "orientation_present", "passed": bool(orientation)})

    tr_dicom = float(getattr(dicom, "RepetitionTime", 0) or 0)
    te_dicom = float(getattr(dicom, "EchoTime", 0) or 0)
    if sidecar_path.is_file():
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        tr_json = float(sidecar.get("RepetitionTime", 0) or 0)
        te_json = float(sidecar.get("EchoTime", 0) or 0)
        if tr_dicom and tr_json:
            tr_ok = _approx_equal(tr_dicom, tr_json, CONVERSION_AUDIT_TOLERANCE_SEC)
            checks.append(
                {"name": "RepetitionTime", "dicom": tr_dicom, "json": tr_json, "passed": tr_ok}
            )
            if not tr_ok:
                errors.append(f"TR mismatch: DICOM {tr_dicom} vs JSON {tr_json}")
        if te_dicom and te_json:
            te_ok = _approx_equal(te_dicom, te_json, CONVERSION_AUDIT_TOLERANCE_SEC)
            checks.append(
                {"name": "EchoTime", "dicom": te_dicom, "json": te_json, "passed": te_ok}
            )
            if not te_ok:
                errors.append(f"TE mismatch: DICOM {te_dicom} vs JSON {te_json}")
    else:
        warnings.append("Missing JSON sidecar for timing/metadata audit")

    modality = _read_dicom_field(dicom, (0x0008, 0x0060))
    checks.append({"name": "modality", "value": modality, "passed": bool(modality)})
    checks.append({"name": "volume_count", "n_volumes": n_volumes, "passed": n_volumes >= 1})

    passed = not errors
    return ConversionAuditResult(
        participant_id=participant_id,
        session_label=session_label,
        series_instance_uid=series_instance_uid,
        source_dicom=str(source_dicom),
        nifti_path=str(nifti_path),
        passed=passed,
        checks=checks,
        errors=errors,
        warnings=warnings,
    )


def audit_results_to_rows(results: list[ConversionAuditResult]) -> list[dict[str, object]]:
    """Flatten audit results for CSV export."""
    rows: list[dict[str, object]] = []
    for result in results:
        rows.append(
            {
                "participant_id": result.participant_id,
                "session_label": result.session_label,
                "series_instance_uid": result.series_instance_uid,
                "source_dicom": result.source_dicom,
                "nifti_path": result.nifti_path,
                "passed": result.passed,
                "error_count": len(result.errors),
                "warning_count": len(result.warnings),
                "errors": "; ".join(result.errors),
                "warnings": "; ".join(result.warnings),
                "checks_json": json.dumps(result.checks, sort_keys=True),
            }
        )
    return rows
