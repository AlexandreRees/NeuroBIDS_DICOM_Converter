"""Tests for SmartNamingRulesEngine."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.bids.naming_rules import NamingRule, SmartNamingRulesEngine
from neuro_pipeline.models import DicomSeries, SeriesStatus


def _series(description: str, *, protocol: str = "", seq: str = "func", uid: str = "u1") -> DicomSeries:
    root = Path("fake")
    return DicomSeries(
        patient_id="SUB001",
        study_description="S",
        series_description=description,
        protocol_name=protocol or description,
        series_number=1,
        acquisition_number=1,
        modality="MR",
        num_images=10,
        source_dir=root,
        sample_file=root / "x.dcm",
        status=SeriesStatus.PENDING,
        sequence_type=seq,
        fine_sequence_type="FMRI_REST",
        smart_name=description,
        series_instance_uid=uid,
    )


def test_rule_modifies_bids_entities() -> None:
    engine = SmartNamingRulesEngine(
        [
            NamingRule(
                name="REST Siemens AP rule",
                priority=10,
                conditions={"ProtocolName_contains": "REST_AP"},
                actions={"task": "rest", "datatype": "func", "suffix": "bold"},
            )
        ]
    )
    series = _series("bold", protocol="REST_AP_MB")
    match = engine.match(series)
    assert match is not None
    assert match.rule.name == "REST Siemens AP rule"
    assert match.actions["task"] == "rest"
    merged, name = engine.apply_to_entities(series, {"datatype": "anat", "suffix": "T1w"})
    assert name == "REST Siemens AP rule"
    assert merged["datatype"] == "func"
    assert merged["task"] == "rest"

    plan = BIDSConversionPlan.from_series(
        [series],
        subject_override="001",
        naming_rules=engine,
    )
    item = plan.get("u1")
    assert item is not None
    assert item.naming_rule_applied == "REST Siemens AP rule"
    assert item.task == "rest"
    assert item.datatype == "func"


def test_disabled_rules_ignored() -> None:
    engine = SmartNamingRulesEngine(
        [
            NamingRule(
                name="disabled",
                enabled=False,
                priority=1,
                conditions={"ProtocolName_contains": "REST"},
                actions={"task": "rest", "datatype": "func", "suffix": "bold"},
            )
        ]
    )
    assert engine.match(_series("x", protocol="REST_AP")) is None


def test_higher_priority_overrides() -> None:
    engine = SmartNamingRulesEngine(
        [
            NamingRule(
                name="low",
                priority=50,
                conditions={"SeriesDescription_contains": "REST"},
                actions={"task": "other", "datatype": "func", "suffix": "bold"},
            ),
            NamingRule(
                name="high",
                priority=5,
                conditions={"SeriesDescription_contains": "REST"},
                actions={"task": "rest", "datatype": "func", "suffix": "bold"},
            ),
        ]
    )
    match = engine.match(_series("REST_EPI"))
    assert match is not None
    assert match.rule.name == "high"
    assert match.actions["task"] == "rest"


def test_invalid_rules_rejected() -> None:
    engine = SmartNamingRulesEngine(
        [
            NamingRule(
                name="bad",
                priority=10,
                conditions={"ProtocolName_contains": "REST"},
                actions={"datatype": "not-a-type", "task": "rest!!"},
            ),
            NamingRule(
                name="dupA",
                priority=20,
                conditions={"ProtocolName_contains": "X"},
                actions={"task": "rest", "datatype": "func", "suffix": "bold"},
            ),
            NamingRule(
                name="dupB",
                priority=20,
                conditions={"ProtocolName_contains": "Y"},
                actions={"task": "movie", "datatype": "func", "suffix": "bold"},
            ),
        ]
    )
    result = engine.validate()
    assert not result.ok
    text = result.summary().lower()
    assert "duplicate priority" in text or "invalid" in text


def test_empty_engine_preserves_backward_compat() -> None:
    series = _series("t1_mprage", protocol="t1_mprage", seq="anat", uid="t1")
    series.fine_sequence_type = "ANAT_T1"
    plan = BIDSConversionPlan.from_series(
        [series],
        subject_override="001",
        naming_rules=SmartNamingRulesEngine([]),
    )
    item = plan.get("t1")
    assert item is not None
    assert item.naming_rule_applied == ""
    assert item.datatype == "anat"
