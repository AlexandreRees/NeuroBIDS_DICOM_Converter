#!/usr/bin/env python3
"""Sync grating/rest publication assets from bids/ → release_dataset/ and write docs.

Actions:
  1. Copy missing task-fmri events (+ events.json) when mag BOLD already in release
  2. Copy missing mag BOLD (+ json, events, sbref) for known bids-only stems
  3. Write coverage / exclusion / dual-rest tables under release docs/
  4. Does not invent events; does not touch raw_original/

Usage:
  python3 code/sync_grating_rest_for_publication.py --dry-run
  python3 code/sync_grating_rest_for_publication.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRATCH = Path("/home/alexrees/scratch")
BIDS = SCRATCH / "bids"
RELEASE = SCRATCH / "release_dataset"
REPORT = SCRATCH / "reports" / "grating_rest_publication_audit"
GAP57 = SCRATCH / "reports" / "grating_gap_audit" / "gap_57_missing_events_detail.tsv"


def mag_stems(root: Path, task: str) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in root.glob(f"sub-*/ses-*/func/*task-{task}*_bold.nii.gz"):
        if "part-phase" in p.name:
            continue
        out[p.name.replace("_bold.nii.gz", "")] = p
    return out


def event_stems(root: Path, task: str) -> dict[str, Path]:
    return {
        p.name.replace("_events.tsv", ""): p
        for p in root.glob(f"sub-*/ses-*/func/*task-{task}*_events.tsv")
    }


def copy_file(src: Path, dst: Path, dry_run: bool, log: list[dict[str, str]]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    action = "WOULD_COPY" if dry_run else "COPIED"
    if dst.exists():
        # overwrite only if sizes differ
        if dst.stat().st_size == src.stat().st_size:
            log.append({"action": "SKIP_SAME", "src": str(src), "dst": str(dst)})
            return
        action = "WOULD_OVERWRITE" if dry_run else "OVERWROTE"
    if not dry_run:
        shutil.copy2(src, dst)
    log.append({"action": action, "src": str(src), "dst": str(dst)})


def sync_events(dry_run: bool) -> list[dict[str, str]]:
    log: list[dict[str, str]] = []
    eb, er = event_stems(BIDS, "fmri"), event_stems(RELEASE, "fmri")
    mr = mag_stems(RELEASE, "fmri")
    for stem in sorted(set(eb) - set(er)):
        if stem not in mr:
            log.append({"action": "SKIP_NO_RELEASE_BOLD", "src": stem, "dst": ""})
            continue
        src_tsv = eb[stem]
        rel = src_tsv.relative_to(BIDS)
        copy_file(src_tsv, RELEASE / rel, dry_run, log)
        src_json = src_tsv.with_name(src_tsv.name.replace("_events.tsv", "_events.json"))
        if src_json.is_file():
            copy_file(src_json, RELEASE / src_json.relative_to(BIDS), dry_run, log)
    return log


def sync_missing_bold_families(dry_run: bool) -> list[dict[str, str]]:
    """Copy mag bold (+json, events, sbref) for stems in bids but not release."""
    log: list[dict[str, str]] = []
    mb, mr = mag_stems(BIDS, "fmri"), mag_stems(RELEASE, "fmri")
    for stem in sorted(set(mb) - set(mr)):
        src_bold = mb[stem]
        func = src_bold.parent
        # copy all non-phase files matching this stem prefix except part-phase bold if any
        for src in sorted(func.glob(f"{stem}*")):
            # keep part-phase_sbref if present; skip part-phase_bold only if we want consistency
            # Include everything that belongs to the run family already partially in release
            copy_file(src, RELEASE / src.relative_to(BIDS), dry_run, log)
    return log


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = fields or list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def build_coverage_tables() -> dict[str, object]:
    mb = mag_stems(BIDS, "fmri")
    mr = mag_stems(RELEASE, "fmri")
    eb = event_stems(BIDS, "fmri")
    er = event_stems(RELEASE, "fmri")

    # Join historical gap reasons when available
    gap_reason: dict[tuple[str, str, str], str] = {}
    if GAP57.is_file():
        for r in csv.DictReader(GAP57.open(encoding="utf-8"), delimiter="\t"):
            run = str(r.get("bids_run") or "").zfill(2)
            gap_reason[(r["subject"], r["session"], run)] = r.get("gap_reason") or ""

    grating_rows = []
    for stem, p in sorted(mr.items()):
        m = re.match(r"(sub-\d+)_(ses-\d+)_task-fmri_run-(\d+)", stem)
        sub, ses, run = (m.group(1), m.group(2), m.group(3)) if m else ("", "", "")
        has_ev = stem in er
        reason = gap_reason.get((sub, ses, run), "")
        if has_ev:
            status = "HAS_EVENTS"
        elif reason:
            status = "NO_EVENTS"
        else:
            status = "NO_EVENTS"
        grating_rows.append(
            {
                "bold_stem": stem,
                "subject": sub,
                "session": ses,
                "run": run,
                "has_events": "yes" if has_ev else "no",
                "events_status": status,
                "gap_reason": reason if not has_ev else "",
                "in_bids": "yes" if stem in mb else "no",
            }
        )

    excl = [r for r in grating_rows if r["has_events"] == "no"]

    # Physio coverage grating/rest
    def phys_map(task: str) -> dict[str, set[str]]:
        out: dict[str, set[str]] = defaultdict(set)
        for p in RELEASE.glob(f"sub-*/ses-*/func/*task-{task}*_physio.tsv.gz"):
            m = re.match(r"(.+)_recording-(\w+)_physio", p.name)
            if m:
                out[m.group(1)].add(m.group(2))
        return out

    gphys, rphys = phys_map("fmri"), phys_map("rest")
    rest_mag = mag_stems(RELEASE, "rest")

    rest_rows = []
    # primary rest run = lowest SeriesNumber per session
    by_ss: dict[tuple[str, str], list[tuple[str, Path]]] = defaultdict(list)
    for stem, p in rest_mag.items():
        m = re.match(r"(sub-\d+)_(ses-\d+)", stem)
        if not m:
            continue
        by_ss[(m.group(1), m.group(2))].append((stem, p))

    primary: dict[str, str] = {}
    dual_rows = []
    for (sub, ses), items in sorted(by_ss.items()):
        scored = []
        for stem, p in items:
            js = p.with_name(p.name.replace("_bold.nii.gz", "_bold.json"))
            sn = 10**9
            if js.is_file():
                try:
                    sn = int(float(json.loads(js.read_text()).get("SeriesNumber") or 10**9))
                except Exception:
                    pass
            scored.append((sn, stem))
        scored.sort()
        prim = scored[0][1]
        for sn, stem in scored:
            primary[stem] = "primary" if stem == prim else "secondary_or_redo"
        if len(scored) > 1:
            dual_rows.append(
                {
                    "subject": sub,
                    "session": ses,
                    "n_rest_runs": str(len(scored)),
                    "primary_bold_stem": prim,
                    "all_stems": ";".join(s for _, s in scored),
                    "note": "Multiple rest magnitude BOLDs in session; prefer primary (lowest SeriesNumber) unless analysis requires otherwise",
                }
            )

    for stem, p in sorted(rest_mag.items()):
        m = re.match(r"(sub-\d+)_(ses-\d+)_task-rest_run-(\d+)", stem)
        sub, ses, run = (m.group(1), m.group(2), m.group(3)) if m else ("", "", "")
        ch = rphys.get(stem, set())
        rest_rows.append(
            {
                "bold_stem": stem,
                "subject": sub,
                "session": ses,
                "run": run,
                "run_role": primary.get(stem, "primary"),
                "has_physio": "yes" if ch else "no",
                "physio_channels": ";".join(sorted(ch)),
                "has_events": "no",
                "events_note": "intentional_absent_continuous_fixation",
            }
        )

    # Incomplete subjects
    all_subs = sorted(p.name for p in RELEASE.glob("sub-*"))
    incomplete = []
    for s in all_subs:
        has_rest = any(
            True
            for _ in (RELEASE / s).glob("ses-*/func/*task-rest*_bold.nii.gz")
            if "part-phase" not in _.name
        )
        has_fmri = any(
            True
            for _ in (RELEASE / s).glob("ses-*/func/*task-fmri*_bold.nii.gz")
            if "part-phase" not in _.name
        )
        if not has_rest or not has_fmri:
            incomplete.append(
                {
                    "subject": s,
                    "has_task_rest_mag": "yes" if has_rest else "no",
                    "has_task_fmri_mag": "yes" if has_fmri else "no",
                    "note": (
                        "No resting-state magnitude BOLD"
                        if not has_rest
                        else "No grating (task-fmri) magnitude BOLD"
                    ),
                }
            )

    g_with_phys = sum(1 for s in mr if s in gphys)
    g_with_pr = sum(1 for s in mr if {"pulse", "respiratory"} <= gphys.get(s, set()))
    r_with_phys = sum(1 for s in rest_mag if s in rphys)

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "grating_mag_bold_release": len(mr),
        "grating_events_release": len(er),
        "grating_events_coverage_pct": round(100.0 * len(er) / len(mr), 1) if mr else 0,
        "grating_without_events": len(excl),
        "grating_physio_any_pct": round(100.0 * g_with_phys / len(mr), 1) if mr else 0,
        "grating_physio_pulse_resp_pct": round(100.0 * g_with_pr / len(mr), 1) if mr else 0,
        "rest_mag_bold_release": len(rest_mag),
        "rest_events": 0,
        "rest_physio_any_pct": round(100.0 * r_with_phys / len(rest_mag), 1) if rest_mag else 0,
        "rest_dual_run_sessions": len(dual_rows),
        "subjects_incomplete_rest_or_grating": len(incomplete),
    }

    docs = RELEASE / "docs" / "Protocols"
    write_tsv(docs / "grating_events_coverage.tsv", grating_rows)
    write_tsv(docs / "grating_events_exclusions.tsv", excl)
    write_tsv(docs / "rest_run_coverage.tsv", rest_rows)
    write_tsv(docs / "rest_dual_run_sessions.tsv", dual_rows)
    write_tsv(docs / "functional_incomplete_subjects.tsv", incomplete)
    (docs / "grating_rest_coverage_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    # Mirror under reports audit folder
    REPORT.mkdir(parents=True, exist_ok=True)
    for name in (
        "grating_events_coverage.tsv",
        "grating_events_exclusions.tsv",
        "rest_run_coverage.tsv",
        "rest_dual_run_sessions.tsv",
        "functional_incomplete_subjects.tsv",
        "grating_rest_coverage_summary.json",
    ):
        src = docs / name
        if src.exists():
            shutil.copy2(src, REPORT / name)

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    log_all: list[dict[str, str]] = []
    # BOLD families first so events for formerly bids-only stems can sync next
    log_all.extend(sync_missing_bold_families(args.dry_run))
    log_all.extend(sync_events(args.dry_run))

    out_log = REPORT / ("sync_log_dryrun.tsv" if args.dry_run else "sync_log.tsv")
    write_tsv(out_log, log_all, ["action", "src", "dst"])
    print(Counter(r["action"] for r in log_all))

    if args.dry_run:
        print("Dry-run only; coverage tables not finalized.")
        return 0

    summary = build_coverage_tables()
    print(json.dumps(summary, indent=2))

    # Post-check parity
    mr = mag_stems(RELEASE, "fmri")
    er = event_stems(RELEASE, "fmri")
    mb = mag_stems(BIDS, "fmri")
    eb = event_stems(BIDS, "fmri")
    print(
        f"POST mag bids/release {len(mb)}/{len(mr)} | events bids/release {len(eb)}/{len(er)} | "
        f"release missing events {len(set(mr)-set(er))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
