"""Tests for silent QC error detection (synthetic NIfTI only)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from neuro_pipeline.qc.errors import ErrorDetector, QCStatus


def _write_nifti(path: Path, shape=(4, 4, 4)) -> None:
    import nibabel as nib

    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.zeros(shape, dtype=np.float32)
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(path))


def test_missing_json_detected(tmp_path: Path) -> None:
    nifti = tmp_path / "anat" / "sub-01_T1w.nii.gz"
    _write_nifti(nifti)
    report = ErrorDetector().detect(tmp_path)
    codes = {i.code for i in report.issues}
    assert "missing_json" in codes


def test_missing_bvec_detected(tmp_path: Path) -> None:
    nifti = tmp_path / "dwi" / "sub-01_dwi.nii.gz"
    _write_nifti(nifti, shape=(4, 4, 4, 3))
    (nifti.parent / "sub-01_dwi.json").write_text("{}", encoding="utf-8")
    (nifti.parent / "sub-01_dwi.bval").write_text("0 1000 2000\n", encoding="utf-8")
    report = ErrorDetector().detect(tmp_path)
    assert any(i.code == "missing_bvec" for i in report.issues)
    assert report.status == QCStatus.FAIL


def test_dimension_mismatch_dwi_3d(tmp_path: Path) -> None:
    nifti = tmp_path / "dwi" / "sub-01_dwi.nii.gz"
    _write_nifti(nifti, shape=(4, 4, 4))
    (nifti.parent / "sub-01_dwi.json").write_text("{}", encoding="utf-8")
    (nifti.parent / "sub-01_dwi.bvec").write_text("0 1\n0 0\n0 0\n", encoding="utf-8")
    (nifti.parent / "sub-01_dwi.bval").write_text("0 1000\n", encoding="utf-8")
    report = ErrorDetector().detect(tmp_path)
    assert any(i.code == "dimension_mismatch" for i in report.issues)


def test_duplicate_outputs(tmp_path: Path) -> None:
    a = tmp_path / "ses-01" / "sub-001_T1w.nii.gz"
    b = tmp_path / "ses-02" / "sub-001_T1w.nii.gz"
    _write_nifti(a)
    _write_nifti(b)
    (a.parent / "sub-001_T1w.json").write_text("{}", encoding="utf-8")
    (b.parent / "sub-001_T1w.json").write_text("{}", encoding="utf-8")
    report = ErrorDetector().detect(tmp_path)
    assert any(i.code == "duplicate_output" for i in report.issues)


def test_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "anat" / "empty.nii.gz"
    empty.parent.mkdir(parents=True)
    empty.write_bytes(b"")
    report = ErrorDetector().detect(tmp_path)
    assert any(i.code == "empty_file" for i in report.issues)
    assert report.status == QCStatus.FAIL


def test_corrupt_nifti(tmp_path: Path) -> None:
    bad = tmp_path / "anat" / "bad.nii.gz"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not-a-nifti")
    report = ErrorDetector().detect(tmp_path)
    assert any(i.code == "corrupt_nifti" for i in report.issues)


def test_pass_clean_anat(tmp_path: Path) -> None:
    nifti = tmp_path / "anat" / "sub-01_T1w.nii.gz"
    _write_nifti(nifti)
    (nifti.parent / "sub-01_T1w.json").write_text("{}", encoding="utf-8")
    report = ErrorDetector().detect(tmp_path)
    assert report.status == QCStatus.PASS
    assert report.warnings == 0
    assert report.failures == 0
