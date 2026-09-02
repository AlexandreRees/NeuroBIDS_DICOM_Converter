"""Dataset audit presentation derived from DatasetContext / plan.validate().

This is a UI adapter, not a second validator. No invented numeric scores.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan, PlanValidationResult
from neuro_pipeline.neurobids.dataset_context import DatasetContext, MetadataIssue


@dataclass(slots=True)
class AuditCheck:
    """One category row on the Audit / Release pages."""

    key: str
    title: str
    level: str  # PASS | REVIEW | FAIL | INFO
    detail: str
    count: int = 0
    ask_prompt: str = ""


@dataclass(slots=True)
class AuditIssueRow:
    """One grouped finding the user can review or ask Copilot about."""

    level: str
    title: str
    detail: str
    count: int
    code: str = ""
    ask_prompt: str = ""
    series_uids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AuditReport:
    """Deterministic audit snapshot for the GUI."""

    n_errors: int = 0
    n_warnings: int = 0
    n_info: int = 0
    n_review: int = 0
    checks: list[AuditCheck] = field(default_factory=list)
    issues: list[AuditIssueRow] = field(default_factory=list)
    validation: PlanValidationResult | None = None
    empty: bool = True
    scanning: bool = False
    message: str = ""

    @property
    def headline(self) -> str:
        if self.scanning:
            return "Dataset is still scanning."
        if self.empty:
            return "No dataset loaded."
        parts: list[str] = []
        if self.n_errors:
            parts.append(f"{self.n_errors} error{'s' if self.n_errors != 1 else ''}")
        if self.n_warnings or self.n_review:
            n = self.n_warnings + self.n_review
            parts.append(f"{n} issue{'s' if n != 1 else ''} requiring review")
        if not parts:
            return "No issues requiring review."
        return " · ".join(parts)

    def to_text_report(self) -> str:
        lines = [
            "NeuroBIDS release-readiness report",
            "=================================",
            "",
            self.headline,
            "",
            "Checks",
            "------",
        ]
        for check in self.checks:
            lines.append(f"[{check.level}] {check.title}: {check.detail}")
        lines.extend(["", "Issues", "------"])
        if not self.issues:
            lines.append("None.")
        for issue in self.issues:
            lines.append(f"[{issue.level}] {issue.title} ({issue.count})")
            if issue.detail:
                lines.append(f"    {issue.detail}")
        lines.extend(
            [
                "",
                "Notes",
                "-----",
                "Original DICOM files are not modified.",
                "This report restates existing plan validation and DatasetContext issues.",
                "It is not a publication-readiness certificate.",
            ]
        )
        return "\n".join(lines)


def _count_sessions(ctx: DatasetContext) -> int:
    return sum(len(s.sessions) for s in ctx.subjects)


def _count_acquisitions(ctx: DatasetContext) -> int:
    return sum(s.n_acquisitions for s in ctx.subjects)


def _group_issues(issues: list[MetadataIssue]) -> list[AuditIssueRow]:
    grouped: dict[tuple[str, str], list[MetadataIssue]] = defaultdict(list)
    for issue in issues:
        grouped[(issue.code or "", issue.level)].append(issue)

    rows: list[AuditIssueRow] = []
    for (code, level), items in grouped.items():
        if not items:
            continue
        ui_level = "FAIL" if level == "error" else "REVIEW" if level == "warning" else "INFO"
        sample = items[0]
        title = _title_for_code(code, len(items), sample.message)
        prompt = _prompt_for_code(code, title)
        rows.append(
            AuditIssueRow(
                level=ui_level,
                title=title,
                detail=sample.message,
                count=len(items),
                code=code,
                ask_prompt=prompt,
                series_uids=[i.series_uid for i in items if i.series_uid],
            )
        )
    order = {"FAIL": 0, "REVIEW": 1, "INFO": 2}
    rows.sort(key=lambda r: (order.get(r.level, 9), -r.count, r.title))
    return rows


def _title_for_code(code: str, n: int, fallback: str) -> str:
    titles = {
        "manual_mapping_required": f"{n} acquisition{'s' if n != 1 else ''} have ambiguous mappings",
        "missing_datatype": f"{n} acquisition{'s' if n != 1 else ''} missing BIDS datatype",
        "not_convertible": f"{n} series may not convert to NIfTI",
        "excluded": f"{n} acquisition{'s' if n != 1 else ''} excluded from conversion",
        "plan_validation": f"{n} BIDS plan validation finding{'s' if n != 1 else ''}",
    }
    return titles.get(code, fallback or f"{n} finding(s)")


def _prompt_for_code(code: str, title: str) -> str:
    prompts = {
        "manual_mapping_required": "Explain the ambiguous acquisition mappings.",
        "missing_datatype": "Which acquisitions are missing a BIDS datatype, and why?",
        "not_convertible": "Which series may not convert to NIfTI?",
        "excluded": "Which acquisitions are excluded from conversion, and why?",
        "plan_validation": "Explain the BIDS plan validation findings.",
    }
    return prompts.get(code, f"Explain these dataset issues: {title}")


def _longitudinal_gaps(ctx: DatasetContext) -> list[str]:
    gaps: list[str] = []
    for subj in ctx.subjects:
        if len(subj.sessions) < 2:
            continue
        by_ses: dict[str, set[str]] = {}
        for ses in subj.sessions:
            dts = {
                (a.bids.datatype if a.bids and a.bids.datatype else a.sequence_type)
                for a in ses.acquisitions
                if a.bids is None or a.bids.include
            }
            by_ses[ses.session_id or "(no session)"] = {d for d in dts if d}
        union: set[str] = set()
        for dts in by_ses.values():
            union |= dts
        for ses_id, dts in by_ses.items():
            missing = sorted(union - dts)
            if missing:
                gaps.append(
                    f"sub-{subj.subject_id.removeprefix('sub-')} {ses_id}: "
                    f"missing {', '.join(missing)}"
                )
    return gaps


def build_audit_report(
    *,
    ctx: DatasetContext | None,
    plan: BIDSConversionPlan | None,
    scanning: bool = False,
) -> AuditReport:
    if scanning:
        return AuditReport(scanning=True, empty=True, message="Scanning…")
    if ctx is None or plan is None or not plan.items:
        return AuditReport(empty=True, message="Scan a DICOM folder to audit the dataset.")

    validation = plan.validate()
    issues = list(ctx.metadata_issues)
    n_errors = sum(1 for i in issues if i.level == "error")
    n_warnings = sum(1 for i in issues if i.level == "warning")
    n_info = sum(1 for i in issues if i.level == "info")

    n_subj = ctx.n_subjects or len(ctx.subjects)
    n_ses = _count_sessions(ctx)
    n_acq = _count_acquisitions(ctx)
    structure_ok = n_subj > 0 and n_acq > 0

    manual = [i for i in issues if i.code == "manual_mapping_required"]
    missing_dt = [i for i in issues if i.code == "missing_datatype"]
    val_errors = list(validation.errors)
    val_warns = list(validation.warnings)
    gaps = _longitudinal_gaps(ctx)

    checks = [
        AuditCheck(
            key="structure",
            title="Dataset structure",
            level="PASS" if structure_ok else "FAIL",
            detail=f"{n_subj} subjects, {n_ses} sessions, {n_acq} acquisitions",
            count=n_acq,
        ),
        AuditCheck(
            key="subjects",
            title="Subject consistency",
            level="PASS" if n_subj else "FAIL",
            detail=f"{n_subj} reconstructed subject(s)",
            count=n_subj,
        ),
        AuditCheck(
            key="sessions",
            title="Session consistency",
            level="REVIEW" if gaps else "PASS",
            detail=(
                f"{len(gaps)} longitudinal gap(s) across sessions"
                if gaps
                else "No missing modalities between sessions"
            ),
            count=len(gaps),
            ask_prompt="Check longitudinal session consistency across subjects.",
        ),
        AuditCheck(
            key="mappings",
            title="BIDS mappings",
            level="REVIEW" if (manual or missing_dt) else "PASS",
            detail=(
                f"{len(manual)} ambiguous, {len(missing_dt)} missing datatype"
                if (manual or missing_dt)
                else "Included acquisitions have BIDS datatypes"
            ),
            count=len(manual) + len(missing_dt),
            ask_prompt="Review the BIDS mappings and list ambiguous acquisitions.",
        ),
        AuditCheck(
            key="metadata",
            title="Metadata",
            level="REVIEW" if n_warnings else "PASS",
            detail=f"{n_warnings} warning(s), {n_info} informational note(s)",
            count=n_warnings,
            ask_prompt="Find potential problems in this dataset.",
        ),
        AuditCheck(
            key="privacy",
            title="De-identification",
            level="INFO",
            detail="Original DICOM is read-only; PatientName is never exported. Manual PHI review is still required.",
            ask_prompt="",
        ),
        AuditCheck(
            key="validation",
            title="BIDS validation",
            level="FAIL" if val_errors else ("REVIEW" if val_warns else "PASS"),
            detail=f"{len(val_errors)} error(s), {len(val_warns)} warning(s)",
            count=len(val_errors) + len(val_warns),
            ask_prompt="Explain the BIDS plan validation findings.",
        ),
    ]

    issue_rows = _group_issues(issues)
    if gaps:
        issue_rows.insert(
            0,
            AuditIssueRow(
                level="REVIEW",
                title=f"{len(gaps)} subject(s) have inconsistent sessions",
                detail="; ".join(gaps[:6]),
                count=len(gaps),
                code="session_consistency",
                ask_prompt="Check longitudinal session consistency across subjects.",
            ),
        )

    n_review = sum(1 for r in issue_rows if r.level in {"REVIEW", "FAIL"})
    return AuditReport(
        n_errors=n_errors + len(val_errors),
        n_warnings=n_warnings,
        n_info=n_info,
        n_review=n_review,
        checks=checks,
        issues=issue_rows,
        validation=validation,
        empty=False,
    )


def dataset_overview(ctx: DatasetContext | None, *, n_files_fallback: int = 0) -> dict[str, Any]:
    if ctx is None:
        return {
            "subjects": 0,
            "sessions": 0,
            "acquisitions": 0,
            "files": n_files_fallback,
            "modalities": [],
            "datatypes": {},
        }
    return {
        "subjects": ctx.n_subjects or len(ctx.subjects),
        "sessions": _count_sessions(ctx),
        "acquisitions": _count_acquisitions(ctx),
        "files": ctx.n_dicom_files or n_files_fallback,
        "modalities": list(ctx.modalities),
        "datatypes": dict(ctx.datatype_summary),
    }
