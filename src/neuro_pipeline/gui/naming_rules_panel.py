"""Settings UI for lab-defined BIDS naming rules."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.bids.naming_rules import NamingRule, SmartNamingRulesEngine
from neuro_pipeline.gui import dialogs


class NamingRulesPanel(QWidget):
    """Manage JSON-backed smart naming rules."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = SmartNamingRulesEngine.load()
        self._build_ui()
        self._refresh_table()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(
            "Optional custom BIDS naming rules. Priority: User rules → "
            "sequence classifier → default BIDS naming. Empty rules = unchanged behaviour."
        )
        hint.setWordWrap(True)
        hint.setObjectName("statusLabel")
        root.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Activée", "Nom de la règle", "Condition", "Action", "Priorité"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        root.addWidget(self.table, 1)

        # Row 1: main editing actions
        row1 = QHBoxLayout()
        self.add_btn = QPushButton("+ Ajouter")
        self.edit_btn = QPushButton("Modifier")
        self.dup_btn = QPushButton("Dupliquer")
        self.del_btn = QPushButton("Supprimer")
        for b in (self.add_btn, self.edit_btn, self.dup_btn, self.del_btn):
            row1.addWidget(b)
        row1.addStretch(1)
        root.addLayout(row1)

        # Row 2: import / export / validate / save
        row2 = QHBoxLayout()
        self.import_btn = QPushButton("Importer JSON")
        self.export_btn = QPushButton("Exporter JSON")
        self.validate_btn = QPushButton("Valider")
        self.save_btn = QPushButton("Enregistrer")
        self.save_btn.setObjectName("primaryButton")
        for b in (self.import_btn, self.export_btn, self.validate_btn, self.save_btn):
            row2.addWidget(b)
        row2.addStretch(1)
        root.addLayout(row2)

        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        root.addWidget(self.status)

        self.add_btn.clicked.connect(self._add)
        self.edit_btn.clicked.connect(self._edit)
        self.dup_btn.clicked.connect(self._duplicate)
        self.del_btn.clicked.connect(self._delete)
        self.import_btn.clicked.connect(self._import)
        self.export_btn.clicked.connect(self._export)
        self.validate_btn.clicked.connect(self._validate)
        self.save_btn.clicked.connect(self._save)

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        for rule in sorted(self.engine.rules, key=lambda r: (r.priority, r.name)):
            row = self.table.rowCount()
            self.table.insertRow(row)
            enabled = QTableWidgetItem("Yes" if rule.enabled else "No")
            enabled.setData(Qt.ItemDataRole.UserRole, rule.name)
            values = [
                enabled,
                QTableWidgetItem(rule.name),
                QTableWidgetItem(rule.condition_summary()),
                QTableWidgetItem(rule.action_summary()),
                QTableWidgetItem(str(rule.priority)),
            ]
            for col, item in enumerate(values):
                self.table.setItem(row, col, item)

    def _selected_rule(self) -> NamingRule | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        name = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        for rule in self.engine.rules:
            if rule.name == name:
                return rule
        return None

    def _add(self) -> None:
        rule = NamingRule(name="New rule", priority=100, conditions={}, actions={})
        if NamingRuleDialog.edit(self, rule):
            self.engine.rules.append(rule)
            self._refresh_table()

    def _edit(self, _index=None) -> None:  # accepts doubleClicked signal arg
        rule = self._selected_rule()
        if rule is None:
            dialogs.show_warning(self, "Règles de nomenclature", "Sélectionnez une règle à modifier.")
            return
        if NamingRuleDialog.edit(self, rule):
            self._refresh_table()

    def _duplicate(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            return
        clone = NamingRule.from_dict(rule.to_dict())
        clone.name = f"{rule.name} copy"
        clone.priority = int(rule.priority) + 1
        self.engine.rules.append(clone)
        self._refresh_table()

    def _delete(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            return
        if not dialogs.confirm(self, "Supprimer la règle", f"Supprimer la règle {rule.name!r} ?"):
            return
        self.engine.rules = [r for r in self.engine.rules if r is not rule]
        self._refresh_table()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import naming rules", "", "JSON (*.json)")
        if not path:
            return
        loaded = SmartNamingRulesEngine.load(path)
        self.engine.rules = list(loaded.rules)
        self._refresh_table()
        self.status.setText(f"Imported {len(self.engine.rules)} rules from {path}")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export naming rules", "naming_rules.json", "JSON (*.json)"
        )
        if not path:
            return
        saved = self.engine.save(path)
        self.status.setText(f"Exported to {saved}")

    def _validate(self) -> None:
        result = self.engine.validate()
        self.status.setText(result.summary().replace("\n", " | "))
        if result.ok:
            dialogs.show_info(self, "Naming rules", result.summary())
        else:
            dialogs.show_warning(self, "Naming rules invalid", result.summary())

    def _save(self) -> None:
        result = self.engine.validate()
        if not result.ok:
            dialogs.show_warning(
                self,
                "Cannot save naming rules",
                "Fix validation errors first.\n\n" + result.summary(),
            )
            return
        saved = self.engine.save()
        self.status.setText(f"Saved to {saved}")
        dialogs.show_info(self, "Naming rules saved", f"Saved:\n{saved}")


class NamingRuleDialog(QDialog):
    """Create / edit one naming rule."""

    def __init__(self, rule: NamingRule, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rule = rule
        self.setWindowTitle("Naming rule")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(rule.name)
        self.enabled_chk = QCheckBox("Enabled")
        self.enabled_chk.setChecked(rule.enabled)
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(0, 10_000)
        self.priority_spin.setValue(int(rule.priority))
        self.conditions_edit = QTextEdit()
        self.conditions_edit.setPlaceholderText(
            'One condition per line:\nProtocolName_contains=REST_AP\nSeriesDescription_contains=REST'
        )
        self.conditions_edit.setPlainText(
            "\n".join(f"{k}={v}" for k, v in rule.conditions.items())
        )
        self.actions_edit = QTextEdit()
        self.actions_edit.setPlaceholderText(
            "One action per line:\ntask=rest\ndatatype=func\nsuffix=bold"
        )
        self.actions_edit.setPlainText("\n".join(f"{k}={v}" for k, v in rule.actions.items()))
        form.addRow("Name", self.name_edit)
        form.addRow(self.enabled_chk)
        form.addRow("Priority (lower = higher)", self.priority_spin)
        form.addRow("Conditions", self.conditions_edit)
        form.addRow("Actions", self.actions_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @classmethod
    def edit(cls, parent: QWidget, rule: NamingRule) -> bool:
        dlg = cls(rule, parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        rule.name = dlg.name_edit.text().strip() or "Unnamed rule"
        rule.enabled = dlg.enabled_chk.isChecked()
        rule.priority = int(dlg.priority_spin.value())
        rule.conditions = _parse_kv_lines(dlg.conditions_edit.toPlainText())
        rule.actions = _parse_kv_lines(dlg.actions_edit.toPlainText())
        return True


def _parse_kv_lines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out
