#!/usr/bin/env python3
"""Generate recoverable task-fmri events.tsv into the live BIDS tree.

Recovery rule (deterministic, no invented timing):
- Use per-run scan_info triggerTimes + fMRI_N Stim_order_selected.
- When runs_random belongs to a different fMRI_number, use the canonical
  paradigm from presentStimParams.m (firstBaselineEnd=10, 12×(8 stim + 10
  baseline), terminal conditionEnd at volume 226).
- Map fmri_number → BIDS run via unique ProtocolName/SeriesDescription match.

Does not overwrite existing events.tsv. Does not invent onsets.
Writes a provenance TSV under reports/stimulus_audit/.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path("/home/alexrees/scratch")
sys.path.insert(0, str(ROOT / "code" / "level1_release"))
from convert_events import (  # noqa: E402
    FMRI_RE,
    SELECTED_RUN_RE,
    StrictEventResult,
    _scan_triggers,
    _stim_order,
    build_strict_events,
    fmri_number,
    selected_run,
    write_events,
)

BIDS = ROOT / "bids"
INV = ROOT / "reports" / "associated_data_inventory.tsv"
SESSION_MAP = ROOT / "metadata" / "session_mapping.csv"
RAW_ROOTS = [
    Path("/project/def-amirs/raw_original"),
    Path("/lustre06/project/6001995/raw_original"),
]
OLD_PREFIXES = [
    "/lustre07/scratch/alexrees/raw_original/",
    "/lustre06/project/6001995/raw_original/",
    "/project/def-amirs/raw_original/",
    "/home/alexrees/scratch/raw_original/",
]
OUT_REPORT = ROOT / "reports" / "stimulus_audit" / "recoverable_events_generation.tsv"
FMRI_STEM = re.compile(r"(?i)^fmri_(\d+)$")
FMRI_PROTOCOL = re.compile(r"(?i)(?:^|[^A-Za-z0-9])fmri[_ -]?0*(\d+)(?!\d)")

# Canonical paradigm from presentStimParams.m / recorded runParadigmFinal
FIRST_BASELINE_END = 10
NUM_CYCLES = 12
CYCLE_STIM = 8
CYCLE_BASELINE = 10
CONDITION_NONE = 0
CONDITION_STIM = 1
CONDITION_END = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def remap(path: str | Path) -> Path:
    text = str(path)
    p = Path(text)
    if p.is_file():
        return p
    rel = None
    for pref in OLD_PREFIXES:
        if text.startswith(pref):
            rel = text[len(pref) :]
            break
    if rel is None:
        return p
    for root in RAW_ROOTS:
        cand = root / rel
        if cand.is_file():
            return cand
    return RAW_ROOTS[0] / rel


def canonical_paradigm() -> np.ndarray:
    """Reproduce presentStimParams.m runParadigmFinal (26×2)."""
    rows: list[list[float]] = [[0, CONDITION_NONE], [FIRST_BASELINE_END, CONDITION_STIM]]
    cycle = np.tile([CYCLE_STIM, CYCLE_BASELINE], NUM_CYCLES)
    conds = np.tile([CONDITION_NONE, CONDITION_STIM], NUM_CYCLES)
    ends = np.cumsum(cycle) + FIRST_BASELINE_END
    for vol, cond in zip(ends, conds, strict=True):
        rows.append([float(vol), float(cond)])
    rows[-1][1] = CONDITION_END
    return np.asarray(rows, dtype=float)


def build_events_canonical(scan_info: Path, stim_order: Path) -> StrictEventResult:
    try:
        scan_number = fmri_number(scan_info)
        stim_number = fmri_number(stim_order)
        chosen_run = selected_run(scan_info)
        if scan_number is None or stim_number is None:
            raise ValueError("run identity missing from source filenames")
        if scan_number != stim_number:
            raise ValueError(
                f"scan/stim fMRI_number mismatch ({scan_number} != {stim_number})"
            )
        triggers = _scan_triggers(scan_info)
        order = _stim_order(stim_order)
        paradigm = canonical_paradigm()
        indices = paradigm[:, 0]
        if not np.all(indices == np.round(indices)):
            raise ValueError("paradigm time axis is not integer scanner-volume indices")
        indices = indices.astype(int)
        if np.any(indices < 0) or np.any(indices > triggers.size):
            raise ValueError(
                f"paradigm index outside trigger/terminal range 0..{triggers.size}"
            )
        if np.any(np.diff(indices) <= 0):
            raise ValueError("paradigm indices are not strictly increasing")

        relative = triggers - triggers[0]
        endpoint_note = ""
        if np.any(indices == triggers.size):
            intervals = np.diff(triggers)
            measured_tr = float(np.median(intervals))
            if measured_tr <= 0 or float(np.max(np.abs(intervals - measured_tr))) > (
                0.01 * measured_tr
            ):
                raise ValueError(
                    "terminal paradigm boundary needs extrapolation but measured TR is unstable"
                )
            relative = np.concatenate([relative, [float(relative[-1] + measured_tr)]])
            endpoint_note = (
                "; terminal boundary derived as final trigger + measured median TR"
            )

        events: list[tuple[float, float, str]] = []
        stim_index = 0
        for index in range(paradigm.shape[0] - 1):
            condition = int(round(float(paradigm[index, 1])))
            if condition == CONDITION_END:
                continue
            onset = float(relative[indices[index]])
            end = float(relative[indices[index + 1]])
            duration = end - onset
            if onset < 0 or duration <= 0:
                raise ValueError("non-positive event duration or negative onset")
            if condition == CONDITION_NONE:
                trial_type = "baseline"
            elif condition == CONDITION_STIM:
                if stim_index >= order.size:
                    raise ValueError("paradigm has more stimulus blocks than stim order")
                trial_type = f"stim-{int(order[stim_index]):02d}"
                stim_index += 1
            else:
                raise ValueError(f"unsupported paradigm condition {condition}")
            events.append((onset, duration, trial_type))
        if stim_index != order.size:
            raise ValueError(
                f"used {stim_index} stimulus labels but order contains {order.size}"
            )
        return StrictEventResult(
            status="ready",
            reason=(
                "actual triggerTimes + canonical presentStimParams paradigm + "
                f"Stim_order_selected; runs_random not required{endpoint_note}"
            ),
            events=tuple(events),
            fmri_number=scan_number,
            selected_run=chosen_run,
        )
    except Exception as exc:  # noqa: BLE001
        return StrictEventResult(status="requires_manual_review", reason=str(exc))


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
        if number in protocol_numbers and "fmri" in sidecar.name.lower():
            matches.append(sidecar)
    if len(matches) != 1:
        return (
            "",
            None,
            f"expected one matching non-phase BOLD sidecar, found {len(matches)}",
        )
    dest = matches[0].with_name(matches[0].name.removesuffix("_bold.json") + "_events.tsv")
    rel = f"{participant}/{session}/func/{dest.name}"
    return rel, dest, "matched by recorded BOLD protocol metadata"


def load_session_mapping() -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], set[str]] = defaultdict(set)
    with SESSION_MAP.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            participant = (row.get("participant_id") or "").strip()
            subject = (
                row.get("canonical_subject_id")
                or row.get("canonical_subject")
                or ""
            ).strip()
            if not participant.startswith("sub-") or not subject:
                continue
            if (row.get("exclusion_status") or "").strip().lower() == "excluded":
                continue
            sessions = {
                (row.get("session_id") or "").strip(),
                (row.get("session_label") or "").strip(),
                (row.get("canonical_session") or "").strip(),
            }
            for session in sessions - {""}:
                values[(subject, session)].add(participant)
    return {key: next(iter(item)) for key, item in values.items() if len(item) == 1}


def collect_timing_families(
    mappings: dict[tuple[str, str], str],
) -> dict[tuple[str, str, str], dict[str, list[Path]]]:
    timing: dict[tuple[str, str, str], dict[str, list[Path]]] = defaultdict(
        lambda: defaultdict(list)
    )
    with INV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            path = remap(row.get("path", ""))
            if not path.is_file() or path.suffix.lower() != ".mat":
                continue
            if "2-grating" not in str(path).lower() and "2-Grating" not in str(path):
                # inventory paths are case-sensitive on disk after remap
                if "/2-Grating/" not in str(path) and "/2-grating/" not in str(path).lower():
                    continue
            subject = (row.get("subject") or "").strip()
            session = (row.get("session") or "").strip()
            participant = mappings.get((subject, session), "")
            if not participant:
                continue
            key = (participant, session, str(path.parent))
            lower = path.name.lower()
            if "scan_info" in lower:
                timing[key]["scan_info"].append(path)
            elif FMRI_STEM.fullmatch(path.stem):
                timing[key]["stim_order"].append(path)
            elif path.stem.lower() == "runs_random":
                timing[key]["runs_random"].append(path)
    return timing


@dataclass
class GenRow:
    participant_id: str
    session_id: str
    fmri_number: int
    destination: str
    status: str
    method: str
    reason: str
    n_events: int
    scan_info: str
    stim_order: str
    already_existed: str


def main() -> int:
    mappings = load_session_mapping()
    timing = collect_timing_families(mappings)
    rows: list[GenRow] = []
    written = 0
    skipped_existing = 0
    failed = 0

    for (participant, session, _parent), families in sorted(timing.items()):
        scans_by_run: dict[int, list[Path]] = defaultdict(list)
        stim_by_run: dict[int, list[Path]] = defaultdict(list)
        for path in families.get("scan_info", []):
            match = re.search(r"(?i)fmri_number_is(\d+)", path.name)
            if match:
                scans_by_run[int(match.group(1))].append(path)
        for path in families.get("stim_order", []):
            match = FMRI_STEM.fullmatch(path.stem)
            if match:
                stim_by_run[int(match.group(1))].append(path)
        workspaces = families.get("runs_random", [])

        for number in sorted(set(scans_by_run) | set(stim_by_run)):
            scans = scans_by_run.get(number, [])
            stims = stim_by_run.get(number, [])
            if len(scans) != 1 or len(stims) != 1:
                rows.append(
                    GenRow(
                        participant,
                        session,
                        number,
                        "",
                        "failed",
                        "cardinality",
                        f"scan={len(scans)}, stim={len(stims)}, workspace={len(workspaces)}",
                        0,
                        ";".join(str(p) for p in scans),
                        ";".join(str(p) for p in stims),
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
                # Recoverable path: canonical paradigm
                result = build_events_canonical(scan_info, stim_order)
                method = "canonical_paradigm"

            rel, dest, match_reason = bids_destination(participant, session, number)
            if result.status != "ready":
                rows.append(
                    GenRow(
                        participant,
                        session,
                        number,
                        rel,
                        "failed",
                        method,
                        result.reason,
                        0,
                        str(scan_info),
                        str(stim_order),
                        "False",
                    )
                )
                failed += 1
                continue
            if dest is None:
                rows.append(
                    GenRow(
                        participant,
                        session,
                        number,
                        "",
                        "failed_no_bids_match",
                        method,
                        match_reason,
                        len(result.events),
                        str(scan_info),
                        str(stim_order),
                        "False",
                    )
                )
                failed += 1
                continue

            existed = dest.exists()
            if existed:
                skipped_existing += 1
                rows.append(
                    GenRow(
                        participant,
                        session,
                        number,
                        rel,
                        "skipped_existing",
                        method,
                        result.reason + "; " + match_reason,
                        len(result.events),
                        str(scan_info),
                        str(stim_order),
                        "True",
                    )
                )
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            write_events(dest, result)
            written += 1
            rows.append(
                GenRow(
                    participant,
                    session,
                    number,
                    rel,
                    "written",
                    method,
                    result.reason + "; " + match_reason,
                    len(result.events),
                    str(scan_info),
                    str(stim_order),
                    "False",
                )
            )

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with OUT_REPORT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "participant_id",
                "session_id",
                "fmri_number",
                "destination",
                "status",
                "method",
                "reason",
                "n_events",
                "scan_info",
                "stim_order",
                "already_existed",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)

    status_counts = Counter(r.status for r in rows)
    method_counts = Counter(r.method for r in rows if r.status == "written")
    total_events = sum(1 for _ in BIDS.glob("sub-*/ses-*/func/*_task-fmri_*_events.tsv"))
    summary = {
        "generated_at_utc": utc_now(),
        "timing_families": len(timing),
        "rows": len(rows),
        "written": written,
        "skipped_existing": skipped_existing,
        "failed": failed,
        "status_counts": dict(status_counts),
        "written_method_counts": dict(method_counts),
        "bids_task_fmri_events_total": total_events,
        "report": str(OUT_REPORT),
    }
    (OUT_REPORT.parent / "recoverable_events_generation_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if written > 0 or skipped_existing > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
