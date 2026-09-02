"""Longitudinal subject / session management helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from neuro_pipeline.bids.subject_manager import SubjectManager, SubjectSessionIds


_VISIT_RE = re.compile(
    r"^(?P<subject>.+?)(?:[_/\- ]+(?:ses(?:sion)?|visit|v|timepoint|tp)[_/\- ]*(?P<session>[A-Za-z0-9]+))$",
    re.I,
)
_SUB_PREFIX = re.compile(r"^sub-", re.I)
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


@dataclass(slots=True)
class LongitudinalEntity:
    raw: str
    subject_label: str
    session_label: str | None
    subject_id: str
    session_id: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "raw": self.raw,
            "subject_label": self.subject_label,
            "session_label": self.session_label,
            "subject_id": self.subject_id,
            "session_id": self.session_id,
        }


class LongitudinalManager:
    """Parse and validate single-subject vs multi-session study structures."""

    def __init__(self, subject_manager: SubjectManager | None = None) -> None:
        self.subjects = subject_manager or SubjectManager()

    def parse_subject(self, value: str) -> str:
        """Return bare alphanumeric subject label."""
        text = str(value or "").strip()
        # If combined token includes visit, prefer subject part
        entity = self.parse_subject_session_token(text)
        return self.subjects.validate_subject_id(entity.subject_label)

    def parse_session(self, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return self.subjects.validate_session_id(str(value).strip())

    def parse_subject_session_token(self, token: str) -> LongitudinalEntity:
        """Parse tokens like ``Subject001_visit1`` → sub-Subject001 / ses-01 style labels."""
        raw = str(token or "").strip()
        subject_part = raw
        session_part: str | None = None
        match = _VISIT_RE.match(raw.replace("\\", "/"))
        if match:
            subject_part = match.group("subject")
            session_part = match.group("session")
        subject_label = self._sanitize_label(subject_part)
        session_label = self._sanitize_session(session_part) if session_part else None
        return LongitudinalEntity(
            raw=raw,
            subject_label=subject_label,
            session_label=session_label,
            subject_id=f"sub-{subject_label}" if subject_label else "",
            session_id=f"ses-{session_label}" if session_label else None,
        )

    def validate_structure(self, dataset_root: Path | str) -> list[str]:
        """Return human-readable structure issues (empty list if OK)."""
        root = Path(dataset_root)
        issues: list[str] = []
        if not root.is_dir():
            return [f"Dataset root does not exist: {root}"]
        subjects = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("sub-"))
        if not subjects:
            issues.append("No sub-* folders found")
            return issues
        for sub in subjects:
            sessions = [p for p in sub.iterdir() if p.is_dir() and p.name.startswith("ses-")]
            datatype_dirs = [p for p in sub.iterdir() if p.is_dir() and p.name in {"anat", "dwi", "func", "fmap"}]
            if sessions and datatype_dirs:
                issues.append(
                    f"{sub.name}: mixed session folders and datatype folders at the same level"
                )
        return issues

    def detect_duplicates(self, entities: Iterable[LongitudinalEntity]) -> list[str]:
        seen: set[tuple[str, str | None]] = set()
        dupes: list[str] = []
        for ent in entities:
            key = (ent.subject_label, ent.session_label)
            if key in seen:
                dupes.append(f"{ent.subject_id}" + (f"/{ent.session_id}" if ent.session_id else ""))
            seen.add(key)
        return dupes

    def queue_from_names(self, names: Iterable[str]) -> list[SubjectSessionIds]:
        """Build a session queue from free-text visit names."""
        out: list[SubjectSessionIds] = []
        for name in names:
            ent = self.parse_subject_session_token(name)
            out.append(
                SubjectSessionIds(
                    subject_label=self.subjects.validate_subject_id(ent.subject_label),
                    session_label=self.subjects.validate_session_id(ent.session_label),
                )
            )
        return out

    def _sanitize_label(self, value: str) -> str:
        text = _SUB_PREFIX.sub("", str(value or "").strip())
        text = _NON_ALNUM.sub("", text)
        return text or "unknown"

    def _sanitize_session(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        text = re.sub(r"^(ses|session|visit|v|tp|timepoint)[_-]?", "", text, flags=re.I)
        text = _NON_ALNUM.sub("", text)
        if text.isdigit():
            text = text.zfill(2)
        return text or None
