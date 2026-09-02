"""Dataset-specific Curation Rules: deterministic, inspectable, reversible."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot import (
    ChangeSet,
    ChangeSetStatus,
    CopilotAgent,
    CopilotSession,
    FakeLLMProvider,
    default_registry,
)
from neuro_pipeline.neurobids.copilot.llm.validation import (
    ToolArgumentValidationError,
    validate_tool_arguments,
)
from neuro_pipeline.neurobids.curation import (
    CurationRule,
    CurationRuleEngine,
    CurationRuleError,
    CurationRuleStore,
    RuleAction,
    RuleCondition,
    RulePredicate,
    propose_rule_from_changeset,
    validate_rule,
)


def _series(
    description: str,
    *,
    seq: str = "anat",
    fine: str = "ANAT_T1",
    patient_id: str = "SUBA",
    series_number: int = 1,
    uid: str = "",
) -> DicomSeries:
    root = Path("synthetic_dicom") / patient_id
    return DicomSeries(
        patient_id=patient_id,
        study_description="Study",
        series_description=description,
        protocol_name=description,
        series_number=series_number,
        acquisition_number=1,
        modality="MR",
        num_images=10,
        source_dir=root,
        sample_file=root / "img.dcm",
        status=SeriesStatus.PENDING,
        sequence_type=seq,
        fine_sequence_type=fine,
        smart_name=description,
        series_instance_uid=uid or f"uid.{patient_id}.{series_number}",
        study_instance_uid="uid.study",
        sequence_confidence=0.85,
        source_subject_folder=str(root),
    )


@pytest.fixture
def session(tmp_path: Path) -> CopilotSession:
    dicom_root = tmp_path / "dicom"
    dicom_root.mkdir()
    for pid in ("patient_A", "patient_B"):
        d = dicom_root / pid
        d.mkdir()
        (d / "img.dcm").write_bytes(b"SYNTHETIC_DICOM_BYTES")
    series = [
        _series("t1_mprage", patient_id="patient_A", uid="uid-a-t1", series_number=1),
        _series(
            "rest_AP",
            seq="func",
            fine="FMRI_REST",
            patient_id="patient_A",
            uid="uid-a-rest",
            series_number=2,
        ),
        _series("t1_mprage", patient_id="patient_B", uid="uid-b-t1", series_number=1),
        _series(
            "rest_AP",
            seq="func",
            fine="FMRI_REST",
            patient_id="patient_B",
            uid="uid-b-rest",
            series_number=2,
        ),
    ]
    for s in series:
        s.source_dir = dicom_root / s.patient_id
        s.sample_file = s.source_dir / "img.dcm"
        s.source_subject_folder = str(s.source_dir)
    plan = BIDSConversionPlan.from_series(
        series,
        dataset_root=dicom_root,
        output_root=tmp_path / "bids_out",
        session_override="01",
    )
    return CopilotSession(
        plan=plan,
        series_list=series,
        detection_method="patient_id",
        n_dicom_files=4,
        curation_rules_path=tmp_path / "curation_rules.json",
    )


@pytest.fixture
def registry():
    return default_registry()


def _mtime_map(root: Path) -> dict[str, int]:
    return {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_rule_contains_required_fields() -> None:
    rule = CurationRule(
        condition=RuleCondition(
            all_of=[RulePredicate("series_description", "equals", "rest_AP")]
        ),
        action=RuleAction.from_dict({"task": "rest"}),
        evidence=["example"],
        confidence=0.8,
    )
    payload = rule.to_dict()
    for key in (
        "id",
        "condition",
        "action",
        "evidence",
        "confidence",
        "provenance",
        "enabled",
        "version",
    ):
        assert key in payload
    assert payload["enabled"] is True
    assert payload["version"] == 1
    assert payload["condition"]["all_of"][0]["field"] == "series_description"


def test_rejects_executable_payload_keys() -> None:
    with pytest.raises(CurationRuleError, match="executable"):
        CurationRule.from_dict(
            {
                "condition": {
                    "all_of": [{"field": "series_description", "op": "equals", "value": "x"}]
                },
                "action": {"task": "rest"},
                "code": "os.system('rm -rf /')",
            }
        )
    with pytest.raises(CurationRuleError, match="executable"):
        RuleCondition.from_dict({"all_of": [], "eval": "1+1"})
    with pytest.raises(CurationRuleError, match="executable"):
        RuleAction.from_dict({"python": "print(1)"})


def test_rejects_unknown_condition_field_and_bad_regex() -> None:
    with pytest.raises(CurationRuleError, match="Unsupported condition field"):
        RulePredicate.from_dict({"field": "patient_name", "op": "equals", "value": "x"})
    with pytest.raises(CurationRuleError, match="Unsupported operator"):
        RulePredicate.from_dict({"field": "series_description", "op": "eval", "value": ".*"})
    rule = CurationRule(
        condition=RuleCondition(all_of=[RulePredicate("series_description", "regex", "(")]),
        action=RuleAction.from_dict({"task": "rest"}),
    )
    result = validate_rule(rule)
    assert result.ok is False
    assert any("regex" in i.message.lower() for i in result.issues)


def test_engine_is_deterministic_and_fail_closed(session: CopilotSession) -> None:
    engine = CurationRuleEngine()
    empty = CurationRule(
        condition=RuleCondition(all_of=[]),
        action=RuleAction.from_dict({"task": "rest"}),
        enabled=True,
    )
    item = session.plan.get("uid-a-rest")
    assert item is not None
    series = session.series_by_uid()["uid-a-rest"]
    assert engine.match_item([empty], item, series) is None

    rule = CurationRule(
        condition=RuleCondition(
            all_of=[RulePredicate("series_description", "equals", "rest_AP")]
        ),
        action=RuleAction.from_dict({"task": "rest"}),
        enabled=True,
    )
    disabled = rule.clone()
    disabled.enabled = False
    assert engine.match_item([disabled], item, series) is None
    assert engine.match_item([rule], item, series) is rule
    t1 = session.plan.get("uid-a-t1")
    assert engine.match_item([rule], t1, session.series_by_uid()["uid-a-t1"]) is None


def test_propose_from_approved_decision_then_save_on_apply(
    session: CopilotSession, registry
) -> None:
    dicom_root = Path(session.plan.dataset_root)
    before = _mtime_map(dicom_root)

    edit = registry.execute(
        "apply_edit",
        session,
        {"series_uid": "uid-a-rest", "run": "07", "reason": "Assign run-07 to REST"},
    )
    assert edit.ok
    cs: ChangeSet = edit.data["changeset"]
    cs.validate(session.plan, rule_store=session.curation_store())
    cs.approve()
    cs.apply(session.plan, rule_store=session.curation_store())
    session.last_applied_changeset = cs
    assert session.plan.get("uid-a-rest").run == "07"
    assert session.curation_store().rules == []

    proposed = registry.execute(
        "propose_curation_rule",
        session,
        {"from_approved_decision": True, "reason": "Reuse REST mapping"},
    )
    assert proposed.ok, proposed.error
    rule_cs: ChangeSet = proposed.data["changeset"]
    assert rule_cs.status == ChangeSetStatus.DRAFT
    assert rule_cs.rule_catalog_op in {"save", "replace"}
    rule = rule_cs.proposed_rule
    assert rule is not None
    assert rule.condition.all_of
    assert rule.action.mapping.get("run") == "07"
    assert 0.0 <= rule.confidence <= 1.0
    assert rule.evidence
    assert rule.provenance.changeset_id == cs.id
    assert session.curation_store().rules == []

    rule_cs.validate(session.plan, rule_store=session.curation_store())
    rule_cs.approve()
    rule_cs.apply(session.plan, rule_store=session.curation_store())
    saved = session.curation_store().rules
    assert len(saved) == 1
    assert saved[0].version == 1
    assert saved[0].enabled is True
    assert saved[0].provenance.approved_at
    assert session.curation_store().path.is_file()
    assert session.plan.get("uid-b-rest").run == "07"
    assert _mtime_map(dicom_root) == before


def test_rule_apply_is_changeset_only_and_reversible(
    session: CopilotSession, registry
) -> None:
    rule = CurationRule(
        condition=RuleCondition(
            all_of=[RulePredicate("series_description", "equals", "t1_mprage")]
        ),
        action=RuleAction.from_dict({"run": "09"}),
        evidence=["manual"],
        confidence=0.9,
    )
    session.curation_store().upsert(rule)
    before_run = {i.source_series_uid: i.run for i in session.plan.items}

    result = registry.execute("apply_curation_rules", session, {})
    assert result.ok, result.error
    cs: ChangeSet = result.data["changeset"]
    assert cs.status == ChangeSetStatus.DRAFT
    for item in session.plan.items:
        assert item.run == before_run[item.source_series_uid]

    cs.validate(session.plan, rule_store=session.curation_store())
    cs.apply(session.plan, rule_store=session.curation_store())
    for uid in ("uid-a-t1", "uid-b-t1"):
        assert session.plan.get(uid).run == "09"
    cs.rollback(session.plan, rule_store=session.curation_store())
    for item in session.plan.items:
        assert item.run == before_run[item.source_series_uid]


def test_disable_rule_is_reversible(session: CopilotSession, registry) -> None:
    rule = CurationRule(
        condition=RuleCondition(
            all_of=[RulePredicate("series_description", "equals", "rest_AP")]
        ),
        action=RuleAction.from_dict({"task": "rest"}),
        enabled=True,
    )
    saved = session.curation_store().upsert(rule)
    result = registry.execute(
        "set_curation_rule_enabled",
        session,
        {"rule_id": saved.id, "enabled": False},
    )
    assert result.ok, result.error
    cs: ChangeSet = result.data["changeset"]
    assert session.curation_store().get(saved.id).enabled is True
    cs.validate(session.plan, rule_store=session.curation_store())
    cs.approve()
    cs.apply(session.plan, rule_store=session.curation_store())
    assert session.curation_store().get(saved.id).enabled is False
    cs.rollback(session.plan, rule_store=session.curation_store())
    assert session.curation_store().get(saved.id).enabled is True


def test_dataset_isolation(session: CopilotSession, tmp_path: Path) -> None:
    rule = CurationRule(
        condition=RuleCondition(
            all_of=[RulePredicate("protocol_name", "equals", "rest_AP")]
        ),
        action=RuleAction.from_dict({"task": "rest"}),
    )
    session.curation_store().upsert(rule)
    other = CurationRuleStore.for_dataset(
        tmp_path / "other_dataset",
        path=tmp_path / "other_rules.json",
    )
    assert other.dataset_id != session.curation_store().dataset_id
    assert other.rules == []


def test_llm_cannot_pass_code_or_apply_rules(session: CopilotSession) -> None:
    registry = default_registry()
    propose = registry.get("propose_curation_rule")
    assert propose is not None
    with pytest.raises(ToolArgumentValidationError, match="unexpected property"):
        validate_tool_arguments(
            propose.input_schema,
            {
                "condition": {
                    "all_of": [{"field": "series_description", "op": "equals", "value": "x"}]
                },
                "action": {"task": "rest"},
                "code": "exec('print(1)')",
            },
        )

    provider = FakeLLMProvider(
        [{"type": "tool_call", "tool_name": "exec_rule", "arguments": {"code": "1+1"}}]
    )
    result = CopilotAgent(session=session, provider=provider, registry=registry).handle(
        "Run this rule: print(1)"
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code in {"forbidden_tool", "invalid_tool_name"}
    assert session.curation_store().rules == []


def test_propose_curation_rule_does_not_auto_apply(session: CopilotSession) -> None:
    provider = FakeLLMProvider(
        [
            {
                "type": "tool_call",
                "tool_name": "propose_curation_rule",
                "arguments": {
                    "from_approved_decision": False,
                    "condition": {
                        "all_of": [
                            {"field": "series_description", "op": "equals", "value": "rest_AP"}
                        ]
                    },
                    "action": {"run": "04"},
                },
            }
        ]
    )
    before_run = session.plan.get("uid-a-rest").run
    result = CopilotAgent(session=session, provider=provider).handle(
        "Save a rule that maps rest_AP to run 04."
    )
    assert result.ok
    assert result.stopped_reason == "awaiting_approval"
    assert result.changeset is not None
    assert result.changeset.status != ChangeSetStatus.APPLIED
    assert session.curation_store().rules == []
    assert session.plan.get("uid-a-rest").run == before_run


def test_list_and_inspect_rules(session: CopilotSession, registry) -> None:
    listed = registry.execute("list_curation_rules", session, {})
    assert listed.ok
    assert listed.data["n_rules"] == 0
    rule = CurationRule(
        condition=RuleCondition(
            all_of=[RulePredicate("series_description", "equals", "rest_AP")]
        ),
        action=RuleAction.from_dict({"task": "rest"}),
        evidence=["unit-test"],
        confidence=0.7,
    )
    saved = session.curation_store().upsert(rule)
    listed = registry.execute("list_curation_rules", session, {})
    assert listed.data["n_rules"] == 1
    inspected = registry.execute("inspect_curation_rule", session, {"rule_id": saved.id})
    assert inspected.ok
    payload = inspected.data["rule"]
    assert payload["id"] == saved.id
    assert payload["evidence"] == ["unit-test"]


def test_subject_rename_does_not_become_a_mapping_rule(
    session: CopilotSession, registry
) -> None:
    result = registry.execute("rename_subjects", session, {"mode": "sequential", "start": 1})
    cs: ChangeSet = result.data["changeset"]
    cs.validate(session.plan)
    cs.apply(session.plan)
    session.last_applied_changeset = cs
    proposed = registry.execute("propose_curation_rule", session, {"from_approved_decision": True})
    assert proposed.ok is False
    assert "reusable mapping" in proposed.error.lower() or "cannot propose" in proposed.error.lower()


def test_rule_rollback_unsaves_new_rule(session: CopilotSession, registry) -> None:
    result = registry.execute(
        "propose_curation_rule",
        session,
        {
            "from_approved_decision": False,
            "condition": {
                "all_of": [{"field": "series_description", "op": "equals", "value": "rest_AP"}]
            },
            "action": {"task": "rest"},
        },
    )
    cs: ChangeSet = result.data["changeset"]
    cs.validate(session.plan, rule_store=session.curation_store())
    cs.approve()
    cs.apply(session.plan, rule_store=session.curation_store())
    assert session.curation_store().rules
    cs.rollback(session.plan, rule_store=session.curation_store())
    assert session.curation_store().rules == []


def test_generalize_from_changeset_uses_description_not_uid(
    session: CopilotSession, registry
) -> None:
    result = registry.execute(
        "apply_edit",
        session,
        {"series_uid": "uid-a-rest", "task": "movie"},
    )
    cs: ChangeSet = result.data["changeset"]
    rule = propose_rule_from_changeset(
        cs,
        items=session.plan.items,
        series_by_uid=session.series_by_uid(),
        dataset_id="test",
    )
    fields = {p.field for p in rule.condition.all_of}
    assert "series_description" in fields or "protocol_name" in fields
    assert rule.action.mapping.get("task") == "movie"
    assert "uid-a-rest" not in str(rule.condition.to_dict())
