"""Tests for optional BIDS export."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.bids.exporter import BIDSExporter
from neuro_pipeline.bids.naming import build_bids_target, subject_id_from_series
from neuro_pipeline.models import ConversionResult, DicomSeries, SeriesStatus


def _series(
    *,
    patient_id: str = "01",
    description: str,
    sequence_type: str,
    smart_name: str = "",
) -> DicomSeries:
    root = Path("fake")
    return DicomSeries(
        patient_id=patient_id,
        study_description="Study",
        series_description=description,
        protocol_name=description,
        series_number=1,
        acquisition_number=1,
        modality="MR",
        num_images=10,
        source_dir=root,
        sample_file=root / "x.dcm",
        status=SeriesStatus.DONE,
        sequence_type=sequence_type,
        smart_name=smart_name or description,
    )


def _touch_nifti_bundle(folder: Path, stem: str, *, with_bval: bool = False) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    nii = folder / f"{stem}.nii.gz"
    nii.write_bytes(b"nifti-bytes")
    files = [nii]
    js = folder / f"{stem}.json"
    js.write_text('{"SeriesDescription": "x"}', encoding="utf-8")
    files.append(js)
    if with_bval:
        bval = folder / f"{stem}.bval"
        bvec = folder / f"{stem}.bvec"
        bval.write_text("0 1000\n", encoding="utf-8")
        bvec.write_text("0 1\n0 0\n0 0\n", encoding="utf-8")
        files.extend([bval, bvec])
    return files


def test_t1_conversion_produces_bids_anat_path(tmp_path: Path) -> None:
    series = _series(description="t1_mprage_sag", sequence_type="anat", smart_name="T1w")
    assert subject_id_from_series(series) == "01"
    target = build_bids_target(series, "01")
    assert target is not None
    assert target.datatype == "anat"
    assert target.filename_stem == "sub-01_T1w"

    staging = tmp_path / "staging"
    files = _touch_nifti_bundle(staging, "T1w")
    result = ConversionResult(series=series, success=True, output_files=files)
    export = BIDSExporter(tmp_path / "bids", subject_id="01").export([result])

    dest = tmp_path / "bids" / "sub-01" / "anat" / "sub-01_T1w.nii.gz"
    assert dest.exists()
    assert (tmp_path / "bids" / "sub-01" / "anat" / "sub-01_T1w.json").exists()
    assert export.exported == 1
    assert (tmp_path / "bids" / "dataset_description.json").exists()
    assert (tmp_path / "bids" / "participants.tsv").exists()
    assert (tmp_path / "bids" / "README").exists()


def test_dwi_preserves_bval_bvec(tmp_path: Path) -> None:
    series = _series(
        description="ep2d_diff_4scan_trace",
        sequence_type="dwi",
        smart_name="DWI",
    )
    staging = tmp_path / "staging"
    files = _touch_nifti_bundle(staging, "DWI", with_bval=True)
    result = ConversionResult(series=series, success=True, output_files=files)
    BIDSExporter(tmp_path / "bids", subject_id="01").export([result])

    dwi_dir = tmp_path / "bids" / "sub-01" / "dwi"
    niftis = list(dwi_dir.glob("*_dwi.nii.gz"))
    assert len(niftis) == 1
    stem = niftis[0].name[: -len(".nii.gz")]
    assert (dwi_dir / f"{stem}.bval").exists()
    assert (dwi_dir / f"{stem}.bvec").exists()
    assert (dwi_dir / f"{stem}.json").exists()


def test_existing_files_are_protected(tmp_path: Path) -> None:
    series = _series(description="t1_mprage", sequence_type="anat")
    bids = tmp_path / "bids"
    dest_dir = bids / "sub-01" / "anat"
    dest_dir.mkdir(parents=True)
    existing = dest_dir / "sub-01_T1w.nii.gz"
    existing.write_text("original-content", encoding="utf-8")

    staging = tmp_path / "staging"
    files = _touch_nifti_bundle(staging, "T1w")
    # Make staging content different
    files[0].write_text("new-content", encoding="utf-8")
    result = ConversionResult(series=series, success=True, output_files=files)
    export = BIDSExporter(bids, subject_id="01").export([result])

    # Original must be untouched; exporter either skips exact path or uses run- disambiguation
    assert existing.read_text(encoding="utf-8") == "original-content"
    assert export.skipped >= 1 or any(
        p.name != "sub-01_T1w.nii.gz" for p in dest_dir.glob("*.nii.gz")
    )
    # Never overwrite the original bytes
    assert existing.read_text(encoding="utf-8") == "original-content"
