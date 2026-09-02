"""Global command palette — routes to existing Copilot / navigation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

# kind: ask | prompt | goto
_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("Ask NeuroBIDS…", "ask", ""),
    ("Explain this dataset", "prompt", "Explain this dataset."),
    ("Find acquisitions", "prompt", "Find acquisitions without a clear BIDS mapping."),
    ("Run dataset audit", "goto", "audit"),
    ("Review BIDS mappings", "prompt", "Review the BIDS mappings and list ambiguous acquisitions."),
    ("Check longitudinal consistency", "prompt", "Check longitudinal session consistency across subjects."),
    ("Rename subjects", "prompt", "Propose renaming subjects sequentially from 001. Do not apply changes."),
    ("Prepare release", "goto", "release"),
    ("Open Map", "goto", "map"),
    ("Open Conversion", "goto", "conversion"),
)


class CommandPalette(QDialog):
    """Ctrl+K palette. Natural-language lines go to Copilot.ask()."""

    ask_requested = Signal(str)
    prompt_requested = Signal(str)
    goto_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("What do you want to do?")
        self.setModal(True)
        self.resize(520, 380)
        layout = QVBoxLayout(self)
        title = QLabel("What do you want to do?")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        hint = QLabel("Ask NeuroBIDS, or choose a command. Mutations still require Apply.")
        hint.setObjectName("statusLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Ask NeuroBIDS…")
        self.search.returnPressed.connect(self._accept_search)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemActivated.connect(self._activate)
        self.list.itemDoubleClicked.connect(self._activate)
        layout.addWidget(self.list, 1)
        self._populate()

    def _populate(self, query: str = "") -> None:
        self.list.clear()
        q = query.strip().lower()
        for label, kind, payload in _ACTIONS:
            if q and q not in label.lower() and q not in payload.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, (kind, payload))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _filter(self, text: str) -> None:
        self._populate(text)

    def _accept_search(self) -> None:
        text = self.search.text().strip()
        current = self.list.currentItem()
        if text and (current is None or text.lower() not in (current.text() or "").lower()):
            self.ask_requested.emit(text)
            self.accept()
            return
        if current is not None:
            self._activate(current)
            return
        if text:
            self.ask_requested.emit(text)
            self.accept()

    def _activate(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole) or ("ask", "")
        kind, payload = data
        if kind == "goto":
            self.goto_requested.emit(payload)
        elif kind == "prompt":
            self.prompt_requested.emit(payload)
        else:
            self.ask_requested.emit(self.search.text().strip())
        self.accept()

    @classmethod
    def install(cls, host: QWidget) -> CommandPalette:
        dialog = cls(host)
        shortcut = QShortcut(QKeySequence("Ctrl+K"), host)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(dialog.open_palette)
        host._command_palette = dialog  # type: ignore[attr-defined]
        host._command_palette_shortcut = shortcut  # type: ignore[attr-defined]
        return dialog

    def open_palette(self) -> None:
        self.search.clear()
        self._populate()
        self.search.setFocus()
        self.exec()
