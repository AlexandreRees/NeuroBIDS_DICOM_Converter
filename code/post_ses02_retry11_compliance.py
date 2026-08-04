#!/usr/bin/env python3
"""Post-conversion BIDS compliance for the 11 retry ses-02 sessions.

Runs after the ses02_r11 Slurm array. Does NOT modify raw_original.
Scoped to subjects_missing_ses02_retry11.tsv sessions only.

Steps:
  1. Inventory NIfTI / JSON / modality dirs
  2. Enforce NIfTI↔JSON pairs for imaging files
  3. Scrub administrative JSON fields (same policy as clean_bids_metadata.py)
  4. Write compliance report under reports/ses02_retry11/
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/alexrees/scratch")
BIDS = ROOT / "bids"
TSV = ROOT / "neuro_pipeline" / "scripts" / "subjects_missing_ses02_retry11.tsv"
REPORTS = ROOT / "reports" / "ses02_retry11"
BACKUP = ROOT / "bids_metadata_backup_ses02_retry11"
LOG_DIR = ROOT / "logs" / "ses02_retry11"

REMOVE_FIELDS = frozenset(
    {
        "InstitutionalDepartmentName",
        "InstitutionName",
        "StationName",
        "DeviceSerialNumber",
        "PatientName",
        "PatientID",
        "PatientBirthDate",
        "PatientAge",
        "PatientSex",
        "OtherPatientIDs",
        "OtherPatientNames",
    }
)

IMAGING_SUFFIXES = (
    "_bold.nii.gz",
    "_sbref.nii.gz",
    "_T1w.nii.gz",
    "_T2w.nii.gz",
    "_FLAIR.nii.gz",
    "_dwi.nii.gz",
    "_epi.nii.gz",
    "_magnitude1.nii.gz",
    "_magnitude2.nii.gz",
    "_phasediff.nii.gz",
    "_phase1.nii.gz",
    "_phase2.nii.gz",
    "_TB1TFL.nii.gz",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_targets() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with TSV.open(encoding="utf-8") as fh:
        data_lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(data_lines, delimiter="\t")
    for row in reader:
        if not row.get("participant_id"):
            continue
        rows.append(row)
    return rows


def is_imaging(name: str) -> bool:
    return any(name.endswith(sfx) for sfx in IMAGING_SUFFIXES)


def scrub_json(path: Path, backup_root: Path) -> list[str]:
    removed: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"INVALID_JSON:{exc}"]
    if not isinstance(data, dict):
        return []
    hit = sorted(REMOVE_FIELDS & set(data.keys()))
    if not hit:
        return []
    rel = path.relative_to(BIDS)
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(path, dest)
    for key in hit:
        data.pop(key, None)
        removed.append(key)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return removed


def audit_session(participant: str, session: str) -> dict:
    ses = BIDS / participant / session
    result = {
        "participant_id": participant,
        "session_id": session,
        "exists": ses.is_dir(),
        "n_nii": 0,
        "n_json": 0,
        "has_anat": False,
        "has_func": False,
        "has_fmap": False,
        "has_dwi": False,
        "missing_json_for_nii": 0,
        "orphan_json": 0,
        "fields_scrubbed": 0,
        "status": "MISSING",
        "notes": "",
    }
    if not ses.is_dir():
        result["notes"] = "session directory absent"
        return result

    niis = sorted(ses.rglob("*.nii.gz")) + sorted(ses.rglob("*.nii"))
    jsons = sorted(ses.rglob("*.json"))
    result["n_nii"] = len(niis)
    result["n_json"] = len(jsons)
    result["has_anat"] = (ses / "anat").is_dir() and any((ses / "anat").glob("*.nii*"))
    result["has_func"] = (ses / "func").is_dir() and any((ses / "func").glob("*_bold.nii*"))
    result["has_fmap"] = (ses / "fmap").is_dir() and any((ses / "fmap").glob("*.nii*"))
    result["has_dwi"] = (ses / "dwi").is_dir() and any((ses / "dwi").glob("*_dwi.nii*"))

    missing = 0
    for nii in niis:
        if not is_imaging(nii.name):
            continue
        side = Path(str(nii).removesuffix(".nii.gz").removesuffix(".nii") + ".json")
        if not side.is_file():
            missing += 1
    result["missing_json_for_nii"] = missing

    # Scrub privacy fields in this session only
    scrubbed = 0
    for js in jsons:
        removed = scrub_json(js, BACKUP)
        if removed and not removed[0].startswith("INVALID"):
            scrubbed += len(removed)
        elif removed and removed[0].startswith("INVALID"):
            result["notes"] += f" invalid_json={js.name};"
    result["fields_scrubbed"] = scrubbed

    if result["n_nii"] >= 20 and result["has_func"] and result["missing_json_for_nii"] == 0:
        result["status"] = "PASS"
    elif result["n_nii"] >= 1:
        result["status"] = "PARTIAL"
        bits = []
        if result["n_nii"] < 20:
            bits.append(f"n_nii={result['n_nii']}<20")
        if not result["has_func"]:
            bits.append("no_func_bold")
        if missing:
            bits.append(f"missing_json={missing}")
        result["notes"] = ";".join(bits)
    else:
        result["status"] = "FAIL"
        result["notes"] = "no NIfTI"
    return result


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    BACKUP.mkdir(parents=True, exist_ok=True)
    targets = load_targets()
    rows = []
    for t in targets:
        rows.append(audit_session(t["participant_id"], t["session_id"]))

    out_tsv = REPORTS / "SES02_RETRY11_COMPLIANCE.tsv"
    fields = [
        "participant_id",
        "session_id",
        "exists",
        "n_nii",
        "n_json",
        "has_anat",
        "has_func",
        "has_fmap",
        "has_dwi",
        "missing_json_for_nii",
        "fields_scrubbed",
        "status",
        "notes",
    ]
    with out_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    n_pass = sum(1 for r in rows if r["status"] == "PASS")
    n_partial = sum(1 for r in rows if r["status"] == "PARTIAL")
    n_fail = sum(1 for r in rows if r["status"] in {"FAIL", "MISSING"})
    n_bids_sessions = sum(
        1
        for p in BIDS.iterdir()
        if p.name.startswith("sub-")
        for s in p.iterdir()
        if s.is_dir() and s.name.startswith("ses-")
    )

    lines = [
        "# ses-02 retry11 — BIDS compliance",
        "",
        f"**Generated (UTC):** {utc_now()}",
        f"**Targets:** {len(targets)}",
        f"**PASS / PARTIAL / FAIL:** {n_pass} / {n_partial} / {n_fail}",
        f"**BIDS sessions on disk (all subjects):** {n_bids_sessions}",
        "",
        "## Per-session",
        "",
        "| Subject | Session | n_nii | anat | func | fmap | dwi | missing JSON | scrubbed | status |",
        "|---|---|---:|:---:|:---:|:---:|:---:|---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['participant_id']} | {r['session_id']} | {r['n_nii']} | "
            f"{'Y' if r['has_anat'] else 'N'} | {'Y' if r['has_func'] else 'N'} | "
            f"{'Y' if r['has_fmap'] else 'N'} | {'Y' if r['has_dwi'] else 'N'} | "
            f"{r['missing_json_for_nii']} | {r['fields_scrubbed']} | {r['status']} |"
        )

    lines += [
        "",
        "## Conversion markers",
        "",
    ]
    if LOG_DIR.is_dir():
        for p in sorted(LOG_DIR.glob("*.SUCCESS*")) + sorted(LOG_DIR.glob("*.FAILED")) + sorted(
            LOG_DIR.glob("*.INCOMPLETE")
        ) + sorted(LOG_DIR.glob("*.SKIPPED")):
            lines.append(f"- `{p.name}`")
    else:
        lines.append("- (no log dir)")

    lines += [
        "",
        "## Notes",
        "",
        "- Metadata scrub applies the same REMOVE_FIELDS policy as `code/clean_bids_metadata.py`.",
        "- Defacing of new anatomicals and MRIQC are **not** included here; run separately before release rebuild.",
        "- Events recovery for new `task-fmri` runs can be re-run via phase-2 events script after conversion.",
        "",
    ]
    (REPORTS / "SES02_RETRY11_COMPLIANCE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"PASS={n_pass} PARTIAL={n_partial} FAIL={n_fail}")
    print(f"Report: {REPORTS / 'SES02_RETRY11_COMPLIANCE.md'}")
    print(f"BIDS sessions now: {n_bids_sessions}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
