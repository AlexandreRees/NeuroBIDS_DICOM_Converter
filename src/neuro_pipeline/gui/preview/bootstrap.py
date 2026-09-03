"""Bootstrap real MainWindow with a synthetic preview dataset."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from neuro_pipeline.batch.input_analysis import InputAnalysis
from neuro_pipeline.gui.main_window import MainWindow
from neuro_pipeline.gui.preview.dataset import UID_002_01_LOC, build_preview_plan
from neuro_pipeline.gui.preview.demo_provider import PreviewDemoProvider
from neuro_pipeline.models.config import AppConfig

Scenario = Literal["normal", "audit", "changeset"]


def apply_preview_scenario(
    window: MainWindow,
    scenario: Scenario = "normal",
    *,
    root: Path | None = None,
) -> None:
    """Load synthetic data into the live Convert/Copilot widgets."""
    root = Path(root) if root is not None else Path("preview_demo")
    with_issues = scenario == "audit"
    series, plan = build_preview_plan(root=root, with_audit_issues=with_issues)

    convert = window.convert_page
    analysis = InputAnalysis.from_series(series, folder=root / "dicom", discovery_mode="patient_id")
    analysis.detection_reason = "NeuroBIDS UI Preview/Demo Mode (synthetic)"
    convert.load_demo_dataset(
        series=series,
        plan=plan,
        dataset_root=str(root / "dicom"),
        output_root=str(root / "bids_out"),
        analysis=analysis,
    )

    provider = PreviewDemoProvider()
    convert.copilot_panel.set_provider(provider)
    # Keep demo responsive and deterministic under headless/Xvfb.
    convert.copilot_panel.controller.set_force_sync(True)

    window.setWindowTitle(f"NeuroBIDS — UI Preview ({scenario})")
    window.set_copilot_visible(True)

    # All scenarios show Conversion; Copilot side panel is open.
    window.show_stage("conversion")

    if scenario == "audit":
        # Select the first acquisition with issues so the BIDS Preview highlights it.
        item = plan.get(UID_002_01_LOC)
        series_obj = next((s for s in series if s.series_instance_uid == UID_002_01_LOC), None)
        if item is not None:
            convert.preview_panel.select_uid(UID_002_01_LOC)
            inspector = getattr(convert, "acquisition_inspector", None)
            if inspector is not None:
                inspector.set_acquisition(item, series_obj, plan)
    elif scenario == "changeset":
        if plan.items:
            convert.preview_panel.select_uid(plan.items[0].source_series_uid)
        convert.copilot_panel.submit_prompt(
            "Rename the subjects sequentially starting from 001.",
            send=True,
        )
    else:
        if plan.items:
            convert.preview_panel.select_uid(plan.items[0].source_series_uid)

    window.refresh_workspace()


def build_preview_window(
    config: AppConfig,
    scenario: Scenario = "normal",
    *,
    root: Path | None = None,
) -> MainWindow:
    """Create :class:`MainWindow` and apply the preview scenario."""
    window = MainWindow(config)
    apply_preview_scenario(window, scenario, root=root)
    return window
