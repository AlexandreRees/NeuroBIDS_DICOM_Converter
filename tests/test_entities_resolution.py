"""Tests for config-driven BIDS entity resolution."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.bids.entities_manager import BIDSEntityResolver
from neuro_pipeline.config.paths import project_root


def test_mprage_resolves_to_anat_t1w() -> None:
    resolver = BIDSEntityResolver(project_root() / "configs" / "bids_entities.yaml")
    resolved = resolver.resolve(probe_text="t1_mprage_sag")
    assert resolved.datatype == "anat"
    assert resolved.suffix == "T1w"


def test_diff_bipolar_protocol_entities() -> None:
    resolver = BIDSEntityResolver(project_root() / "configs" / "bids_entities.yaml")
    resolved = resolver.resolve(
        dicom_metadata={"ProtocolName": "ep2d_diff_4scan_trace_bipolar"}
    )
    data = resolved.to_dict()
    assert data["datatype"] == "dwi"
    assert data["acquisition"] == "4scan"
    assert data["direction"] == "bipolar"
    assert data["suffix"] == "dwi"


def test_user_overrides_win() -> None:
    resolver = BIDSEntityResolver(project_root() / "configs" / "bids_entities.yaml")
    resolved = resolver.resolve(
        probe_text="mprage",
        user_input={"task": "rest", "subject": "001", "session": "01"},
    )
    assert resolved.subject == "001"
    assert resolved.session == "01"
    assert resolved.task == "rest"
    assert resolved.datatype == "anat"


def test_func_rest_pattern() -> None:
    resolver = BIDSEntityResolver(project_root() / "configs" / "bids_entities.yaml")
    resolved = resolver.resolve(probe_text="ep2d_bold_rest_AP")
    assert resolved.datatype == "func"
    assert resolved.suffix == "bold"
    assert resolved.task == "rest"


def test_missing_config_returns_unknown(tmp_path: Path) -> None:
    resolver = BIDSEntityResolver(tmp_path / "missing.yaml")
    resolved = resolver.resolve(probe_text="something_unknown_xyz")
    assert resolved.datatype == "unknown"
