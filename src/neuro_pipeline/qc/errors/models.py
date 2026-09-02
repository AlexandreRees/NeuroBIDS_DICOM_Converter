"""QC status models for silent error detection."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class QCStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass(slots=True)
class QCIssue:
    code: str
    status: QCStatus
    message: str
    path: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(slots=True)
class QCReport:
    status: QCStatus = QCStatus.PASS
    issues: list[QCIssue] = field(default_factory=list)
    warnings: int = 0
    failures: int = 0

    def add(self, issue: QCIssue) -> None:
        self.issues.append(issue)
        if issue.status == QCStatus.WARNING:
            self.warnings += 1
        elif issue.status == QCStatus.FAIL:
            self.failures += 1
        self.status = self._aggregate()

    def _aggregate(self) -> QCStatus:
        if self.failures:
            return QCStatus.FAIL
        if self.warnings:
            return QCStatus.WARNING
        return QCStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "warnings": self.warnings,
            "failures": self.failures,
            "issues": [i.to_dict() for i in self.issues],
        }
