"""Tests for DWI / ADC companion validation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

nibabel = pytest.importorskip("nibabel")
import nibabel as nib  # noqa: E402

from neuro_pipeline.validation.dwi_validator import DiffusionValidator
from neuro_pipeline.validation.models import ValidationStatus
from neuro_pipeline.validation.nifti_validator import NiftiValidator


def _write_dwi_bundle(
    folder: Path,
    *,
    stem: str = "sub-01_dwi",
    n_vol: int = 4,
    with_bvec: bool = True,
    with_bval: bool = True,
    with_json: bool = True,
    bad_bvec_norm: bool = False,
) -> Path:
    data = np.ones((4, 4, 4, n_vol), dtype=np.float32)
    nifti = folder / f"{stem}.nii.gz"
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(nifti))

    if with_bval:
        (folder / f"{stem}.bval").write_text(" ".join(["0"] + ["1000"] * (n_vol - 1)) + "\n")
    if with_bvec:
        xs = ["0"] + (["0"] * (n_vol - 1) if bad_bvec_norm else ["1"] * (n_vol - 1))
        ys = ["0"] * n_vol
        zs = ["0"] * n_vol
        if bad_bvec_norm:
            xs = ["0"] * n_vol
        (folder / f"{stem}.bvec").write_text(
            " ".join(xs) + "\n" + " ".join(ys) + "\n" + " ".join(zs) + "\n"
        )
    if with_json:
        (folder / f"{stem}.json").write_text(
            '{"SeriesDescription": "DWI", "Manufacturer": "Generic"}',
            encoding="utf-8",
        )
    return nifti


def test_dwi_with_bval_bvec_passes(tmp_path: Path) -> None:
    nifti = _write_dwi_bundle(tmp_path, n_vol=64)
    result = DiffusionValidator(tmp_path).validate_one(nifti)
    assert result.status == ValidationStatus.PASS
    assert result.n_volumes == 64
    assert result.n_gradients == 64
    assert "Valid DWI" in result.message


def test_adc_without_bval_bvec_passes(tmp_path: Path) -> None:
    data = np.ones((6, 6, 6), dtype=np.float32)
    nifti = tmp_path / "series_ADC.nii.gz"
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(nifti))
    result = DiffusionValidator(tmp_path).validate_one(nifti)
    assert result.status == ValidationStatus.PASS
    assert result.kind == "adc"
    assert "ADC map without gradients" in result.message


def test_adc_apparent_diffusion_coefficient_name(tmp_path: Path) -> None:
    nifti = tmp_path / "apparent_diffusion_coefficient.nii.gz"
    nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), np.eye(4)), str(nifti))
    result = DiffusionValidator(tmp_path).validate_one(nifti)
    assert result.status == ValidationStatus.PASS
    assert result.kind == "adc"


def test_missing_bvec_for_dwi_fails(tmp_path: Path) -> None:
    nifti = _write_dwi_bundle(tmp_path, with_bvec=False)
    result = DiffusionValidator(tmp_path).validate_one(nifti)
    assert result.status == ValidationStatus.FAIL
    assert "Missing bvec" in result.message


def test_bad_bvec_norm_is_warning_not_fail(tmp_path: Path) -> None:
    nifti = _write_dwi_bundle(tmp_path, n_vol=4, bad_bvec_norm=True)
    result = DiffusionValidator(tmp_path).validate_one(nifti)
    assert result.status == ValidationStatus.WARNING
    assert "bvec normalization" in result.message.lower()


def test_b0_zero_vectors_ignored(tmp_path: Path) -> None:
    """bval==0 entries may have zero bvecs without warning."""
    nifti = _write_dwi_bundle(tmp_path, n_vol=3, bad_bvec_norm=False)
    stem = "sub-01_dwi"
    # b0 zero vector + two unit vectors
    (tmp_path / f"{stem}.bval").write_text("0 1000 1000\n")
    (tmp_path / f"{stem}.bvec").write_text("0 1 0\n0 0 1\n0 0 0\n")
    result = DiffusionValidator(tmp_path).validate_one(nifti)
    assert result.status == ValidationStatus.PASS


def test_4d_nifti_spatial_voxel_dims_pass(tmp_path: Path) -> None:
    """4D DWI with TR in 4th zoom must not trip voxel-size checks."""
    path = tmp_path / "dwi_4d.nii.gz"
    data = np.ones((8, 8, 8, 12), dtype=np.float32)
    # pixdim4 often ~TR seconds (e.g. 8.0) — must be ignored for spatial validation
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    img = nib.Nifti1Image(data, affine)
    hdr = img.header
    zooms = list(hdr.get_zooms())
    # Force a huge 4th zoom that would fail if validated
    while len(zooms) < 4:
        zooms.append(1.0)
    zooms[3] = 80.0
    hdr.set_zooms(tuple(zooms[: data.ndim]))
    nib.save(img, str(path))

    result = NiftiValidator(tmp_path).validate_one(path)
    assert result.status == ValidationStatus.PASS
    assert result.voxel_size is not None
    assert len(result.voxel_size) == 3
    assert result.dimensions == (8, 8, 8, 12)
