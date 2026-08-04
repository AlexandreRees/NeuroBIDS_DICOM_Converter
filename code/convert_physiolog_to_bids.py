#!/usr/bin/env python3
"""Convert READY Siemens PhysioLog DICOM objects to BIDS physiology sidecars.

Only FINAL_DECISION=READY_FOR_BIDS_CONVERSION rows are converted.

Outputs (next to matching BOLD):
  <bold_stem>_recording-{pulse|respiratory|trigger|ecg}_physio.tsv.gz
  <bold_stem>_recording-..._physio.json

PHI policy (hard):
  - Never copy Patient*/Institution*/Device*/Operator*/Physician* DICOM fields
  - Never write UUID, ScanDate, SeriesInstanceUID, source paths, or calendar dates
  - JSON allowlist only (ALLOWED_JSON_KEYS)
  - TSV = numeric physiology columns only
  - Source DICOMs stay in raw_original/ (not published)

Usage:
  python3 code/convert_physiolog_to_bids.py --dry-run --limit 3
  python3 code/convert_physiolog_to_bids.py --workers 8 --also-release
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

LOGGER = logging.getLogger("physiolog_bids_convert")

AUDIT = Path("/home/alexrees/scratch/reports/physiology_audit")
READY_DIR = AUDIT / "final_bids_physio_readiness"
DEFAULT_BIDS = Path("/home/alexrees/scratch/bids")
DEFAULT_RELEASE = Path("/home/alexrees/scratch/release_dataset")
DEFAULT_OUT_REPORT = READY_DIR / "conversion_run"

DECISION_TSV = READY_DIR / "FINAL_PHYSIO_CONVERSION_DECISION.tsv"
STARTTIME_TSV = READY_DIR / "starttime_validation.tsv"
SF_TSV = READY_DIR / "sampling_frequency_validation.tsv"
MAP_TSV = READY_DIR / "run_mapping_validation.tsv"
STATUS_TSV = AUDIT / "physio_conversion_status.tsv"
INVENTORY_TSV = AUDIT / "physiolog_inventory.tsv"

_PMU_CONTROL = {5000, 5002, 5003, 6000, 6002, 6003}

# Siemens channel -> (recording entity, BIDS column)
CHANNEL_TO_BIDS = {
    "ECG": ("ecg", "cardiac"),
    "PULS": ("pulse", "cardiac"),
    "RESP": ("respiratory", "respiratory"),
    "EXT": ("trigger", "trigger"),
    "EXT2": ("trigger", "trigger"),
}

ALLOWED_JSON_KEYS = frozenset(
    {
        "SamplingFrequency",
        "StartTime",
        "Columns",
        "Manufacturer",
        "ConversionSoftware",
        "ConversionSoftwareVersion",
        "StartTimeMethod",
        "StartTimeConfidence",
        "SiemensChannel",
        "SampleTime_ms",
    }
)

FORBIDDEN_JSON_KEYS = frozenset(
    {
        "PatientName",
        "PatientID",
        "PatientBirthDate",
        "PatientAge",
        "PatientSex",
        "PatientWeight",
        "InstitutionName",
        "InstitutionalDepartmentName",
        "InstitutionAddress",
        "DeviceSerialNumber",
        "StationName",
        "OperatorsName",
        "PhysicianName",
        "ReferringPhysicianName",
        "PerformingPhysicianName",
        "AcquisitionDate",
        "AcquisitionTime",
        "SeriesDate",
        "StudyDate",
        "StudyTime",
        "SeriesInstanceUID",
        "StudyInstanceUID",
        "SOPInstanceUID",
        "UUID",
        "ScanDate",
        "SourceFile",
        "SourcePath",
        "Filepath",
        "AccessionNumber",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def build_jobs() -> list[dict[str, Any]]:
    decisions = _load_tsv(DECISION_TSV)
    start_by = {r["physio_uid"]: r for r in _load_tsv(STARTTIME_TSV)}
    map_by = {r["physio_uid"]: r for r in _load_tsv(MAP_TSV)}
    status_by = {r["physio_series_uid"]: r for r in _load_tsv(STATUS_TSV)}

    sf_by: dict[str, dict[str, float]] = defaultdict(dict)
    sf_ms_by: dict[str, dict[str, float]] = defaultdict(dict)
    for r in _load_tsv(SF_TSV):
        if r.get("status") != "PASS":
            continue
        try:
            hz = float(r["sampling_frequency_hz"])
            ms = float(r["sample_time_ms"])
        except (KeyError, ValueError, TypeError):
            continue
        ch = str(r["channel"]).upper()
        sf_by[r["physio_uid"]][ch] = hz
        sf_ms_by[r["physio_uid"]][ch] = ms

    inv_index: dict[tuple[str, str, str], str] = {}
    inv_score: dict[tuple[str, str, str], int] = {}
    for r in _load_tsv(INVENTORY_TSV):
        key = (r["subject"], r["session"], r.get("protocol_name") or "")
        emb = (r.get("embedded_logs") or "").upper()
        score = sum(x in emb for x in ("PULS", "RESP", "ECG"))
        if key not in inv_index or score >= inv_score.get(key, -1):
            inv_index[key] = r["filepath"]
            inv_score[key] = score

    jobs: list[dict[str, Any]] = []
    for d in decisions:
        if d.get("FINAL_DECISION") != "READY_FOR_BIDS_CONVERSION":
            continue
        uid = d["physio_uid"]
        st = start_by.get(uid)
        mp = map_by.get(uid)
        st_status = status_by.get(uid)
        if not st or st.get("status") != "PASS":
            continue
        if not mp or mp.get("status") != "PASS":
            continue
        if not st_status:
            continue
        proto = mp.get("protocol_name") or ""
        sub = d["subject"]
        ses = d["session"]
        fp = inv_index.get((sub, ses, proto))
        if not fp:
            continue
        hz_map = sf_by.get(uid) or {}
        if not hz_map:
            continue
        jobs.append(
            {
                "physio_uid": uid,
                "subject": sub,
                "session": ses,
                "channels": [
                    c.strip().upper()
                    for c in str(
                        d.get("channels") or st_status.get("channels_available") or ""
                    ).split(";")
                    if c.strip()
                ],
                "filepath": fp,
                "bold_path": mp["BIDS_bold_file"],
                "start_time": float(st["StartTime"]),
                "start_confidence": st.get("confidence") or "MEDIUM",
                "hz_by_channel": hz_map,
                "ms_by_channel": sf_ms_by.get(uid) or {},
            }
        )
    return jobs


def _extract_channel_samples(text: str, channel: str) -> np.ndarray:
    pat = re.compile(
        rf"Physio_\d{{8}}_\d{{6}}_[0-9a-f\-]+_{channel}\.log", re.IGNORECASE
    )
    m = pat.search(text)
    if not m:
        return np.asarray([], dtype=np.float64)
    start = m.end()
    m2 = re.search(r"Physio_\d{8}_\d{6}_", text[start:])
    end = start + m2.start() if m2 else len(text)
    tokens = text[start:end].split()

    values: list[int] = []
    if "6002" in tokens:
        i0 = tokens.index("6002") + 1
        for tok in tokens[i0:]:
            if tok == "5003":
                break
            if tok.lstrip("-").isdigit():
                v = int(tok)
                if v not in _PMU_CONTROL and abs(v) < 10_000_000:
                    values.append(v)
        if values:
            return np.asarray(values, dtype=np.float64)

    for tok in tokens:
        if not tok.lstrip("-").isdigit():
            continue
        v = int(tok)
        if v in _PMU_CONTROL or abs(v) >= 10_000_000:
            continue
        values.append(v)
    return np.asarray(values, dtype=np.float64)


def _read_csa_text(filepath: str) -> str:
    import pydicom

    ds = pydicom.dcmread(filepath, stop_before_pixels=False, force=True)
    raw = bytes(ds[0x7FE1, 0x1010].value)
    return raw.decode("latin-1", errors="replace")


def _bold_stem(bold_path: str) -> str:
    name = Path(bold_path).name
    if name.endswith("_bold.nii.gz"):
        return name[: -len("_bold.nii.gz")]
    if name.endswith("_bold.nii"):
        return name[: -len("_bold.nii")]
    return Path(bold_path).stem


def _phi_safe_json(
    *,
    sf: float,
    start: float,
    columns: list[str],
    siemens_channel: str,
    sample_time_ms: float | None,
    start_confidence: str,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "SamplingFrequency": float(sf),
        "StartTime": float(start),
        "Columns": columns,
        "Manufacturer": "Siemens",
        "ConversionSoftware": "convert_physiolog_to_bids.py",
        "ConversionSoftwareVersion": "1.0.0",
        "StartTimeMethod": "CSA_tick_difference_x_0.0025s",
        "StartTimeConfidence": start_confidence,
        "SiemensChannel": siemens_channel,
    }
    if sample_time_ms is not None:
        meta["SampleTime_ms"] = float(sample_time_ms)
    cleaned = {k: v for k, v in meta.items() if k in ALLOWED_JSON_KEYS}
    for bad in FORBIDDEN_JSON_KEYS:
        cleaned.pop(bad, None)
    return cleaned


def _assert_json_phi_safe(meta: dict[str, Any], path: Path) -> list[str]:
    issues: list[str] = []
    for k in meta:
        if k not in ALLOWED_JSON_KEYS:
            issues.append(f"{path}: non-allowlisted key {k}")
        if k in FORBIDDEN_JSON_KEYS:
            issues.append(f"{path}: FORBIDDEN key {k}")
    for k, v in meta.items():
        if not isinstance(v, str):
            continue
        if "/lustre" in v or "/home/" in v or "raw_original" in v:
            issues.append(f"{path}: path-like value in {k}")
        if re.search(r"\bPatient|\bSUBC\d+|@|\bMRN\b", v, re.I):
            issues.append(f"{path}: suspicious token in {k}={v!r}")
    return issues


def write_physio_pair(
    out_dir: Path,
    stem: str,
    recording: str,
    column: str,
    samples: np.ndarray,
    sf: float,
    start: float,
    siemens_channel: str,
    sample_time_ms: float | None,
    start_confidence: str,
) -> tuple[Path, Path, list[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{stem}_recording-{recording}_physio"
    tsv_path = out_dir / f"{base}.tsv.gz"
    json_path = out_dir / f"{base}.json"

    with gzip.open(tsv_path, "wt", encoding="utf-8", newline="") as fh:
        fh.write(f"{column}\n")
        for v in samples:
            if float(v).is_integer():
                fh.write(f"{int(v)}\n")
            else:
                fh.write(f"{float(v):.6g}\n")

    meta = _phi_safe_json(
        sf=sf,
        start=start,
        columns=[column],
        siemens_channel=siemens_channel,
        sample_time_ms=sample_time_ms,
        start_confidence=start_confidence,
    )
    issues = _assert_json_phi_safe(meta, json_path)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return tsv_path, json_path, issues


def convert_one(
    job: dict[str, Any], bids_root: Path, release_root: Path | None, dry_run: bool
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "physio_uid": job["physio_uid"],
        "subject": job["subject"],
        "session": job["session"],
        "status": "FAIL",
        "n_files": 0,
        "outputs": "",
        "error": "",
        "phi_issues": "",
    }
    try:
        text = _read_csa_text(job["filepath"])
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"dicom_read:{type(exc).__name__}:{exc}"
        return result

    bold_path = Path(job["bold_path"])
    if not bold_path.is_file():
        alt = bids_root / job["subject"] / job["session"] / "func" / bold_path.name
        if alt.is_file():
            bold_path = alt
        else:
            result["error"] = f"missing_bold:{bold_path}"
            return result

    stem = _bold_stem(str(bold_path))
    out_dir = bold_path.parent
    written: list[str] = []
    phi_issues: list[str] = []
    n_ok = 0

    for ch in job["channels"]:
        ch_u = ch.upper()
        if ch_u not in CHANNEL_TO_BIDS or ch_u not in job["hz_by_channel"]:
            continue
        recording, column = CHANNEL_TO_BIDS[ch_u]
        samples = _extract_channel_samples(text, ch_u)
        if samples.size < 10:
            continue
        if float(np.ptp(samples)) == 0.0:
            continue  # skip flat (common for EXT)

        sf = float(job["hz_by_channel"][ch_u])
        ms = job["ms_by_channel"].get(ch_u)

        targets = [out_dir]
        if release_root is not None:
            rel_dir = release_root / job["subject"] / job["session"] / "func"
            if rel_dir.is_dir():
                targets.append(rel_dir)

        for target in targets:
            if dry_run:
                written.append(
                    str(target / f"{stem}_recording-{recording}_physio.tsv.gz")
                )
                n_ok += 1
                continue
            _tsv_p, json_p, issues = write_physio_pair(
                target,
                stem,
                recording,
                column,
                samples,
                sf,
                float(job["start_time"]),
                ch_u,
                ms,
                job["start_confidence"],
            )
            written.append(str(json_p))
            phi_issues.extend(issues)
            n_ok += 1

    if n_ok == 0:
        result["error"] = "no_channels_extracted"
        return result
    if phi_issues:
        result["status"] = "PHI_FAIL"
        result["phi_issues"] = " | ".join(phi_issues[:20])
        result["n_files"] = n_ok
        result["outputs"] = ";".join(written[:12])
        return result

    result["status"] = "OK" if not dry_run else "DRY_RUN_OK"
    result["n_files"] = n_ok
    result["outputs"] = ";".join(written[:20])
    return result


def audit_written_json(bids_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(bids_root.rglob("*_physio.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "file": str(path),
                    "finding": f"json_parse_error:{exc}",
                    "severity": "FAIL",
                }
            )
            continue
        for k in meta:
            if k in FORBIDDEN_JSON_KEYS:
                rows.append(
                    {
                        "file": str(path),
                        "finding": f"forbidden_key:{k}",
                        "severity": "PHI_RISK",
                    }
                )
            elif k not in ALLOWED_JSON_KEYS:
                rows.append(
                    {
                        "file": str(path),
                        "finding": f"non_allowlisted_key:{k}",
                        "severity": "REVIEW",
                    }
                )
        for k, v in meta.items():
            if isinstance(v, str) and (
                "/lustre" in v
                or "raw_original" in v
                or re.search(r"\bSUBC\d+", v)
            ):
                rows.append(
                    {
                        "file": str(path),
                        "finding": f"path_or_source_id_in_{k}",
                        "severity": "PHI_RISK",
                    }
                )
    return rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bids-root", type=Path, default=DEFAULT_BIDS)
    p.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE)
    p.add_argument("--also-release", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--report-dir", type=Path, default=DEFAULT_OUT_REPORT)
    p.add_argument("--skip-phi-audit", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    report_dir = args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Building READY job list…")
    jobs = build_jobs()
    LOGGER.info("READY jobs with filepath+gates: %d", len(jobs))
    if args.limit and args.limit > 0:
        jobs = jobs[: args.limit]
        LOGGER.info("Limited to %d jobs", len(jobs))

    release_root = args.release_root if args.also_release else None
    results: list[dict[str, Any]] = []

    if args.workers <= 1 or args.dry_run:
        for i, job in enumerate(jobs, 1):
            results.append(convert_one(job, args.bids_root, release_root, args.dry_run))
            if i % 50 == 0 or i == len(jobs):
                LOGGER.info("Converted %d / %d", i, len(jobs))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = [
                ex.submit(convert_one, job, args.bids_root, release_root, args.dry_run)
                for job in jobs
            ]
            done = 0
            for fut in as_completed(futs):
                results.append(fut.result())
                done += 1
                if done % 50 == 0 or done == len(jobs):
                    LOGGER.info("Converted %d / %d", done, len(jobs))

    fields = [
        "physio_uid",
        "subject",
        "session",
        "status",
        "n_files",
        "outputs",
        "error",
        "phi_issues",
    ]
    _write_tsv(report_dir / "conversion_results.tsv", fields, results)
    counts = Counter(r["status"] for r in results)
    LOGGER.info("Status counts: %s", dict(counts))

    phi_rows: list[dict[str, str]] = []
    if not args.dry_run and not args.skip_phi_audit:
        LOGGER.info("PHI audit of *_physio.json under %s", args.bids_root)
        phi_rows = audit_written_json(args.bids_root)
        _write_tsv(
            report_dir / "physio_json_phi_audit.tsv",
            ["file", "finding", "severity"],
            phi_rows,
        )
        risk = sum(1 for r in phi_rows if r["severity"] == "PHI_RISK")
        LOGGER.info("PHI audit findings: %d (PHI_RISK=%d)", len(phi_rows), risk)

    n_ok = sum(1 for r in results if r["status"] in {"OK", "DRY_RUN_OK"})
    n_phi = sum(1 for r in results if r["status"] == "PHI_FAIL")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    md = report_dir / "CONVERSION_SUMMARY.md"
    md.write_text(
        "\n".join(
            [
                "# PhysioLog → BIDS conversion summary",
                "",
                f"**Generated:** `{_now()}`",
                f"**READY jobs attempted:** {len(jobs)}",
                f"**OK:** {n_ok}",
                f"**FAIL:** {n_fail}",
                f"**PHI_FAIL:** {n_phi}",
                f"**Dry run:** {args.dry_run}",
                f"**Also release_dataset:** {bool(release_root)}",
                "",
                "## PHI policy",
                "",
                "- JSON allowlist only: " + ", ".join(sorted(ALLOWED_JSON_KEYS)),
                "- Forbidden keys never written (Patient*, Institution*, DeviceSerial*, dates, UIDs, paths).",
                "- Source PhysioLog DICOMs remain outside the public BIDS tree.",
                "",
                f"- Post-write PHI findings: **{len(phi_rows)}** "
                f"(PHI_RISK={sum(1 for r in phi_rows if r.get('severity')=='PHI_RISK')})",
                "",
                "## Outputs",
                "",
                f"- `{report_dir / 'conversion_results.tsv'}`",
                f"- `{report_dir / 'physio_json_phi_audit.tsv'}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    LOGGER.info("Wrote %s", md)

    if n_phi > 0 or any(r.get("severity") == "PHI_RISK" for r in phi_rows):
        LOGGER.error("PHI issues detected — inspect physio_json_phi_audit.tsv")
        return 2
    if n_fail > 0 and n_ok == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
