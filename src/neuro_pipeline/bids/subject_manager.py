"""BIDS subject / session identity helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_LABEL_RE = re.compile(r"^[A-Za-z0-9]+$")


@dataclass(slots=True)
class SubjectSessionIds:
    """Normalized BIDS subject / optional session labels (without prefixes)."""

    subject_label: str
    session_label: str | None = None

    @property
    def subject_id(self) -> str:
        return f"sub-{self.subject_label}"

    @property
    def session_id(self) -> str | None:
        return f"ses-{self.session_label}" if self.session_label else None


class SubjectManager:
    """Validate and create BIDS-compliant subject (/ session) folders."""

    def validate_subject_id(self, value: str) -> str:
        """Return bare subject label (without ``sub-``)."""
        label = self._normalize_label(value, prefix="sub-")
        if not label:
            raise ValueError("Subject ID is required")
        if not _LABEL_RE.fullmatch(label):
            raise ValueError(
                "Subject ID must be alphanumeric only (BIDS: sub-<label>). "
                "Spaces and special characters are not allowed."
            )
        return label

    def validate_session_id(self, value: str | None) -> str | None:
        """Return bare session label (without ``ses-``) or None if empty."""
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        label = self._normalize_label(raw, prefix="ses-")
        if not _LABEL_RE.fullmatch(label):
            raise ValueError(
                "Session ID must be alphanumeric only (BIDS: ses-<label>). "
                "Spaces and special characters are not allowed."
            )
        return label

    def create_bids_subject(
        self,
        dataset_root: Path | str,
        subject: str,
        session: str | None = None,
    ) -> Path:
        """Create ``sub-<id>[/ses-<id>]`` under the dataset root."""
        ids = SubjectSessionIds(
            subject_label=self.validate_subject_id(subject),
            session_label=self.validate_session_id(session),
        )
        root = Path(dataset_root)
        path = root / ids.subject_id
        if ids.session_label:
            path = path / ids.session_id  # type: ignore[operator]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def parse(self, subject: str, session: str | None = None) -> SubjectSessionIds:
        return SubjectSessionIds(
            subject_label=self.validate_subject_id(subject),
            session_label=self.validate_session_id(session),
        )

    @staticmethod
    def _normalize_label(value: str, *, prefix: str) -> str:
        text = str(value).strip()
        lower = text.lower()
        pref = prefix.lower()
        if lower.startswith(pref):
            text = text[len(prefix) :]
        return text.strip()
