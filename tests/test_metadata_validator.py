"""Tests for advanced BIDS metadata validation (synthetic JSON only)."""

from __future__ import annotations

import json
from pathlib import Path

from neuro_pipeline.bids.metadata_validator import MetadataStatus, MetadataValidator


def test_validate_anat_pass(tmp_path: Path) -> None:
    path = tmp_path / "sub-01_T1w.json"
    path.write_text(
        json.dumps(
            {
                "MagneticFieldStrength": 3,
                "Manufacturer": "SyntheticVendor",
                "SequenceName": "tfl3d1",
            }
        ),
        encoding="utf-8",
    )
    result = MetadataValidator().validate_file(path)
    assert result.status == MetadataStatus.PASS
    assert result.missing_fields == []


def test_validate_anat_missing_fields() -> None:
    result = MetadataValidator().validate_anat({"Manufacturer": "X"})
    assert result.status == MetadataStatus.WARNING
    assert "MagneticFieldStrength" in result.missing_fields
    assert "SequenceName" in result.missing_fields


def test_validate_func_requires_tr_task() -> None:
    result = MetadataValidator().validate_func({"RepetitionTime": 2.0})
    assert result.status == MetadataStatus.WARNING
    assert "TaskName" in result.missing_fields


def test_validate_fmap_pass() -> None:
    result = MetadataValidator().validate_fmap(
        {"EchoTime": 0.005, "PhaseEncodingDirection": "j-"}
    )
    assert result.status == MetadataStatus.PASS


def test_validate_dwi_missing_bvec(tmp_path: Path) -> None:
    dwi_dir = tmp_path / "dwi"
    dwi_dir.mkdir()
    json_path = dwi_dir / "sub-01_dwi.json"
    json_path.write_text(
        json.dumps({"DiffusionGradientOrientation": [[1, 0, 0]]}),
        encoding="utf-8",
    )
    (dwi_dir / "sub-01_dwi.bval").write_text("0 1000\n", encoding="utf-8")
    result = MetadataValidator().validate_dwi(
        {"DiffusionGradientOrientation": [[1, 0, 0]]},
        path=json_path,
    )
    assert "bvec" in result.missing_fields
    assert result.status in {MetadataStatus.WARNING, MetadataStatus.FAIL}


def test_html_report(tmp_path: Path) -> None:
    validator = MetadataValidator()
    results = [
        validator.validate_anat(
            {
                "MagneticFieldStrength": 3,
                "Manufacturer": "X",
                "SequenceName": "y",
            },
            path=tmp_path / "T1w.json",
        ),
        validator.validate_dwi({}, path=tmp_path / "DWI.json"),
    ]
    report = validator.write_html_report(results, tmp_path)
    assert report.name == "metadata_validation_report.html"
    text = report.read_text(encoding="utf-8")
    assert "PASS" in text
    assert "DWI.json" in text
