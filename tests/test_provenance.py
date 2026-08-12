"""Tests for conversion provenance and hashing."""

from __future__ import annotations

import json
from pathlib import Path

from neuro_pipeline.provenance.hash_manager import HashManager
from neuro_pipeline.provenance.conversion_provenance import ProvenanceRecorder


def test_hash_file_stable(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")
    h1 = HashManager().hash_file(path)
    h2 = HashManager().hash_file(path)
    assert h1 == h2
    assert len(h1) == 64


def test_hash_folder_aggregate(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    digest, records = HashManager().hash_folder(tmp_path)
    assert digest
    assert len(records) == 2
    assert {r["path"] for r in records} == {"a.txt", "b.txt"}


def test_provenance_written_under_derivatives(tmp_path: Path) -> None:
    source = tmp_path / "dicom"
    source.mkdir()
    (source / "img.dcm").write_bytes(b"dicom-bytes")
    out = tmp_path / "out"
    out.mkdir()
    (out / "sub-001_T1w.nii.gz").write_bytes(b"nifti")

    recorder = ProvenanceRecorder()
    input_hash = recorder.hash_input(source)
    # Mutating source after hash must not happen in app; here we only check write
    path = recorder.write(
        dataset_or_output_root=out,
        input_path=source,
        input_hash=input_hash,
        dcm2niix_version="v1.test",
        parameters={"compress": True},
    )
    assert path == out / "derivatives" / "neuro_pipeline" / "conversion_provenance.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["software"]["name"] == "NeuroPipeline"
    assert data["input"]["hash"] == input_hash.hash
    assert data["output"]["hash"]
    assert data["conversion"]["dcm2niix_version"] == "v1.test"
    manifest = out / "derivatives" / "neuro_pipeline" / "conversion_manifest.json"
    assert manifest.exists()
    # Source unchanged
    assert (source / "img.dcm").read_bytes() == b"dicom-bytes"
