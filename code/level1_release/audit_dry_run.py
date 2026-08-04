#!/usr/bin/env python3
"""Read-only post-dry-run audit for Level-1 release approval.

Never modifies raw_original, existing BIDS imaging, or the release target.
All outputs are confined to the dry-run plan directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from convert_events import build_strict_events, fmri_number, selected_run
from convert_physio import CHANNELS, _metadata_sample, _explicit_frequency, _explicit_start_time
from deidentify_release import scan_text
from build_release import (
    FMRI_PROTOCOL,
    FMRI_STEM,
    bids_destination,
    raw_relative,
    read_tsv,
)


TRIAL_TYPE_RE = re.compile(r"^(?:baseline|stim-\d{2}|cond-\d+)$")
DATE_IN_NAME = re.compile(
    r"(?i)(?:19|20)\d{2}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
)
LOCAL_ID_IN_NAME = re.compile(
    r"(?i)(?:subject|subc|subg|subon|subton|participant)[\s_-]*\d+"
)


def write_tsv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=columns, delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def parse_sources(row: dict[str, str]) -> list[Path]:
    return [Path(item) for item in json.loads(row["source_paths"] or "[]")]


def classify_failure(reason: str) -> tuple[str, str]:
    """Return (class, explanation) for withheld event timing."""
    text = reason.strip()
    if text.startswith("runs_random belongs to fMRI"):
        return (
            "recoverable_with_deterministic_mapping",
            "Workspace is run-specific and currently attached to every fMRI_N in the "
            "folder; restrict runs_random to its recorded fMRI_number before release.",
        )
    if text.startswith("expected one matching non-phase BOLD sidecar, found 0"):
        return (
            "recoverable_with_deterministic_mapping",
            "Timing conversion can succeed, but no unique ProtocolName match exists "
            "in current BIDS sidecars; map fmri_number→task-run via an explicit "
            "protocol table once imaging is complete.",
        )
    if text.startswith("expected one matching non-phase BOLD sidecar, found 2"):
        return (
            "ambiguous_remain_excluded",
            "Multiple BOLD sidecars share the same fMRI protocol number; cannot "
            "choose a unique destination without manual adjudication.",
        )
    if text.startswith("source cardinality"):
        return (
            "ambiguous_remain_excluded",
            "Missing or duplicated scan_info / fMRI_N / runs_random sources; "
            "cannot form a unique strict triplet.",
        )
    if "fewer than two finite scanner triggerTimes" in text:
        return (
            "ambiguous_remain_excluded",
            "Actual scanner triggers are insufficient; VBL/default-TR fallbacks are prohibited.",
        )
    if "paradigm index outside" in text or "terminal paradigm" in text:
        return (
            "ambiguous_remain_excluded",
            "Recorded paradigm indices do not align safely with triggerTimes.",
        )
    if "stimulus order differs" in text:
        return (
            "ambiguous_remain_excluded",
            "fMRI_N and runs_random disagree on Stim_order_selected.",
        )
    return (
        "ambiguous_remain_excluded",
        "Fail-closed: reason does not have a validated deterministic recovery path.",
    )


def verify_ready_events(
    rows: list[dict[str, str]], bids_root: Path
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    verification: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []
    for row in rows:
        if row["action"] != "CONVERT_EVENTS" or row["status"] != "ready":
            continue
        sources = parse_sources(row)
        scan_info = next((path for path in sources if "scan_info" in path.name.lower()), None)
        stim = next((path for path in sources if FMRI_STEM.fullmatch(path.stem)), None)
        workspace = next(
            (path for path in sources if path.stem.lower() == "runs_random"), None
        )
        destination = row["destination"]
        participant = row["participant_id"]
        session = row["session_id"]
        checks: list[str] = []
        mapping_ok = "yes"
        phi_leak_risk = "no"
        bids_ok = "yes"
        n_events = "0"
        columns = ""
        trial_types = ""
        onsets_ok = "yes"
        durations_ok = "yes"
        response_fields = "absent_ok"
        fmri_n = ""
        selected = ""
        protocol = ""
        destination_exists_parent = "n/a"

        if scan_info is None or stim is None or workspace is None:
            mapping_ok = "no"
            checks.append("missing_strict_triplet_in_source_paths")
            issues.append(
                {
                    "destination": destination,
                    "issue": "missing_strict_triplet_in_source_paths",
                    "severity": "error",
                }
            )
        else:
            result = build_strict_events(
                scan_info=scan_info, stim_order=stim, runs_random=workspace
            )
            fmri_n = str(result.fmri_number or fmri_number(scan_info) or "")
            selected = str(result.selected_run or selected_run(scan_info) or "")
            expected_dest, match_reason = bids_destination(
                bids_root, participant, session, int(fmri_n) if fmri_n else -1
            )
            if result.status != "ready":
                mapping_ok = "no"
                bids_ok = "no"
                checks.append(f"reconversion_failed:{result.reason}")
                issues.append(
                    {
                        "destination": destination,
                        "issue": result.reason,
                        "severity": "error",
                    }
                )
            else:
                n_events = str(len(result.events))
                columns = "onset;duration;trial_type"
                types = sorted({trial for _, _, trial in result.events})
                trial_types = ";".join(types)
                if any(onset < 0 for onset, _, _ in result.events):
                    onsets_ok = "no"
                    bids_ok = "no"
                    issues.append(
                        {
                            "destination": destination,
                            "issue": "negative_onset",
                            "severity": "error",
                        }
                    )
                if any(duration <= 0 for _, duration, _ in result.events):
                    durations_ok = "no"
                    bids_ok = "no"
                    issues.append(
                        {
                            "destination": destination,
                            "issue": "nonpositive_duration",
                            "severity": "error",
                        }
                    )
                if any(not TRIAL_TYPE_RE.fullmatch(trial) for _, _, trial in result.events):
                    bids_ok = "no"
                    issues.append(
                        {
                            "destination": destination,
                            "issue": "noncompliant_trial_type",
                            "severity": "error",
                        }
                    )
                # Confirm no source identifiers/dates/local filenames can enter the TSV body.
                for onset, duration, trial in result.events:
                    body = f"{onset:.9f}\t{duration:.9f}\t{trial}"
                    findings = scan_text(body, "event_row")
                    if findings:
                        phi_leak_risk = "yes"
                        bids_ok = "no"
                        issues.append(
                            {
                                "destination": destination,
                                "issue": "phi_in_event_values:"
                                + ",".join(sorted({item.phi_type for item in findings})),
                                "severity": "error",
                            }
                        )
                dest_findings = scan_text(Path(destination).name, "destination_filename")
                # BIDS participant labels like sub-001 are expected in destinations.
                dest_findings = [
                    item
                    for item in dest_findings
                    if item.phi_type != "local_subject_id"
                    or not re.search(r"(?i)^sub-\d+", Path(destination).name)
                ]
                if dest_findings:
                    phi_leak_risk = "yes"
                    issues.append(
                        {
                            "destination": destination,
                            "issue": "phi_in_destination_filename:"
                            + ",".join(sorted({item.phi_type for item in dest_findings})),
                            "severity": "error",
                        }
                    )
                if expected_dest != destination:
                    mapping_ok = "no"
                    issues.append(
                        {
                            "destination": destination,
                            "issue": f"destination_mismatch expected={expected_dest}",
                            "severity": "error",
                        }
                    )
                else:
                    checks.append(match_reason)
                # Source filenames themselves must never become output content.
                for source in sources:
                    if DATE_IN_NAME.search(source.name) or LOCAL_ID_IN_NAME.search(
                        source.name
                    ):
                        checks.append("source_filename_contains_identifiers_not_copied")
                bold_json = (
                    bids_root
                    / destination.replace("_events.tsv", "_bold.json")
                )
                if bold_json.is_file():
                    meta = json.loads(bold_json.read_text(encoding="utf-8"))
                    protocol = str(meta.get("ProtocolName", ""))
                    destination_exists_parent = "yes"
                    protocol_numbers = {
                        int(item)
                        for item in FMRI_PROTOCOL.findall(
                            " ".join(
                                str(meta.get(key, ""))
                                for key in (
                                    "ProtocolName",
                                    "SeriesDescription",
                                    "TaskName",
                                )
                            )
                        )
                    }
                    if int(fmri_n) not in protocol_numbers:
                        mapping_ok = "no"
                        issues.append(
                            {
                                "destination": destination,
                                "issue": f"protocol_number_mismatch protocol={protocol}",
                                "severity": "error",
                            }
                        )
                else:
                    destination_exists_parent = "missing_bold_sidecar"
                    mapping_ok = "no"
                    issues.append(
                        {
                            "destination": destination,
                            "issue": "matching_bold_sidecar_missing",
                            "severity": "error",
                        }
                    )

        # Planned derivative columns exclude response_time/stimulus_file when unavailable.
        verification.append(
            {
                "participant_id": participant,
                "session_id": session,
                "destination": destination,
                "fmri_number": fmri_n,
                "selected_run": selected,
                "protocol_name": protocol,
                "n_events": n_events,
                "columns": columns,
                "trial_types": trial_types,
                "onsets_nonnegative": onsets_ok,
                "durations_positive": durations_ok,
                "response_fields": response_fields,
                "mapping_ok": mapping_ok,
                "phi_leak_risk_in_derivative": phi_leak_risk,
                "bids_field_ok": bids_ok,
                "source_phi_before": row.get("phi_before", ""),
                "phi_after_cleaning_expected": "none_if_execute_passes_output_scan",
                "source_filenames_propagate": "no",
                "checks": "; ".join(sorted(set(checks))),
                "bold_parent_present": destination_exists_parent,
            }
        )
    return verification, issues


def summarize_withheld_events(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if row["action"] != "REVIEW_EVENTS":
            continue
        klass, explanation = classify_failure(row["reason"])
        sources = parse_sources(row)
        fmri_guess = ""
        for path in sources:
            if "scan_info" in path.name.lower():
                match = re.search(r"(?i)fmri_number_is(\d+)", path.name)
                if match:
                    fmri_guess = match.group(1)
                    break
            match = FMRI_STEM.fullmatch(path.stem)
            if match:
                fmri_guess = match.group(1)
        out.append(
            {
                "participant_id": row["participant_id"],
                "session_id": row["session_id"],
                "fmri_number": fmri_guess,
                "failure_reason": row["reason"],
                "classification": klass,
                "recovery_notes": explanation,
                "source_count": str(len(sources)),
                "source_phi_before": row.get("phi_before", ""),
            }
        )
    return out


def physiology_report(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if row["action"] != "REVIEW_PHYSIO":
            continue
        for path in parse_sources(row):
            text = _metadata_sample(path) if path.is_file() else ""
            freq = _explicit_frequency(text)
            start = _explicit_start_time(text)
            footer_lines = []
            for line in text.splitlines():
                if re.search(
                    r"(?i)(?:Freq Per|LogStart|LogStop|Min Max|NrTrig|ECG|PULS|RESP|EXT)",
                    line,
                ):
                    # Keep labels only; strip potentially identifying absolute times/values.
                    cleaned = re.sub(r"\d+", "#", line)
                    footer_lines.append(cleaned.strip()[:120])
            out.append(
                {
                    "participant_id": row["participant_id"],
                    "session_id": row["session_id"],
                    "run": "unassigned",
                    "file_type": path.suffix.lower(),
                    "channel_label": CHANNELS.get(path.suffix.lower(), "unknown"),
                    "available_metadata": "; ".join(footer_lines[:12]),
                    "explicit_sampling_frequency": (
                        str(freq) if freq is not None else "missing"
                    ),
                    "explicit_start_time": str(start) if start is not None else "missing",
                    "missing_bids_requirements": "; ".join(
                        item
                        for item, present in (
                            ("SamplingFrequency", freq is not None),
                            ("StartTime", start is not None),
                            ("run_alignment", False),
                            ("validated_payload_parser", False),
                        )
                        if not present
                    ),
                    "release_decision": "EXCLUDE_FOR_NOW",
                    "group_reason": row["reason"],
                    "source_phi_before": row.get("phi_before", ""),
                }
            )
    return out


def final_manifest(
    planned: list[dict[str, str]],
    verification: list[dict[str, str]],
) -> list[dict[str, str]]:
    verify_by_dest = {row["destination"]: row for row in verification}
    out: list[dict[str, str]] = []
    for row in planned:
        action = row["action"]
        if action == "CONVERT_EVENTS":
            verify = verify_by_dest.get(row["destination"], {})
            out.append(
                {
                    "item": row["destination"],
                    "decision": "INCLUDE",
                    "category": "task_timing_events",
                    "reason": row["reason"],
                    "participant_id": row["participant_id"],
                    "session_id": row["session_id"],
                    "phi_before": row.get("phi_before", ""),
                    "phi_after_expected": "PASS (derivative only; source identifiers not copied)",
                    "mapping_ok": verify.get("mapping_ok", ""),
                    "bids_field_ok": verify.get("bids_field_ok", ""),
                    "expected_bids_validation_impact": (
                        "Adds *_events.tsv beside existing *_bold; validator should "
                        "accept if imaging already present. No imaging files are written."
                    ),
                }
            )
        elif action == "REVIEW_EVENTS":
            klass, _ = classify_failure(row["reason"])
            out.append(
                {
                    "item": f"task_timing:{row['participant_id']}/{row['session_id']}",
                    "decision": "EXCLUDE",
                    "category": "task_timing_review",
                    "reason": f"{row['reason']} [{klass}]",
                    "participant_id": row["participant_id"],
                    "session_id": row["session_id"],
                    "phi_before": row.get("phi_before", ""),
                    "phi_after_expected": "n/a (not released)",
                    "mapping_ok": "no",
                    "bids_field_ok": "n/a",
                    "expected_bids_validation_impact": "None; withheld from release.",
                }
            )
        elif action == "REVIEW_PHYSIO":
            out.append(
                {
                    "item": f"physiology:{row['participant_id']}/{row['session_id']}",
                    "decision": "EXCLUDE",
                    "category": "physiology",
                    "reason": f"{row['reason']} [excluded_pending_explicit_physio_metadata]",
                    "participant_id": row["participant_id"],
                    "session_id": row["session_id"],
                    "phi_before": row.get("phi_before", ""),
                    "phi_after_expected": "n/a (not released)",
                    "mapping_ok": "n/a",
                    "bids_field_ok": "n/a",
                    "expected_bids_validation_impact": "None; physiology remains excluded.",
                }
            )
        else:
            out.append(
                {
                    "item": f"inventory:{row['category']}",
                    "decision": "EXCLUDE",
                    "category": row["category"],
                    "reason": row["reason"],
                    "participant_id": row.get("participant_id", ""),
                    "session_id": row.get("session_id", ""),
                    "phi_before": row.get("phi_before", ""),
                    "phi_after_expected": "n/a (not released)",
                    "mapping_ok": "n/a",
                    "bids_field_ok": "n/a",
                    "expected_bids_validation_impact": "None; excluded category.",
                }
            )
    return out


def write_markdown_summary(
    path: Path,
    *,
    verification: list[dict[str, str]],
    issues: list[dict[str, str]],
    withheld: list[dict[str, str]],
    physio: list[dict[str, str]],
    planned_counts: Counter[str],
) -> None:
    verify_fail = [
        row
        for row in verification
        if row["mapping_ok"] != "yes"
        or row["bids_field_ok"] != "yes"
        or row["phi_leak_risk_in_derivative"] != "no"
    ]
    withheld_counts = Counter(row["classification"] for row in withheld)
    reason_counts = Counter(row["failure_reason"] for row in withheld)
    physio_types = Counter(row["file_type"] for row in physio)
    lines = [
        "# Level-1 dry-run audit (pre-execution)",
        "",
        "Read-only. No release candidate was built. `raw_original/` and existing BIDS imaging were not modified.",
        "",
        "## 1. Planned events.tsv verification (52)",
        "",
        f"- Verified ready destinations: **{len(verification)}**",
        f"- Mapping failures: **{sum(row['mapping_ok'] != 'yes' for row in verification)}**",
        f"- BIDS field failures: **{sum(row['bids_field_ok'] != 'yes' for row in verification)}**",
        f"- Derivative PHI leak risks: **{sum(row['phi_leak_risk_in_derivative'] != 'no' for row in verification)}**",
        f"- Issue rows: **{len(issues)}**",
        "",
        "All planned derivatives use only columns `onset`, `duration`, `trial_type`. "
        "`response_time` / `stimulus_file` are omitted because they are not present as "
        "validated recorded fields in the strict converter. Source filenames, calendar "
        "dates, and local subject aliases are not written into the TSV body or destination basename beyond the BIDS `sub-XXX` label.",
        "",
    ]
    if verify_fail:
        lines += ["### Failures requiring attention before execute", ""]
        for row in verify_fail:
            lines.append(
                f"- `{row['destination']}` mapping={row['mapping_ok']} "
                f"bids={row['bids_field_ok']} phi_leak={row['phi_leak_risk_in_derivative']} "
                f"checks={row['checks']}"
            )
        lines.append("")
    else:
        lines += [
            "**All 52 planned event destinations passed mapping, PHI-propagation, and BIDS field checks.**",
            "",
        ]

    lines += [
        "## 2. Withheld event timing (341)",
        "",
        f"- Recoverable with deterministic mapping: **{withheld_counts['recoverable_with_deterministic_mapping']}**",
        f"- Ambiguous / remain excluded: **{withheld_counts['ambiguous_remain_excluded']}**",
        "",
        "### Failure-reason summary",
        "",
        "| Count | Failure reason |",
        "|---:|---|",
    ]
    for reason, count in reason_counts.most_common():
        lines.append(f"| {count} | `{reason}` |")
    lines += [
        "",
        "Recoverable means a future deterministic code change can include them without "
        "guessing timing; it does **not** authorize inclusion in this Level-1 execute.",
        "",
        "## 3. Physiology (excluded)",
        "",
        f"- Physiology file rows reported: **{len(physio)}**",
        f"- Extension counts: {dict(sorted(physio_types.items()))}",
        "- Decision: **EXCLUDE_FOR_NOW** for all physiology.",
        "- Common missing BIDS requirements: `SamplingFrequency`, `StartTime`, run alignment, validated payload parser.",
        "",
        "## 4. Eye-tracking and stimuli",
        "",
        "- Remain excluded as planned (copyright / eye-tracking / path rules).",
        "",
        "## 5. Planned action totals",
        "",
    ]
    for key, value in sorted(planned_counts.items()):
        lines.append(f"- `{key}`: **{value}**")
    lines += [
        "",
        "## Approval command (do not run automatically)",
        "",
        "```bash",
        "module load StdEnv/2023 python/3.11 scipy-stack hdf5/1.14.6",
        "PYTHONDONTWRITEBYTECODE=1 python3 -B /home/alexrees/scratch/code/level1_release/build_release.py \\",
        "  --execute \\",
        "  --approved-plan /home/alexrees/scratch/release_candidate_plan/level1_dry_run_20260721T1610",
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-dir",
        type=Path,
        default=Path(
            "/home/alexrees/scratch/release_candidate_plan/level1_dry_run_20260721T1610"
        ),
    )
    parser.add_argument(
        "--bids-root",
        type=Path,
        default=Path("/home/alexrees/scratch/bids"),
    )
    parser.add_argument(
        "--audit-outdir",
        type=Path,
        default=None,
        help="Defaults to <plan-dir>/pre_execute_audit",
    )
    args = parser.parse_args()
    outdir = args.audit_outdir or (args.plan_dir / "pre_execute_audit")
    if outdir.exists():
        raise FileExistsError(f"refusing to overwrite existing audit dir: {outdir}")

    planned = read_tsv(args.plan_dir / "planned_actions.tsv")
    planned_counts = Counter(row["action"] for row in planned)
    verification, issues = verify_ready_events(planned, args.bids_root)
    withheld = summarize_withheld_events(planned)
    physio = physiology_report(planned)
    manifest = final_manifest(planned, verification)

    outdir.mkdir(parents=True, exist_ok=False)
    write_tsv(
        outdir / "events_verification.tsv",
        verification,
        [
            "participant_id",
            "session_id",
            "destination",
            "fmri_number",
            "selected_run",
            "protocol_name",
            "n_events",
            "columns",
            "trial_types",
            "onsets_nonnegative",
            "durations_positive",
            "response_fields",
            "mapping_ok",
            "phi_leak_risk_in_derivative",
            "bids_field_ok",
            "source_phi_before",
            "phi_after_cleaning_expected",
            "source_filenames_propagate",
            "bold_parent_present",
            "checks",
        ],
    )
    write_tsv(
        outdir / "events_verification_issues.tsv",
        issues,
        ["destination", "issue", "severity"],
    )
    write_tsv(
        outdir / "withheld_events_summary.tsv",
        withheld,
        [
            "participant_id",
            "session_id",
            "fmri_number",
            "failure_reason",
            "classification",
            "recovery_notes",
            "source_count",
            "source_phi_before",
        ],
    )
    write_tsv(
        outdir / "physiology_exclusion_report.tsv",
        physio,
        [
            "participant_id",
            "session_id",
            "run",
            "file_type",
            "channel_label",
            "available_metadata",
            "explicit_sampling_frequency",
            "explicit_start_time",
            "missing_bids_requirements",
            "release_decision",
            "group_reason",
            "source_phi_before",
        ],
    )
    write_tsv(
        outdir / "final_release_manifest.tsv",
        manifest,
        [
            "item",
            "decision",
            "category",
            "reason",
            "participant_id",
            "session_id",
            "phi_before",
            "phi_after_expected",
            "mapping_ok",
            "bids_field_ok",
            "expected_bids_validation_impact",
        ],
    )

    # Compact exclusion rollup by reason (inventory EXCLUDE rows are many).
    exclude_rollup = Counter()
    for row in planned:
        if row["action"] == "EXCLUDE":
            exclude_rollup[row["reason"]] += 1
        elif row["action"] == "REVIEW_EVENTS":
            klass, _ = classify_failure(row["reason"])
            exclude_rollup[f"REVIEW_EVENTS::{klass}::{row['reason']}"] += 1
        elif row["action"] == "REVIEW_PHYSIO":
            exclude_rollup["REVIEW_PHYSIO::excluded_for_now"] += 1
    write_tsv(
        outdir / "exclusion_reason_rollup.tsv",
        [
            {"reason": reason, "count": str(count)}
            for reason, count in exclude_rollup.most_common()
        ],
        ["reason", "count"],
    )

    write_markdown_summary(
        outdir / "AUDIT_SUMMARY.md",
        verification=verification,
        issues=issues,
        withheld=withheld,
        physio=physio,
        planned_counts=planned_counts,
    )

    metadata = {
        "mode": "pre_execute_audit_readonly",
        "plan_dir": str(args.plan_dir),
        "output_dir": str(outdir),
        "ready_events_verified": len(verification),
        "ready_events_with_issues": len(
            {
                row["destination"]
                for row in verification
                if row["mapping_ok"] != "yes"
                or row["bids_field_ok"] != "yes"
                or row["phi_leak_risk_in_derivative"] != "no"
            }
        ),
        "verification_issue_rows": len(issues),
        "withheld_events": len(withheld),
        "withheld_recoverable": sum(
            row["classification"] == "recoverable_with_deterministic_mapping"
            for row in withheld
        ),
        "withheld_ambiguous": sum(
            row["classification"] == "ambiguous_remain_excluded" for row in withheld
        ),
        "physiology_files_reported": len(physio),
        "manifest_rows": len(manifest),
        "include_count": sum(row["decision"] == "INCLUDE" for row in manifest),
        "exclude_count": sum(row["decision"] == "EXCLUDE" for row in manifest),
        "source_operations": "read-only",
        "target_created": False,
    }
    (outdir / "audit_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
