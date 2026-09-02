"""Unit tests for NeuroBIDS Copilot LLM adapter (mock provider only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot import (
    ChangeSetStatus,
    CopilotAgent,
    CopilotLLMClient,
    CopilotSession,
    FakeLLMProvider,
    LLMConfig,
    default_registry,
)
from neuro_pipeline.neurobids.copilot.llm.provider import (
    LLMProviderError,
    UnavailableLLMProvider,
    build_provider_from_config,
)
from neuro_pipeline.neurobids.copilot.llm.schemas import parse_assistant_payload
from neuro_pipeline.neurobids.copilot.llm.validation import (
    ToolArgumentValidationError,
    validate_tool_arguments,
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
        output_root=tmp_path / "bids_out",
        session_override="01",
    )
    return CopilotSession(
        plan=plan,
        series_list=series,
        detection_method="patient_id",
        n_dicom_files=3,
    )


def test_nl_request_to_structured_tool_call(session_two_subjects: CopilotSession) -> None:
    provider = FakeLLMProvider(
        [
            {
                "type": "tool_call",
                "tool_name": "rename_subjects",
                "arguments": {"mode": "sequential", "start": 1, "preserve_sessions": True},
            }
        ]
    )
    agent = CopilotAgent(session=session_two_subjects, provider=provider)
    result = agent.handle("Rename all subjects sequentially while preserving sessions.")
    assert result.ok
    assert result.tool_traces[0].tool_name == "rename_subjects"
    assert result.stopped_reason == "awaiting_approval"
    assert result.changeset is not None


def test_valid_tool_call_execution(session_two_subjects: CopilotSession) -> None:
    provider = FakeLLMProvider(
        [
            {"type": "tool_call", "tool_name": "list_subjects", "arguments": {}},
            {"type": "message", "content": "There are 2 subjects."},
        ]
    )
    result = CopilotAgent(session=session_two_subjects, provider=provider).handle(
        "How many subjects are there?"
    )
    assert result.ok
    assert result.message == "There are 2 subjects."
    assert result.tool_traces[0].ok
    assert result.stopped_reason == "message"


def test_invalid_tool_name_rejected(session_two_subjects: CopilotSession) -> None:
    provider = FakeLLMProvider(
        [{"type": "tool_call", "tool_name": "rm_rf_dicom", "arguments": {}}]
    )
    result = CopilotAgent(session=session_two_subjects, provider=provider).handle("Delete DICOM")
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "invalid_tool_name"


def test_invalid_arguments_rejected(session_two_subjects: CopilotSession) -> None:
    provider = FakeLLMProvider(
        [
            {
                "type": "tool_call",
                "tool_name": "rename_subjects",
                "arguments": {"prefix": "sub", "strategy": "sequential"},
            }
        ]
    )
    result = CopilotAgent(session=session_two_subjects, provider=provider).handle(
        "Rename subjects"
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "invalid_tool_arguments"


def test_readonly_request(session_two_subjects: CopilotSession) -> None:
    provider = FakeLLMProvider(
        [
            {"type": "tool_call", "tool_name": "list_subjects", "arguments": {}},
            {
                "type": "message",
                "content": "One subject has two acquisitions in a single session.",
            },
        ]
    )
    result = CopilotLLMClient(session_two_subjects, provider=provider).handle(
        "How many subjects have two sessions?"
    )
    assert result.ok
    assert result.changeset is None
    assert result.tool_traces[0].mutates_data is False


def test_mutation_creates_changeset_not_applied(session_two_subjects: CopilotSession) -> None:
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
    assert result.changeset.status in {ChangeSetStatus.DRAFT, ChangeSetStatus.VALIDATED}
    assert result.changeset.status != ChangeSetStatus.APPLIED
    after = [(i.subject, i.session) for i in session_two_subjects.plan.items]
    assert before == after
    assert result.stopped_reason == "awaiting_approval"


def test_provider_failure(session_two_subjects: CopilotSession) -> None:
    class Boom(FakeLLMProvider):
        def generate(self, **kwargs):  # type: ignore[no-untyped-def]
            raise LLMProviderError("simulated outage", code="provider_unavailable")

    result = CopilotAgent(session=session_two_subjects, provider=Boom([])).handle("Hello")
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "provider_unavailable"


def test_malformed_response(session_two_subjects: CopilotSession) -> None:
    class Bad(FakeLLMProvider):
        def generate(self, **kwargs):  # type: ignore[no-untyped-def]
            return parse_assistant_payload({"type": "not_a_real_type", "content": "x"})

    result = CopilotAgent(session=session_two_subjects, provider=Bad([])).handle("Hello")
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "malformed_response"


def test_maximum_tool_call_limit(session_two_subjects: CopilotSession) -> None:
    provider = FakeLLMProvider(
        [
            {"type": "tool_call", "tool_name": "list_subjects", "arguments": {}},
            {"type": "tool_call", "tool_name": "inspect_dataset", "arguments": {}},
            {"type": "message", "content": "should not reach"},
        ]
    )
    result = CopilotAgent(
        session=session_two_subjects,
        provider=provider,
        max_tool_calls=2,
    ).handle("Explore the dataset thoroughly")
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "max_tool_calls"
    assert len(result.tool_traces) == 2
    assert provider._index == 2  # noqa: SLF001 — third scripted response unused


def test_ambiguous_request_asks_clarify(session_two_subjects: CopilotSession) -> None:
    provider = FakeLLMProvider(
        [
            {
                "type": "clarify",
                "content": "Which naming strategy should I use: sequential or an explicit mapping?",
            }
        ]
    )
    result = CopilotAgent(session=session_two_subjects, provider=provider).handle(
        "Rename the subjects."
    )
    assert result.ok
    assert result.clarify
    assert "strategy" in result.message.lower() or "mapping" in result.message.lower()
    assert result.changeset is None


def test_sensitive_data_absent_from_llm_context(session_two_subjects: CopilotSession) -> None:
    provider = FakeLLMProvider([{"type": "message", "content": "ok"}])
    CopilotAgent(session=session_two_subjects, provider=provider).handle("Summarize")
    payload = provider.calls[0]["user_payload"]
    assert "PatientName" not in payload
    assert "SYNTHETIC_DICOM" not in payload
    # Absolute tmp paths should not appear as dataset roots in compact context
    assert str(session_two_subjects.plan.dataset_root) not in payload
    ctx = session_two_subjects.dataset_context().to_llm_context()
    dumped = str(ctx)
    assert "PatientName" not in dumped
    assert str(session_two_subjects.plan.dataset_root) not in dumped


def test_provider_swappable_without_modifying_tools(session_two_subjects: CopilotSession) -> None:
    registry = default_registry()
    tools_before = registry.to_llm_tools()
    p1 = FakeLLMProvider([{"type": "message", "content": "from-provider-1"}])
    p2 = FakeLLMProvider([{"type": "message", "content": "from-provider-2"}])
    r1 = CopilotAgent(session=session_two_subjects, provider=p1, registry=registry).handle("Hi")
    r2 = CopilotAgent(session=session_two_subjects, provider=p2, registry=registry).handle("Hi")
    assert r1.message == "from-provider-1"
    assert r2.message == "from-provider-2"
    assert registry.to_llm_tools() == tools_before


def test_unavailable_provider_without_api_key(session_two_subjects: CopilotSession) -> None:
    cfg = LLMConfig(provider="none")
    provider = build_provider_from_config(cfg)
    assert isinstance(provider, UnavailableLLMProvider)
    result = CopilotAgent(session=session_two_subjects, provider=provider).handle("Hello")
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "provider_unavailable"


def test_to_llm_tools_exposes_kind_not_internals() -> None:
    tools = default_registry().to_llm_tools()
    by_name = {t["name"]: t for t in tools}
    assert "rename_subjects" in by_name
    assert by_name["rename_subjects"]["mutates_data"] is True
    assert "ChangeSet" in by_name["rename_subjects"]["description"]
    assert "execute" not in by_name["rename_subjects"]
    assert "list_subjects" in by_name
    assert by_name["list_subjects"]["kind"] == "read_only"


def test_argument_schema_validation_unit() -> None:
    schema = {
        "type": "object",
        "properties": {"subject_id": {"type": "string"}},
        "required": ["subject_id"],
        "additionalProperties": False,
    }
    validate_tool_arguments(schema, {"subject_id": "01"})
    with pytest.raises(ToolArgumentValidationError):
        validate_tool_arguments(schema, {})
    with pytest.raises(ToolArgumentValidationError):
        validate_tool_arguments(schema, {"subject_id": "01", "extra": 1})
