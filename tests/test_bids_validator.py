"""Tests for integrated BIDS validation (synthetic datasets only)."""

from __future__ import annotations

import json
from pathlib import Path

from neuro_pipeline.bids.validator import BIDSValidationStatus, BIDSValidator
from neuro_pipeline.reports.bids_validation_report import BidsValidationReportWriter


def _write_minimal_bids(root: Path, *, with_json: bool = True) -> None:
    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "Synthetic", "BIDSVersion": "1.8.0"}),
        encoding="utf-8",
    )
    (root / "README").write_text("synthetic\n", encoding="utf-8")
    (root / "participants.tsv").write_text(
        "participant_id\tsex\tage\nsub-001\tn/a\tn/a\n",
        encoding="utf-8",
    )
    anat = root / "sub-001" / "anat"
    anat.mkdir(parents=True)
    (anat / "sub-001_T1w.nii.gz").write_bytes(b"fake-nifti")
    if with_json:
        (anat / "sub-001_T1w.json").write_text(
            json.dumps({"Manufacturer": "Siemens", "MagneticFieldStrength": 3}),
            encoding="utf-8",
        )


def test_structural_validator_pass_with_warnings_when_cli_missing(tmp_path: Path) -> None:
    root = tmp_path / "bids"
    root.mkdir()
    _write_minimal_bids(root)
    result = BIDSValidator(bids_validator_path="/nonexistent/bids-validator").validate(root)
    # Official tool missing → structural fallback; may be WARNING due to missing CLI note
    assert result.status in {BIDSValidationStatus.PASS, BIDSValidationStatus.WARNING}
    assert result.errors == []
    assert any("bids-validator executable was not found" in w for w in result.warnings)
    assert result.validator_backend == "structural-fallback"


def test_structural_validator_fails_without_dataset_description(tmp_path: Path) -> None:
    root = tmp_path / "bids"
    anat = root / "sub-001" / "anat"
    anat.mkdir(parents=True)
    (anat / "sub-001_T1w.nii.gz").write_bytes(b"x")
    result = BIDSValidator(bids_validator_path="/nonexistent/bids-validator").validate(root)
    assert result.status == BIDSValidationStatus.FAIL
    assert any("dataset_description.json" in e for e in result.errors)


def test_bids_validation_report_written(tmp_path: Path) -> None:
    root = tmp_path / "bids"
    root.mkdir()
    _write_minimal_bids(root)
    result = BIDSValidator(bids_validator_path="/nonexistent/x").validate(root)
    path = BidsValidationReportWriter(root).write(result)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "BIDS Validation Report" in text
    assert "NeuroPipeline" in text
    assert str(root) in text


def test_session_layout_accepted(tmp_path: Path) -> None:
    root = tmp_path / "bids"
    root.mkdir()
    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "Ses", "BIDSVersion": "1.8.0"}),
        encoding="utf-8",
    )
    (root / "README").write_text("x\n", encoding="utf-8")
    (root / "participants.tsv").write_text(
        "participant_id\tsex\tage\nsub-001\tn/a\tn/a\n", encoding="utf-8"
    )
    anat = root / "sub-001" / "ses-01" / "anat"
    anat.mkdir(parents=True)
    (anat / "sub-001_ses-01_T1w.nii.gz").write_bytes(b"x")
    (anat / "sub-001_ses-01_T1w.json").write_text("{}", encoding="utf-8")
    result = BIDSValidator(bids_validator_path="/nonexistent/x").validate(root)
    assert result.status in {BIDSValidationStatus.PASS, BIDSValidationStatus.WARNING}
    assert not any("No subject" in e for e in result.errors)
