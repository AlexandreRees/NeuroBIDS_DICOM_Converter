"""Modality-specific integrity checks for acquisition validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import nibabel as nib
import numpy as np

from neuro_pipeline.acquisition.catalog import (
    T1_ACQUISITION_ID,
    ExpectedAcquisition,
    extract_pe_direction,
)

if TYPE_CHECKING:
    from neuro_pipeline.acquisition.consistency import BidsFileInfo

STRUCTURAL_ACQUISITIONS = frozenset(
    {"T1w_MPR", "Sag_Flair_3D_0.8", "WMn_MPRAGE_sagittal"}
)
FUNC_CATEGORIES = frozenset({"functional", "movie", "task_fmri", "control"})
SPIN_ECHO_FMAP_IDS = frozenset({"SpinEchoFieldMap_AP", "SpinEchoFieldMap_PA"})

ANAT_JSON_FIELDS = ("SeriesDescription", "ProtocolName", "MagneticFieldStrength")
FUNC_JSON_FIELDS = ("RepetitionTime", "EchoTime", "PhaseEncodingDirection")
DWI_COMPANION_SUFFIXES = (".json", ".bval", ".bvec")


def _pe_from_json_value(value: str) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    if normalized == "j-":
        return "AP"
    if normalized == "j+":
        return "PA"
    if normalized == "i-":
        return "RL"
    if normalized == "i+":
        return "LR"
    return value.upper()


@dataclass
class ModalityIntegrityResult:
    """Outcome of modality-specific integrity checks."""

    metadata_validation_status: str = "skip"
    integrity_status: str = "skip"
    missing_companion_files: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.messages.append(message)
        self.metadata_validation_status = _worst(self.metadata_validation_status, "error")
        self.integrity_status = _worst(self.integrity_status, "error")

    def add_warning(self, message: str) -> None:
        self.messages.append(message)
        self.metadata_validation_status = _worst(self.metadata_validation_status, "warning")
        if self.integrity_status == "skip":
            self.integrity_status = "warning"
        else:
            self.integrity_status = _worst(self.integrity_status, "warning")

    def mark_pass(self) -> None:
        if self.metadata_validation_status == "skip":
            self.metadata_validation_status = "pass"
        if self.integrity_status == "skip":
            self.integrity_status = "pass"


def _worst(current: str, new: str) -> str:
    order = {"skip": 0, "pass": 1, "warning": 2, "error": 3}
    return new if order.get(new, 0) > order.get(current, 0) else current


def _nifti_base_path(raw_bids: Path, relative_nifti: str) -> Path:
    path = raw_bids / relative_nifti
    if path.name.endswith(".nii.gz"):
        return Path(str(path).replace(".nii.gz", ""))
    return path.with_suffix("")


def _load_sidecar(raw_bids: Path, relative_json: str) -> dict[str, object]:
    if not relative_json:
        return {}
    sidecar = raw_bids / relative_json
    if not sidecar.is_file():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _check_json_fields(
    sidecar: dict[str, object],
    required: tuple[str, ...],
    result: ModalityIntegrityResult,
    *,
    severity: str = "warning",
) -> None:
    missing = [name for name in required if not sidecar.get(name)]
    if not missing:
        if result.metadata_validation_status == "skip":
            result.metadata_validation_status = "pass"
        return
    message = f"Missing JSON metadata: {', '.join(missing)}"
    if severity == "error":
        result.add_error(message)
    else:
        result.add_warning(message)


def _check_nifti_geometry(nifti_path: Path, result: ModalityIntegrityResult) -> int | None:
    """Validate NIfTI header geometry; return volume count when available."""
    if not nifti_path.is_file():
        result.add_error(f"NIfTI file missing: {nifti_path.name}")
        return None
    try:
        image = nib.load(str(nifti_path))
    except Exception as exc:
        result.add_error(f"Invalid NIfTI header: {exc}")
        return None

    shape = image.shape
    if len(shape) < 3 or min(shape[:3]) <= 0:
        result.add_error(f"Invalid image dimensions: {shape}")
        return None

    zooms = image.header.get_zooms()
    if len(zooms) >= 3 and any(float(z) <= 0 for z in zooms[:3]):
        result.add_error(f"Invalid voxel size: {zooms[:3]}")
        return None

    affine = image.affine
    if affine is None or not np.isfinite(affine).all():
        result.add_error("Invalid or non-finite affine matrix")
        return None

    if result.integrity_status in {"skip", "warning"}:
        result.integrity_status = "pass"
    return int(shape[3]) if len(shape) == 4 else 1


def _parse_bval_bvec_counts(bval_path: Path, bvec_path: Path) -> tuple[int, int]:
    bvals = np.loadtxt(str(bval_path))
    bvals = bvals.ravel()
    bvecs = np.loadtxt(str(bvec_path))
    if bvecs.ndim == 1:
        bvecs = bvecs.reshape(1, -1)
    if bvecs.shape[0] == 3:
        n_bvecs = bvecs.shape[1]
    elif bvecs.shape[1] == 3:
        n_bvecs = bvecs.shape[0]
    else:
        n_bvecs = 0
    return len(bvals), n_bvecs


def check_dwi_integrity(
    raw_bids: Path,
    expected: ExpectedAcquisition,
    series_row: dict[str, str],
    bids_file: Any | None,
) -> ModalityIntegrityResult:
    """Validate diffusion companion files, gradients, and AP/PA consistency."""
    result = ModalityIntegrityResult()
    if bids_file is None:
        result.add_error("DWI integrity check skipped — BIDS file not found")
        return result

    base = _nifti_base_path(raw_bids, bids_file.relative_path)
    companions = {
        "nii.gz": Path(f"{base}.nii.gz"),
        "json": Path(f"{base}.json"),
        "bval": Path(f"{base}.bval"),
        "bvec": Path(f"{base}.bvec"),
    }
    for label, path in companions.items():
        if not path.is_file():
            result.missing_companion_files.append(label)
    if result.missing_companion_files:
        result.add_error(
            "Missing diffusion companion files: "
            + ", ".join(result.missing_companion_files)
        )
        return result

    n_volumes = _check_nifti_geometry(companions["nii.gz"], result)
    if n_volumes is None:
        return result

    try:
        n_bvals, n_bvecs = _parse_bval_bvec_counts(companions["bval"], companions["bvec"])
    except (OSError, ValueError) as exc:
        result.add_error(f"Cannot read bval/bvec: {exc}")
        return result

    if n_bvals != n_volumes or n_bvecs != n_volumes:
        result.add_error(
            f"Gradient/volume mismatch: NIfTI={n_volumes}, bval={n_bvals}, bvec={n_bvecs}"
        )

    sidecar = _load_sidecar(raw_bids, bids_file.json_path)
    _check_json_fields(sidecar, ("SeriesDescription",), result, severity="warning")

    if expected.expected_pe_direction:
        combined = (
            f"{series_row.get('series_description', '')} "
            f"{series_row.get('protocol_name', '')}"
        )
        dicom_pe = extract_pe_direction(combined)
        json_pe = _pe_from_json_value(str(sidecar.get("PhaseEncodingDirection", "") or ""))
        bids_pe = bids_file.pe_dir_label or json_pe
        if not dicom_pe:
            result.add_error("AP/PA missing from DICOM series metadata")
        elif dicom_pe != expected.expected_pe_direction:
            result.add_error(
                f"AP/PA mismatch (DICOM): expected {expected.expected_pe_direction}, "
                f"found {dicom_pe}"
            )
        if bids_pe and bids_pe in {"AP", "PA"} and bids_pe != expected.expected_pe_direction:
            result.add_error(
                f"AP/PA mismatch (BIDS): expected {expected.expected_pe_direction}, "
                f"found {bids_pe}"
            )

    if not result.messages:
        result.mark_pass()
    return result


def check_func_integrity(
    raw_bids: Path,
    expected: ExpectedAcquisition,
    bids_file: Any | None,
) -> ModalityIntegrityResult:
    """Validate BOLD NIfTI/JSON, TaskName, and run metadata."""
    result = ModalityIntegrityResult()
    if bids_file is None:
        result.add_error("Functional integrity check skipped — BIDS file not found")
        return result

    nifti_path = raw_bids / bids_file.relative_path
    if not nifti_path.is_file():
        result.missing_companion_files.append("nii.gz")
        result.add_error("Functional NIfTI missing")
        return result
    if not bids_file.json_path:
        result.missing_companion_files.append("json")
        result.add_error("Functional JSON sidecar missing")
        return result

    _check_nifti_geometry(nifti_path, result)
    sidecar = _load_sidecar(raw_bids, bids_file.json_path)
    _check_json_fields(sidecar, FUNC_JSON_FIELDS, result, severity="warning")

    if expected.expected_task:
        if not bids_file.task:
            result.add_error("TaskName missing from BIDS filename")
        elif bids_file.task != expected.expected_task:
            result.add_warning(
                f"TaskName mismatch: expected '{expected.expected_task}', "
                f"found '{bids_file.task}'"
            )
        json_task = str(sidecar.get("TaskName", "") or "").lower()
        if json_task and json_task != expected.expected_task:
            result.add_warning(
                f"JSON TaskName mismatch: expected '{expected.expected_task}', "
                f"found '{json_task}'"
            )

    if expected.expected_run is not None and bids_file.run != expected.expected_run:
        result.add_error(
            f"Run number mismatch: expected run-{expected.expected_run:02d}, "
            f"found run-{bids_file.run or 'missing'}"
        )

    if not result.messages:
        result.mark_pass()
    return result


def check_structural_integrity(
    raw_bids: Path,
    expected: ExpectedAcquisition,
    bids_file: Any | None,
) -> ModalityIntegrityResult:
    """Validate anatomical JSON metadata and NIfTI geometry."""
    result = ModalityIntegrityResult()
    if bids_file is None:
        result.add_error("Structural integrity check skipped — BIDS file not found")
        return result

    nifti_path = raw_bids / bids_file.relative_path
    if not nifti_path.is_file():
        result.missing_companion_files.append("nii.gz")
        result.add_error("Structural NIfTI missing")
        return result
    if not bids_file.json_path:
        result.missing_companion_files.append("json")
        result.add_error("Structural JSON sidecar missing")
        return result

    _check_nifti_geometry(nifti_path, result)
    sidecar = _load_sidecar(raw_bids, bids_file.json_path)
    _check_json_fields(sidecar, ANAT_JSON_FIELDS, result, severity="error")

    if expected.acquisition_id == "Sag_Flair_3D_0.8" and bids_file.suffix != "FLAIR":
        result.add_warning(
            f"Expected FLAIR suffix, found '{bids_file.suffix or 'unknown'}'"
        )
    if expected.acquisition_id == T1_ACQUISITION_ID and bids_file.suffix != "T1w":
        result.add_warning(
            f"Expected T1w suffix for reference anatomical, found '{bids_file.suffix or 'unknown'}'"
        )

    if not result.messages:
        result.mark_pass()
    return result


def check_fieldmap_integrity(
    raw_bids: Path,
    expected: ExpectedAcquisition,
    bids_file: Any | None,
    *,
    pair_present: bool,
    func_dwi_targets: set[str],
) -> ModalityIntegrityResult:
    """Validate spin-echo fieldmap files and IntendedFor linkage."""
    result = ModalityIntegrityResult()
    if expected.acquisition_id not in SPIN_ECHO_FMAP_IDS:
        if bids_file is None:
            result.integrity_status = "skip"
            result.metadata_validation_status = "skip"
            return result

    if not pair_present:
        result.add_error(f"Incomplete SpinEcho fieldmap pair for {expected.acquisition_id}")
        return result

    if bids_file is None:
        result.add_error("Fieldmap integrity check skipped — BIDS file not found")
        return result

    nifti_path = raw_bids / bids_file.relative_path
    if not nifti_path.is_file():
        result.missing_companion_files.append("nii.gz")
        result.add_error("Fieldmap NIfTI missing")
        return result
    if not bids_file.json_path:
        result.missing_companion_files.append("json")
        result.add_error("Fieldmap JSON sidecar missing")
        return result

    _check_nifti_geometry(nifti_path, result)
    sidecar = _load_sidecar(raw_bids, bids_file.json_path)
    _check_json_fields(
        sidecar,
        ("PhaseEncodingDirection", "SeriesDescription"),
        result,
        severity="error",
    )

    if expected.expected_pe_direction:
        json_pe = _pe_from_json_value(str(sidecar.get("PhaseEncodingDirection", "") or ""))
        pe = bids_file.pe_dir_label or json_pe
        if not pe:
            result.add_error("PhaseEncodingDirection missing from fieldmap metadata")
        elif pe != expected.expected_pe_direction:
            result.add_error(
                f"Fieldmap AP/PA mismatch: expected {expected.expected_pe_direction}, found {pe}"
            )

    if expected.acquisition_id in SPIN_ECHO_FMAP_IDS:
        if not bids_file.intended_for:
            result.add_error(f"IntendedFor missing for fieldmap {bids_file.stem}")
        else:
            invalid = set(bids_file.intended_for) - func_dwi_targets
            if invalid:
                result.add_error(
                    f"IntendedFor references unknown files: {sorted(invalid)}"
                )

    if not result.messages:
        result.mark_pass()
    return result


def run_modality_integrity_check(
    raw_bids: Path,
    expected: ExpectedAcquisition,
    series_row: dict[str, str],
    bids_file: Any | None,
    *,
    spin_echo_pair_present: bool = True,
    func_dwi_targets: set[str] | None = None,
) -> ModalityIntegrityResult:
    """Dispatch integrity checks based on acquisition category/datatype."""
    targets = func_dwi_targets or set()
    if expected.expected_datatype == "dwi":
        return check_dwi_integrity(raw_bids, expected, series_row, bids_file)
    if expected.category in FUNC_CATEGORIES or expected.expected_datatype == "func":
        return check_func_integrity(raw_bids, expected, bids_file)
    if expected.acquisition_id in STRUCTURAL_ACQUISITIONS:
        return check_structural_integrity(raw_bids, expected, bids_file)
    if expected.expected_datatype == "fmap":
        return check_fieldmap_integrity(
            raw_bids,
            expected,
            bids_file,
            pair_present=spin_echo_pair_present,
            func_dwi_targets=targets,
        )
    result = ModalityIntegrityResult()
    result.integrity_status = "skip"
    result.metadata_validation_status = "skip"
    return result


def check_single_t1_reference(
    t1_rows: list[tuple[str, Any | None]],
) -> tuple[str, str]:
    """Confirm exactly one valid T1 reference exists for a session."""
    valid = [
        acquisition_id
        for acquisition_id, bids_file in t1_rows
        if acquisition_id == T1_ACQUISITION_ID and bids_file is not None
    ]
    if len(valid) == 1:
        return "pass", ""
    if len(valid) == 0:
        return "error", "No T1 reference image (T1w_MPR) available for session"
    return "error", "Multiple T1 reference candidates detected for session"
