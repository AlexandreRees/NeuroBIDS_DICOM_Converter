"""Auditable Copilot explanations — evidence, not hidden chain-of-thought."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot import (
    ChangeSetStatus,
    CopilotAgent,
    CopilotExplanation,
    CopilotSession,
    FakeLLMProvider,
    default_registry,
)
from neuro_pipeline.neurobids.copilot.explain import (
    explain_changeset,
    explain_mapping,
    sanitize_metadata,
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
def session_two_subjects(tmp_path: Path) -> CopilotSession:
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
    ]
    for s in series:
        s.source_dir = dicom_root / s.patient_id
        s.sample_file = s.source_dir / "img.dcm"
        s.source_subject_folder = str(s.source_dir)
    plan = BIDSConversionPlan.from_series(
        series,
        dataset_root=dicom_root,
        output_root=tmp_path / "out",
        session_override="01",
    )
    return CopilotSession(plan=plan, series_list=series)


def _assert_no_hidden_or_phi(payload: dict) -> None:
    blob = str(payload).lower()
    for key in ("thinking", "chain_of_thought", "scratchpad", "inner_monologue"):
        assert key not in payload
        assert f"'{key}'" not in blob
    assert "patientname" not in blob
    assert "patient_name" not in blob
    dumped = str(payload)
    assert "SYNTHETIC_DICOM" not in dumped
    assert "img.dcm" not in dumped


def test_explain_mapping_has_required_fields(session_two_subjects: CopilotSession) -> None:
    expl = explain_mapping(session_two_subjects, "uid-a-t1")
    assert expl.decision
    assert expl.evidence
    assert "classify_acquisition" in expl.tools_consulted
    assert expl.confidence is not None
    assert 0.0 <= float(expl.confidence) <= 1.0
    assert "uid-a-t1" in expl.affected_acquisitions
    assert expl.changeset_id == ""
    payload = expl.to_dict()
    for key in (
        "decision",
        "evidence",
        "tools_consulted",
        "metadata",
        "confidence",
        "affected_acquisitions",
        "changeset_id",
    ):
        assert key in payload
    _assert_no_hidden_or_phi(payload)
    text = expl.to_text()
    assert "Decision:" in text
    assert "Evidence:" in text
    assert "Tools consulted:" in text
    assert "Confidence:" in text
    assert "Affected acquisitions:" in text
    assert "thinking" not in text.lower()
    assert "T1w" in expl.decision or "t1" in expl.decision.lower() or "anat" in expl.decision


def test_explain_mapping_tool_is_read_only(session_two_subjects: CopilotSession) -> None:
    registry = default_registry()
    tool = registry.get("explain_mapping")
    assert tool is not None
    assert tool.mutates_data is False
    before = [(i.subject, i.suffix, i.datatype) for i in session_two_subjects.plan.items]
    result = registry.execute(
        "explain_mapping", session_two_subjects, {"series_uid": "uid-a-t1"}
    )
    assert result.ok, result.error
    expl = result.data["explanation"]
    assert expl["decision"]
    assert expl["evidence"]
    assert expl["confidence"] is not None
    assert expl["affected_acquisitions"] == ["uid-a-t1"]
    assert expl.get("changeset_id") in {"", None}
    assert "thinking" not in expl
    after = [(i.subject, i.suffix, i.datatype) for i in session_two_subjects.plan.items]
    assert before == after


def test_explain_changeset_includes_id_and_edits(session_two_subjects: CopilotSession) -> None:
    registry = default_registry()
    before = [i.subject for i in session_two_subjects.plan.items]
    result = registry.execute(
        "rename_subjects",
        session_two_subjects,
        {"mode": "sequential", "start": 1},
    )
    assert result.ok
    cs = result.data["changeset"]
    expl = explain_changeset(cs)
    assert expl.changeset_id == cs.id
    assert expl.changeset_id
    assert expl.affected_acquisitions
    assert any("→" in line or "subject" in line.lower() for line in expl.evidence)
    assert "rename_subjects" in expl.tools_consulted
    text = expl.to_text()
    assert f"ChangeSet ID: {cs.id}" in text
    assert [i.subject for i in session_two_subjects.plan.items] == before
    assert cs.status != ChangeSetStatus.APPLIED
    _assert_no_hidden_or_phi(expl.to_dict())


def test_agent_mapping_turn_attaches_explanation(
    session_two_subjects: CopilotSession,
) -> None:
    provider = FakeLLMProvider(
        [
            {
                "type": "tool_call",
                "tool_name": "propose_bids_mapping",
                "arguments": {"series_uid": "uid-a-t1"},
            },
            {"type": "message", "content": "Proposed an anatomical mapping."},
        ]
    )
    result = CopilotAgent(session=session_two_subjects, provider=provider).handle(
        "Propose a BIDS mapping for the T1 series."
    )
    assert result.ok
    assert result.changeset is None
    assert result.explanation is not None
    assert "propose_bids_mapping" in result.explanation.tools_consulted
    assert "uid-a-t1" in result.explanation.affected_acquisitions
    assert result.explanation.confidence is not None
    dumped = result.to_dict()
    assert dumped["explanation"]["decision"]
    _assert_no_hidden_or_phi(dumped["explanation"])


def test_agent_mutation_explanation_has_changeset_id_not_applied(
    session_two_subjects: CopilotSession,
) -> None:
    before = [(i.subject, i.session) for i in session_two_subjects.plan.items]
    provider = FakeLLMProvider(
        [
            {
                "type": "tool_call",
                "tool_name": "rename_subjects",
                "arguments": {"mode": "sequential", "start": 1},
            }
        ]
    )
    result = CopilotAgent(session=session_two_subjects, provider=provider).handle(
        "Rename subjects sequentially."
    )
    assert result.ok
    assert result.changeset is not None
    assert result.changeset.status != ChangeSetStatus.APPLIED
    assert result.explanation is not None
    assert result.explanation.changeset_id == result.changeset.id
    assert "rename_subjects" in result.explanation.tools_consulted
    assert result.explanation.affected_acquisitions
    assert [(i.subject, i.session) for i in session_two_subjects.plan.items] == before
    assert result.stopped_reason == "awaiting_approval"
    assert f"ChangeSet ID: {result.changeset.id}" in result.explanation.to_text()


def test_sanitize_metadata_drops_phi_and_cot() -> None:
    cleaned = sanitize_metadata(
        {
            "series_description": "t1_mprage",
            "PatientName": "SECRET",
            "patient_id": "HOSPITAL-99",
            "thinking": "I should guess T1w",
            "source_dir": "/tmp/secret/dicom",
            "datatype": "anat",
        }
    )
    assert cleaned["series_description"] == "t1_mprage"
    assert cleaned["datatype"] == "anat"
    assert "PatientName" not in cleaned
    assert "patient_id" not in cleaned
    assert "thinking" not in cleaned
    assert "source_dir" not in cleaned


def test_explanation_from_dict_strips_hidden_keys() -> None:
    expl = CopilotExplanation.from_dict(
        {
            "decision": "Mapped as anat/T1w",
            "evidence": ["series_description=t1_mprage"],
            "tools_consulted": ["classify_acquisition"],
            "metadata": {"datatype": "anat"},
            "confidence": 0.9,
            "affected_acquisitions": ["uid-a-t1"],
            "changeset_id": "",
            "thinking": "secret chain of thought",
            "chain_of_thought": "do not leak",
        }
    )
    assert expl is not None
    payload = expl.to_dict()
    assert "thinking" not in payload
    assert "chain_of_thought" not in payload
    assert expl.decision == "Mapped as anat/T1w"
