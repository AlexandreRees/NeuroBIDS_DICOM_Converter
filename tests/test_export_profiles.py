"""Tests for clinical / research / archive export profiles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neuro_pipeline.export import ExportProfileManager, get_profile
from neuro_pipeline.export.profiles import PROFILES


def _seed_conversion_output(root: Path) -> None:
    anat = root / "sub-001" / "anat"
    anat.mkdir(parents=True)
    (anat / "sub-001_T1w.nii.gz").write_bytes(b"nii")
    (anat / "sub-001_T1w.json").write_text(
        json.dumps({"Manufacturer": "Siemens", "MagneticFieldStrength": 3}),
        encoding="utf-8",
    )
    (root / "series_metadata").mkdir()
    (root / "series_metadata" / "t1_metadata.json").write_text(
        json.dumps({"patient_id": "SECRET", "scanner": "Siemens Prisma", "TR": 2300}),
        encoding="utf-8",
    )
    (root / "logs").mkdir()
    (root / "logs" / "conversion.log").write_text("ok\n", encoding="utf-8")


def test_profiles_registered() -> None:
    assert set(PROFILES) == {"bids", "clinical", "archive"}
    assert get_profile("bids").label.startswith("Research")
    with pytest.raises(ValueError):
        get_profile("unknown")


def test_bids_profile(tmp_path: Path) -> None:
    src = tmp_path / "in"
    dest = tmp_path / "out"
    _seed_conversion_output(src)
    result = ExportProfileManager().apply(input_dir=src, output_dir=dest, profile="bids")
    assert (dest / "dataset_description.json").exists()
    assert (dest / "participants.tsv").exists()
    assert (dest / "README").exists()
    assert (dest / "sub-001" / "anat" / "sub-001_T1w.nii.gz").exists()
    assert result.profile == "bids"


def test_clinical_strips_patient_id(tmp_path: Path) -> None:
    src = tmp_path / "in"
    dest = tmp_path / "out"
    _seed_conversion_output(src)
    ExportProfileManager().apply(input_dir=src, output_dir=dest, profile="clinical")
    clinical_meta = dest / "nifti" / "metadata_clinical.json"
    assert clinical_meta.exists()
    data = json.loads(clinical_meta.read_text(encoding="utf-8"))
    assert "patient_id" not in data
    assert data.get("scanner") == "Siemens Prisma"
    assert list((dest / "nifti").glob("*.nii.gz"))


def test_archive_writes_checksums(tmp_path: Path) -> None:
    src = tmp_path / "in"
    dest = tmp_path / "out"
    _seed_conversion_output(src)
    result = ExportProfileManager().apply(input_dir=src, output_dir=dest, profile="archive")
    assert (dest / "checksums.sha256").exists()
    assert (dest / "archive_manifest.json").exists()
    assert (dest / "data" / "sub-001" / "anat" / "sub-001_T1w.nii.gz").exists()
    assert (dest / "logs" / "conversion.log").exists()
    assert result.files_written


def test_no_overwrite_dataset_description(tmp_path: Path) -> None:
    src = tmp_path / "in"
    dest = tmp_path / "out"
    _seed_conversion_output(src)
    dest.mkdir()
    (dest / "dataset_description.json").write_text('{"Name": "Keep"}\n', encoding="utf-8")
    result = ExportProfileManager().apply(input_dir=src, output_dir=dest, profile="bids")
    data = json.loads((dest / "dataset_description.json").read_text(encoding="utf-8"))
    assert data["Name"] == "Keep"
    assert "dataset_description.json" in result.skipped
