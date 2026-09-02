"""Tests for NIfTI and metadata validation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

nibabel = pytest.importorskip("nibabel")
import nibabel as nib  # noqa: E402

from neuro_pipeline.validation import NiftiValidator, ValidationStatus, run_full_validation
from neuro_pipeline.validation.metadata_validator import MetadataValidator


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> None:
    aff = np.eye(4) if affine is None else affine
    nib.save(nib.Nifti1Image(data.astype(np.float32), aff), str(path))


def test_valid_nifti_passes(tmp_path: Path) -> None:
    path = tmp_path / "brain.nii.gz"
    _write_nifti(path, np.ones((8, 8, 8)))
    result = NiftiValidator(tmp_path).validate_one(path)
    assert result.status == ValidationStatus.PASS
    assert result.dimensions == (8, 8, 8)


def test_corrupted_nifti_fails(tmp_path: Path) -> None:
    path = tmp_path / "broken.nii.gz"
    path.write_bytes(b"this is not a nifti file")
    result = NiftiValidator(tmp_path).validate_one(path)
    assert result.status == ValidationStatus.FAIL


def test_unusual_voxel_size_warns(tmp_path: Path) -> None:
    path = tmp_path / "huge_voxels.nii.gz"
    affine = np.diag([60.0, 60.0, 60.0, 1.0])
    _write_nifti(path, np.ones((4, 4, 4)), affine=affine)
    result = NiftiValidator(tmp_path).validate_one(path)
    assert result.status == ValidationStatus.WARNING
    assert "unusual voxel size" in result.message


def test_metadata_missing_fields_are_warnings(tmp_path: Path) -> None:
    path = tmp_path / "series.json"
    path.write_text('{"SeriesDescription": "MPRAGE"}', encoding="utf-8")
    result = MetadataValidator(tmp_path).validate_one(path)
    assert result.status == ValidationStatus.WARNING
    assert "Manufacturer" in result.missing_fields


def test_run_full_validation(tmp_path: Path) -> None:
    _write_nifti(tmp_path / "t1.nii.gz", np.ones((6, 6, 6)))
    summary = run_full_validation(tmp_path)
    assert summary.nifti_results
    assert summary.overall_status in {
        ValidationStatus.PASS,
        ValidationStatus.INFO,
        ValidationStatus.WARNING,
        ValidationStatus.FAIL,
    }


def test_4d_spatial_zooms_only(tmp_path: Path) -> None:
    path = tmp_path / "bold_4d.nii.gz"
    data = np.ones((6, 6, 6, 20), dtype=np.float32)
    affine = np.diag([3.0, 3.0, 3.0, 1.0])
    img = nib.Nifti1Image(data, affine)
    hdr = img.header
    zooms = list(hdr.get_zooms())
    while len(zooms) < 4:
        zooms.append(1.0)
    zooms[3] = 100.0  # would warn/fail if treated as spatial mm
    hdr.set_zooms(tuple(zooms[:4]))
    nib.save(img, str(path))
    result = NiftiValidator(tmp_path).validate_one(path)
    assert result.status == ValidationStatus.PASS
    assert result.voxel_size == pytest.approx((3.0, 3.0, 3.0), abs=1e-3)
