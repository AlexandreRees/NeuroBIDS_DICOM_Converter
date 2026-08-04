#!/usr/bin/env python3
"""Pre-QC gate for the 11 ses-02 retry sessions.

Checks (in order):
  1. Conversion completeness (markers + NIfTI inventory)
  2. BIDS structure (imaging NIfTI↔JSON pairs, entity naming)
  3. No PHI / administrative fields in JSON sidecars
  4. JSON parseability

Writes reports under reports/ses02_retry11/. Exit 0 only if gate PASS
(allowing documented PARTIAL sessions such as sub-078 with sparse data).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/alexrees/scratch")
BIDS = ROOT / "bids"
TSV = ROOT / "neuro_pipeline" / "scripts" / "subjects_missing_ses02_retry11.tsv"
REPORTS = ROOT / "reports" / "ses02_retry11"
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

# Heuristic PHI value patterns (case-insensitive) in string JSON values.
PHI_VALUE_RE = re.compile(
    r"(?i)\b(patient\s*name|mrn\b|date\s*of\s*birth|d\.?o\.?b\.?|"
    r"hospital\s*name|institution\s*name)\b"
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

BIDS_NAME_RE = re.compile(
    r"^sub-[A-Za-z0-9]+_ses-[A-Za-z0-9]+_.+\.nii\.gz$"
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
        # Normalize canonical field name across TSV variants
        if "canonical_id" not in row and row.get("canonical_subject_id"):
            row["canonical_id"] = row["canonical_subject_id"]
        rows.append(row)
    return rows


def is_imaging(name: str) -> bool:
    return any(name.endswith(sfx) for sfx in IMAGING_SUFFIXES)


def marker_for(canonical: str, session: str) -> str | None:
    base = f"{canonical}_{session}"
    for suf in (".SUCCESS", ".SUCCESS_PARTIAL", ".FAILED", ".INCOMPLETE", ".SKIPPED"):
        p = LOG_DIR / f"{base}{suf}"
        if p.is_file():
            return p.name
    return None


def scan_json_phi(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"INVALID_JSON:{exc}"]
    if not isinstance(data, dict):
        return ["NOT_OBJECT"]
    bad_keys = sorted(REMOVE_FIELDS & set(data.keys()))
    for k in bad_keys:
        issues.append(f"FORBIDDEN_KEY:{k}")
    for k, v in data.items():
        if isinstance(v, str) and PHI_VALUE_RE.search(v):
            issues.append(f"PHI_VALUE:{k}")
    return issues


def audit_one(t: dict[str, str]) -> dict:
    participant = t["participant_id"]
    session = t["session_id"]
    canonical = t["canonical_id"]
    ses = BIDS / participant / session
    out: dict = {
        "participant_id": participant,
        "session_id": session,
        "canonical_id": canonical,
        "exists": ses.is_dir(),
        "n_nii": 0,
        "n_json": 0,
        "n_t1w": 0,
        "n_bold_mag": 0,
        "n_dwi": 0,
        "missing_json": 0,
        "bad_bids_names": 0,
        "forbidden_fields": 0,
        "invalid_json": 0,
        "phi_value_hits": 0,
        "marker": marker_for(canonical, session) or "NONE",
        "conversion_ok": False,
        "bids_ok": False,
        "phi_ok": False,
        "gate": "FAIL",
        "notes": "",
    }
    if not ses.is_dir():
        out["notes"] = "session missing"
        return out

    niis = sorted(ses.rglob("*.nii.gz"))
    jsons = sorted(ses.rglob("*.json"))
    out["n_nii"] = len(niis)
    out["n_json"] = len(jsons)
    out["n_t1w"] = len(list(ses.glob("anat/*T1w.nii.gz")))
    out["n_dwi"] = len(list(ses.glob("dwi/*_dwi.nii.gz")))
    out["n_bold_mag"] = len(
        [
            p
            for p in ses.glob("func/*_bold.nii.gz")
            if "part-phase" not in p.name
        ]
    )

    missing = 0
    bad_names = 0
    for nii in niis:
        if not BIDS_NAME_RE.match(nii.name):
            bad_names += 1
        if not is_imaging(nii.name):
            continue
        side = Path(str(nii).removesuffix(".nii.gz") + ".json")
        if not side.is_file():
            missing += 1
    out["missing_json"] = missing
    out["bad_bids_names"] = bad_names

    forb = 0
    invalid = 0
    phi_val = 0
    for jp in jsons:
        issues = scan_json_phi(jp)
        for iss in issues:
            if iss.startswith("INVALID_JSON") or iss == "NOT_OBJECT":
                invalid += 1
            elif iss.startswith("FORBIDDEN_KEY"):
                forb += 1
            elif iss.startswith("PHI_VALUE"):
                phi_val += 1
    out["forbidden_fields"] = forb
    out["invalid_json"] = invalid
    out["phi_value_hits"] = phi_val

    # Conversion: usable if ≥20 NIfTI with func, or documented sparse session with any func.
    marker = out["marker"]
    sparse_ok = participant == "sub-078" and out["n_nii"] >= 1 and out["n_bold_mag"] >= 1
    out["conversion_ok"] = (
        out["n_nii"] >= 20 and out["n_bold_mag"] >= 1
    ) or sparse_ok or marker.endswith(".SUCCESS") or marker.endswith(".SUCCESS_PARTIAL")

    out["bids_ok"] = (
        out["exists"]
        and out["n_nii"] >= 1
        and missing == 0
        and bad_names == 0
        and invalid == 0
    )
    out["phi_ok"] = forb == 0 and phi_val == 0 and invalid == 0

    if out["conversion_ok"] and out["bids_ok"] and out["phi_ok"]:
        out["gate"] = "PASS"
    elif out["exists"] and out["n_nii"] >= 1:
        out["gate"] = "BLOCK"
        bits = []
        if not out["conversion_ok"]:
            bits.append("conversion_incomplete")
        if not out["bids_ok"]:
            bits.append("bids_issues")
        if not out["phi_ok"]:
            bits.append("phi_or_institution")
        out["notes"] = ";".join(bits)
    else:
        out["gate"] = "FAIL"
        out["notes"] = "missing_or_empty"
    return out


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    targets = load_targets()
    rows = [audit_one(t) for t in targets]

    out_tsv = REPORTS / "SES02_RETRY11_QC_GATE.tsv"
    fields = list(rows[0].keys()) if rows else []
    with out_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    n_pass = sum(1 for r in rows if r["gate"] == "PASS")
    n_block = sum(1 for r in rows if r["gate"] == "BLOCK")
    n_fail = sum(1 for r in rows if r["gate"] == "FAIL")
    all_pass = n_block == 0 and n_fail == 0 and n_pass == len(rows)

    lines = [
        "# ses-02 retry11 — pre-QC gate",
        "",
        f"**Generated (UTC):** {utc_now()}",
        f"**Targets:** {len(targets)}",
        f"**PASS / BLOCK / FAIL:** {n_pass} / {n_block} / {n_fail}",
        f"**Overall gate:** {'PASS' if all_pass else 'HOLD — do not launch QC arrays'}",
        "",
        "| Subject | n_nii | T1w | BOLD | DWI | marker | conv | bids | phi | gate | notes |",
        "|---|---:|---:|---:|---:|---|:---:|:---:|:---:|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['participant_id']} | {r['n_nii']} | {r['n_t1w']} | {r['n_bold_mag']} | "
            f"{r['n_dwi']} | `{r['marker']}` | "
            f"{'Y' if r['conversion_ok'] else 'N'} | "
            f"{'Y' if r['bids_ok'] else 'N'} | "
            f"{'Y' if r['phi_ok'] else 'N'} | {r['gate']} | {r['notes']} |"
        )
    lines += [
        "",
        "## Criteria",
        "",
        "- Conversion: ≥20 NIfTI + BOLD (or documented sparse sub-078), or SUCCESS marker.",
        "- BIDS: every imaging NIfTI has a JSON sidecar; filenames match `sub-*_ses-*_*.nii.gz`.",
        "- PHI / admin: no InstitutionName / InstitutionalDepartmentName / StationName / "
        "DeviceSerialNumber / Patient* keys; JSON must parse.",
        "",
    ]
    md = REPORTS / "SES02_RETRY11_QC_GATE.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"PASS={n_pass} BLOCK={n_block} FAIL={n_fail} overall={'PASS' if all_pass else 'HOLD'}")
    print(f"Report: {md}")
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
