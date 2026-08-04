#!/usr/bin/env python3
"""Unit tests for the BIDS physiology QC pipeline.

Run (Compute Canada)::

    module load scipy-stack
    python -m pytest tests/test_physiology_qc.py -q

Or via the built-in smoke test::

    python code/physiology_qc.py --smoke-test
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

import physiology_qc as pqc  # noqa: E402


def _write_tsv_gz(path: Path, column: str, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as handle:
        handle.write(f"{column}\n")
        for v in values:
            if np.isfinite(v):
                handle.write(f"{float(v):.6f}\n")
            else:
                handle.write("n/a\n")


def test_simple_physio_load(tmp_path: Path) -> None:
    bids = tmp_path / "bids"
    func = bids / "sub-002" / "ses-01" / "func"
    data = np.sin(np.linspace(0, 20, 500))
    tsv = func / "sub-002_ses-01_task-rest_run-01_recording-pulse_physio.tsv.gz"
    _write_tsv_gz(tsv, "cardiac", data)
    (tsv.with_name(tsv.name.replace(".tsv.gz", ".json"))).write_text(
        json.dumps(
            {
                "SamplingFrequency": 50.0,
                "StartTime": -2.0,
                "Columns": ["cardiac"],
                "SiemensChannel": "PULS",
                "StartTimeConfidence": "HIGH",
            }
        ),
        encoding="utf-8",
    )
    records = pqc.load_physio_records(tsv, bids)
    assert len(records) == 1
    rec = records[0]
    assert rec.channel == "cardiac"
    assert rec.recording_type == "pulse"
    assert rec.sampling_frequency == 50.0
    assert rec.signal.size == 500
    assert rec.file_path_relative.startswith("sub-002/")


def test_missing_json(tmp_path: Path) -> None:
    bids = tmp_path / "bids"
    func = bids / "sub-003" / "ses-01" / "func"
    data = np.ones(100)
    tsv = func / "sub-003_ses-01_task-fmri_run-02_recording-respiratory_physio.tsv.gz"
    _write_tsv_gz(tsv, "respiratory", data)
    records = pqc.load_physio_records(tsv, bids)
    assert len(records) == 1
    assert records[0].sampling_frequency is None
    assert records[0].channel == "respiratory"
    sqc = pqc.compute_signal_qc(records[0])
    assert "BAD_SAMPLING" in sqc.flags


def test_trigger_extraction_and_tr() -> None:
    fs = 50.0
    tr = 2.0
    n_vol = 30
    n = int(fs * n_vol * tr)
    trig = np.zeros(n)
    onsets = (np.arange(n_vol) * tr * fs).astype(int)
    trig[onsets] = 1
    rec = pqc.PhysioRecord(
        participant_id="001",
        session_id="01",
        task="rest",
        run="01",
        recording_type="trigger",
        channel="trigger",
        file_path_relative="sub-001/ses-01/func/x_physio.tsv.gz",
        signal=trig,
        sampling_frequency=fs,
        start_time=-1.0,
        metadata={},
    )
    tqc = pqc.compute_trigger_qc(rec, bold_tr=2.0, n_bold_volumes=30)
    assert tqc.trigger_count == 30
    assert tqc.estimated_TR is not None
    assert abs(tqc.estimated_TR - 2.0) < 1e-6
    assert tqc.trigger_status == "PASS"
    assert tqc.TR_relative_diff is not None
    assert tqc.TR_relative_diff < 0.05


def test_flat_signal_detection() -> None:
    rec = pqc.PhysioRecord(
        participant_id="001",
        session_id="01",
        task="rest",
        run="01",
        recording_type="pulse",
        channel="cardiac",
        file_path_relative="sub-001/x.tsv.gz",
        signal=np.full(200, 42.0),
        sampling_frequency=50.0,
        start_time=-1.0,
        metadata={},
    )
    sqc = pqc.compute_signal_qc(rec)
    assert "FLAT_SIGNAL" in sqc.flags
    assert "SATURATION" in sqc.flags
    status = pqc.file_qc_status(sqc, None, "cardiac")
    assert status == "FAIL"


def test_large_gaps() -> None:
    fs = 10.0
    x = np.ones(100)
    x[10:50] = np.nan  # 4 seconds at 10 Hz
    rec = pqc.PhysioRecord(
        participant_id="001",
        session_id="01",
        task="movie",
        run="01",
        recording_type="respiratory",
        channel="respiratory",
        file_path_relative="sub-001/x.tsv.gz",
        signal=x,
        sampling_frequency=fs,
        start_time=-1.0,
        metadata={},
    )
    sqc = pqc.compute_signal_qc(rec)
    assert "LARGE_GAPS" in sqc.flags
    assert sqc.longest_gap_seconds == pytest.approx(4.0)


def test_relative_paths_are_phi_safe(tmp_path: Path) -> None:
    bids = tmp_path / "bids"
    path = bids / "sub-010" / "ses-02" / "func" / "file_physio.tsv.gz"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    rel = pqc.relative_to_bids(path, bids)
    assert "home" not in rel
    assert not rel.startswith("/")
    assert rel == "sub-010/ses-02/func/file_physio.tsv.gz"


def test_smoke_pipeline(tmp_path: Path) -> None:
    pytest.importorskip("nibabel")
    bids = pqc.write_synthetic_bids(tmp_path)
    out = tmp_path / "derivatives" / "physiology_qc"
    stats = pqc.run_pipeline(bids, out, tasks=["rest"], overwrite=True)
    assert stats["n_pass"] >= 1
    assert (out / "physiology_inventory.tsv").is_file()
    assert (out / "physiology_qc_summary.tsv").is_file()
    assert (out / "physiology_qc_summary.json").is_file()
    assert (out / "physio_bold_alignment.tsv").is_file()
    assert (out / "trigger_qc.tsv").is_file()
    assert (out / "starttime_summary.tsv").is_file()
    assert (out / "dataset_physio_summary.png").is_file()
    assert (out / "PHYSIOLOGY_QC_REPORT.md").is_file()
    trig = __import__("pandas").read_csv(out / "trigger_qc.tsv", sep="\t")
    assert int(trig.iloc[0]["trigger_count"]) == 30
    assert abs(float(trig.iloc[0]["estimated_TR"]) - 2.0) < 0.05
