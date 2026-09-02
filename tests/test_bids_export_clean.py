"""Clean BIDS export naming tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.bids.exporter import BIDSExporter
from neuro_pipeline.bids.naming import build_bids_target
from neuro_pipeline.models import ConversionResult, DicomSeries, SeriesStatus
from neuro_pipeline.utils.exceptions import NeuroPipelineError


def _series(description: str, seq: str, **kwargs: object) -> DicomSeries:
    root = Path("fake")
    return DicomSeries(
        patient_id=str(kwargs.get("patient_id", "IGNORE")),
        study_description="S",
        series_description=description,
        protocol_name=description,
        series_number=1,
        acquisition_number=1,
        modality="MR",
        num_images=10,
        source_dir=root,
        sample_file=root / "x.dcm",
        status=SeriesStatus.DONE,
        sequence_type=seq,
        smart_name=description,
    )


def _bundle(folder: Path, stem: str, *, bval: bool = False) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    nii = folder / f"{stem}.nii.gz"
    nii.write_bytes(b"nii")
    js = folder / f"{stem}.json"
    js.write_text("{}", encoding="utf-8")
    files = [nii, js]
    if bval:
        (folder / f"{stem}.bval").write_text("0 1000\n", encoding="utf-8")
        (folder / f"{stem}.bvec").write_text("0 1\n0 0\n0 0\n", encoding="utf-8")
        files.extend([folder / f"{stem}.bval", folder / f"{stem}.bvec"])
    return files


def test_t1_clean_names(tmp_path: Path) -> None:
    series = _series("t1_mprage", "anat")
    files = _bundle(tmp_path / "stg", "T1w")
    BIDSExporter(tmp_path / "bids", subject_id="001").export(
        [ConversionResult(series=series, success=True, output_files=files)]
    )
    dest = tmp_path / "bids" / "sub-001" / "anat" / "sub-001_T1w.nii.gz"
    assert dest.exists()
    assert dest.with_suffix("").with_suffix(".json").exists() or (
        tmp_path / "bids" / "sub-001" / "anat" / "sub-001_T1w.json"
    ).exists()


def test_dwi_acq_names(tmp_path: Path) -> None:
    series = _series("ep2d_diff_4scan_trace", "dwi")
    files = _bundle(tmp_path / "stg", "DWI", bval=True)
    BIDSExporter(tmp_path / "bids", subject_id="001").export(
        [ConversionResult(series=series, success=True, output_files=files)]
    )
    dwi = list((tmp_path / "bids" / "sub-001" / "dwi").glob("*_dwi.nii.gz"))
    assert len(dwi) == 1
    assert "acq-" in dwi[0].name
    stem = dwi[0].name[: -len(".nii.gz")]
    assert (dwi[0].parent / f"{stem}.bval").exists()
    assert (dwi[0].parent / f"{stem}.bvec").exists()


def test_func_and_fmap_names() -> None:
    func = build_bids_target(_series("bold_rest", "func"), "001")
    assert func is not None
    assert func.filename_stem == "sub-001_task-rest_bold"
    fmap = build_bids_target(_series("se_epi_AP", "fmap"), "001")
    assert fmap is not None
    assert fmap.filename_stem.startswith("sub-001_dir-")
    assert fmap.filename_stem.endswith("_epi")


def test_subject_id_required(tmp_path: Path) -> None:
    series = _series("t1_mprage", "anat")
    files = _bundle(tmp_path / "stg", "T1w")
    with pytest.raises(NeuroPipelineError):
        BIDSExporter(tmp_path / "bids").export(
            [ConversionResult(series=series, success=True, output_files=files)]
        )


def test_never_uses_folder_patient_name(tmp_path: Path) -> None:
    series = _series("t1_mprage", "anat", patient_id="MonkeyCoil")
    files = _bundle(tmp_path / "stg", "T1w")
    BIDSExporter(tmp_path / "bids", subject_id="001").export(
        [ConversionResult(series=series, success=True, output_files=files)]
    )
    assert (tmp_path / "bids" / "sub-001").is_dir()
    assert not (tmp_path / "bids" / "sub-MonkeyCoil").exists()
    assert not list((tmp_path / "bids").rglob("*unknown*"))
