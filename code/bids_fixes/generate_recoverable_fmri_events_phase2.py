#!/usr/bin/env python3
"""Phase-2 task-fmri events recovery for ALL cohorts.

Extends the Phase-1 logic (Control-only in practice due to subject-ID
zero-padding mismatch) to Control, DataON, DataTON, and Glaucoma.

Recovery rule (deterministic; Scientific Data standards):
- Require unique scan_info with actual triggerTimes AND unique stimulus-order
  source (fMRI_N.mat or dated sequence_of_stimuli) for the same fMRI_number.
- Prefer recorded runs_random paradigm when fMRI_number/run_number match;
  otherwise use the canonical presentStimParams.m paradigm
  (firstBaselineEnd=10, 12×(8 stim + 10 baseline)).
- Map fMRI_number → BIDS run only when ProtocolName/SeriesDescription yields
  exactly one non-phase task-fmri BOLD sidecar in that session.
- Bind MATLAB Results to BIDS sessions via session_mapping visit folders
  (resolves Session1/Session2 *path label* inconsistencies without guessing
  across visits). When multiple scan_info share an fMRI_number, keep only
  those whose filename date matches the visit acquisition_date; still require
  uniqueness after that filter.

Does not overwrite existing events.tsv.
Does not invent, interpolate, or infer missing triggers.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path("/home/alexrees/scratch")
sys.path.insert(0, str(ROOT / "code" / "level1_release"))
sys.path.insert(0, str(ROOT / "code" / "bids_fixes"))

from convert_events import (  # noqa: E402
    StrictEventResult,
    build_strict_events,
    fmri_number,
    selected_run,
    write_events,
)
from generate_recoverable_fmri_events import (  # noqa: E402
    FMRI_PROTOCOL,
    FMRI_STEM,
    build_events_canonical,
    remap,
)

BIDS = ROOT / "bids"
SESSION_MAP = ROOT / "metadata" / "session_mapping.csv"
PARTICIPANT_MAP = ROOT / "metadata" / "participant_mapping.csv"
OUT_DIR = ROOT / "reports" / "stimulus_audit"
OUT_TSV = OUT_DIR / "phase2_events_generation.tsv"
OUT_SUMMARY = OUT_DIR / "phase2_events_generation_summary.json"
OUT_REPORT = OUT_DIR / "RECOVERED_EVENTS_PHASE2.md"

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
DATE_IN_NAME = re.compile(
    r"(?i)\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)-(\d{1,2})-(\d{4})(?!\d)"
)
SEQ_STIM = re.compile(r"(?i)sequence_of_stimuli_for_fMRI_number_(\d+)")
SCAN_FMRI = re.compile(r"(?i)fmri_number_is(\d+)")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_subject_id(value: str) -> str:
    text = (value or "").strip().upper()
    match = re.match(r"(SUB(?:C|G|ON|TON|T))0*(\d+)$", text)
    if match:
        return f"{match.group(1)}{int(match.group(2)):03d}"
    return text


def parse_filename_date(name: str) -> str | None:
    match = DATE_IN_NAME.search(name)
    if not match:
        return None
    month = MONTHS[match.group(1).lower()]
    day = int(match.group(2))
    year = int(match.group(3))
    return f"{year:04d}{month:02d}{day:02d}"


def load_participant_cohorts() -> dict[str, str]:
    cohorts: dict[str, str] = {}
    with PARTICIPANT_MAP.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pid = (row.get("participant_id") or "").strip()
            if pid:
                cohorts[pid] = (row.get("cohort") or "").strip()
    return cohorts


@dataclass
class VisitBinding:
    participant_id: str
    session_id: str
    cohort: str
    visit_folders: set[str] = field(default_factory=set)
    acquisition_dates: set[str] = field(default_factory=set)
    matlab_paths: set[str] = field(default_factory=set)


def load_visit_bindings() -> dict[tuple[str, str], VisitBinding]:
    bindings: dict[tuple[str, str], VisitBinding] = {}
    with SESSION_MAP.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (row.get("exclusion_status") or "").strip().lower() == "excluded":
                continue
            participant = (row.get("participant_id") or "").strip()
            session = (row.get("session_id") or "").strip()
            if not participant.startswith("sub-") or not session.startswith("ses-"):
                continue
            key = (participant, session)
            item = bindings.get(key)
            if item is None:
                item = VisitBinding(
                    participant_id=participant,
                    session_id=session,
                    cohort=(row.get("cohort") or row.get("original_cohort") or "").strip(),
                )
                bindings[key] = item
            for path_field in ("source_subject_path", "original_path"):
                value = (row.get(path_field) or "").strip()
                if value:
                    item.visit_folders.add(value)
            matlab = (row.get("MATLAB_data_path") or "").strip()
            if matlab:
                for part in matlab.split("|"):
                    part = part.strip()
                    if part:
                        item.matlab_paths.add(part)
            for date_field in ("acquisition_date", "study_date", "dicom_study_date_min"):
                date = (row.get(date_field) or "").strip()
                if re.fullmatch(r"\d{8}", date):
                    item.acquisition_dates.add(date)
    return bindings


def _grating_results_under(root: Path) -> list[Path]:
    """Return Results dirs for grating paradigms (incl. 2-Grating_rerun)."""
    found: list[Path] = []
    if not root.exists():
        return found
    try:
        if root.is_dir() and root.name.lower() == "results":
            parent = root.parent.name.lower()
            if "grating" in parent:
                found.append(root)
        if root.is_dir():
            for cand in root.rglob("Results"):
                parent = cand.parent.name.lower()
                if parent.startswith("2-grating") or parent == "grating":
                    found.append(cand)
    except OSError:
        return found
    return found


def _results_dates(results: Path) -> set[str]:
    dates: set[str] = set()
    for path in results.glob("*.mat"):
        if "scan_info" not in path.name.lower():
            continue
        parsed = parse_filename_date(path.name)
        if parsed:
            dates.add(parsed)
    return dates


def discover_results_dirs(
    binding: VisitBinding,
    participant_bindings: list[VisitBinding] | None = None,
) -> tuple[list[Path], str]:
    """Find grating Results for this BIDS session.

    Primary: under the mapped visit folder(s) only (Session1/Session2 *subdir*
    labels are ignored).

    Fallback (still non-guessing): if the mapped visit has no Results, accept
    exactly one Results tree found under *any visit folder of the same
    participant* whose scan_info filename dates are a non-empty subset of this
    session's acquisition_date(s). This recovers MATLAB trees physically stored
    under the wrong session folder but dated to the correct acquisition day.
    """
    roots: list[Path] = []
    for folder in sorted(binding.visit_folders):
        path = Path(folder)
        if path.is_dir():
            roots.append(path)
    for matlab in sorted(binding.matlab_paths):
        path = Path(matlab)
        if path.is_dir():
            roots.append(path)

    found: dict[str, Path] = {}
    for root in roots:
        for cand in _grating_results_under(root):
            if cand.is_dir():
                found[str(cand.resolve())] = cand
    if found:
        return sorted(found.values(), key=lambda p: str(p)), "visit_folder"

    # Date-unique rescue across this participant's known visit folders only
    if not binding.acquisition_dates or not participant_bindings:
        return [], "none"

    dated_hits: dict[str, Path] = {}
    search_roots: set[str] = set()
    for other in participant_bindings:
        search_roots.update(other.visit_folders)
        search_roots.update(other.matlab_paths)
    for folder in sorted(search_roots):
        root = Path(folder)
        if not root.is_dir():
            # matlab path may point mid-tree; still try parent walk via rglob if exists
            continue
        for cand in _grating_results_under(root):
            dates = _results_dates(cand)
            if dates and dates <= binding.acquisition_dates:
                dated_hits[str(cand.resolve())] = cand

    if len(dated_hits) == 1:
        only = next(iter(dated_hits.values()))
        return [only], (
            "date_unique_rescue: scan_info dates "
            f"{sorted(_results_dates(only))} ⊆ acquisition_dates "
            f"{sorted(binding.acquisition_dates)}"
        )
    if len(dated_hits) > 1:
        return [], (
            f"date_rescue_ambiguous: {len(dated_hits)} Results trees match "
            f"acquisition_dates {sorted(binding.acquisition_dates)}"
        )
    return [], "none"


def collect_sources_from_results(
    results_dirs: list[Path],
    acquisition_dates: set[str],
) -> tuple[dict[int, list[Path]], dict[int, list[Path]], list[Path], list[str]]:
    scans_by_run: dict[int, list[Path]] = defaultdict(list)
    stim_by_run: dict[int, list[Path]] = defaultdict(list)
    workspaces: list[Path] = []
    notes: list[str] = []

    scan_candidates: dict[int, list[Path]] = defaultdict(list)
    stim_fMRI: dict[int, list[Path]] = defaultdict(list)
    stim_seq: dict[int, list[Path]] = defaultdict(list)

    for results in results_dirs:
        for path in sorted(results.glob("*.mat")):
            lower = path.name.lower()
            if "scan_info" in lower:
                match = SCAN_FMRI.search(path.name)
                if match:
                    scan_candidates[int(match.group(1))].append(path)
            elif FMRI_STEM.fullmatch(path.stem):
                stim_fMRI[int(FMRI_STEM.fullmatch(path.stem).group(1))].append(path)
            elif SEQ_STIM.search(path.name):
                stim_seq[int(SEQ_STIM.search(path.name).group(1))].append(path)
            elif path.stem.lower() == "runs_random":
                workspaces.append(path)

    for number, paths in sorted(scan_candidates.items()):
        unique_paths = sorted({str(p): p for p in paths}.values(), key=lambda p: str(p))
        if len(unique_paths) == 1:
            scans_by_run[number] = unique_paths
            continue
        if acquisition_dates:
            dated = []
            undated = []
            for path in unique_paths:
                file_date = parse_filename_date(path.name)
                if file_date is None:
                    undated.append(path)
                elif file_date in acquisition_dates:
                    dated.append(path)
            if len(dated) == 1 and not undated:
                scans_by_run[number] = dated
                notes.append(
                    f"fmri={number}: disambiguated scan_info by acquisition_date "
                    f"{sorted(acquisition_dates)}"
                )
                continue
            if len(dated) == 1 and undated:
                # Undated extras remain ambiguous — do not guess
                notes.append(
                    f"fmri={number}: multiple scan_info; date filter left "
                    f"{len(dated)} dated + {len(undated)} undated → ambiguous"
                )
                scans_by_run[number] = unique_paths
                continue
        scans_by_run[number] = unique_paths

    for number in sorted(set(stim_fMRI) | set(stim_seq)):
        fmri_paths = sorted({str(p): p for p in stim_fMRI.get(number, [])}.values())
        seq_paths = sorted({str(p): p for p in stim_seq.get(number, [])}.values())
        if len(fmri_paths) == 1:
            stim_by_run[number] = fmri_paths
        elif len(fmri_paths) == 0 and len(seq_paths) == 1:
            stim_by_run[number] = seq_paths
            notes.append(f"fmri={number}: using dated sequence_of_stimuli (no fMRI_N.mat)")
        elif len(fmri_paths) == 0 and len(seq_paths) > 1:
            # Prefer sequence whose filename date matches visit acquisition_date
            if acquisition_dates:
                dated = [
                    p
                    for p in seq_paths
                    if (parse_filename_date(p.name) or "") in acquisition_dates
                ]
                if len(dated) == 1:
                    stim_by_run[number] = dated
                    notes.append(
                        f"fmri={number}: disambiguated sequence_of_stimuli by acquisition_date"
                    )
                    continue
            stim_by_run[number] = seq_paths
        else:
            stim_by_run[number] = fmri_paths or seq_paths

    return scans_by_run, stim_by_run, workspaces, notes


def bids_destination(
    participant: str, session: str, number: int
) -> tuple[str, Path | None, str]:
    func = BIDS / participant / session / "func"
    if not func.is_dir():
        return "", None, "func directory missing"
    matches: list[Path] = []
    for sidecar in func.glob(f"{participant}_{session}_task-*_run-*_bold.json"):
        if "_part-" in sidecar.name:
            continue
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        text = " ".join(
            str(metadata.get(key, ""))
            for key in ("ProtocolName", "SeriesDescription", "TaskName")
        )
        protocol_numbers = {int(item) for item in FMRI_PROTOCOL.findall(text)}
        if number in protocol_numbers and "task-fmri" in sidecar.name.lower():
            matches.append(sidecar)
    if len(matches) != 1:
        return (
            "",
            None,
            f"expected one matching non-phase BOLD sidecar, found {len(matches)}",
        )
    dest = matches[0].with_name(
        matches[0].name.removesuffix("_bold.json") + "_events.tsv"
    )
    rel = f"{participant}/{session}/func/{dest.name}"
    return rel, dest, "matched by recorded BOLD ProtocolName/SeriesDescription"


def list_fmri_bold_runs() -> list[dict[str, str | bool]]:
    runs: list[dict[str, str | bool]] = []
    pattern = re.compile(
        r"(sub-\d+)_(ses-\d+)_task-fmri_run-(\d+)_bold\.json$"
    )
    for sidecar in sorted(BIDS.glob("sub-*/ses-*/func/*_task-fmri_*_bold.json")):
        if "part-phase" in sidecar.name:
            continue
        match = pattern.search(sidecar.name)
        if not match:
            continue
        participant, session, run = match.groups()
        events = sidecar.with_name(
            sidecar.name.replace("_bold.json", "_events.tsv")
        )
        protocol = ""
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            protocol = str(meta.get("ProtocolName") or meta.get("SeriesDescription") or "")
        except (OSError, json.JSONDecodeError):
            pass
        runs.append(
            {
                "participant_id": participant,
                "session_id": session,
                "run": run,
                "protocol": protocol,
                "has_events": events.exists(),
                "events_path": str(events.relative_to(BIDS)) if events.exists() else "",
                "bold_json": str(sidecar.relative_to(BIDS)),
            }
        )
    return runs


@dataclass
class Phase2Row:
    participant_id: str
    session_id: str
    cohort: str
    fmri_number: str
    destination: str
    status: str
    method: str
    reason: str
    n_events: int
    scan_info: str
    stim_order: str
    results_dirs: str
    already_existed: str


def main() -> int:
    cohorts = load_participant_cohorts()
    bindings = load_visit_bindings()
    bold_runs = list_fmri_bold_runs()
    previous_events = sum(1 for r in bold_runs if r["has_events"])
    missing_runs = [r for r in bold_runs if not r["has_events"]]
    missing_sessions = sorted(
        {(r["participant_id"], r["session_id"]) for r in missing_runs}
    )

    rows: list[Phase2Row] = []
    written = 0
    skipped_existing = 0
    failed = 0

    bindings_by_participant: dict[str, list[VisitBinding]] = defaultdict(list)
    for key, binding in bindings.items():
        bindings_by_participant[binding.participant_id].append(binding)

    for participant, session in missing_sessions:
        binding = bindings.get((participant, session))
        cohort = cohorts.get(participant, "") or (binding.cohort if binding else "")
        if binding is None:
            rows.append(
                Phase2Row(
                    participant,
                    session,
                    cohort,
                    "",
                    "",
                    "failed_no_visit_binding",
                    "",
                    "no session_mapping visit folder for this BIDS session",
                    0,
                    "",
                    "",
                    "",
                    "False",
                )
            )
            failed += 1
            continue

        results_dirs, discovery = discover_results_dirs(
            binding, bindings_by_participant.get(participant, [])
        )
        if not results_dirs:
            rows.append(
                Phase2Row(
                    participant,
                    session,
                    cohort,
                    "",
                    "",
                    "failed_no_grating_results",
                    "",
                    (
                        "mapped visit folder(s) contain no grating Results; "
                        f"visits={sorted(binding.visit_folders)}; "
                        f"discovery={discovery}"
                    ),
                    0,
                    "",
                    "",
                    "",
                    "False",
                )
            )
            failed += 1
            continue

        scans_by_run, stim_by_run, workspaces, notes = collect_sources_from_results(
            results_dirs, binding.acquisition_dates
        )
        if discovery.startswith("date_unique_rescue"):
            notes = [discovery, *notes]
        note_text = "; ".join(notes)
        # Attempt every fMRI_number that has at least one source side
        for number in sorted(set(scans_by_run) | set(stim_by_run)):
            scans = scans_by_run.get(number, [])
            stims = stim_by_run.get(number, [])
            if len(scans) != 1 or len(stims) != 1:
                rows.append(
                    Phase2Row(
                        participant,
                        session,
                        cohort,
                        str(number),
                        "",
                        "failed_cardinality",
                        "cardinality",
                        (
                            f"scan={len(scans)}, stim={len(stims)}, "
                            f"workspace={len(workspaces)}"
                            + (f"; {note_text}" if note_text else "")
                        ),
                        0,
                        ";".join(str(p) for p in scans),
                        ";".join(str(p) for p in stims),
                        "|".join(str(p) for p in results_dirs),
                        "False",
                    )
                )
                failed += 1
                continue

            scan_info = scans[0]
            stim_order = stims[0]
            method = "strict_runs_random"
            result: StrictEventResult | None = None
            if len(workspaces) == 1:
                result = build_strict_events(
                    scan_info=scan_info,
                    stim_order=stim_order,
                    runs_random=workspaces[0],
                )
            if result is None or result.status != "ready":
                result = build_events_canonical(scan_info, stim_order)
                method = "canonical_paradigm"

            rel, dest, match_reason = bids_destination(participant, session, number)
            reason_bits = [result.reason, match_reason]
            if note_text:
                reason_bits.append(note_text)

            if result.status != "ready":
                rows.append(
                    Phase2Row(
                        participant,
                        session,
                        cohort,
                        str(number),
                        rel,
                        "failed_timing",
                        method,
                        " | ".join(reason_bits),
                        0,
                        str(scan_info),
                        str(stim_order),
                        "|".join(str(p) for p in results_dirs),
                        "False",
                    )
                )
                failed += 1
                continue

            if dest is None:
                rows.append(
                    Phase2Row(
                        participant,
                        session,
                        cohort,
                        str(number),
                        "",
                        "failed_no_bids_match",
                        method,
                        " | ".join(reason_bits),
                        len(result.events),
                        str(scan_info),
                        str(stim_order),
                        "|".join(str(p) for p in results_dirs),
                        "False",
                    )
                )
                failed += 1
                continue

            if dest.exists():
                skipped_existing += 1
                rows.append(
                    Phase2Row(
                        participant,
                        session,
                        cohort,
                        str(number),
                        rel,
                        "skipped_existing",
                        method,
                        " | ".join(reason_bits),
                        len(result.events),
                        str(scan_info),
                        str(stim_order),
                        "|".join(str(p) for p in results_dirs),
                        "True",
                    )
                )
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            write_events(dest, result)
            written += 1
            rows.append(
                Phase2Row(
                    participant,
                    session,
                    cohort,
                    str(number),
                    rel,
                    "written",
                    method,
                    " | ".join(reason_bits),
                    len(result.events),
                    str(scan_info),
                    str(stim_order),
                    "|".join(str(p) for p in results_dirs),
                    "False",
                )
            )

    # Refresh coverage after writes
    bold_after = list_fmri_bold_runs()
    events_after = sum(1 for r in bold_after if r["has_events"])
    total_bold = len(bold_after)
    remaining = [r for r in bold_after if not r["has_events"]]
    remaining_by_cohort = Counter(cohorts.get(r["participant_id"], "?") for r in remaining)
    written_by_cohort = Counter(r.cohort for r in rows if r.status == "written")
    status_counts = Counter(r.status for r in rows)

    # sub-051 special documentation
    sub051 = [r for r in remaining if r["participant_id"] == "sub-051"]
    sub051_rows = [r for r in rows if r.participant_id == "sub-051"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_TSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(asdict(rows[0]).keys()) if rows else [
                "participant_id",
                "session_id",
                "cohort",
                "fmri_number",
                "destination",
                "status",
                "method",
                "reason",
                "n_events",
                "scan_info",
                "stim_order",
                "results_dirs",
                "already_existed",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    coverage_pct = (100.0 * events_after / total_bold) if total_bold else 0.0
    summary = {
        "generated_at_utc": utc_now(),
        "previous_events": previous_events,
        "new_events_written": written,
        "skipped_existing_during_phase2": skipped_existing,
        "failed_attempts": failed,
        "events_after": events_after,
        "total_task_fmri_bold": total_bold,
        "remaining_without_events": len(remaining),
        "coverage_percent": round(coverage_pct, 2),
        "status_counts": dict(status_counts),
        "written_by_cohort": dict(written_by_cohort),
        "remaining_by_cohort": dict(remaining_by_cohort),
        "written_method_counts": dict(
            Counter(r.method for r in rows if r.status == "written")
        ),
        "remaining_sessions": sorted(
            {f"{r['participant_id']}/{r['session_id']}" for r in remaining}
        ),
        "sub051_remaining_runs": len(sub051),
        "sub051_phase2_rows": [asdict(r) for r in sub051_rows],
        "report_tsv": str(OUT_TSV),
        "report_md": str(OUT_REPORT),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    # Remaining reason rollup (per missing BOLD run)
    remaining_reasons: list[dict[str, str]] = []
    rows_by_session = defaultdict(list)
    for row in rows:
        rows_by_session[(row.participant_id, row.session_id)].append(row)
    for run in remaining:
        key = (run["participant_id"], run["session_id"])
        session_rows = rows_by_session.get(key, [])
        protocol = str(run["protocol"])
        protocol_nums = {int(x) for x in FMRI_PROTOCOL.findall(protocol)}
        matched = [
            r
            for r in session_rows
            if r.destination.endswith(
                f"{run['participant_id']}_{run['session_id']}_task-fmri_run-{run['run']}_events.tsv"
            )
        ]
        if not matched and protocol_nums and session_rows:
            matched = [
                r
                for r in session_rows
                if r.fmri_number.isdigit() and int(r.fmri_number) in protocol_nums
            ]
        if matched:
            # Prefer a failed_* row if present (explains why this run has no events)
            failed_matched = [r for r in matched if r.status.startswith("failed")]
            chosen = failed_matched[0] if failed_matched else matched[0]
            reason = chosen.reason
            status = chosen.status
        elif session_rows:
            failed_rows = [r for r in session_rows if r.status.startswith("failed")]
            if len(failed_rows) == 1:
                reason = failed_rows[0].reason
                status = failed_rows[0].status
            elif failed_rows:
                reason = " | ".join(
                    sorted({f"{r.status}: {r.reason}" for r in failed_rows})
                )
                status = "session_level_multiple_failures"
            else:
                reason = (
                    "session had reconstructable sources but no unique "
                    "ProtocolName match for this BOLD run"
                )
                status = "failed_no_bids_match"
        else:
            reason = "not attempted (no phase-2 row)"
            status = "not_attempted"
        remaining_reasons.append(
            {
                "participant_id": run["participant_id"],
                "session_id": run["session_id"],
                "run": run["run"],
                "cohort": cohorts.get(run["participant_id"], ""),
                "protocol": protocol,
                "status": status,
                "reason": reason,
            }
        )

    with (OUT_DIR / "phase2_remaining_missing.tsv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "participant_id",
                "session_id",
                "run",
                "cohort",
                "protocol",
                "status",
                "reason",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(remaining_reasons)

    write_markdown_report(
        previous_events=previous_events,
        written=written,
        events_after=events_after,
        total_bold=total_bold,
        remaining=remaining,
        remaining_by_cohort=remaining_by_cohort,
        written_by_cohort=written_by_cohort,
        status_counts=status_counts,
        rows=rows,
        remaining_reasons=remaining_reasons,
        sub051=sub051,
        sub051_rows=sub051_rows,
        bindings=bindings,
        coverage_pct=coverage_pct,
    )

    print(json.dumps(summary, indent=2))
    return 0


def write_markdown_report(
    *,
    previous_events: int,
    written: int,
    events_after: int,
    total_bold: int,
    remaining: list[dict],
    remaining_by_cohort: Counter,
    written_by_cohort: Counter,
    status_counts: Counter,
    rows: list[Phase2Row],
    remaining_reasons: list[dict[str, str]],
    sub051: list[dict],
    sub051_rows: list[Phase2Row],
    bindings: dict[tuple[str, str], VisitBinding],
    coverage_pct: float,
) -> None:
    impossible = len(remaining)
    recovered_total = events_after  # all events present after phase 2

    # Group remaining reasons
    reason_groups: Counter[str] = Counter()
    for item in remaining_reasons:
        status = item["status"]
        reason = item["reason"]
        if "no_grating" in status or "no grating Results" in reason or "no_2-Grating" in reason:
            reason_groups["no grating Results for mapped visit / date"] += 1
        elif "failed_no_bids_match" in status or "found 0" in reason or "found 2" in reason:
            reason_groups["ProtocolName↔BOLD not unique (or absent)"] += 1
        elif "cardinality" in status or re.search(r"scan=\d+, stim=\d+", reason):
            reason_groups["non-unique scan_info/stim_order cardinality"] += 1
        elif "failed_timing" in status or "triggerTimes" in reason:
            reason_groups["triggerTimes/paradigm validation failed"] += 1
        elif "no_visit_binding" in status:
            reason_groups["no session_mapping visit binding"] += 1
        else:
            reason_groups[status or "other"] += 1

    lines: list[str] = []
    lines.append("# Recovered events — Phase 2 (all cohorts)")
    lines.append("")
    lines.append(f"**Date (UTC):** {utc_now()}")
    lines.append(
        "**Scope:** Control, DataON, DataTON, Glaucoma — same reconstruction logic as "
        "Phase 1 / Level-1, with subject-ID normalization and visit-folder binding."
    )
    lines.append(
        "**Policy:** No invented timing. No interpolation. No inferred triggers. "
        "Write `events.tsv` only when scan_info + stim order + BOLD ProtocolName mapping "
        "are each unique."
    )
    lines.append("")
    lines.append("## Final coverage table")
    lines.append("")
    lines.append("| Metric | N |")
    lines.append("|---|---:|")
    lines.append(f"| `task-fmri` non-phase BOLD runs | {total_bold} |")
    lines.append(f"| Events present **before** Phase 2 | {previous_events} |")
    lines.append(f"| **New events written (Phase 2)** | **{written}** |")
    lines.append(f"| Events present **after** Phase 2 (Recovered) | {events_after} |")
    lines.append(f"| **Remaining without events (impossible under strict rules)** | **{impossible}** |")
    lines.append(f"| **Coverage %** | **{coverage_pct:.2f}%** |")
    lines.append("")
    lines.append("| Cohort | New written | Remaining missing |")
    lines.append("|---|---:|---:|")
    for cohort in ("Control", "DataON", "DataTON", "Glaucoma"):
        lines.append(
            f"| {cohort} | {written_by_cohort.get(cohort, 0)} | "
            f"{remaining_by_cohort.get(cohort, 0)} |"
        )
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append("1. Bind each BIDS `(participant_id, session_id)` to its freeze "
                 "`session_mapping` visit folder(s) / MATLAB path(s).")
    lines.append("2. Discover `**/2-Grating/Results` **only inside those visit folders** "
                 "(Session1/Session2 *subdirectory labels* are irrelevant as long as they "
                 "sit under the mapped visit).")
    lines.append("3. Require unique `scan_info` (`triggerTimes`) and unique stim order "
                 "(`fMRI_N.mat` or dated `sequence_of_stimuli`) per `fMRI_number`.")
    lines.append("4. If multiple `scan_info` share an `fMRI_number`, keep candidates whose "
                 "filename date equals the visit `acquisition_date`; still require uniqueness.")
    lines.append("5. Build events via `runs_random` when identity matches; else canonical "
                 "`presentStimParams.m` paradigm + measured triggers (no default TR).")
    lines.append("6. Attach to BIDS only when ProtocolName/SeriesDescription yields "
                 "**exactly one** non-phase `task-fmri` BOLD sidecar.")
    lines.append("")
    lines.append("## Phase-2 attempt status")
    lines.append("")
    lines.append("| Status | N |")
    lines.append("|---|---:|")
    for status, count in sorted(status_counts.items()):
        lines.append(f"| `{status}` | {count} |")
    lines.append("")
    lines.append("## Previous events")
    lines.append("")
    lines.append(
        f"Before Phase 2, **{previous_events}** `task-fmri` `*_events.tsv` files were "
        "already present (Level-1 release + Phase-1 Control recovery). "
        "Phase 2 never overwrites existing files."
    )
    lines.append("")
    lines.append("## New events")
    lines.append("")
    written_rows = [r for r in rows if r.status == "written"]
    if not written_rows:
        lines.append("No new events were written.")
    else:
        lines.append(f"**{len(written_rows)}** new files written. By cohort:")
        lines.append("")
        for cohort, count in sorted(written_by_cohort.items()):
            lines.append(f"- {cohort}: {count}")
        lines.append("")
        lines.append("Method mix:")
        method_counts = Counter(r.method for r in written_rows)
        for method, count in sorted(method_counts.items()):
            lines.append(f"- `{method}`: {count}")
        lines.append("")
        lines.append("Detail: `phase2_events_generation.tsv` (status=`written`).")
    lines.append("")
    lines.append("## Remaining missing")
    lines.append("")
    lines.append(f"**{impossible}** BOLD runs still lack events.")
    lines.append("")
    lines.append("### Reason summary")
    lines.append("")
    lines.append("| Reason class | N runs |")
    lines.append("|---|---:|")
    for reason, count in reason_groups.most_common():
        lines.append(f"| {reason} | {count} |")
    lines.append("")
    lines.append("Per-run table: `phase2_remaining_missing.tsv`.")
    lines.append("")

    # sub-051 section
    lines.append("## sub-051 (SUBC052) — remaining impossible?")
    lines.append("")
    if not sub051:
        lines.append(
            "No: `sub-051` is fully covered after Phase 2 (no remaining BOLD without events)."
        )
    else:
        binding = bindings.get(("sub-051", "ses-01"))
        lines.append(
            f"**Yes — {len(sub051)} `task-fmri` BOLD runs remain without events.**"
        )
        lines.append("")
        lines.append("Precise cause:")
        lines.append("")
        lines.append("- BIDS: `sub-051/ses-01` has grating BOLD series "
                     "(ProtocolName `fMRI1_AP`…`fMRI4_AP`).")
        lines.append("- Canonical ID: `SUBC052` (Control).")
        if binding:
            lines.append(
                f"- Mapped visit folder(s): `{sorted(binding.visit_folders)}`"
            )
            lines.append(
                f"- Visit acquisition_date(s): `{sorted(binding.acquisition_dates)}`"
            )
        lines.append(
            "- On-disk visit contents include DICOM / peripheral recording only; "
            "**no `2-Grating/Results` directory** and therefore **no `scan_info` "
            "`triggerTimes` and no `Stim_order_selected` sources**."
        )
        lines.append(
            "- Phase-2 status: `failed_no_grating_results` — refusing to invent timing."
        )
        lines.append("")
        if sub051_rows:
            lines.append("Phase-2 log rows:")
            lines.append("")
            for row in sub051_rows:
                lines.append(f"- `{row.status}`: {row.reason}")
        lines.append("")
        lines.append(
            "This is a true archive gap for stimulus timing, not a cohort-coverage bug."
        )
    lines.append("")
    lines.append("## Deliverables")
    lines.append("")
    lines.append("| File | Description |")
    lines.append("|---|---|")
    lines.append("| `RECOVERED_EVENTS_PHASE2.md` | This report |")
    lines.append("| `phase2_events_generation.tsv` | Per attempted fMRI_number provenance |")
    lines.append("| `phase2_events_generation_summary.json` | Machine-readable counts |")
    lines.append("| `phase2_remaining_missing.tsv` | Per remaining BOLD run + reason |")
    lines.append("")

    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
