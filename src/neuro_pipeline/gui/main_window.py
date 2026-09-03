"""Main application window — NeuroBIDS navigation shell + stacked pages."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui.audit_summary import build_audit_report
from neuro_pipeline.gui.command_palette import CommandPalette
from neuro_pipeline.gui.convert_widget import ConvertWidget
from neuro_pipeline.gui.conversion_queue_widget import ConversionQueueWidget
from neuro_pipeline.gui.log_widget import LogWidget
from neuro_pipeline.gui.settings_widget import SettingsWidget
from neuro_pipeline.gui.workspace_status import WorkspaceStatusBar
from neuro_pipeline.logging.privacy import safe_folder_label
from neuro_pipeline.models.config import AppConfig
from neuro_pipeline.utils.naming import SmartFilenameEngine

LOGGER = logging.getLogger(__name__)

# (stage_id, nav label, group)
_NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("conversion", "Conversion", "TOOLS"),
    ("queue", "Queue", "TOOLS"),
    ("settings", "Settings", "TOOLS"),
    ("logs", "Logs", "TOOLS"),
)


class MainWindow(QMainWindow):
    """NeuroBIDS dataset curation main window."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._naming_engine = self._load_naming_engine()
        self._copilot_open = False
        self._copilot_width = 340
        self._page_index: dict[str, int] = {}
        self._nav_by_id: dict[str, QPushButton] = {}

        self.setWindowTitle("NeuroBIDS")
        self.resize(1280, 800)
        self.setMinimumSize(960, 640)
        self._build_ui()
        self._install_shortcuts()
        self.refresh_workspace()

    def _load_naming_engine(self) -> SmartFilenameEngine:
        path = Path(self.config.naming_rules_path) if self.config.naming_rules_path else None
        if path and path.exists():
            try:
                return SmartFilenameEngine.from_yaml(path)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to load naming rules: %s", exc)
        return SmartFilenameEngine()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_nav())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        header = QFrame()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        self.dataset_header = QLabel("No dataset loaded")
        self.dataset_header.setObjectName("monoLabel")
        self.dataset_header.setWordWrap(True)
        header_layout.addWidget(self.dataset_header, 1)
        self.copilot_toggle = QPushButton("Copilot")
        self.copilot_toggle.setCheckable(True)
        self.copilot_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copilot_toggle.setToolTip("Show or hide NeuroBIDS Copilot (Ctrl+J)")
        self.copilot_toggle.clicked.connect(self._on_copilot_toggled)
        header_layout.addWidget(self.copilot_toggle)
        right_layout.addWidget(header)

        self.convert_page = ConvertWidget(self.config, self._naming_engine)
        self.queue_page = ConversionQueueWidget(self.config)
        self.settings_page = SettingsWidget(
            self.config,
            on_apply=self._on_settings_applied,
            on_llm_apply=self._on_llm_settings_applied,
            connection_tester=self._start_llm_connection_test,
        )
        self.settings_page.llm_config_changed.connect(self._on_llm_settings_applied)
        self.log_page = LogWidget(self.config)

        self.stack = QStackedWidget()
        page_widgets: list[tuple[str, QWidget]] = [
            ("conversion", self.convert_page),
            ("queue", self.queue_page),
            ("settings", self.settings_page),
            ("logs", self.log_page),
        ]
        for index, (page_id, widget) in enumerate(page_widgets):
            self._page_index[page_id] = index
            self.stack.addWidget(widget)

        self.copilot_panel = self.convert_page.copilot_panel
        self.copilot_panel.collapse_requested.connect(lambda: self.set_copilot_visible(False))
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.addWidget(self.stack)
        self.workspace_splitter.addWidget(self.copilot_panel)
        self.workspace_splitter.setStretchFactor(0, 5)
        self.workspace_splitter.setStretchFactor(1, 2)
        self.workspace_splitter.setCollapsible(0, False)
        self.workspace_splitter.setCollapsible(1, True)
        self.workspace_splitter.splitterMoved.connect(self._on_copilot_splitter_moved)
        right_layout.addWidget(self.workspace_splitter, 1)

        self.status_bar = WorkspaceStatusBar()
        right_layout.addWidget(self.status_bar)
        layout.addWidget(right, stretch=1)

        self.convert_page.dataset_changed.connect(self.refresh_workspace)
        self.convert_page.busy_changed.connect(lambda _=False: self.refresh_workspace())
        self.copilot_panel.configure_requested.connect(self._on_configure_copilot)
        self.copilot_panel.controller.changeset_updated.connect(self.refresh_workspace)
        self.copilot_panel.controller.connection_test_finished.connect(
            self._on_llm_connection_test_finished
        )

        self.palette = CommandPalette.install(self)
        self.palette.ask_requested.connect(self._ask_copilot)
        self.palette.prompt_requested.connect(self._ask_copilot)
        self.palette.goto_requested.connect(self.show_stage)

        self._nav_buttons[0].setChecked(True)
        self.show_stage("conversion")
        self.set_copilot_visible(False)

    def _build_nav(self) -> QFrame:
        nav = QFrame()
        nav.setObjectName("navPanel")
        nav.setFixedWidth(168)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(10, 14, 10, 14)
        nav_layout.setSpacing(4)

        brand = QLabel("NeuroBIDS")
        brand.setObjectName("navBrand")
        brand.setWordWrap(True)
        nav_layout.addWidget(brand)
        subtitle = QLabel("From raw data to a research-ready dataset")
        subtitle.setObjectName("navSubtitle")
        subtitle.setWordWrap(True)
        nav_layout.addWidget(subtitle)
        nav_layout.addSpacing(8)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        current_group = ""
        for index, (page_id, label, group) in enumerate(_NAV_ITEMS):
            if group != current_group:
                current_group = group
                section = QLabel(group)
                section.setObjectName("navSection")
                nav_layout.addWidget(section)
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("stage", page_id)
            btn.clicked.connect(lambda _=False, i=index: self._show_page(i))
            self._nav_group.addButton(btn)
            self._nav_buttons.append(btn)
            self._nav_by_id[page_id] = btn
            nav_layout.addWidget(btn)

        nav_layout.addStretch(1)
        return nav

    def _install_shortcuts(self) -> None:
        toggle = QShortcut(QKeySequence("Ctrl+J"), self)
        toggle.setContext(Qt.ShortcutContext.ApplicationShortcut)
        toggle.activated.connect(self.toggle_copilot)

    def current_stage(self) -> str:
        index = self.stack.currentIndex()
        for name, idx in self._page_index.items():
            if idx == index:
                return name
        return "discover"

    def show_stage(self, name: str) -> None:
        index = self._page_index.get(name)
        if index is None:
            return
        self._show_page(index)

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        stage = self.current_stage()
        if stage == "logs":
            self.log_page.refresh()

    def set_copilot_visible(self, visible: bool) -> None:
        self._copilot_open = bool(visible)
        self.copilot_toggle.setChecked(self._copilot_open)
        self.copilot_toggle.setText("Copilot" if not self._copilot_open else "Hide Copilot")
        total = max(self.workspace_splitter.size().width(), 800)
        if self._copilot_open:
            width = max(int(self._copilot_width or 340), 280)
            if width >= total - 200:
                width = max(280, int(total * 0.28))
            self.copilot_panel.setMinimumWidth(260)
            self.copilot_panel.setVisible(True)
            self.workspace_splitter.setSizes([max(total - width, 400), width])
        else:
            sizes = self.workspace_splitter.sizes()
            if len(sizes) > 1 and sizes[1] > 80:
                self._copilot_width = sizes[1]
            self.copilot_panel.setMinimumWidth(0)
            self.workspace_splitter.setSizes([max(total, 1), 0])
            self.copilot_panel.setVisible(False)

    def toggle_copilot(self) -> None:
        self.set_copilot_visible(not self._copilot_open)

    def copilot_is_visible(self) -> bool:
        return bool(self._copilot_open)

    def _on_copilot_splitter_moved(self, _pos: int = 0, _index: int = 0) -> None:
        sizes = self.workspace_splitter.sizes()
        if len(sizes) < 2:
            return
        copilot_w = sizes[1]
        if copilot_w < 40:
            if self._copilot_open:
                self._copilot_open = False
                self.copilot_toggle.setChecked(False)
                self.copilot_toggle.setText("Copilot")
                self.copilot_panel.setMinimumWidth(0)
        elif copilot_w >= 80:
            self._copilot_width = copilot_w
            if not self._copilot_open:
                self._copilot_open = True
                self.copilot_toggle.setChecked(True)
                self.copilot_toggle.setText("Hide Copilot")
                self.copilot_panel.setMinimumWidth(260)

    def _on_copilot_toggled(self, checked: bool) -> None:
        self.set_copilot_visible(checked)

    def _ask_copilot(self, prompt: str = "") -> None:
        self.set_copilot_visible(True)
        if prompt:
            self.copilot_panel.submit_prompt(prompt, send=False)
            self.copilot_panel.input_edit.setFocus()

    def _on_configure_copilot(self) -> None:
        self.show_stage("settings")

    def _on_llm_settings_applied(self, config=None) -> None:  # noqa: ANN001
        controller = self.copilot_panel.controller
        if config is not None:
            controller.set_config(config)
            controller.set_provider(None)
        else:
            controller.reload_config_from_env()
        self.copilot_panel._refresh_availability()
        self.copilot_panel._refresh_state_banner()

    def _start_llm_connection_test(self) -> bool:
        controller = self.copilot_panel.controller
        controller.reload_config_from_env()
        return controller.test_connection(sync=False)

    def _on_llm_connection_test_finished(self, result: object) -> None:
        status = getattr(result, "status", "provider_unavailable")
        message = getattr(result, "message", "Connection test failed.")
        self.settings_page.set_connection_result(str(status), str(message))
        self.copilot_panel._refresh_availability()

    def refresh_workspace(self) -> None:
        convert = self.convert_page
        folder = convert.input_edit.text().strip()
        self.dataset_header.setText(
            safe_folder_label(folder) if folder else "No dataset loaded"
        )
        plan = convert.preview_panel.plan
        session = self.copilot_panel.controller.session
        ctx = None
        if session is not None and plan is not None and plan.items:
            ctx = session.dataset_context()
        scanning = convert.is_scanning()
        report = build_audit_report(ctx=ctx, plan=plan, scanning=scanning)
        planned = 0
        if plan is not None:
            planned = sum(1 for i in plan.items if i.include_in_conversion)
        structure_ok = None
        if not report.empty:
            structure_ok = not any(
                c.key == "validation" and c.level == "FAIL" for c in report.checks
            )
            if structure_ok:
                structure_ok = not any(
                    c.key == "structure" and c.level == "FAIL" for c in report.checks
                )
        self.status_bar.refresh(
            dataset=safe_folder_label(folder) if folder else "No dataset",
            planned=planned,
            issues=report.n_warnings + report.n_review,
            errors=report.n_errors,
            scanning=scanning,
            conversion_busy=convert.is_converting(),
            pending_changeset=self.copilot_panel.controller.pending_changeset is not None,
            has_dataset=bool(plan and plan.items),
            structure_ok=structure_ok,
        )
        if self.current_stage() == "logs":
            self.log_page.refresh()

    def _on_settings_applied(self, config: AppConfig) -> None:
        self.config = config
        self.convert_page.config = config
        self.queue_page.config = config
        path = str(config.dcm2niix_path or "auto")
        if path.strip().lower() not in {"", "auto"}:
            self.convert_page.set_dcm2niix_override(path)
        else:
            self.convert_page.set_dcm2niix_override("")
        self.convert_page.apply_config_defaults()
        self.log_page.config = config
        self.queue_page.manager.options.dcm2niix_path = path
        self.queue_page.manager.options.compress = bool(config.compression)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.convert_page.shutdown()
        self.queue_page.shutdown()
        self.log_page.shutdown()
        super().closeEvent(event)
