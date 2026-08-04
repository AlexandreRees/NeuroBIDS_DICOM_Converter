#!/usr/bin/env python3
"""Decompose why 118 task-fmri BOLD runs were tagged sources_uncertain_or_absent."""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/home/alexrees/scratch")
BIDS = ROOT / "bids"
WITHHELD = (
    ROOT
    / "release_candidate_plan/level1_dry_run_20260721T1610/pre_execute_audit/withheld_events_summary.tsv"
)
READY = ROOT / "release_candidate_plan/level1_final_audit_20260721/ready_events_verification.tsv"
INV = ROOT / "reports/stimulus_audit/stimulus_inventory.tsv"
OUT = ROOT / "reports/stimulus_audit"
PMAP = ROOT / "metadata/participant_mapping.csv"

bold_re = re.compile(r"(sub-\d+)_(ses-\d+)_task-([a-zA-Z0-9]+)_run-(\d+)_bold\.json$")
events_set = {p.name for p in BIDS.glob("sub-*/ses-*/func/*_events.tsv")}
fmri_bold = []
for p in BIDS.glob("sub-*/ses-*/func/*_bold.json"):
    if "part-phase" in p.name:
        continue
    m = bold_re.search(p.name)
    if not m:
        continue
    sub, ses, task, run = m.groups()
    if task != "fmri":
        continue
    ev = f"{sub}_{ses}_task-{task}_run-{run}_events.tsv"
    fmri_bold.append(
        {
            "participant_id": sub,
            "session_id": ses,
            "run": run,
            "has_events": ev in events_set,
        }
    )

print(f"fmri_bold={len(fmri_bold)} with_events={sum(1 for r in fmri_bold if r['has_events'])}")

ready_rows = list(csv.DictReader(READY.open(), delimiter="\t")) if READY.exists() else []
withheld_rows = (
    list(csv.DictReader(WITHHELD.open(), delimiter="\t")) if WITHHELD.exists() else []
)
print(f"ready={len(ready_rows)} withheld={len(withheld_rows)}")
print("withheld cols:", list(withheld_rows[0].keys()) if withheld_rows else None)
print("classification:", Counter(r.get("classification") for r in withheld_rows))
print("failure_reason top:")
for reason, n in Counter(r.get("failure_reason") for r in withheld_rows).most_common(12):
    print(f"  {n:4d}  {reason[:140]}")

withheld_by_session = defaultdict(list)
for r in withheld_rows:
    withheld_by_session[(r["participant_id"], r["session_id"])].append(r)

ready_sessions = set()
for r in ready_rows:
    dest = r.get("destination", "")
    m = re.search(r"(sub-\d+)/(ses-\d+)/", dest)
    if m:
        ready_sessions.add(m.groups())
    elif r.get("participant_id") and r.get("session_id"):
        ready_sessions.add((r["participant_id"], r["session_id"]))

level1_sessions = set(withheld_by_session) | ready_sessions
print(f"level1 sessions covered (withheld∪ready): {len(level1_sessions)}")

status_by_run = []
for br in fmri_bold:
    key = (br["participant_id"], br["session_id"])
    if br["has_events"]:
        status = "already_released"
    else:
        sess_w = withheld_by_session.get(key, [])
        if sess_w:
            classes = Counter(w["classification"] for w in sess_w)
            if classes.get("recoverable_with_deterministic_mapping", 0) >= 1:
                status = "reconstructable_with_mapping_fix"
            else:
                status = "ambiguous"
        else:
            status = "sources_uncertain_or_absent"
    status_by_run.append({**br, "status": status, "in_level1_session": key in level1_sessions})

print("status counts:", Counter(r["status"] for r in status_by_run))

uncertain = [r for r in status_by_run if r["status"] == "sources_uncertain_or_absent"]
print(f"uncertain runs={len(uncertain)}")
print(
    "uncertain sessions:",
    len({(r["participant_id"], r["session_id"]) for r in uncertain}),
)
print("uncertain runs per session (top 30):")
for (sub, ses), n in Counter(
    (r["participant_id"], r["session_id"]) for r in uncertain
).most_common(30):
    print(f"  {n:3d}  {sub} {ses}")

nums = sorted({int(r["participant_id"].split("-")[1]) for r in uncertain})
print(f"uncertain subjects: n={len(nums)} min={nums[0]} max={nums[-1]}")
print("  " + ",".join(f"{n:03d}" for n in nums))

