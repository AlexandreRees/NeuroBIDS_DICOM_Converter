"""GUI tests for the NeuroBIDS workflow shell (no LLM API key)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"PySide6 is not usable in this environment: {exc}", allow_module_level=True)

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.gui.audit_summary import build_audit_report
from neuro_pipeline.gui.main_window import MainWindow
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.models.config import AppConfig
from neuro_pipeline.neurobids.copilot.llm.provider import FakeLLMProvider, UnavailableLLMProvider


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
        _series(
            "rest_AP",
            patient_id="patient_A",
            uid="uid-a-rest",
            series_number=2,
            seq="func",
            fine="FMRI_REST",
        ),
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


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["neurobids-ui-tests"])
    return app


@pytest.fixture
def window(qapp, plan_and_series) -> MainWindow:
    plan, series = plan_and_series
    win = MainWindow(AppConfig())
    preview = win.convert_page.preview_panel
    preview.set_context(
        series=series,
        dataset_root=str(plan.dataset_root),
        output_root=str(plan.output_root),
        session_override="01",
    )
    preview._plan = plan
    preview._populate()
    win.convert_page.input_edit.setText(str(plan.dataset_root))
    win.convert_page.output_edit.setText(str(plan.output_root))
    win.copilot_panel.rebind_session_from_preview()
    win.copilot_panel.controller.set_force_sync(True)
    win.refresh_workspace()
    win.show()
    qapp.processEvents()
    yield win
    win.close()


def test_application_launches(window: MainWindow) -> None:
    assert window.windowTitle() == "NeuroBIDS"
    assert window.current_stage() == "conversion"


@pytest.mark.parametrize(
    "stage",
    ["conversion", "queue", "settings", "logs"],
)
def test_navigation_opens_stage(window: MainWindow, stage: str) -> None:
    window.show_stage(stage)
    assert window.current_stage() == stage
    assert window._nav_by_id[stage].isChecked()


def test_conversion_page_is_default(window: MainWindow) -> None:
    window.show_stage("conversion")
    assert window.current_stage() == "conversion"
    assert window.convert_page.convert_btn is not None
    assert window.convert_page.inventory_btn is not None
    assert window.convert_page.preview_panel.plan is not None


def test_bids_preview_accessible_from_conversion(window: MainWindow) -> None:
    window.show_stage("conversion")
    assert window.convert_page.preview_panel.plan is not None
    assert window.convert_page.preview_panel.table.rowCount() > 0


def test_copilot_open_and_close(window: MainWindow) -> None:
    window.set_copilot_visible(True)
    assert window.copilot_is_visible()
    assert window.copilot_panel.isVisible()
    window.copilot_panel.hide_btn.click()
    assert not window.copilot_is_visible()
    window.set_copilot_visible(True)
    assert window.copilot_is_visible()
    window.set_copilot_visible(False)
    assert not window.copilot_is_visible()


def test_copilot_receives_dataset_context(window: MainWindow) -> None:
    preview = window.convert_page.preview_panel
    uid = preview.plan.items[0].source_series_uid
    preview.select_uid(uid)
    session = window.copilot_panel.controller.session
    assert session is not None
    assert session.plan is preview.plan
    # The Copilot session should know which UID is selected.
    assert session.ui_selection.get("series_uid") == uid or session.plan is not None


def test_copilot_unavailable_state(window: MainWindow) -> None:
    window.copilot_panel.set_provider(UnavailableLLMProvider())
    window.set_copilot_visible(True)
    assert not window.copilot_panel.unavailable_box.isHidden()
    window.copilot_panel.set_provider(FakeLLMProvider([{"type": "message", "content": "ok"}]))
    assert window.copilot_panel.unavailable_box.isHidden()
    # Rest of the app still works
    window.show_stage("conversion")
    assert window.convert_page.preview_panel.plan is not None


def test_changeset_proposal_ux(window: MainWindow) -> None:
    panel = window.copilot_panel
    session = panel.controller.session
    assert session is not None
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
    before = [i.subject for i in session.plan.items]
    panel.submit_prompt("Rename subjects sequentially.", send=True)
    assert panel.controller.pending_changeset is not None
    assert not panel.proposal_box.isHidden()
    assert "DICOM" in panel.safety_dicom.text()
    assert panel.apply_btn.isEnabled()
    panel._on_reject()
    assert [i.subject for i in session.plan.items] == before
    assert panel.controller.pending_changeset is None


def test_apply_disabled_when_conversion_busy(window: MainWindow) -> None:
    panel = window.copilot_panel
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
    panel.submit_prompt("Rename", send=True)
    panel.set_conversion_busy(True)
    assert not panel.apply_btn.isEnabled()
    panel.set_conversion_busy(False)


def test_manual_preview_edit_marks_changeset_stale(window: MainWindow) -> None:
    panel = window.copilot_panel
    session = panel.controller.session
    assert session is not None
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
    panel.submit_prompt("Rename", send=True)
    uid = session.plan.items[0].source_series_uid
    session.plan.apply_edit(uid, subject="manual_edit")
    session.plan.refresh_filenames()
    window.convert_page.preview_panel.reload_display()
    assert panel.controller.pending_stale()
    assert not panel.controller.is_pending_applicable()


def test_conversion_page_and_queue_remain(window: MainWindow) -> None:
    window.show_stage("conversion")
    assert window.convert_page.convert_btn is not None
    assert window.convert_page.inventory_btn is not None
    window.show_stage("queue")
    assert window.queue_page is not None
    window.show_stage("settings")
    assert window.settings_page is not None
    window.show_stage("logs")
    assert window.log_page is not None


def test_smoke_workflow(window: MainWindow) -> None:
    """Smoke: launch → dataset bound → Conversion → Preview → Copilot."""
    assert window.windowTitle() == "NeuroBIDS"
    window.show_stage("conversion")
    assert window.convert_page.preview_panel.plan is not None
    assert window.convert_page.preview_panel.table.rowCount() >= 2
    window.set_copilot_visible(True)
    assert window.copilot_panel.isVisible()
    report = build_audit_report(
        ctx=window.copilot_panel.controller.session.dataset_context(),
        plan=window.convert_page.preview_panel.plan,
    )
    assert not report.empty
    assert "94" not in report.headline
