"""Settings page for default conversion preferences and Copilot configuration."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.config.paths import project_root
from neuro_pipeline.gui.naming_rules_panel import NamingRulesPanel
from neuro_pipeline.models.config import AppConfig
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig


class SettingsWidget(QWidget):
    """Application settings (GUI-layer defaults only)."""

    llm_config_changed = Signal(object)  # LLMConfig

    def __init__(
        self,
        config: AppConfig,
        *,
        parent: QWidget | None = None,
        on_apply=None,  # noqa: ANN001
        on_llm_apply=None,  # noqa: ANN001
        connection_tester=None,  # noqa: ANN001 — callable() -> bool
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._on_apply = on_apply
        self._on_llm_apply = on_llm_apply
        self._connection_tester = connection_tester
        self._build_ui()
        self._load_from_config()
        self._load_llm_from_env()
        self._update_llm_fields()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title = QLabel("Settings")
        title.setObjectName("titleLabel")
        title_frame = QFrame()
        title_layout = QVBoxLayout(title_frame)
        title_layout.setContentsMargins(12, 10, 12, 4)
        title_layout.addWidget(title)
        root.addWidget(title_frame)

        tabs = QTabWidget()

        # ── General tab: wrap in a scroll area so it never overflows ──
        general_inner = QWidget()
        general_layout = QVBoxLayout(general_inner)
        general_layout.setContentsMargins(12, 8, 12, 12)
        general_layout.setSpacing(8)

        general_scroll = QScrollArea()
        general_scroll.setWidgetResizable(True)
        general_scroll.setFrameShape(QFrame.Shape.NoFrame)
        general_scroll.setWidget(general_inner)
        general = general_scroll  # used below for tabs.addTab

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

        general_layout.addWidget(self._build_copilot_box())

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

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        general_layout.addWidget(self.status_label)

        general_layout.addStretch(1)

        tabs.addTab(general_scroll, "General")
        self.naming_rules_panel = NamingRulesPanel()
        tabs.addTab(self.naming_rules_panel, "Nomenclature BIDS")
        root.addWidget(tabs, 1)

    def _build_copilot_box(self) -> QGroupBox:
        copilot_box = QGroupBox("NeuroBIDS Copilot")
        copilot_layout = QVBoxLayout(copilot_box)

        intro = QLabel(
            "AI Copilot is optional. NeuroBIDS works without an AI provider.\n"
            "Ollama is not required for conversion, audit, or BIDS curation."
        )
        intro.setObjectName("statusLabel")
        intro.setWordWrap(True)
        copilot_layout.addWidget(intro)

        mode_row = QHBoxLayout()
        self.radio_llm_none = QRadioButton("Disabled")
        self.radio_llm_local = QRadioButton("Local AI (Ollama)")
        self.radio_llm_remote = QRadioButton("OpenAI-compatible API")
        self.llm_mode_group = QButtonGroup(self)
        self.llm_mode_group.addButton(self.radio_llm_none)
        self.llm_mode_group.addButton(self.radio_llm_local)
        self.llm_mode_group.addButton(self.radio_llm_remote)
        mode_row.addWidget(self.radio_llm_none)
        mode_row.addWidget(self.radio_llm_local)
        mode_row.addWidget(self.radio_llm_remote)
        mode_row.addStretch(1)
        copilot_layout.addLayout(mode_row)
        self.radio_llm_none.toggled.connect(self._update_llm_fields)
        self.radio_llm_local.toggled.connect(self._update_llm_fields)
        self.radio_llm_remote.toggled.connect(self._update_llm_fields)

        self.llm_privacy = QLabel("")
        self.llm_privacy.setObjectName("statusLabel")
        self.llm_privacy.setWordWrap(True)
        copilot_layout.addWidget(self.llm_privacy)

        form = QFormLayout()
        self.llm_base_url = QLineEdit()
        self.llm_base_url.setPlaceholderText("http://localhost:11434/v1")
        self.llm_model = QLineEdit()
        self.llm_model.setPlaceholderText("Model name (e.g. qwen3:30b or gpt-4o-mini)")
        self.llm_api_key = QLineEdit()
        self.llm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_api_key.setPlaceholderText("Leave blank to keep the existing key")
        self.llm_api_key_status = QLabel("")
        self.llm_api_key_status.setObjectName("statusLabel")
        form.addRow("Base URL", self.llm_base_url)
        form.addRow("Model", self.llm_model)
        form.addRow("API key", self.llm_api_key)
        form.addRow("", self.llm_api_key_status)
        copilot_layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.llm_test_btn = QPushButton("Test connection")
        self.llm_test_btn.clicked.connect(self._test_connection)
        self.llm_ollama_btn = QPushButton("Learn how to install Ollama")
        self.llm_ollama_btn.clicked.connect(self._open_ollama_docs)
        self.llm_clear_key_btn = QPushButton("Clear API key")
        self.llm_clear_key_btn.clicked.connect(self._clear_api_key)
        btn_row.addWidget(self.llm_test_btn)
        btn_row.addWidget(self.llm_ollama_btn)
        btn_row.addWidget(self.llm_clear_key_btn)
        btn_row.addStretch(1)
        copilot_layout.addLayout(btn_row)

        self.llm_status = QLabel("")
        self.llm_status.setObjectName("statusLabel")
        self.llm_status.setWordWrap(True)
        copilot_layout.addWidget(self.llm_status)

        hint = QLabel(
            "Settings apply for this session. API keys are never shown and are not "
            "written to disk by NeuroBIDS. You can also set NEUROBIDS_LLM_* environment variables."
        )
        hint.setObjectName("statusLabel")
        hint.setWordWrap(True)
        copilot_layout.addWidget(hint)
        return copilot_box

    def _load_from_config(self) -> None:
        self.dcm2niix_edit.setText(str(self.config.dcm2niix_path or "auto"))
        layout = str(getattr(self.config, "output_layout", "nifti") or "nifti").lower()
        if layout == "bids":
            self.radio_bids.setChecked(True)
        else:
            self.radio_nifti.setChecked(True)
        self.chk_compress.setChecked(bool(self.config.compression))
        self.config_edit.setText(str(project_root() / "configs"))

    def _load_llm_from_env(self) -> None:
        cfg = LLMConfig.from_env()
        provider = (cfg.provider or "none").lower()
        if provider in {"local"}:
            self.radio_llm_local.setChecked(True)
        elif provider in {"openai", "compatible", "azure"}:
            self.radio_llm_remote.setChecked(True)
        else:
            self.radio_llm_none.setChecked(True)
        self.llm_model.setText(cfg.model or "")
        self.llm_base_url.setText(cfg.base_url or "")
        self.llm_api_key.clear()
        self._refresh_api_key_status(cfg)

    def _refresh_api_key_status(self, cfg: LLMConfig | None = None) -> None:
        cfg = cfg or LLMConfig.from_env()
        if cfg.api_key_configured:
            self.llm_api_key_status.setText("API key: configured (value hidden)")
        else:
            self.llm_api_key_status.setText("API key: not configured")

    def _selected_provider(self) -> str:
        if self.radio_llm_local.isChecked():
            return "local"
        if self.radio_llm_remote.isChecked():
            return "openai"
        return "none"

    def _update_llm_fields(self) -> None:
        provider = self._selected_provider()
        local = provider == "local"
        remote = provider == "openai"
        enabled = local or remote
        self.llm_base_url.setEnabled(enabled)
        self.llm_model.setEnabled(enabled)
        self.llm_api_key.setEnabled(remote)
        self.llm_clear_key_btn.setEnabled(remote)
        self.llm_test_btn.setEnabled(enabled)
        self.llm_ollama_btn.setVisible(local or provider == "none")
        if provider == "none":
            self.llm_privacy.setText(
                "NeuroBIDS itself works without AI. Conversion, audit, and BIDS curation stay available."
            )
        elif local:
            self.llm_privacy.setText(
                "Run an LLM locally using Ollama. Inference stays on this machine. "
                "NeuroBIDS does not install Ollama automatically."
            )
            if not self.llm_base_url.text().strip():
                self.llm_base_url.setText("http://localhost:11434/v1")
        else:
            self.llm_privacy.setText(
                "Remote APIs may send prompts and dataset context summaries to an external service. "
                "Do not use a remote provider with identifiable patient data unless your policy allows it."
            )

    def build_llm_config(self, *, clear_api_key: bool = False) -> LLMConfig:
        """Assemble LLMConfig from the form + existing env key when blank."""
        current = LLMConfig.from_env()
        provider = self._selected_provider()
        typed_key = self.llm_api_key.text().strip()
        if clear_api_key:
            api_key = ""
        elif typed_key:
            api_key = typed_key
        else:
            api_key = current.api_key
        base = self.llm_base_url.text().strip()
        if provider == "local" and not base:
            base = "http://localhost:11434/v1"
        return LLMConfig(
            provider=provider,
            model=self.llm_model.text().strip(),
            api_key=api_key,
            base_url=base,
            timeout_seconds=current.timeout_seconds,
            max_tool_calls=current.max_tool_calls,
            max_retries=current.max_retries,
            retry_backoff_seconds=current.retry_backoff_seconds,
        )

    def set_connection_result(self, status: str, message: str) -> None:
        """Update the connection-test status label (called from MainWindow)."""
        label = {
            "connected": "Connected",
            "provider_unavailable": "Provider unavailable",
            "model_unavailable": "Model unavailable",
            "invalid_configuration": "Invalid configuration",
            "timeout": "Timeout",
        }.get(status, status or "Unknown")
        self.llm_status.setText(f"{label}: {message}")
        self.llm_test_btn.setEnabled(self._selected_provider() != "none")

    def _test_connection(self) -> None:
        cfg = self.build_llm_config()
        cfg.apply_to_environ(include_api_key=True)
        self.llm_api_key.clear()
        self._refresh_api_key_status(cfg)
        self.llm_status.setText("Testing connection…")
        self.llm_test_btn.setEnabled(False)
        if callable(self._connection_tester):
            started = bool(self._connection_tester())
            if not started:
                self.llm_status.setText("Could not start connection test.")
                self.llm_test_btn.setEnabled(True)
            return
        # Fallback sync probe (tests / headless)
        from neuro_pipeline.neurobids.copilot.llm.connection import probe_llm_connection

        result = probe_llm_connection(cfg)
        self.set_connection_result(result.status, result.message)

    def _open_ollama_docs(self) -> None:
        QDesktopServices.openUrl(QUrl("https://ollama.com/download"))

    def _clear_api_key(self) -> None:
        self.llm_api_key.clear()
        cfg = self.build_llm_config(clear_api_key=True)
        cfg.apply_to_environ(include_api_key=True)
        self._refresh_api_key_status(cfg)
        self.llm_status.setText("API key cleared for this session.")

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

        llm = self.build_llm_config()
        llm.apply_to_environ(include_api_key=True)
        self.llm_api_key.clear()
        self._refresh_api_key_status(llm)
        self.llm_config_changed.emit(llm)
        if callable(self._on_llm_apply):
            self._on_llm_apply(llm)

        self.status_label.setText(
            f"Settings applied for this session. Copilot: {llm.provider_label}."
        )
