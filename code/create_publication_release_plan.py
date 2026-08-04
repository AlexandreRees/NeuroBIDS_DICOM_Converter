#!/usr/bin/env python3
"""Create a conservative, read-only publication release plan.

This script never converts or copies data and never writes under ``raw_original``.
It reads the associated-data inventory, inspects filenames/text/MATLAB variable
names, and writes planning artifacts under ``release_candidate_plan/``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MANIFEST_COLUMNS: tuple[str, ...] = (
    "source_path",
    "subject",
    "session",
    "file_type",
    "category",
    "scientific_value",
    "privacy_risk",
    "copyright_risk",
    "recommended_destination",
    "release_decision",
    "manual_review",
)

PHI_COLUMNS: tuple[str, ...] = ("file", "finding", "severity", "action")
COPYRIGHT_COLUMNS: tuple[str, ...] = (
    "file",
    "type",
    "redistribution_status",
    "decision",
)

RELEASE_DECISIONS: frozenset[str] = frozenset(
    {
        "KEEP_BIDS",
        "KEEP_SOURCEDATA",
        "KEEP_CODE",
        "REVIEW_REQUIRED",
        "EXCLUDE",
    }
)

PHYSIO_EXTENSIONS = frozenset(
    {".resp", ".puls", ".ecg", ".pmu", ".ext", ".ext1", ".ext2"}
)
EYE_EXTENSIONS = frozenset({".edf", ".asc"})
MEDIA_EXTENSIONS = frozenset({".mp4", ".avi", ".wav", ".audio"})
TEXT_EXTENSIONS = frozenset(
    {".m", ".asc", ".csv", ".tsv", ".txt", ".log", ".json", ".xml"}
)
STIMULUS_EXTENSIONS = frozenset({".mp4", ".avi", ".wav", ".audio"})

STREAM_CHUNK_BYTES = 4 * 1024 * 1024
STREAM_OVERLAP_BYTES = 4096
PHYSIO_METADATA_SAMPLE_BYTES = 1024 * 1024

TASK_RE = re.compile(
    r"(?i)(?:^|[^a-z])(?:onsets?|events?|timing|triggers?|trials?|conditions?|"
    r"responses?|reaction[\s_.-]*time|stim[\s_.-]*order|vbl|trial[\s_.-]*type)"
    r"(?:$|[^a-z])"
)
EYE_RE = re.compile(
    r"(?i)(?:^|[^a-z])(?:eye|eyelink|gaze|pupil|fixations?|saccades?|blinks?)"
    r"(?:$|[^a-z])"
)
CALIBRATION_RE = re.compile(
    r"(?i)(?:calibrat|configuration|config|greenlevel|redlevel|fixrect|screenrect)"
)
BEHAVIOR_RE = re.compile(
    r"(?i)(?:response|reaction[\s_.-]*time|accuracy|choice|button|keypress)"
)

SUBJECT_ID_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:sub-(?:\d{1,4})|"
    r"SUB(?:TON|ON|G|C|T)[\s_-]?0*\d{1,4})(?![A-Za-z0-9])"
)
LABELED_SUBJECT_RE = re.compile(
    r"(?i)(?:subject|participant|patient)[\s_.-]*(?:is|id|identifier)?"
    r"[\s_.:=/-]*[A-Za-z]*0*\d{1,6}"
)
DATE_RE = re.compile(
    r"(?i)(?<!\d)(?:(?:19|20)\d{2}[-_/]?(?:0[1-9]|1[0-2])[-_/]?"
    r"(?:0[1-9]|[12]\d|3[01])|(?:0[1-9]|[12]\d|3[01])[-_/]"
    r"(?:0[1-9]|1[0-2])[-_/](?:19|20)\d{2})(?!\d)|"
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)[- _]?\d{1,2}(?:st|nd|rd|th)?"
    r"(?:[- _,]+)(?:19|20)\d{2}(?!\d)"
)
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
)
WINDOWS_USER_RE = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")
LINUX_HOME_RE = re.compile(r"(?<![A-Za-z0-9])/(?:home|Users)/[^/\s]+/")

PHI_FIELD_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "PERSON_NAME_FIELD",
        "HIGH",
        re.compile(
            r"(?i)(?:patient|subject|participant|operator|physician)"
            r"[\s_.-]*name"
        ),
    ),
    (
        "PATIENT_OR_SUBJECT_IDENTIFIER",
        "HIGH",
        re.compile(
            r"(?i)(?:patient|subject|participant|hospital)[\s_.-]*"
            r"(?:id|identifier|number)"
        ),
    ),
    (
        "DOB_OR_BIRTH_FIELD",
        "HIGH",
        re.compile(r"(?i)(?:date[\s_.-]*of[\s_.-]*birth|birth[\s_.-]*date|dob)"),
    ),
    ("EMAIL_FIELD", "HIGH", re.compile(r"(?i)(?:e[\s_.-]*mail|email)")),
    ("PHONE_FIELD", "HIGH", re.compile(r"(?i)(?:phone|telephone|mobile)")),
    (
        "INSTITUTION_FIELD",
        "MEDIUM",
        re.compile(r"(?i)(?:institution|hospital|site[\s_.-]*name)"),
    ),
    (
        "OPERATOR_FIELD",
        "MEDIUM",
        re.compile(r"(?i)operator(?:[\s_.-]*name)?"),
    ),
    (
        "SCANNER_SERIAL_FIELD",
        "MEDIUM",
        re.compile(r"(?i)(?:scanner|device|station)[\s_.-]*serial"),
    ),
    (
        "ACCESSION_FIELD",
        "HIGH",
        re.compile(r"(?i)accession[\s_.-]*(?:number|no|num)?"),
    ),
    (
        "DATE_FIELD",
        "MEDIUM",
        re.compile(
            r"(?i)(?:acquisition|study|series|scan|session)[\s_.-]*"
            r"(?:date|datetime)"
        ),
    ),
)

SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


@dataclass(frozen=True)
class Finding:
    label: str
    severity: str
    action: str


@dataclass
class FileEvidence:
    findings: set[Finding] = field(default_factory=set)
    tokens: set[str] = field(default_factory=set)
    mat_variables: set[str] = field(default_factory=set)
    error: str = ""
    source_stat_unchanged: bool = True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def add_finding(
    evidence: FileEvidence,
    label: str,
    severity: str,
    action: str,
) -> None:
    evidence.findings.add(Finding(label, severity, action))


def scan_text(text: str, evidence: FileEvidence, location: str) -> None:
    """Scan text without storing matched values in outputs."""
    if not text:
        return
    evidence.tokens.add(text)
    for label, severity, pattern in PHI_FIELD_PATTERNS:
        if pattern.search(text):
            add_finding(
                evidence,
                f"{label} in {location}",
                severity,
                "Remove or replace the field in a de-identified derivative; verify before release.",
            )
    if SUBJECT_ID_RE.search(text) or LABELED_SUBJECT_RE.search(text):
        add_finding(
            evidence,
            f"LOCAL_SUBJECT_ID in {location}",
            "HIGH",
            "Replace with the final BIDS participant label; never publish the local identifier.",
        )
    if DATE_RE.search(text):
        add_finding(
            evidence,
            f"CALENDAR_DATE in {location}",
            "MEDIUM",
            "Remove or consistently shift the calendar date in a derivative.",
        )
    if EMAIL_RE.search(text):
        add_finding(
            evidence,
            f"EMAIL_ADDRESS in {location}",
            "HIGH",
            "Remove the email address.",
        )
    if PHONE_RE.search(text):
        add_finding(
            evidence,
            f"PHONE_NUMBER in {location}",
            "HIGH",
            "Remove the phone number.",
        )
    if WINDOWS_USER_RE.search(text):
        add_finding(
            evidence,
            f"WINDOWS_USER_PATH in {location}",
            "MEDIUM",
            r"Remove local C:\Users path and username; replace with portable provenance.",
        )
    if LINUX_HOME_RE.search(text):
        add_finding(
            evidence,
            f"LINUX_HOME_PATH in {location}",
            "MEDIUM",
            "Remove local /home or /Users path and username; replace with portable provenance.",
        )


def inspect_text_file(path: Path, evidence: FileEvidence) -> None:
    overlap = b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(STREAM_CHUNK_BYTES)
            if not chunk:
                break
            combined = overlap + chunk
            scan_text(decode_text(combined), evidence, "text content")
            overlap = combined[-STREAM_OVERLAP_BYTES:]


def inspect_physio_metadata(path: Path, evidence: FileEvidence) -> None:
    """Inspect header/footer metadata without loading a huge numeric payload."""
    size = path.stat().st_size
    half = PHYSIO_METADATA_SAMPLE_BYTES // 2
    with path.open("rb") as handle:
        if size <= PHYSIO_METADATA_SAMPLE_BYTES:
            data = handle.read()
        else:
            data = handle.read(half)
            handle.seek(max(0, size - half))
            data += handle.read(half)
    scan_text(decode_text(data), evidence, "physiology header/footer")


def inspect_mat_variables(path: Path, evidence: FileEvidence) -> None:
    """Inspect all discoverable MATLAB variable/group names, not array payloads."""
    with path.open("rb") as handle:
        header = handle.read(128)
    scan_text(decode_text(header), evidence, "MATLAB header")
    if header.startswith(b"MATLAB 7.3"):
        try:
            import h5py
        except ImportError as exc:
            evidence.error = f"h5py unavailable: {exc}"
            return
        try:
            with h5py.File(path, "r") as handle:
                def visitor(name: str, obj: Any) -> None:
                    evidence.mat_variables.add(name)
                    scan_text(name, evidence, "MATLAB variable name")
                    for attr_name in obj.attrs:
                        scan_text(str(attr_name), evidence, "MATLAB attribute name")

                handle.visititems(visitor)
        except Exception as exc:  # noqa: BLE001 - planner must retain the row
            evidence.error = f"MATLAB 7.3 inspection failed: {exc}"
        return

    try:
        import scipy.io as sio
    except ImportError as exc:
        evidence.error = f"scipy unavailable: {exc}"
        return
    try:
        for name, _shape, _matlab_class in sio.whosmat(str(path)):
            evidence.mat_variables.add(str(name))
            scan_text(str(name), evidence, "MATLAB variable name")
    except Exception as exc:  # noqa: BLE001
        evidence.error = f"MATLAB variable inspection failed: {exc}"


def inspect_file(path: Path, extension: str) -> FileEvidence:
    evidence = FileEvidence()
    scan_text(path.name, evidence, "filename")
    try:
        before = path.stat()
        if extension == ".mat":
            inspect_mat_variables(path, evidence)
        elif extension in PHYSIO_EXTENSIONS:
            inspect_physio_metadata(path, evidence)
        elif extension in TEXT_EXTENSIONS:
            inspect_text_file(path, evidence)
        after = path.stat()
        evidence.source_stat_unchanged = (
            before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns
            and before.st_ino == after.st_ino
        )
        if not evidence.source_stat_unchanged:
            evidence.error = "source stat changed during read-only inspection"
    except Exception as exc:  # noqa: BLE001
        evidence.error = f"{type(exc).__name__}: {exc}"
    return evidence


def resolve_inventory_source(
    path: Path, raw_root: Path
) -> tuple[Path, bool]:
    """Resolve stale inventory paths against the current immutable raw root."""
    if path.is_file():
        return path, False
    try:
        index = path.parts.index("raw_original")
    except ValueError:
        return path, False
    candidate = raw_root.joinpath(*path.parts[index + 1 :])
    if candidate.is_file():
        return candidate, True
    return path, False


def compact_subject_finding(
    filename: str, subject: str, evidence: FileEvidence
) -> None:
    match = re.fullmatch(r"(?i)SUB(TON|ON|G|C|T)?0*(\d{1,4})", subject.strip())
    if not match:
        return
    group = (match.group(1) or "").upper()
    number = int(match.group(2))
    compact = {"C": "C", "G": "G", "ON": "ON", "TON": "TON", "T": "TON"}.get(
        group, group
    )
    aliases = [rf"SUB{compact}0*{number}"]
    if compact:
        aliases.append(rf"{compact}0*{number}")
    if re.search(rf"(?i)(?<![A-Za-z0-9])(?:{'|'.join(aliases)})(?!\d)", filename):
        add_finding(
            evidence,
            "LOCAL_SUBJECT_ID in filename",
            "HIGH",
            "Replace with the final BIDS participant label.",
        )


def combined_evidence_text(path: Path, evidence: FileEvidence) -> str:
    return " ".join(
        [
            path.name,
            path.parent.name,
            *sorted(evidence.mat_variables),
            *sorted(evidence.tokens),
        ]
    )


def privacy_risk(evidence: FileEvidence) -> str:
    if evidence.error:
        return "UNKNOWN"
    if not evidence.findings:
        return "LOW"
    return max(
        (finding.severity for finding in evidence.findings),
        key=lambda severity: SEVERITY_ORDER[severity],
    )


def decision_for_file(
    *,
    path: Path,
    extension: str,
    category: str,
    evidence: FileEvidence,
) -> tuple[str, str, str, str, str]:
    """Return scientific value, copyright risk, destination, decision, review."""
    text = combined_evidence_text(path, evidence)
    task = bool(TASK_RE.search(text)) or category == "task_timing"
    eye = extension in EYE_EXTENSIONS or bool(EYE_RE.search(text)) or category == "eye_tracking"
    calibration = bool(CALIBRATION_RE.search(text))
    behavior = bool(BEHAVIOR_RE.search(text)) or category == "behavior"

    if extension in MEDIA_EXTENSIONS:
        return (
            "Potential stimulus value; scientific use depends on task provenance.",
            "HIGH",
            "none",
            "EXCLUDE",
            "YES — copyright/license uncertainty; do not redistribute without documented rights.",
        )

    if eye:
        return (
            "HIGH — eye tracking/gaze/pupil/fixation/saccade information.",
            "LOW",
            "func/*_eyetrack.tsv.gz (future validated conversion)",
            "REVIEW_REQUIRED",
            "YES — requires validated BIDS eye-tracking conversion and synchronization validation.",
        )

    if extension in PHYSIO_EXTENSIONS:
        return (
            "HIGH — physiology; required metadata: sampling_frequency, channels, units, start_time.",
            "LOW",
            "func/*_physio.tsv.gz",
            "KEEP_BIDS",
            "YES" if evidence.findings else "NO",
        )

    if task:
        return (
            "HIGH — task timing/events; required fields: onset, duration, trial_type; "
            "optional: response_time, accuracy, stimulus.",
            "LOW",
            "func/*_events.tsv",
            "KEEP_BIDS",
            "YES" if evidence.findings or evidence.error else "NO",
        )

    if extension == ".m":
        detail = "calibration/configuration script" if calibration else "experimental source script"
        return (
            f"MEDIUM — {detail}; useful for reproducibility.",
            "LOW",
            "code/",
            "KEEP_CODE",
            "YES" if evidence.findings or evidence.error else "NO",
        )

    if extension == ".mat":
        detail = "calibration/configuration source" if calibration else (
            "behavioral source" if behavior else "MATLAB source workspace"
        )
        return (
            f"MEDIUM — {detail}; preserve only when needed for provenance/reproduction.",
            "LOW",
            "sourcedata/",
            "KEEP_SOURCEDATA",
            "YES" if evidence.findings or evidence.error else "NO",
        )

    if calibration:
        return (
            "MEDIUM — calibration/configuration provenance.",
            "LOW",
            "sourcedata/",
            "KEEP_SOURCEDATA",
            "YES" if evidence.findings or evidence.error else "NO",
        )

    return (
        "UNKNOWN — scientific role not established automatically.",
        "LOW",
        "undetermined",
        "REVIEW_REQUIRED",
        "YES — manual scientific, privacy, and format review required.",
    )


def copyright_rows_for_file(
    path: Path,
    extension: str,
    category: str,
) -> list[dict[str, str]]:
    if extension in MEDIA_EXTENSIONS:
        return [
            {
                "file": str(path),
                "type": extension.lstrip(".") or "media",
                "redistribution_status": "UNKNOWN — license and ownership not documented",
                "decision": "EXCLUDE pending explicit redistribution rights",
            }
        ]
    if category == "stimulus":
        return [
            {
                "file": str(path),
                "type": extension.lstrip(".") or "stimulus",
                "redistribution_status": "REVIEW — verify authorship, third-party assets, and license",
                "decision": "REVIEW_REQUIRED before redistribution",
            }
        ]
    return []


def read_inventory(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(
    path: Path,
    rows: Iterable[dict[str, str]],
    columns: tuple[str, ...],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def validate_output_location(output_dir: Path, raw_root: Path) -> None:
    output = output_dir.resolve()
    raw = raw_root.resolve()
    if output == raw or output.is_relative_to(raw):
        raise ValueError(f"Refusing to write release plan under immutable raw root: {output}")


def choose_inventory(data_root: Path, requested: Path | None) -> tuple[Path, str]:
    if requested is not None:
        if not requested.is_file():
            raise FileNotFoundError(f"Inventory not found: {requested}")
        return requested, "explicit"
    preferred = data_root / "metadata" / "associated_data_inventory.tsv"
    fallback = data_root / "reports" / "associated_data_inventory.tsv"
    if preferred.is_file():
        return preferred, "metadata"
    if fallback.is_file():
        return fallback, "reports fallback (metadata inventory absent)"
    raise FileNotFoundError(
        f"No inventory found at {preferred} or {fallback}"
    )


def summary_inventory_count(summary_path: Path) -> int | None:
    text = summary_path.read_text(encoding="utf-8")
    match = re.search(r"(?i)Files inventoried\s*\|\s*(\d+)", text)
    return int(match.group(1)) if match else None


def generate_plan(
    *,
    data_root: Path,
    raw_root: Path,
    inventory_path: Path | None = None,
    summary_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    raw_root = raw_root.resolve()
    inventory, inventory_source = choose_inventory(data_root, inventory_path)
    summary = summary_path or data_root / "reports" / "associated_data_summary.md"
    if not summary.is_file():
        raise FileNotFoundError(f"Associated-data summary not found: {summary}")
    output = output_dir or data_root / "release_candidate_plan"
    validate_output_location(output, raw_root)
    output.mkdir(parents=True, exist_ok=True)

    inventory_rows = read_inventory(inventory)
    expected_count = summary_inventory_count(summary)
    if expected_count is not None and expected_count != len(inventory_rows):
        raise ValueError(
            f"Inventory/summary count mismatch: TSV={len(inventory_rows)} summary={expected_count}"
        )

    manifest_rows: list[dict[str, str]] = []
    phi_rows: list[dict[str, str]] = []
    copyright_rows: list[dict[str, str]] = []
    missing = 0
    rebased = 0
    stat_changes = 0

    for index, inventory_row in enumerate(inventory_rows, start=1):
        original = Path(inventory_row.get("path", ""))
        source, was_rebased = resolve_inventory_source(original, raw_root)
        rebased += int(was_rebased)
        extension = (inventory_row.get("extension") or source.suffix).lower()
        subject = inventory_row.get("subject", "")
        session = inventory_row.get("session", "")
        category = inventory_row.get("category", "") or "unknown"

        if not source.is_file():
            missing += 1
            evidence = FileEvidence(error="source missing or not a regular file")
        else:
            evidence = inspect_file(source, extension)
            compact_subject_finding(source.name, subject, evidence)
            if not evidence.source_stat_unchanged:
                stat_changes += 1

        science, copyright_risk, destination, decision, manual_review = decision_for_file(
            path=source,
            extension=extension,
            category=category,
            evidence=evidence,
        )
        if evidence.error:
            decision = "REVIEW_REQUIRED"
            manual_review = f"YES — {evidence.error}"
        if decision not in RELEASE_DECISIONS:
            raise AssertionError(f"Invalid release decision: {decision}")

        manifest_rows.append(
            {
                "source_path": str(source),
                "subject": subject,
                "session": session,
                "file_type": extension or "<none>",
                "category": category,
                "scientific_value": science,
                "privacy_risk": privacy_risk(evidence),
                "copyright_risk": copyright_risk,
                "recommended_destination": destination,
                "release_decision": decision,
                "manual_review": manual_review,
            }
        )
        for finding in sorted(
            evidence.findings,
            key=lambda item: (item.severity, item.label, item.action),
        ):
            phi_rows.append(
                {
                    "file": str(source),
                    "finding": finding.label,
                    "severity": finding.severity,
                    "action": finding.action,
                }
            )
        if evidence.error:
            phi_rows.append(
                {
                    "file": str(source),
                    "finding": f"INSPECTION_INDETERMINATE: {evidence.error}",
                    "severity": "HIGH",
                    "action": "Resolve the inspection error and repeat PHI review before release.",
                }
            )
        copyright_rows.extend(
            copyright_rows_for_file(source, extension, category)
        )
        if index % 250 == 0:
            print(f"Inspected {index}/{len(inventory_rows)}", file=sys.stderr)

    manifest_path = output / "release_manifest.tsv"
    phi_path = output / "phi_audit.tsv"
    copyright_path = output / "copyright_review.tsv"
    write_tsv(manifest_path, manifest_rows, MANIFEST_COLUMNS)
    write_tsv(phi_path, phi_rows, PHI_COLUMNS)
    write_tsv(copyright_path, copyright_rows, COPYRIGHT_COLUMNS)

    decisions = Counter(row["release_decision"] for row in manifest_rows)
    privacy = Counter(row["privacy_risk"] for row in manifest_rows)
    manual_count = sum(row["manual_review"].startswith("YES") for row in manifest_rows)
    generated = utc_now()
    readme = output / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# Publication release candidate plan",
                "",
                f"Generated: `{generated}`",
                "",
                "This is a conservative planning artifact for a future BIDS/FAIR release. "
                "**No files were copied or converted, and `raw_original/` was not modified.**",
                "",
                "## Inputs",
                "",
                f"- Immutable raw root: `{raw_root}`",
                f"- Inventory: `{inventory}` ({inventory_source})",
                f"- Existing summary: `{summary}`",
                f"- Inventory rows: **{len(inventory_rows)}**",
                f"- Stale inventory paths rebased read-only: **{rebased}**",
                f"- Missing source files: **{missing}**",
                f"- Source stat changes detected: **{stat_changes}**",
                "",
                "## Release decisions",
                "",
                f"- Total files audited: **{len(manifest_rows)}**",
                f"- KEEP_BIDS: **{decisions['KEEP_BIDS']}**",
                f"- KEEP_SOURCEDATA: **{decisions['KEEP_SOURCEDATA']}**",
                f"- KEEP_CODE: **{decisions['KEEP_CODE']}**",
                f"- REVIEW_REQUIRED: **{decisions['REVIEW_REQUIRED']}**",
                f"- EXCLUDE: **{decisions['EXCLUDE']}**",
                f"- Files marked for manual review: **{manual_count}**",
                "",
                "## Risk findings",
                "",
                f"- PHI audit findings: **{len(phi_rows)}**",
                f"- Files with HIGH privacy risk: **{privacy['HIGH']}**",
                f"- Files with MEDIUM privacy risk: **{privacy['MEDIUM']}**",
                f"- Files with UNKNOWN privacy risk: **{privacy['UNKNOWN']}**",
                f"- Copyright review findings: **{len(copyright_rows)}**",
                "",
                "A KEEP decision identifies a scientifically appropriate future destination; "
                "it is not authorization to copy or publish the source file. All release gates "
                "must pass on separately created, de-identified derivatives.",
                "",
                "## Reproduce",
                "",
                "```bash",
                "module load StdEnv/2023 python/3.11 scipy-stack hdf5/1.14.6",
                "python3 code/create_publication_release_plan.py \\",
                f"  --data-root {data_root} \\",
                f"  --raw-root {raw_root}",
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )

    gates = output / "release_gates.md"
    gates.write_text(
        "\n".join(
            [
                "# Final publication release gates",
                "",
                "All gates apply to the separately built release candidate, not to immutable source data.",
                "",
                "- [ ] No unresolved identifiers",
                "- [ ] BIDS validator pass",
                "- [ ] events.tsv validated",
                "- [ ] physio metadata complete",
                "- [ ] eye tracking synchronization validated",
                "- [ ] stimulus rights documented",
                "- [ ] source-to-release manifest created",
                "- [ ] checksums generated",
                "",
            ]
        ),
        encoding="utf-8",
    )

    metadata_path = output / "plan_metadata.json"
    metadata = {
        "generated_at": generated,
        "data_root": str(data_root),
        "raw_root": str(raw_root),
        "inventory": str(inventory),
        "inventory_source": inventory_source,
        "summary": str(summary),
        "total_files_audited": len(manifest_rows),
        "stale_inventory_paths_rebased": rebased,
        "missing_source_files": missing,
        "source_stat_changes_detected": stat_changes,
        "decision_counts": dict(sorted(decisions.items())),
        "privacy_risk_counts": dict(sorted(privacy.items())),
        "phi_findings": len(phi_rows),
        "copyright_findings": len(copyright_rows),
        "manual_review_files": manual_count,
        "source_operations": "read-only; no copy, conversion, rename, move, or deletion",
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "release_manifest": manifest_path,
        "phi_audit": phi_path,
        "copyright_review": copyright_path,
        "README": readme,
        "release_gates": gates,
        "plan_metadata": metadata_path,
        "metadata": metadata,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a conservative read-only publication release plan."
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path.home() / "scratch",
        help="Dataset data root (default: ~/scratch).",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("/project/def-amirs/raw_original"),
        help="Current immutable raw_original root.",
    )
    parser.add_argument("--inventory", type=Path, default=None)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    written = generate_plan(
        data_root=args.data_root,
        raw_root=args.raw_root,
        inventory_path=args.inventory,
        summary_path=args.summary,
        output_dir=args.output_dir,
    )
    for name, path in written.items():
        if name != "metadata":
            print(f"{name}: {path}")
    print(json.dumps(written["metadata"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
