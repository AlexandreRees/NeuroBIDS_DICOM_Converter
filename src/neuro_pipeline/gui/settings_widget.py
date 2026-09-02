"""Settings page for default conversion preferences."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.config.paths import project_root
from neuro_pipeline.gui.naming_rules_panel import NamingRulesPanel
from neuro_pipeline.models.config import AppConfig


class SettingsWidget(QWidget):
    """Application settings (GUI-layer defaults only)."""

    def __init__(
        self,
        config: AppConfig,
        *,
        parent: QWidget | None = None,
        on_apply=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._on_apply = on_apply
        self._build_ui()
        self._load_from_config()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        title = QLabel("Settings")
        title.setObjectName("titleLabel")
        root.addWidget(title)

        tabs = QTabWidget()
        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.setContentsMargins(0, 8, 0, 0)

        dcm_box = QGroupBox("dcm2niix")
        dcm_layout = QHBoxLayout(dcm_box)
        self.dcm2niix_edit = QLineEdit()
        self.dcm2niix_edit.setPlaceholderText("auto or path to executable")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_dcm2niix)
        dcm_layout.addWidget(QLabel("Location:"))
        dcm_layout.addWidget(self.dcm2niix_edit, 1)
        dcm_layout.addWidget(browse)
        general_layout.addWidget(dcm_box)

        fmt_box = QGroupBox("Default output format")
        fmt_layout = QHBoxLayout(fmt_box)
        self.radio_nifti = QRadioButton("NIfTI folder")
        self.radio_bids = QRadioButton("BIDS dataset")
        self.format_group = QButtonGroup(self)
        self.format_group.addButton(self.radio_nifti)
        self.format_group.addButton(self.radio_bids)
        fmt_layout.addWidget(self.radio_nifti)
        fmt_layout.addWidget(self.radio_bids)
        fmt_layout.addStretch(1)
        general_layout.addWidget(fmt_box)

        opt_box = QGroupBox("Defaults")
        opt_layout = QVBoxLayout(opt_box)
        self.chk_compress = QCheckBox("Default compression (.nii.gz)")
        opt_layout.addWidget(self.chk_compress)
        general_layout.addWidget(opt_box)

        cfg_box = QGroupBox("Config folder")
        cfg_layout = QHBoxLayout(cfg_box)
        self.config_edit = QLineEdit()
        self.config_edit.setReadOnly(True)
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(self._open_config_folder)
        cfg_layout.addWidget(self.config_edit, 1)
        cfg_layout.addWidget(open_btn)
        general_layout.addWidget(cfg_box)

        apply_row = QHBoxLayout()
        apply_row.addStretch(1)
        self.apply_btn = QPushButton("Apply settings")
        self.apply_btn.setObjectName("primaryButton")
        self.apply_btn.clicked.connect(self._apply)
        apply_row.addWidget(self.apply_btn)
        general_layout.addLayout(apply_row)
        general_layout.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        general_layout.addWidget(self.status_label)

        tabs.addTab(general, "General")
        self.naming_rules_panel = NamingRulesPanel()
        tabs.addTab(self.naming_rules_panel, "Naming Rules")
        root.addWidget(tabs, 1)

    def _load_from_config(self) -> None:
        self.dcm2niix_edit.setText(str(self.config.dcm2niix_path or "auto"))
        layout = str(getattr(self.config, "output_layout", "nifti") or "nifti").lower()
        if layout == "bids":
            self.radio_bids.setChecked(True)
        else:
            self.radio_nifti.setChecked(True)
        self.chk_compress.setChecked(bool(self.config.compression))
        self.config_edit.setText(str(project_root() / "configs"))

    def _browse_dcm2niix(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Locate dcm2niix",
            "",
            "Executable (dcm2niix.exe dcm2niix);;All files (*)",
        )
        if path:
            self.dcm2niix_edit.setText(path)

    def _open_config_folder(self) -> None:
        from neuro_pipeline.gui.convert_widget import _open_path

        folder = Path(self.config_edit.text().strip() or (project_root() / "configs"))
        folder.mkdir(parents=True, exist_ok=True)
        _open_path(folder)

    def _apply(self) -> None:
        path = self.dcm2niix_edit.text().strip() or "auto"
        self.config.dcm2niix_path = path
        self.config.output_layout = "bids" if self.radio_bids.isChecked() else "nifti"
        self.config.compression = self.chk_compress.isChecked()
        if callable(self._on_apply):
            self._on_apply(self.config)
        self.status_label.setText("Settings applied for this session.")
