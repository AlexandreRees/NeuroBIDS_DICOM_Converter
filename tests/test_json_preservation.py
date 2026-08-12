"""Tests for dcm2niix JSON sidecar preservation."""

from __future__ import annotations

import json
from pathlib import Path

from neuro_pipeline.metadata.sidecar_manager import MetadataManager


def test_collect_and_validate_sidecar(tmp_path: Path) -> None:
    nii = tmp_path / "sub-001_T1w.nii.gz"
    js = tmp_path / "sub-001_T1w.json"
    nii.write_bytes(b"nii")
    js.write_text(
        json.dumps(
            {
                "Manufacturer": "Siemens",
                "ManufacturersModelName": "Prisma",
                "MagneticFieldStrength": 3.0,
                "SequenceName": "*tfl3d1_16ns",
                "ProtocolName": "MPRAGE",
                "RepetitionTime": 2.3,
                "EchoTime": 0.00298,
            }
        ),
        encoding="utf-8",
    )
    mgr = MetadataManager()
    infos = mgr.collect_sidecars(tmp_path)
    assert len(infos) == 1
    assert infos[0].manufacturer == "Siemens"
    assert infos[0].field_strength == "3T"
    assert "Manufacturer" in infos[0].present_fields
    assert infos[0].missing_fields == []


def test_optional_fields_missing_do_not_crash(tmp_path: Path) -> None:
    js = tmp_path / "x.json"
    js.write_text(json.dumps({"ProtocolName": "T1"}), encoding="utf-8")
    info = MetadataManager().validate_sidecar(js)
    assert "RepetitionTime" in info.missing_fields
    assert any("Optional field missing" in m for m in info.messages)


def test_copy_sidecar_no_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "a.json"
    dest = tmp_path / "out" / "a.json"
    src.write_text('{"Manufacturer": "Siemens"}', encoding="utf-8")
    dest.parent.mkdir()
    dest.write_text('{"Manufacturer": "GE"}', encoding="utf-8")
    out = MetadataManager().copy_sidecar(src, dest)
    assert out == dest
    assert dest.read_text(encoding="utf-8") == '{"Manufacturer": "GE"}'


def test_ensure_reports_missing_json(tmp_path: Path) -> None:
    (tmp_path / "sub-001_T1w.nii.gz").write_bytes(b"x")
    summary = MetadataManager().ensure_sidecars_for_niftis(tmp_path)
    assert summary.missing_json_for
    assert summary.scanner == "Unknown"


def test_metadata_summary_scanner_fields(tmp_path: Path) -> None:
    (tmp_path / "a.nii.gz").write_bytes(b"x")
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "Manufacturer": "Siemens",
                "ManufacturersModelName": "Prisma",
                "MagneticFieldStrength": 3,
                "SequenceName": "MPRAGE",
            }
        ),
        encoding="utf-8",
    )
    summary = MetadataManager().summarize(tmp_path)
    assert "Siemens" in summary.scanner
    assert summary.field_strength == "3T"
    assert summary.sequence == "MPRAGE"
