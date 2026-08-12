"""Main application window — navigation shell + stacked pages."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui.convert_widget import ConvertWidget
from neuro_pipeline.gui.conversion_queue_widget import ConversionQueueWidget
from neuro_pipeline.gui.log_widget import LogWidget
from neuro_pipeline.gui.settings_widget import SettingsWidget
from neuro_pipeline.models.config import AppConfig
from neuro_pipeline.utils.naming import SmartFilenameEngine

LOGGER = logging.getLogger(__name__)

_NAV_ITEMS = (
    ("Convert", 0),
    ("Queue", 1),
    ("Settings", 2),
    ("Logs", 3),
)


class MainWindow(QMainWindow):
    """NeuroPipeline DICOM Converter main window."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._naming_engine = self._load_naming_engine()

        self.setWindowTitle("NeuroPipeline DICOM Converter")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 650)
        self._build_ui()

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

        # ---- Left navigation ----
        nav = QFrame()
        nav.setObjectName("navPanel")
        nav.setFixedWidth(148)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(10, 14, 10, 14)
        nav_layout.setSpacing(6)

        brand = QLabel("NeuroPipeline")
        brand.setObjectName("navBrand")
        brand.setWordWrap(True)
        nav_layout.addWidget(brand)
        subtitle = QLabel("DICOM Converter")
        subtitle.setObjectName("navSubtitle")
        nav_layout.addWidget(subtitle)
        nav_layout.addSpacing(12)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for label, index in _NAV_ITEMS:
            btn = QPushButton(label)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=index: self._show_page(i))
            self._nav_group.addButton(btn)
            self._nav_buttons.append(btn)
            nav_layout.addWidget(btn)

        nav_layout.addStretch(1)
        layout.addWidget(nav)

        # ---- Right content stack ----
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)

        self.convert_page = ConvertWidget(self.config, self._naming_engine)
        self.queue_page = ConversionQueueWidget(self.config)
        self.settings_page = SettingsWidget(
            self.config, on_apply=self._on_settings_applied
        )
        self.log_page = LogWidget(self.config)

        self.stack.addWidget(self.convert_page)
        self.stack.addWidget(self.queue_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.log_page)

        self._nav_buttons[0].setChecked(True)
        self._show_page(0)

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        if index == 3:
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
