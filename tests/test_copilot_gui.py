"""GUI / controller tests for NeuroBIDS Copilot panel (fake LLM only)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Headless Qt for CI / remote sessions
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.gui.bids_preview_panel import BIDSPreviewPanel
from neuro_pipeline.gui.copilot_controller import CopilotController, friendly_copilot_error
from neuro_pipeline.gui.neurobids_copilot_panel import NeuroBIDSCopilotPanel
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot import ChangeSetStatus, CopilotSession, FakeLLMProvider
from neuro_pipeline.neurobids.copilot.llm.agent import CopilotAgent
from neuro_pipeline.neurobids.copilot.llm.provider import UnavailableLLMProvider
from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint


def _series(
    description: str,
    *,
    patient_id: str = "SUBA",
    series_number: int = 1,
    uid: str = "",
    seq: str = "anat",
    fine: str = "ANAT_T1",
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
def plan_and_series(tmp_path: Path):
    dicom_root = tmp_path / "dicom"
    dicom_root.mkdir()
    for pid in ("patient_A", "patient_B"):
        d = dicom_root / pid
        d.mkdir()
        (d / "img.dcm").write_bytes(b"SYNTHETIC")
    series = [
        _series("t1", patient_id="patient_A", uid="uid-a", series_number=1),
        _series("t1", patient_id="patient_B", uid="uid-b", series_number=1),
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
    return plan, series


@pytest.fixture
def session(plan_and_series) -> CopilotSession:
    plan, series = plan_and_series
    return CopilotSession(plan=plan, series_list=series)


@pytest.fixture
def preview(qtbot, plan_and_series) -> BIDSPreviewPanel:
    plan, series = plan_and_series
    panel = BIDSPreviewPanel()
    qtbot.addWidget(panel)
    panel.set_context(
        series=series,
        dataset_root=str(plan.dataset_root),
        output_root=str(plan.output_root),
        session_override="01",
    )
    panel._plan = plan
    panel._populate()
    return panel


@pytest.fixture
def panel(qtbot, preview, session) -> NeuroBIDSCopilotPanel:
    """Bound Copilot panel; sync asks avoid QThread/shiboken crashes under offscreen."""
    p = NeuroBIDSCopilotPanel()
    qtbot.addWidget(p)
    p.bind_preview(preview)
    p.controller.bind_session(session)
    p.controller.set_force_sync(True)
    return p


def test_copilot_panel_creation(qtbot) -> None:
    p = NeuroBIDSCopilotPanel()
    qtbot.addWidget(p)
    assert p.send_btn is not None
    assert "Ask NeuroBIDS" in p.input_edit.placeholderText()
    assert p.proposal_box.isHidden()


def test_readonly_request_displays_response(panel: NeuroBIDSCopilotPanel) -> None:
    panel.set_provider(
        FakeLLMProvider(
            [
                {"type": "tool_call", "tool_name": "list_subjects", "arguments": {}},
                {"type": "message", "content": "There are 2 subjects in this dataset."},
            ]
        )
    )
    panel.input_edit.setPlainText("How many subjects are in this dataset?")
    panel._on_send()
    assert "2 subjects" in panel.conversation.toPlainText()
    assert panel.controller.pending_changeset is None
    assert panel.proposal_box.isHidden()


def test_mutation_displays_changeset_no_auto_apply(
    panel: NeuroBIDSCopilotPanel, session: CopilotSession
) -> None:
    before = [(i.subject, i.session) for i in session.plan.items]
    panel.set_provider(
        FakeLLMProvider(
            [
                {
                    "type": "tool_call",
                    "tool_name": "rename_subjects",
                    "arguments": {"mode": "sequential", "start": 1},
                }
            ]
        )
    )
    panel.input_edit.setPlainText("Rename subjects sequentially.")
    panel._on_send()
    assert panel.controller.pending_changeset is not None
    assert not panel.proposal_box.isHidden()
    assert panel.controller.pending_changeset.status != ChangeSetStatus.APPLIED
    assert [(i.subject, i.session) for i in session.plan.items] == before


def test_apply_applies_valid_changeset(
    panel: NeuroBIDSCopilotPanel, session: CopilotSession
) -> None:
    panel.set_provider(
        FakeLLMProvider(
            [
                {
                    "type": "tool_call",
                    "tool_name": "rename_subjects",
                    "arguments": {"mode": "sequential", "start": 1},
                }
            ]
        )
    )
    panel.input_edit.setPlainText("Rename sequentially.")
    panel._on_send()
    assert panel.apply_btn.isEnabled()
    panel._on_apply()
    subjects = {i.subject.removeprefix("sub-") for i in session.plan.items}
    assert "001" in subjects
    assert "002" in subjects
    assert panel.controller.pending_changeset is None


def test_reject_does_not_modify_plan(
    panel: NeuroBIDSCopilotPanel, session: CopilotSession
) -> None:
    before = [(i.subject, i.include_in_conversion) for i in session.plan.items]
    panel.set_provider(
        FakeLLMProvider(
            [
                {
                    "type": "tool_call",
                    "tool_name": "rename_subjects",
                    "arguments": {"mode": "sequential", "start": 1},
                }
            ]
        )
    )
    panel.input_edit.setPlainText("Rename")
    panel._on_send()
    panel._on_reject()
    assert [(i.subject, i.include_in_conversion) for i in session.plan.items] == before
    assert panel.controller.pending_changeset is None


def test_stale_changeset_rejected(
    panel: NeuroBIDSCopilotPanel, session: CopilotSession
) -> None:
    panel.set_provider(
        FakeLLMProvider(
            [
                {
                    "type": "tool_call",
                    "tool_name": "rename_subjects",
                    "arguments": {"mode": "sequential", "start": 1},
                }
            ]
        )
    )
    panel.input_edit.setPlainText("Rename")
    panel._on_send()
    uid = session.plan.items[0].source_series_uid
    session.plan.apply_edit(uid, subject="manual_edit")
    session.plan.refresh_filenames()
    assert panel.controller.pending_stale()
    ok, msg = panel.controller.apply_pending()
    assert not ok
    assert "no longer valid" in msg.lower() or "stale" in msg.lower()


def test_busy_conversion_prevents_apply(panel: NeuroBIDSCopilotPanel) -> None:
    panel.set_provider(
        FakeLLMProvider(
            [
                {
                    "type": "tool_call",
                    "tool_name": "rename_subjects",
                    "arguments": {"mode": "sequential", "start": 1},
                }
            ]
        )
    )
    panel.input_edit.setPlainText("Rename")
    panel._on_send()
    panel.set_conversion_busy(True)
    assert not panel.controller.is_pending_applicable()
    ok, msg = panel.controller.apply_pending()
    assert not ok
    assert "conversion" in msg.lower()


def test_preview_refreshes_after_apply(
    panel: NeuroBIDSCopilotPanel, preview: BIDSPreviewPanel
) -> None:
    panel.set_provider(
        FakeLLMProvider(
            [
                {
                    "type": "tool_call",
                    "tool_name": "rename_subjects",
                    "arguments": {"mode": "sequential", "start": 1},
                }
            ]
        )
    )
    panel.input_edit.setPlainText("Rename")
    panel._on_send()
    panel._on_apply()
    texts = []
    for row in range(preview.table.rowCount()):
        cell = preview.table.item(row, 1)
        if cell:
            texts.append(cell.text())
    assert any("001" in t or "002" in t for t in texts)


def test_no_provider_handled_gracefully(panel: NeuroBIDSCopilotPanel) -> None:
    panel.set_provider(UnavailableLLMProvider())
    errors: list[str] = []
    panel.controller.error.connect(errors.append)
    panel.input_edit.setPlainText("Hello")
    panel._on_send()
    assert errors
    assert "provider" in errors[0].lower() or "configured" in errors[0].lower()


def test_controller_apply_without_auto_on_response(session: CopilotSession) -> None:
    provider = FakeLLMProvider(
        [
            {
                "type": "tool_call",
                "tool_name": "rename_subjects",
                "arguments": {"mode": "sequential", "start": 1},
            }
        ]
    )
    before_fp = plan_fingerprint(session.plan)
    agent = CopilotAgent(session=session, provider=provider)
    result = agent.handle("Rename sequentially")
    assert result.changeset is not None
    assert result.changeset.status != ChangeSetStatus.APPLIED
    assert plan_fingerprint(session.plan) == before_fp


def test_friendly_error_messages() -> None:
    assert "no longer valid" in friendly_copilot_error("stale_changeset").lower()
    assert "provider" in friendly_copilot_error("provider_unavailable").lower()


def test_worker_class_matches_existing_pattern() -> None:
    """CopilotWorker follows the same QObject + run() contract as other workers."""
    from neuro_pipeline.workers import CopilotWorker, start_worker

    assert callable(start_worker)
    assert hasattr(CopilotWorker, "run")
    assert hasattr(CopilotWorker, "response_ready")