bids_sessions = {(r["participant_id"], r["session_id"]) for r in fmri_bold}
print(
    f"BIDS fmri sessions={len(bids_sessions)} level1={len(level1_sessions)} "
    f"bids_not_in_level1={len(bids_sessions - level1_sessions)}"
)

# Participant mapping
bids_to_sources: dict[str, set[str]] = defaultdict(set)
if PMAP.exists():
    with PMAP.open() as f:
        rows = list(csv.DictReader(f))
        print("pmap cols:", list(rows[0].keys()) if rows else None)
        print("pmap sample:", rows[0] if rows else None)
        for row in rows:
            bids = ""
            src = ""
            for k, v in row.items():
                kl = k.lower()
                if not bids and ("participant" in kl or kl in {"bids_id", "sub", "bids_subject"}):
                    bids = (v or "").strip()
                if not src and (
                    "source" in kl
                    or "original" in kl
                    or "local" in kl
                    or kl in {"subject", "subject_id"}
                ):
                    src = (v or "").strip()
            if bids and not bids.startswith("sub-"):
                digs = re.findall(r"\d+", bids)
                if digs:
                    bids = f"sub-{int(digs[0]):03d}"
            if src and bids:
                bids_to_sources[bids].add(src)

print(f"bids_with_sources={len(bids_to_sources)}")

# Inventory index
inv = list(csv.DictReader(INV.open(), delimiter="\t"))
scan_by_src = defaultdict(list)
stim_by_src = defaultdict(list)
ws_by_src = defaultdict(list)
for r in inv:
    src = (r.get("subject_source") or "").strip()
    if r["role"] == "scan_info_triggers":
        scan_by_src[src].append(r)
    elif r["role"] == "stim_order":
        stim_by_src[src].append(r)
    elif r["role"] == "runs_random_workspace":
        ws_by_src[src].append(r)

print(
    f"inventory unique subjects with scan_info={len(scan_by_src)} "
    f"stim={len(stim_by_src)} ws={len(ws_by_src)}"
)
print("sample inventory subject_source:", list(scan_by_src)[:15])


def variants(sources: set[str]) -> set[str]:
    out: set[str] = set()
    for s in sources:
        out.add(s)
        out.add(s.upper())
        m = re.match(r"([A-Za-z_]+)0*(\d+)$", s)
        if m:
            pref, num = m.group(1), m.group(2)
            out.add(f"{pref}{int(num):02d}")
            out.add(f"{pref}{int(num):03d}")
            out.add(f"{pref}{num}")
            out.add(f"{pref.upper()}{int(num):02d}")
            out.add(f"{pref.upper()}{int(num):03d}")
    return out


def ses_match(rows: list[dict], ses: str) -> list[dict]:
    out = []
    for r in rows:
        ss = r.get("session_source", "")
        path = r.get("path_original", "").lower()
        is_ses02 = (
            "ses-02" in ss
            or ss.endswith("02")
            or "session2" in path
            or "session02" in path
            or "session_02" in path
            or "session02" in path
        )
        if ses == "ses-02":
            if is_ses02:
                out.append(r)
        else:
            if not is_ses02:
                out.append(r)
    return out


uncertain_sessions = sorted({(r["participant_id"], r["session_id"]) for r in uncertain})
detail_rows = []
has_scan = has_stim = has_ws = has_none = 0
for sub, ses in uncertain_sessions:
    sources = bids_to_sources.get(sub, set())
    vars_ = variants(sources)
    scans = ses_match([r for s in vars_ for r in scan_by_src[s]], ses)
    stims = ses_match([r for s in vars_ for r in stim_by_src[s]], ses)
    wss = ses_match([r for s in vars_ for r in ws_by_src[s]], ses)
    nruns = sum(
        1 for r in uncertain if r["participant_id"] == sub and r["session_id"] == ses
    )
    flag = "HAS_MATLAB_SOURCES" if scans or stims else "NO_MATLAB_MATCHED"
    if scans:
        has_scan += 1
    if stims:
        has_stim += 1
    if wss:
        has_ws += 1
    if not scans and not stims:
        has_none += 1
    detail_rows.append(
        {
            "participant_id": sub,
            "session_id": ses,
            "n_uncertain_bold_runs": nruns,
            "source_ids": "|".join(sorted(sources)) or "UNMAPPED",
            "n_scan_info_matched": len(scans),
            "n_stim_order_matched": len(stims),
            "n_workspace_matched": len(wss),
            "matlab_source_status": flag,
        }
    )

