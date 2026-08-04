#!/usr/bin/env python3
"""Re-validate former runmap=LIKELY PhysioLog cases and convert if CONFIRMED.

Fail-closed gates (same as production converter):
  * SampleTime-derived SamplingFrequency (PASS)
  * CSA tick StartTime (PASS, MEDIUM)
  * Unique ProtocolName → magnitude BOLD match (CONFIRMED)
  * Non-flat waveform samples (≥10)

Writes under bids/ only (not release) unless --also-release.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse production converter helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert_physiolog_to_bids import (  # noqa: E402
    CHANNEL_TO_BIDS,
    convert_one,
    _write_tsv,
)

SIEMENS_CSA_TICK_SECONDS = 0.0025
BIDS = Path("/lustre07/scratch/alexrees/bids")
AUDIT = Path("/lustre07/scratch/alexrees/reports/physiology_audit")
READY = AUDIT / "final_bids_physio_readiness"
DEEP_TSV = AUDIT / "physiolog_dicom_deep.tsv"
EXCLUDED_TSV = READY / "EXCLUDED_324_physio_reasons.tsv"
OUT_DIR = READY / "likely_recovery"

_RE_BOLD = re.compile(
    r"(sub-\d+)_(ses-\d+)_task-([A-Za-z0-9]+)(?:_.*)?_run-(\d+)_bold\.json$"
)

# UID → (subject, session, protocol, scandate_key)
TARGET_CASES = {
    "1.3.12.2.1107.5.2.43.166092.2023101912101959759548539.0.0.0": (
        "sub-024",
        "ses-01",
        "Control2_AP",
        "20231019_121019",
    ),
    "1.3.12.2.1107.5.2.43.166092.2023101912123562697556028.0.0.0": (
        "sub-024",
        "ses-01",
        "Control3_PA",
        "20231019_121053",
    ),
    "1.3.12.2.1107.5.2.43.166092.2023101911150376273181168.0.0.0": (
        "sub-024",
        "ses-01",
        "fMRI2_AP",
        "20231019_111503",
    ),
    "1.3.12.2.1107.5.2.43.166092.2024092011565638337150295.0.0.0": (
        "sub-047",
        "ses-01",
        "fMRI4_AP",
        "20240920_115655",
    ),
}


def load_bold_index(
    bids_root: Path, subjects: set[str] | None = None
) -> dict[tuple[str, str], list[dict[str, str]]]:
    out: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    sub_dirs = (
        [bids_root / s for s in sorted(subjects)]
        if subjects
        else sorted(bids_root.glob("sub-*"))
    )
    for sub_dir in sub_dirs:
        if not sub_dir.is_dir():
            continue
        for jp in sub_dir.glob("ses-*/func/*_bold.json"):
            m = _RE_BOLD.search(jp.name)
            if not m:
                continue  # drops part-phase
            data = json.loads(jp.read_text(encoding="utf-8"))
            nii = jp.with_name(jp.name.replace("_bold.json", "_bold.nii.gz"))
            out[(m.group(1), m.group(2))].append(
                {
                    "json": str(jp),
                    "nii": str(nii),
                    "protocol_name": str(data.get("ProtocolName") or ""),
                    "task": m.group(3),
                    "run": m.group(4),
                }
            )
    return out


def find_deep_row(rows: list[dict[str, str]], protocol: str, scandate_key: str, subject_hint: str) -> dict[str, str] | None:
    hits = []
    for r in rows:
        if (r.get("protocol_name") or "") != protocol:
            continue
        sd = r.get("scandate") or ""
        fp = r.get("filepath") or ""
        if scandate_key and not (sd.startswith(scandate_key) or scandate_key in sd):
            # Control3: match by protocol + SUBC25 session01 path
            if protocol == "Control3_PA" and "SUBC25-Session01" in fp:
                hits.append(r)
            continue
        # subject path hints
        if subject_hint == "sub-024" and "SUBC25" not in fp:
            continue
        if subject_hint == "sub-047" and "SUBC48_Session01_2024SEP20" not in fp and "SUBC48_Session01" not in fp:
            # allow SESSION01_2024SEP20 variants
            if "2024SEP20" not in fp and "20240920" not in fp:
                continue
        hits.append(r)
    if not hits:
        return None
    # Prefer unique filepath (dedupe identical content rows)
    uniq = {}
    for h in hits:
        uniq[h["filepath"]] = h
    hits = list(uniq.values())
    if len(hits) == 1:
        return hits[0]
    # Prefer Session01 2024SEP20 for sub-047
    if subject_hint == "sub-047":
        pref = [h for h in hits if "Session01_2024SEP20" in h["filepath"] or "SESSION01_2024SEP20" in h["filepath"]]
        if len(pref) == 1:
            return pref[0]
        if pref:
            return pref[0]
    return hits[0]


def parse_sampletimes(s: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in (s or "").split(";"):
        if "=" not in part:
            continue
        ch, ms = part.split("=", 1)
        out[ch.strip().upper()] = float(ms)
    return out


def build_job(
    uid: str,
    subject: str,
    session: str,
    protocol: str,
    deep: dict[str, str],
    bold: dict[str, str],
) -> dict[str, Any]:
    ms_map = parse_sampletimes(deep.get("sampletime_by_type") or "")
    hz_map = {ch: 1000.0 / ms for ch, ms in ms_map.items() if ms > 0}
    vol0 = int(deep["vol0_acq_start_tics"])
    tick = int(deep.get("first_puls_tick") or deep.get("first_resp_tick"))
    start = (tick - vol0) * SIEMENS_CSA_TICK_SECONDS
    channels = [c for c in ("PULS", "RESP", "EXT", "ECG") if c in hz_map]
    return {
        "physio_uid": uid,
        "subject": subject,
        "session": session,
        "channels": channels,
        "filepath": deep["filepath"],
        "bold_path": bold["nii"],
        "start_time": float(start),
        "start_confidence": "MEDIUM",
        "hz_by_channel": hz_map,
        "ms_by_channel": ms_map,
        "protocol_name": protocol,
        "mapping_confidence": "CONFIRMED",
        "candidate_count": 1,
        "start_method": "CSA_(first_PULS_ACQ_TIME_TICS - vol0_ACQ_START_TICS)*0.0025_s_per_tick",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--also-release", action="store_true")
    ap.add_argument("--bids-root", type=Path, default=BIDS)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading deep PhysioLog table…", flush=True)
    deep_rows = list(csv.DictReader(DEEP_TSV.open(encoding="utf-8"), delimiter="\t"))
    needed_subjects = {meta[0] for meta in TARGET_CASES.values()}
    print(f"Indexing BOLD ProtocolName for {sorted(needed_subjects)}…", flush=True)
    bold_index = load_bold_index(args.bids_root, subjects=needed_subjects)
    print(f"Indexed {sum(len(v) for v in bold_index.values())} magnitude BOLD runs", flush=True)

    validations: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []

    for uid, (subject, session, protocol, scandate_key) in TARGET_CASES.items():
        row: dict[str, Any] = {
            "physio_uid": uid,
            "subject": subject,
            "session": session,
            "protocol_name": protocol,
            "decision": "REJECT",
            "reason": "",
            "bold_target": "",
            "StartTime": "",
            "filepath": "",
        }
        deep = find_deep_row(deep_rows, protocol, scandate_key, subject)
        if not deep:
            row["reason"] = "deep_row_not_found"
            validations.append(row)
            continue
        row["filepath"] = deep["filepath"]
        if deep.get("has_acquisition_info") != "true":
            row["reason"] = "missing_acquisition_info"
            validations.append(row)
            continue
        if not deep.get("vol0_acq_start_tics") or not (
            deep.get("first_puls_tick") or deep.get("first_resp_tick")
        ):
            row["reason"] = "missing_csa_ticks"
            validations.append(row)
            continue
        ms_map = parse_sampletimes(deep.get("sampletime_by_type") or "")
        if not ms_map:
            row["reason"] = "missing_sampletime"
            validations.append(row)
            continue

        cands = [
            b
            for b in bold_index.get((subject, session), [])
            if b["protocol_name"] == protocol and Path(b["nii"]).is_file()
        ]
        if len(cands) != 1:
            row["reason"] = f"mapping_not_unique_or_missing n={len(cands)}"
            row["bold_target"] = ",".join(Path(c["nii"]).name for c in cands)
            validations.append(row)
            continue

        job = build_job(uid, subject, session, protocol, deep, cands[0])
        row.update(
            {
                "decision": "READY_FOR_BIDS_CONVERSION",
                "reason": "SF+StartTime+CONFIRMED_unique_ProtocolName",
                "bold_target": job["bold_path"],
                "StartTime": f"{job['start_time']:.6f}",
                "channels": ";".join(job["channels"]),
                "sampling_frequency": ";".join(
                    f"{k}={v:g}" for k, v in sorted(job["hz_by_channel"].items())
                ),
            }
        )
        validations.append(row)
        jobs.append(job)

    _write_tsv(
        OUT_DIR / "likely_revalidation.tsv",
        [
            "physio_uid",
            "subject",
            "session",
            "protocol_name",
            "decision",
            "reason",
            "bold_target",
            "StartTime",
            "channels",
            "sampling_frequency",
            "filepath",
        ],
        validations,
    )

    ready_jobs = [j for j in jobs]
    print(f"Revalidated: {len(validations)} | READY: {len(ready_jobs)}")
    for v in validations:
        print(
            f"  {v['subject']} {v['protocol_name']}: {v['decision']} "
            f"({v['reason']}) StartTime={v.get('StartTime','')}"
        )

    release_root = Path("/lustre07/scratch/alexrees/release_dataset") if args.also_release else None
    results = []
    for job in ready_jobs:
        res = convert_one(job, args.bids_root, release_root, args.dry_run)
        results.append(res)
        print(
            f"CONVERT {job['subject']} {job['protocol_name']}: "
            f"{res['status']} n_files={res['n_files']} err={res.get('error','')}"
        )

    _write_tsv(
        OUT_DIR / "likely_conversion_results.tsv",
        ["physio_uid", "subject", "session", "status", "n_files", "outputs", "error", "phi_issues"],
        results,
    )

    # Append READY rows into decision/validation tables for provenance (non-destructive copy).
    prov = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_targets": len(TARGET_CASES),
        "n_ready": len(ready_jobs),
        "n_converted_ok": sum(1 for r in results if r["status"] in {"OK", "DRY_RUN_OK"}),
        "dry_run": args.dry_run,
        "cases": validations,
    }
    (OUT_DIR / "likely_recovery_summary.json").write_text(
        json.dumps(prov, indent=2) + "\n", encoding="utf-8"
    )

    # Update FINAL decision TSV rows for recovered UIDs (only when not dry-run and OK).
    if not args.dry_run and any(r["status"] == "OK" for r in results):
        decision_path = READY / "FINAL_PHYSIO_CONVERSION_DECISION.tsv"
        decisions = list(csv.DictReader(decision_path.open(encoding="utf-8"), delimiter="\t"))
        by_uid = {r["physio_uid"]: r for r in decisions}
        ok_uids = {r["physio_uid"] for r in results if r["status"] == "OK"}
        for job in ready_jobs:
            if job["physio_uid"] not in ok_uids:
                continue
            by_uid[job["physio_uid"]] = {
                "physio_uid": job["physio_uid"],
                "subject": job["subject"],
                "session": job["session"],
                "channels": ";".join(job["channels"]),
                "BIDS_target": job["bold_path"],
                "sampling_frequency_status": "PASS",
                "starttime_status": "PASS",
                "mapping_status": "PASS",
                "waveform_status": "PASS",
                "FINAL_DECISION": "READY_FOR_BIDS_CONVERSION",
            }
        # rewrite preserving order + append new if missing
        fields = list(decisions[0].keys())
        out_rows = []
        seen = set()
        for r in decisions:
            uid = r["physio_uid"]
            if uid in by_uid and uid in ok_uids:
                out_rows.append(by_uid[uid])
            else:
                out_rows.append(r)
            seen.add(uid)
        for uid, r in by_uid.items():
            if uid not in seen and uid in ok_uids:
                out_rows.append(r)
        _write_tsv(decision_path, fields, out_rows)

        # Append validation rows
        st_path = READY / "starttime_validation.tsv"
        sf_path = READY / "sampling_frequency_validation.tsv"
        map_path = READY / "run_mapping_validation.tsv"
        st_rows = list(csv.DictReader(st_path.open(encoding="utf-8"), delimiter="\t"))
        sf_rows = list(csv.DictReader(sf_path.open(encoding="utf-8"), delimiter="\t"))
        map_rows = list(csv.DictReader(map_path.open(encoding="utf-8"), delimiter="\t"))
        existing_st = {r["physio_uid"] for r in st_rows}
        existing_map = {r["physio_uid"] for r in map_rows}
        existing_sf = {(r["physio_uid"], r["channel"]) for r in sf_rows}
        for job in ready_jobs:
            if job["physio_uid"] not in ok_uids:
                continue
            if job["physio_uid"] not in existing_st:
                st_rows.append(
                    {
                        "physio_uid": job["physio_uid"],
                        "BIDS_run": job["bold_path"],
                        "StartTime": f"{job['start_time']:.6f}",
                        "method": job["start_method"],
                        "confidence": "MEDIUM",
                        "status": "PASS",
                    }
                )
            if job["physio_uid"] not in existing_map:
                map_rows.append(
                    {
                        "physio_uid": job["physio_uid"],
                        "BIDS_bold_file": job["bold_path"],
                        "protocol_name": job["protocol_name"],
                        "candidate_count": "1",
                        "mapping_confidence": "CONFIRMED",
                        "status": "PASS",
                    }
                )
            for ch, hz in job["hz_by_channel"].items():
                key = (job["physio_uid"], ch)
                if key in existing_sf:
                    continue
                sf_rows.append(
                    {
                        "physio_uid": job["physio_uid"],
                        "subject": job["subject"],
                        "session": job["session"],
                        "channel": ch,
                        "sample_time_ms": str(job["ms_by_channel"][ch]),
                        "sampling_frequency_hz": f"{hz:.6g}",
                        "source": "Siemens_CSA_SampleTime_ms",
                        "status": "PASS",
                    }
                )
        _write_tsv(st_path, list(st_rows[0].keys()), st_rows)
        _write_tsv(map_path, list(map_rows[0].keys()), map_rows)
        _write_tsv(sf_path, list(sf_rows[0].keys()), sf_rows)

    n_fail = sum(1 for r in results if r["status"] not in {"OK", "DRY_RUN_OK"})
    n_reject = sum(1 for v in validations if v["decision"] != "READY_FOR_BIDS_CONVERSION")
    print(f"Wrote reports under {OUT_DIR}")
    return 1 if (n_fail or n_reject) else 0


if __name__ == "__main__":
    raise SystemExit(main())
