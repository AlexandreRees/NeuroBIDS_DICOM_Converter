#!/usr/bin/env python3
"""Convert HIGH-confidence MAPPING_AMBIGUOUS PhysioLogs (PULS/RESP) after spot-check.

Accepts only recommendation rows with:
  confidence=HIGH
  channels containing PULS and/or RESP
  start_time_available=yes
  unique recommended_bold_stem (no collisions)
  BIDS ProtocolName match + |ΔSeriesNumber|≤2
  no existing physio sidecars on the target stem

Writes to bids/ and optionally release_dataset/. Does not touch raw_original/.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert_physiolog_to_bids import convert_one  # noqa: E402

SIEMENS_CSA_TICK_SECONDS = 0.0025
SCRATCH = Path("/home/alexrees/scratch")
BIDS = SCRATCH / "bids"
RELEASE = SCRATCH / "release_dataset"
AUDIT = SCRATCH / "reports" / "physiology_audit"
READY = AUDIT / "final_bids_physio_readiness"
REC_TSV = AUDIT / "mapping_recovery" / "physio_bold_mapping_recommendations.tsv"
DEEP_TSV = AUDIT / "physiolog_dicom_deep.tsv"
OUT_DIR = READY / "high_mapping_recovery"


def parse_sampletimes(s: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in (s or "").split(";"):
        if "=" not in part:
            continue
        ch, ms = part.split("=", 1)
        out[ch.strip().upper()] = float(ms)
    return out


def load_high_puls_resp() -> list[dict[str, str]]:
    rows = list(csv.DictReader(REC_TSV.open(encoding="utf-8"), delimiter="\t"))
    return [
        r
        for r in rows
        if r.get("confidence") == "HIGH"
        and (
            "PULS" in (r.get("channels_available") or "")
            or "RESP" in (r.get("channels_available") or "")
        )
        and (r.get("start_time_available") or "").lower() == "yes"
    ]


def build_job(rec: dict[str, str], deep: dict[str, str], bold_nii: Path) -> dict[str, Any]:
    ms_map = parse_sampletimes(deep.get("sampletime_by_type") or "")
    hz_map = {ch: 1000.0 / ms for ch, ms in ms_map.items() if ms > 0}
    vol0 = int(deep["vol0_acq_start_tics"])
    tick = int(deep.get("first_puls_tick") or deep.get("first_resp_tick"))
    start = (tick - vol0) * SIEMENS_CSA_TICK_SECONDS
    channels = [c for c in ("PULS", "RESP", "EXT", "ECG") if c in hz_map]
    return {
        "physio_uid": rec["physio_series_uid"],
        "subject": rec["subject"],
        "session": rec["session"],
        "channels": channels,
        "filepath": deep["filepath"],
        "bold_path": str(bold_nii),
        "start_time": float(start),
        "start_confidence": "MEDIUM",
        "hz_by_channel": hz_map,
        "ms_by_channel": ms_map,
        "protocol_name": rec["physio_protocol_name"],
        "mapping_confidence": "HIGH_RECOVERY",
        "recommended_bold_stem": rec["recommended_bold_stem"],
        "spotcheck": "PASS",
    }


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--also-release", action="store_true", default=True)
    ap.add_argument("--no-release", action="store_true")
    ap.add_argument("--bids-root", type=Path, default=BIDS)
    args = ap.parse_args()
    also_release = bool(args.also_release) and not args.no_release

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    high = load_high_puls_resp()
    deep_by = {
        r["filepath"]: r
        for r in csv.DictReader(DEEP_TSV.open(encoding="utf-8"), delimiter="\t")
    }

    spot: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    stems_seen: dict[str, str] = {}

    for rec in high:
        row: dict[str, Any] = {
            "physio_uid": rec["physio_series_uid"],
            "subject": rec["subject"],
            "session": rec["session"],
            "channels_available": rec["channels_available"],
            "physio_protocol_name": rec["physio_protocol_name"],
            "physio_series_number": rec["physio_series_number"],
            "recommended_bold_stem": rec["recommended_bold_stem"],
            "recommended_bold_series_number": rec["recommended_bold_series_number"],
            "seriesnumber_distance": rec["seriesnumber_distance"],
            "bold_immediately_after_physio": rec["bold_immediately_after_physio"],
            "confidence_reason": rec["confidence_reason"],
            "decision": "REJECT",
            "reason": "",
            "StartTime": "",
        }
        stem = rec["recommended_bold_stem"]
        if stem in stems_seen:
            row["reason"] = f"bold_stem_collision_with:{stems_seen[stem]}"
            spot.append(row)
            continue
        deep = deep_by.get(rec["physio_filepath"])
        if not deep:
            row["reason"] = "deep_row_not_found"
            spot.append(row)
            continue
        if deep.get("has_acquisition_info") != "true":
            row["reason"] = "missing_acquisition_info"
            spot.append(row)
            continue
        if not deep.get("vol0_acq_start_tics") or not (
            deep.get("first_puls_tick") or deep.get("first_resp_tick")
        ):
            row["reason"] = "missing_csa_ticks"
            spot.append(row)
            continue
        ms_map = parse_sampletimes(deep.get("sampletime_by_type") or "")
        if "PULS" not in ms_map and "RESP" not in ms_map:
            row["reason"] = "missing_puls_resp_sampletime"
            spot.append(row)
            continue

        bold_json = (
            args.bids_root
            / rec["subject"]
            / rec["session"]
            / "func"
            / f"{stem}_bold.json"
        )
        bold_nii = bold_json.with_name(bold_json.name.replace("_bold.json", "_bold.nii.gz"))
        if not bold_json.is_file() or not bold_nii.is_file():
            row["reason"] = "missing_bold"
            spot.append(row)
            continue
        existing = list(
            (args.bids_root / rec["subject"] / rec["session"] / "func").glob(
                f"{stem}_recording-*_physio.tsv.gz"
            )
        )
        if existing:
            row["reason"] = f"already_has_physio_n={len(existing)}"
            spot.append(row)
            continue

        import json as _json

        meta = _json.loads(bold_json.read_text(encoding="utf-8"))
        if str(meta.get("ProtocolName") or "") != rec["physio_protocol_name"]:
            row["reason"] = (
                f"protocol_mismatch bids={meta.get('ProtocolName')} "
                f"phys={rec['physio_protocol_name']}"
            )
            spot.append(row)
            continue
        try:
            dsn = abs(float(meta["SeriesNumber"]) - float(rec["physio_series_number"]))
        except (KeyError, TypeError, ValueError):
            dsn = None
        if dsn is None or dsn > 2:
            row["reason"] = f"seriesnumber_distance_fail dsn={dsn}"
            spot.append(row)
            continue

        job = build_job(rec, deep, bold_nii)
        stems_seen[stem] = rec["physio_series_uid"]
        row.update(
            {
                "decision": "ACCEPT_HIGH",
                "reason": "spotcheck_pass_protocol+dsn<=2+csa_ok+no_existing",
                "StartTime": f"{job['start_time']:.6f}",
                "filepath": deep["filepath"],
                "bold_path": str(bold_nii),
            }
        )
        spot.append(row)
        jobs.append(job)

    write_tsv(
        OUT_DIR / "high_spotcheck.tsv",
        spot,
        [
            "physio_uid",
            "subject",
            "session",
            "channels_available",
            "physio_protocol_name",
            "physio_series_number",
            "recommended_bold_stem",
            "recommended_bold_series_number",
            "seriesnumber_distance",
            "bold_immediately_after_physio",
            "confidence_reason",
            "decision",
            "reason",
            "StartTime",
            "filepath",
            "bold_path",
        ],
    )

    print(
        f"Spot-check: ACCEPT={sum(1 for r in spot if r['decision']=='ACCEPT_HIGH')} "
        f"REJECT={sum(1 for r in spot if r['decision']!='ACCEPT_HIGH')} "
        f"jobs={len(jobs)}",
        flush=True,
    )
    for r in spot:
        print(
            f"  {r['subject']} {r['session']} → {r['recommended_bold_stem']}: "
            f"{r['decision']} ({r['reason']})",
            flush=True,
        )

    release_root = RELEASE if also_release else None
    results: list[dict[str, Any]] = []
    for job in jobs:
        res = convert_one(job, args.bids_root, release_root, args.dry_run)
        results.append(res)
        print(
            f"CONVERT {job['subject']} {job['recommended_bold_stem']}: "
            f"{res['status']} n_files={res['n_files']} err={res.get('error','')}",
            flush=True,
        )

    write_tsv(
        OUT_DIR / "high_conversion_results.tsv",
        results,
        [
            "physio_uid",
            "subject",
            "session",
            "status",
            "n_files",
            "outputs",
            "error",
            "phi_issues",
        ],
    )

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_high_puls_resp_candidates": len(high),
        "n_accepted": len(jobs),
        "n_converted_ok": sum(1 for r in results if r["status"] in {"OK", "DRY_RUN_OK"}),
        "dry_run": args.dry_run,
        "also_release": also_release,
        "status_counts": dict(Counter(r["status"] for r in results)),
        "accepted_stems": [j["recommended_bold_stem"] for j in jobs],
    }
    (OUT_DIR / "high_recovery_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if all(r["status"] in {"OK", "DRY_RUN_OK"} for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
