"""NeuroBIDS dataset context (metadata only — no DICOM pixels).

This layer is for reasoning and BIDS curation (e.g. NeuroBIDS Copilot).
It reuses existing plan / series models as *inputs* and never mutates
DICOM files or the conversion pipeline.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from neuro_pipeline.bids.conversion_plan import (
    BIDSConversionPlan,
    PlannedAcquisition,
    PlanValidationResult,
)
from neuro_pipeline.logging.privacy import safe_folder_label
from neuro_pipeline.models import DicomSeries

# Soft limits for LLM payloads (characters / items).
_LLM_DESC_MAX = 80
_LLM_ISSUES_MAX = 40
_LLM_ACQ_PER_SESSION_MAX = 80


@dataclass(slots=True)
class MetadataIssue:
    """One metadata / mapping / validation concern (never pixel data)."""

    level: str  # "error" | "warning" | "info"
    message: str
    code: str = ""
    series_uid: str = ""
    subject: str = ""
    session: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "series_uid": self.series_uid,
            "subject": self.subject,
            "session": self.session,
        }

    def to_llm_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "level": self.level,
            "message": _truncate(self.message, 160),
        }
        if self.code:
            out["code"] = self.code
        if self.series_uid:
            out["series_uid"] = _short_uid(self.series_uid)
        if self.subject:
            out["subject"] = self.subject
        if self.session:
            out["session"] = self.session
        return out


@dataclass(slots=True)
class BidsMappingContext:
    """BIDS entity mapping for one acquisition (plan-side only)."""

    subject: str = ""
    session: str = ""
    datatype: str = ""
    suffix: str = ""
    task: str = ""
    run: str = ""
    acquisition: str = ""
    direction: str = ""
    intended_filename: str = ""
    include: bool = True
    naming_rule_applied: str = ""
    confidence_score: float = 0.0
    classification_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_llm_dict(self) -> dict[str, Any]:
        """Compact mapping; omit empty optional entities."""
        out: dict[str, Any] = {
            "subject": self.subject,
            "datatype": self.datatype,
            "suffix": self.suffix,
            "include": self.include,
        }
        if self.session:
            out["session"] = self.session
        if self.task:
            out["task"] = self.task
        if self.run:
            out["run"] = self.run
        if self.acquisition:
            out["acquisition"] = self.acquisition
        if self.direction:
            out["direction"] = self.direction
        if self.intended_filename:
            out["filename"] = self.intended_filename
        if self.naming_rule_applied:
            out["naming_rule"] = self.naming_rule_applied
        if self.confidence_score:
            out["confidence"] = round(float(self.confidence_score), 3)
        if self.classification_source:
            out["classification_source"] = self.classification_source
        return out


@dataclass(slots=True)
class AcquisitionContext:
    """One DICOM series as curation metadata (no pixels, no absolute paths)."""

    series_uid: str
    series_number: int | None = None
    series_description: str = ""
    protocol_name: str = ""
    modality: str = ""
    sequence_type: str = "unknown"
    fine_sequence_type: str = ""
    num_images: int = 0
    convertibility: str = ""
    convertible_to_nifti: bool = True
    requires_manual_mapping: bool = False
    source_subject_folder: str = ""
    bids: BidsMappingContext | None = None
    metadata_issues: list[MetadataIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_uid": self.series_uid,
            "series_number": self.series_number,
            "series_description": self.series_description,
            "protocol_name": self.protocol_name,
            "modality": self.modality,
            "sequence_type": self.sequence_type,
            "fine_sequence_type": self.fine_sequence_type,
            "num_images": self.num_images,
            "convertibility": self.convertibility,
            "convertible_to_nifti": self.convertible_to_nifti,
            "requires_manual_mapping": self.requires_manual_mapping,
            "source_subject_folder": self.source_subject_folder,
            "bids": None if self.bids is None else self.bids.to_dict(),
            "metadata_issues": [i.to_dict() for i in self.metadata_issues],
        }

    def to_llm_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "uid": _short_uid(self.series_uid),
            "desc": _truncate(self.series_description or self.protocol_name, _LLM_DESC_MAX),
            "modality": self.modality or "MR",
            "seq": self.sequence_type or "unknown",
        }
        if self.series_number is not None:
            out["series_number"] = self.series_number
        if self.fine_sequence_type:
            out["fine_seq"] = self.fine_sequence_type
        if self.num_images:
            out["n_images"] = self.num_images
        if self.requires_manual_mapping:
            out["needs_manual_mapping"] = True
        if not self.convertible_to_nifti:
            out["convertible"] = False
            if self.convertibility:
                out["convertibility"] = self.convertibility
        if self.bids is not None:
            out["bids"] = self.bids.to_llm_dict()
        if self.metadata_issues:
            out["issues"] = [i.to_llm_dict() for i in self.metadata_issues[:10]]
        return out


@dataclass(slots=True)
class SessionContext:
    """One session under a subject."""

    session_id: str
    acquisitions: list[AcquisitionContext] = field(default_factory=list)

    @property
    def modalities(self) -> list[str]:
        return sorted({a.modality for a in self.acquisitions if a.modality})

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "modalities": self.modalities,
            "acquisitions": [a.to_dict() for a in self.acquisitions],
        }

    def to_llm_dict(self) -> dict[str, Any]:
        acqs = self.acquisitions[:_LLM_ACQ_PER_SESSION_MAX]
        out: dict[str, Any] = {
            "session": self.session_id or None,
            "n_acquisitions": len(self.acquisitions),
            "modalities": self.modalities,
            "acquisitions": [a.to_llm_dict() for a in acqs],
        }
        if len(self.acquisitions) > len(acqs):
            out["acquisitions_truncated"] = True
        return out


@dataclass(slots=True)
class SubjectContext:
    """One subject with nested sessions."""

    subject_id: str
    sessions: list[SessionContext] = field(default_factory=list)
    source_folder: str = ""
    detection_method: str = ""

    @property
    def modalities(self) -> list[str]:
        mods: set[str] = set()
        for ses in self.sessions:
            mods.update(ses.modalities)
        return sorted(mods)

    @property
    def n_acquisitions(self) -> int:
        return sum(len(s.acquisitions) for s in self.sessions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "source_folder": self.source_folder,
            "detection_method": self.detection_method,
            "modalities": self.modalities,
            "sessions": [s.to_dict() for s in self.sessions],
        }

    def to_llm_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject_id,
            "n_sessions": len(self.sessions),
            "n_acquisitions": self.n_acquisitions,
            "modalities": self.modalities,
            "sessions": [s.to_llm_dict() for s in self.sessions],
        }


@dataclass(slots=True)
class DatasetContext:
    """Currently loaded neuroimaging dataset for NeuroBIDS reasoning.

    Contains subjects, sessions, acquisitions, modalities, metadata issues,
    and BIDS mappings. Never contains DICOM pixel data.
    """

    dataset_label: str = ""
    output_label: str = ""
    detection_method: str = ""
    detection_reason: str = ""
    subjects: list[SubjectContext] = field(default_factory=list)
    metadata_issues: list[MetadataIssue] = field(default_factory=list)
    n_series: int = 0
    n_dicom_files: int = 0
    n_subjects: int = 0

    # ------------------------------------------------------------------
    # Factories (reuse existing models; do not alter conversion pipeline)
    # ------------------------------------------------------------------

    @classmethod
    def from_conversion_plan(
        cls,
        plan: BIDSConversionPlan,
        *,
        series_list: Sequence[DicomSeries] | None = None,
        validation: PlanValidationResult | None = None,
        detection_method: str = "",
        detection_reason: str = "",
        n_dicom_files: int = 0,
    ) -> DatasetContext:
        """Build context from an existing :class:`BIDSConversionPlan`.

        Prefer ``series_list`` when available; otherwise use plan-backed
        series (metadata fields only — never pixels).
        """
        series_by_uid: dict[str, DicomSeries] = {}
        if series_list is not None:
            for s in series_list:
                uid = s.series_instance_uid or s.display_name
                series_by_uid[uid] = s
        else:
            # Access plan's private cache only as a fallback for metadata.
            series_by_uid = dict(getattr(plan, "_series_by_uid", {}) or {})

        issues = _issues_from_validation(validation)
        issues_by_uid: dict[str, list[MetadataIssue]] = defaultdict(list)
        dataset_issues: list[MetadataIssue] = []
        for issue in issues:
            if issue.series_uid:
                issues_by_uid[issue.series_uid].append(issue)
            else:
                dataset_issues.append(issue)

        # Group planned acquisitions by subject → session.
        grouped: dict[str, dict[str, list[tuple[PlannedAcquisition, DicomSeries | None]]]] = (
            defaultdict(lambda: defaultdict(list))
        )
        for item in plan.items:
            series = series_by_uid.get(item.source_series_uid)
            subj = item.subject or "unknown"
            ses = item.session or ""
            grouped[subj][ses].append((item, series))

        subjects: list[SubjectContext] = []
        for subject_id in sorted(grouped.keys()):
            sessions: list[SessionContext] = []
            for session_id in sorted(grouped[subject_id].keys(), key=lambda x: (x == "", x)):
                acqs: list[AcquisitionContext] = []
                for item, series in grouped[subject_id][session_id]:
                    acqs.append(
                        _acquisition_from_planned(
                            item,
                            series,
                            issues_by_uid.get(item.source_series_uid, []),
                        )
                    )
                sessions.append(SessionContext(session_id=session_id, acquisitions=acqs))
            subjects.append(
                SubjectContext(
                    subject_id=subject_id,
                    sessions=sessions,
                    source_folder=_folder_label_for_subject(grouped[subject_id]),
                )
            )

        # Heuristic issues from series metadata (manual mapping / non-convertible).
        for subject in subjects:
            for session in subject.sessions:
                for acq in session.acquisitions:
                    dataset_issues.extend(_heuristic_issues(acq, subject.subject_id, session.session_id))

        return cls(
            dataset_label=safe_folder_label(plan.dataset_root) if plan.dataset_root else "",
            output_label=safe_folder_label(plan.output_root) if plan.output_root else "",
            detection_method=detection_method,
            detection_reason=detection_reason,
            subjects=subjects,
            metadata_issues=_dedupe_issues(dataset_issues),
            n_series=len(plan.items),
            n_dicom_files=n_dicom_files,
            n_subjects=len(subjects),
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Full JSON-serializable representation (metadata only)."""
        return {
            "dataset_label": self.dataset_label,
            "output_label": self.output_label,
            "detection_method": self.detection_method,
            "detection_reason": self.detection_reason,
            "n_subjects": self.n_subjects or len(self.subjects),
            "n_series": self.n_series,
            "n_dicom_files": self.n_dicom_files,
            "modalities": self.modalities,
            "metadata_issues": [i.to_dict() for i in self.metadata_issues],
            "subjects": [s.to_dict() for s in self.subjects],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_llm_context(self) -> dict[str, Any]:
        """Compact, PHI-aware payload suitable for an LLM prompt.

        Omits absolute paths and patient names; truncates long descriptions;
        prefers BIDS mappings and validation issues for curation reasoning.
        """
        issues = [i.to_llm_dict() for i in self.metadata_issues[:_LLM_ISSUES_MAX]]
        return {
            "dataset": self.dataset_label or "unnamed",
            "output": self.output_label or None,
            "detection": {
                "method": self.detection_method or None,
                "reason": _truncate(self.detection_reason, 120) or None,
            },
            "counts": {
                "subjects": self.n_subjects or len(self.subjects),
                "series": self.n_series,
                "dicom_files": self.n_dicom_files or None,
                "issues": len(self.metadata_issues),
            },
            "modalities": self.modalities,
            "datatype_summary": self.datatype_summary,
            "issues": issues,
            "subjects": [s.to_llm_dict() for s in self.subjects],
            "notes": [
                "Source DICOM is read-only; only BIDS mappings are editable.",
                "No DICOM pixel data is included.",
            ],
        }

    # ------------------------------------------------------------------
    # Derived summaries
    # ------------------------------------------------------------------

    @property
    def modalities(self) -> list[str]:
        mods: set[str] = set()
        for subj in self.subjects:
            mods.update(subj.modalities)
        return sorted(mods)

    @property
    def datatype_summary(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for subj in self.subjects:
            for ses in subj.sessions:
                for acq in ses.acquisitions:
                    if acq.bids and acq.bids.datatype:
                        counts[acq.bids.datatype] += 1
                    elif acq.sequence_type:
                        counts[acq.sequence_type] += 1
        return dict(counts.most_common())

    def iter_acquisitions(self) -> list[AcquisitionContext]:
        out: list[AcquisitionContext] = []
        for subj in self.subjects:
            for ses in subj.sessions:
                out.extend(ses.acquisitions)
        return out


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _short_uid(uid: str) -> str:
    uid = (uid or "").strip()
    if len(uid) <= 24:
        return uid
    return uid[:10] + "…" + uid[-8:]


def _issues_from_validation(validation: PlanValidationResult | None) -> list[MetadataIssue]:
    if validation is None:
        return []
    out: list[MetadataIssue] = []
    for issue in validation.issues:
        out.append(
            MetadataIssue(
                level=issue.level,
                message=issue.message,
                code="plan_validation",
                series_uid=issue.series_uid or "",
            )
        )
    return out


def _heuristic_issues(
    acq: AcquisitionContext,
    subject: str,
    session: str,
) -> list[MetadataIssue]:
    issues: list[MetadataIssue] = []
    if acq.requires_manual_mapping:
        issues.append(
            MetadataIssue(
                level="warning",
                code="manual_mapping_required",
                message=f"Series '{acq.series_description or acq.series_uid}' needs manual BIDS mapping.",
                series_uid=acq.series_uid,
                subject=subject,
                session=session,
            )
        )
    if not acq.convertible_to_nifti:
        issues.append(
            MetadataIssue(
                level="warning",
                code="not_convertible",
                message=f"Series may not convert to NIfTI ({acq.convertibility or 'unknown'}).",
                series_uid=acq.series_uid,
                subject=subject,
                session=session,
            )
        )
    if acq.bids and not acq.bids.include:
        issues.append(
            MetadataIssue(
                level="info",
                code="excluded",
                message="Acquisition excluded from conversion.",
                series_uid=acq.series_uid,
                subject=subject,
                session=session,
            )
        )
    if acq.bids and not acq.bids.datatype:
        issues.append(
            MetadataIssue(
                level="warning",
                code="missing_datatype",
                message="BIDS datatype is empty.",
                series_uid=acq.series_uid,
                subject=subject,
                session=session,
            )
        )
    return issues


def _dedupe_issues(issues: Sequence[MetadataIssue]) -> list[MetadataIssue]:
    seen: set[tuple[str, str, str]] = set()
    out: list[MetadataIssue] = []
    for issue in issues:
        key = (issue.code, issue.series_uid, issue.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def _folder_label_for_subject(
    sessions: Mapping[str, list[tuple[PlannedAcquisition, DicomSeries | None]]],
) -> str:
    for items in sessions.values():
        for item, series in items:
            if series and series.source_subject_folder:
                return safe_folder_label(series.source_subject_folder)
            if item.source_subject_folder:
                return safe_folder_label(item.source_subject_folder)
    return ""


def _acquisition_from_planned(
    item: PlannedAcquisition,
    series: DicomSeries | None,
    issues: Sequence[MetadataIssue],
) -> AcquisitionContext:
    bids = BidsMappingContext(
        subject=item.subject,
        session=item.session,
        datatype=item.datatype,
        suffix=item.suffix,
        task=item.task,
        run=item.run,
        acquisition=item.acquisition,
        direction=item.direction,
        intended_filename=item.intended_filename,
        include=item.include_in_conversion,
        naming_rule_applied=item.naming_rule_applied,
        confidence_score=item.confidence_score,
        classification_source=item.classification_source,
    )
    if series is not None:
        return AcquisitionContext(
            series_uid=item.source_series_uid,
            series_number=series.series_number
            if series.series_number is not None
            else item.source_series_number,
            series_description=series.series_description or item.source_series_description,
            protocol_name=series.protocol_name or item.source_protocol_name,
            modality=series.modality or "",
            sequence_type=series.sequence_type or item.source_sequence_type or "unknown",
            fine_sequence_type=series.fine_sequence_type or "",
            num_images=series.num_images,
            convertibility=series.convertibility or "",
            convertible_to_nifti=series.convertible_to_nifti,
            requires_manual_mapping=series.requires_manual_mapping,
            source_subject_folder=safe_folder_label(series.source_subject_folder)
            if series.source_subject_folder
            else safe_folder_label(item.source_subject_folder),
            bids=bids,
            metadata_issues=list(issues),
        )
    return AcquisitionContext(
        series_uid=item.source_series_uid,
        series_number=item.source_series_number,
        series_description=item.source_series_description,
        protocol_name=item.source_protocol_name,
        modality="",
        sequence_type=item.source_sequence_type or "unknown",
        fine_sequence_type="",
        num_images=0,
        source_subject_folder=safe_folder_label(item.source_subject_folder),
        bids=bids,
        metadata_issues=list(issues),
    )


__all__ = [
    "AcquisitionContext",
    "BidsMappingContext",
    "DatasetContext",
    "MetadataIssue",
    "SessionContext",
    "SubjectContext",
]
