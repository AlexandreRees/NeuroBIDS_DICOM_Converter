"""Persistent Copilot provenance logging tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot import ChangeSetStatus, CopilotAgent, CopilotSession
from neuro_pipeline.neurobids.copilot.llm.provider import FakeLLMProvider
from neuro_pipeline.neurobids.copilot.provenance import (
    PROVENANCE_SCHEMA_VERSION,
    CopilotProvenanceStore,
    sanitize_for_provenance,
)
from neuro_pipeline.neurobids.copilot.provenance.schema import RECORD_DECISION, RECORD_TURN


def _series(patient_id: str, uid: str, n: int = 1) -> DicomSeries:
    root = Path("synthetic") / patient_id
    return DicomSeries(
        patient_id=patient_id,
        study_description="Study",
        series_description="t1_mprage",
        protocol_name="t1_mprage",
        series_number=n,
        acquisition_number=1,
        modality="MR",
        num_images=2,
        source_dir=root,
        sample_file=root / "img.dcm",
        status=SeriesStatus.PENDING,
        sequence_type="anat",
        fine_sequence_type="ANAT_T1",
        smart_name="t1_mprage",
        series_instance_uid=uid,
        study_instance_uid="uid.study",
        sequence_confidence=0.9,
        source_subject_folder=str(root),
    )


@pytest.fixture
def session(tmp_path: Path) -> CopilotSession:
    series = [_series("patient_A", "uid-a"), _series("patient_B", "uid-b", n=2)]
    for s in series:
        d = tmp_path / "dicom" / s.patient_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "img.dcm").write_bytes(b"SYNTHETIC_PIXELS_SHOULD_NOT_BE_LOGGED")
        s.source_dir = d
        s.sample_file = d / "img.dcm"
        s.source_subject_folder = str(d)
    plan = BIDSConversionPlan.from_series(
        series,
        dataset_root=tmp_path / "dicom",
        output_root=tmp_path / "out",
        session_override="01",
    )
    return CopilotSession(plan=plan, series_list=series)


@pytest.fixture
def store(tmp_path: Path) -> CopilotProvenanceStore:
    return CopilotProvenanceStore(tmp_path / "prov")


def test_sanitize_redacts_secrets_paths_and_pixels() -> None:
    payload = {
        "api_key": "sk-secret-value",
        "PatientName": "DOE^JOHN",
        "dataset_root": "/abs/path/to/dicom",
        "pixel_data": b"\x00\x01\x02",
        "ok": True,
        "n": 3,
    }
    cleaned = sanitize_for_provenance(payload)
    assert cleaned["api_key"] == "[redacted]"
    assert cleaned["PatientName"] == "[redacted]"
    assert cleaned["dataset_root"] == "[redacted_path]"
    assert cleaned["pixel_data"] == "[binary_omitted]"
    assert cleaned["ok"] is True
    assert cleaned["n"] == 3


def test_turn_provenance_records_request_model_tools(session: CopilotSession, store: CopilotProvenanceStore) -> None:
    provider = FakeLLMProvider(
        [
            {
                "type": "tool_call",
                "tool_name": "inspect_dataset",
                "arguments": {},
            },
            {"type": "message", "content": "Dataset has 2 subjects."},
        ]
    )
    agent = CopilotAgent(session=session, provider=provider, provenance_store=store)
    turn = agent.handle("How many subjects?")
    assert turn.ok
    assert turn.provenance_turn_id
    rows = store.records_for_turn(turn.provenance_turn_id)
    assert len(rows) == 1
    record = rows[0]
    assert record["schema_version"] == PROVENANCE_SCHEMA_VERSION
    assert record["record_type"] == RECORD_TURN
    assert record["request"]["text"] == "How many subjects?"
    assert record["request"]["text_sha256"]
    assert record["model_responses"]
    assert any(r.get("type") == "tool_call" for r in record["model_responses"])
    assert record["tool_calls"]
    assert record["tool_calls"][0]["tool_name"] == "inspect_dataset"
    assert record["tool_calls"][0]["ok"] is True
    assert record["tool_calls"][0]["arguments"] == {}
    assert record["tool_calls"][0]["result"] is not None
    dumped = json.dumps(record)
    assert "SYNTHETIC_PIXELS" not in dumped
    assert "sk-" not in dumped
    assert str(session.plan.dataset_root) not in dumped or "[redacted_path]" in dumped


def test_rejected_and_applied_changesets_distinguishable_and_reproducible(
    session: CopilotSession, store: CopilotProvenanceStore, tmp_path: Path
) -> None:
    from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint
    from neuro_pipeline.neurobids.copilot.provenance import build_decision_record

    # --- Rejected proposal ---
    reject_provider = FakeLLMProvider(
        [
            {
                "type": "tool_call",
                "tool_name": "rename_subjects",
                "arguments": {"mode": "sequential", "start": 10, "width": 3},
            }
        ]
    )
    agent = CopilotAgent(session=session, provider=reject_provider, provenance_store=store)
    turn_reject = agent.handle("Rename subjects sequentially from 010.")
    assert turn_reject.ok
    assert turn_reject.changeset is not None
    assert turn_reject.stopped_reason == "awaiting_approval"
    reject_cs = turn_reject.changeset
    reject_cs_id = reject_cs.id
    status_before_reject = reject_cs.status.value
    subjects_before = sorted({i.subject for i in session.plan.items})
    reject_cs.reject()
    store.append(
        build_decision_record(
            turn_id=turn_reject.provenance_turn_id,
            action="rejected",
            changeset=reject_cs,
            status_before=status_before_reject,
            message="Proposal rejected (REJECTED). Plan unchanged.",
            applied_summary=None,
            dataset_root=session.plan.dataset_root,
            plan_fingerprint_after=plan_fingerprint(session.plan),
        )
    )
    assert reject_cs.status == ChangeSetStatus.REJECTED
    assert sorted({i.subject for i in session.plan.items}) == subjects_before

    # --- Applied proposal ---
    apply_provider = FakeLLMProvider(
        [
            {
                "type": "tool_call",
                "tool_name": "rename_subjects",
                "arguments": {"mode": "sequential", "start": 20, "width": 3},
            }
        ]
    )
    agent = CopilotAgent(session=session, provider=apply_provider, provenance_store=store)
    turn_apply = agent.handle("Rename subjects sequentially from 020.")
    assert turn_apply.ok
    assert turn_apply.changeset is not None
    apply_cs = turn_apply.changeset
    apply_cs_id = apply_cs.id
    status_before_apply = apply_cs.status.value
    apply_cs.validate(session.plan, conversion_busy=False)
    apply_cs.approve()
    apply_cs.apply(session.plan, conversion_busy=False, require_validated=True)
    preview = apply_cs.preview()
    store.append(
        build_decision_record(
            turn_id=turn_apply.provenance_turn_id,
            action="applied",
            changeset=apply_cs,
            status_before=status_before_apply,
            message="Proposed changes applied to the BIDS conversion plan.",
            applied_summary={
                "n_edits": len(apply_cs.edits),
                "subject_renames": dict(preview.get("subject_renames") or {}),
                "plan_fingerprint_before": apply_cs.plan_fingerprint,
                "plan_fingerprint_after": plan_fingerprint(session.plan),
            },
            dataset_root=session.plan.dataset_root,
            plan_fingerprint_after=plan_fingerprint(session.plan),
        )
    )
    assert apply_cs.status == ChangeSetStatus.APPLIED
    subjects_after = sorted({i.subject for i in session.plan.items})
    assert subjects_after != subjects_before

    reject_decisions = store.decisions_for_changeset(reject_cs_id)
    apply_decisions = store.decisions_for_changeset(apply_cs_id)
    assert len(reject_decisions) == 1
    assert len(apply_decisions) == 1
    rejected = reject_decisions[0]
    applied = apply_decisions[0]

    assert rejected["record_type"] == RECORD_DECISION
    assert applied["record_type"] == RECORD_DECISION
    assert rejected["decision"]["action"] == "rejected"
    assert applied["decision"]["action"] == "applied"
    assert rejected["decision"]["status_after"] == "REJECTED"
    assert applied["decision"]["status_after"] == "APPLIED"
    assert rejected["decision"]["applied_summary"] is None
    assert applied["decision"]["applied_summary"] is not None
    assert applied["decision"]["applied_summary"]["n_edits"] >= 1
    assert "020" in str(applied["decision"]["applied_summary"].get("subject_renames") or {})
    assert rejected["changeset"]["id"] == reject_cs_id
    assert applied["changeset"]["id"] == apply_cs_id
    assert rejected["turn_id"] == turn_reject.provenance_turn_id
    assert applied["turn_id"] == turn_apply.provenance_turn_id

    export_path = tmp_path / "export" / "copilot_provenance.json"
    store.export_json(export_path)
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == PROVENANCE_SCHEMA_VERSION
    assert payload["n_records"] >= 4  # 2 turns + 2 decisions
    actions = {
        (
            r.get("changeset_id") or (r.get("changeset") or {}).get("id"),
            r["decision"]["action"],
        )
        for r in payload["records"]
        if r.get("record_type") == RECORD_DECISION
    }
    assert (reject_cs_id, "rejected") in actions
    assert (apply_cs_id, "applied") in actions

    reloaded = CopilotProvenanceStore(store.root)
    assert reloaded.decisions_for_changeset(reject_cs_id)[0]["decision"]["action"] == "rejected"
    assert reloaded.decisions_for_changeset(apply_cs_id)[0]["decision"]["action"] == "applied"
    assert sorted({i.subject for i in session.plan.items}) == subjects_after