print(f"\nUncertain sessions={len(uncertain_sessions)}")
print(f"  with scan_info matched: {has_scan}")
print(f"  with stim_order matched: {has_stim}")
print(f"  with workspace matched: {has_ws}")
print(f"  NO matlab matched: {has_none}")

no = [d for d in detail_rows if d["matlab_source_status"] == "NO_MATLAB_MATCHED"]
yes = [d for d in detail_rows if d["matlab_source_status"] == "HAS_MATLAB_SOURCES"]
print(
    f"\nNO_MATLAB_MATCHED: sessions={len(no)} runs={sum(d['n_uncertain_bold_runs'] for d in no)}"
)
print(f"  unmapped bids: {sum(1 for d in no if d['source_ids']=='UNMAPPED')}")
print(
    f"  mapped but no inventory hit: {sum(1 for d in no if d['source_ids']!='UNMAPPED')}"
)
print(
    f"\nHAS_MATLAB_SOURCES (false uncertain vs Level-1 gap): "
    f"sessions={len(yes)} runs={sum(d['n_uncertain_bold_runs'] for d in yes)}"
)
for d in yes[:40]:
    print(
        f"  {d['participant_id']} {d['session_id']} runs={d['n_uncertain_bold_runs']} "
        f"scan={d['n_scan_info_matched']} stim={d['n_stim_order_matched']} src={d['source_ids']}"
    )

print("\nNO_MATLAB sample:")
for d in no[:40]:
    print(
        f"  {d['participant_id']} {d['session_id']} runs={d['n_uncertain_bold_runs']} "
        f"src={d['source_ids']}"
    )

# Why Level-1 missed sessions that have MATLAB?
# Compare level1 subject set vs all BIDS
level1_subs = {s[0] for s in level1_sessions}
bids_subs = {s[0] for s in bids_sessions}
print(f"\nlevel1 subjects={len(level1_subs)} bids subjects={len(bids_subs)}")
print(f"bids subjects not in level1: {sorted(bids_subs - level1_subs)}")

# Check if Level-1 plan only covered Control / low IDs
l1_nums = sorted(int(s.split("-")[1]) for s in level1_subs)
print(f"level1 subject nums: min={l1_nums[0]} max={l1_nums[-1]} n={len(l1_nums)}")

fields = list(detail_rows[0].keys())
with (OUT / "uncertain_118_session_breakdown.tsv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
    w.writeheader()
    w.writerows(
        sorted(
            detail_rows,
            key=lambda d: (d["matlab_source_status"], d["participant_id"], d["session_id"]),
        )
    )

recon = []
for br in status_by_run:
    recon.append(
        {
            "participant_id": br["participant_id"],
            "session_id": br["session_id"],
            "bids_run": br["run"],
            "has_events_tsv": str(br["has_events"]),
            "reconstruction_status": br["status"],
            "in_level1_session": str(br["in_level1_session"]),
            "can_reconstruct_complete_events": (
                "YES"
                if br["status"]
                in {"already_released", "reconstructable_with_mapping_fix"}
                else "UNCERTAIN"
                if br["status"] == "sources_uncertain_or_absent"
                else "NO"
            ),
            "blockers": (
                "not in Level-1 events plan for this session"
                if br["status"] == "sources_uncertain_or_absent"
                else ""
            ),
        }
    )
with (OUT / "fmri_events_reconstruction.tsv").open("w", newline="") as f:
    w = csv.DictWriter(
        f, fieldnames=list(recon[0].keys()), delimiter="\t", lineterminator="\n"
    )
    w.writeheader()
    w.writerows(recon)

summary = {
    "n_uncertain_runs": len(uncertain),
    "n_uncertain_sessions": len(uncertain_sessions),
    "sessions_with_matlab": len(yes),
    "runs_with_matlab_but_uncertain": sum(d["n_uncertain_bold_runs"] for d in yes),
    "sessions_without_matlab_match": len(no),
    "runs_without_matlab_match": sum(d["n_uncertain_bold_runs"] for d in no),
    "status_counts": dict(Counter(r["status"] for r in status_by_run)),
}
(OUT / "uncertain_118_summary.json").write_text(
    __import__("json").dumps(summary, indent=2) + "\n"
)
print("\nWrote uncertain_118_session_breakdown.tsv, uncertain_118_summary.json")
print("regenerated fmri_events_reconstruction.tsv")
print(summary)
