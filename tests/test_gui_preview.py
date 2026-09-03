"""Tests for NeuroBIDS UI Preview/Demo Mode."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from neuro_pipeline.gui.preview.dataset import UID_002_01_LOC, build_preview_plan, build_preview_series
from neuro_pipeline.gui.preview.demo_provider import PreviewDemoProvider
from neuro_pipeline.neurobids.copilot.changeset import ChangeSetStatus
from neuro_pipeline.neurobids.copilot.llm.agent import CopilotAgent

try:
    from PySide6.QtWidgets import QApplication  # noqa: F401
except Exception as exc:  # noqa: BLE001
    _QT_IMPORT_ERROR = exc
else:
    _QT_IMPORT_ERROR = None

if _QT_IMPORT_ERROR is None:
    from neuro_pipeline.config.loader import load_app_config
    from neuro_pipeline.gui.preview.bootstrap import apply_preview_scenario, build_preview_window
else:
    load_app_config = None  # type: ignore[assignment]
    apply_preview_scenario = None
    build_preview_window = None


def test_preview_dataset_is_tiny_and_deterministic() -> None:
    series = build_preview_series()
    assert len(series) == 5
    series2, plan = build_preview_plan(with_audit_issues=False)
    assert len(series2) == 5
    assert len(plan.items) == 5
    loc = plan.get(UID_002_01_LOC)
    assert loc is not None
    assert loc.include_in_conversion is False
    _, plan_audit = build_preview_plan(with_audit_issues=True)
    assert plan_audit.get(UID_002_01_LOC).include_in_conversion is True


def test_preview_demo_provider_rename_and_readonly() -> None:
    import json

    provider = PreviewDemoProvider()
    tools = [{"name": "list_subjects"}]
    rename = provider.generate(
        system="x",
        user_payload=json.dumps({"user_request": "Rename subjects sequentially from 001"}),
        tools=tools,
    )
    assert rename.type.value == "tool_call"
    assert rename.tool_call is not None
    assert rename.tool_call.tool_name == "rename_subjects"

    first = provider.generate(
        system="x",
        user_payload=json.dumps({"user_request": "How many subjects are in this dataset?"}),
        tools=tools,
    )
    assert first.tool_call is not None
    assert first.tool_call.tool_name == "list_subjects"
    follow = provider.generate(
        system="x",
        user_payload=json.dumps(
            {
                "user_request": "How many subjects?",
                "prior_tool_results": [
                    {
                        "tool_name": "list_subjects",
                        "ok": True,
                        "data": {"n_subjects": 2, "subjects": []},
                    }
                ],
            }
        ),
        tools=tools,
    )
    assert follow.type.value == "message"
    assert "2" in follow.content


def test_preview_window_normal_scenario(tmp_path) -> None:
    if _QT_IMPORT_ERROR is not None:
        pytest.skip(f"PySide6 is not usable in this environment: {_QT_IMPORT_ERROR}")
    config = load_app_config()
    win = build_preview_window(config, scenario="normal", root=tmp_path)
    try:
        assert win.convert_page.preview_panel.plan is not None
        assert len(win.convert_page.preview_panel.plan.items) == 5
        assert win.copilot_is_visible()
        assert win.current_stage() == "conversion"
        assert isinstance(win.copilot_panel.controller._provider, PreviewDemoProvider)
        assert win.convert_page.preview_panel.table.rowCount() == 5
    finally:
        win.close()


def test_preview_changeset_scenario_ask_reject_apply(tmp_path) -> None:
    if _QT_IMPORT_ERROR is not None:
        pytest.skip(f"PySide6 is not usable in this environment: {_QT_IMPORT_ERROR}")
    config = load_app_config()
    win = build_preview_window(config, scenario="changeset", root=tmp_path)
    try:
        cs = win.copilot_panel.controller.pending_changeset
        assert cs is not None
        assert cs.status in {ChangeSetStatus.DRAFT, ChangeSetStatus.VALIDATED}
        before = [(i.subject, i.session) for i in win.convert_page.preview_panel.plan.items]
        win.copilot_panel._on_reject()
        assert win.copilot_panel.controller.pending_changeset is None
        assert [(i.subject, i.session) for i in win.convert_page.preview_panel.plan.items] == before

        win.copilot_panel.submit_prompt(
            "Rename the subjects sequentially starting from 001.",
            send=True,
        )
        assert win.copilot_panel.controller.pending_changeset is not None
        win.copilot_panel._on_apply()
        subjects = {i.subject.removeprefix("sub-") for i in win.convert_page.preview_panel.plan.items}
        assert "001" in subjects and "002" in subjects
    finally:
        win.close()


def test_preview_audit_scenario(tmp_path) -> None:
    if _QT_IMPORT_ERROR is not None:
        pytest.skip(f"PySide6 is not usable in this environment: {_QT_IMPORT_ERROR}")
    config = load_app_config()
    win = build_preview_window(config, scenario="audit", root=tmp_path)
    try:
        assert win.current_stage() == "conversion"
        loc = win.convert_page.preview_panel.plan.get(UID_002_01_LOC)
        assert loc is not None
        assert loc.include_in_conversion is True
    finally:
        win.close()


def test_preview_agent_uses_tools_without_api_key(tmp_path) -> None:
    series, plan = build_preview_plan(root=tmp_path)
    from neuro_pipeline.neurobids.copilot.session import CopilotSession

    session = CopilotSession(plan=plan, series_list=series, detection_method="preview_demo")
    result = CopilotAgent(session=session, provider=PreviewDemoProvider()).handle(
        "How many subjects are in this dataset?"
    )
    assert result.ok
    assert any(t.tool_name == "list_subjects" for t in result.tool_traces)
    assert "2" in (result.message or "")
