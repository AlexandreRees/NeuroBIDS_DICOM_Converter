#!/usr/bin/env python3
"""READ-ONLY BIDS JSON sidecar privacy audit.

Never modifies BIDS files. Writes only under
reports/deidentification_validation/.

Examples:
  python code/audit_bids_sidecar_privacy.py --dry-run \\
    --bids-dir /home/alexrees/scratch/bids

  python code/audit_bids_sidecar_privacy.py \\
    --bids-dir /home/alexrees/scratch/bids
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BIDS = Path("/home/alexrees/scratch/bids")
DEFAULT_OUT = Path("/home/alexrees/scratch/reports/deidentification_validation")

# Forbidden / sensitive keys — classification policy
FORBIDDEN_FIELDS: dict[str, str] = {
    "PatientName": "PHI_RISK",
    "PatientID": "PHI_RISK",
    "PatientBirthDate": "PHI_RISK",
    "PatientAge": "PHI_RISK",
    "PatientSex": "REVIEW_REQUIRED",  # flag only
    "InstitutionName": "PHI_RISK",
    "InstitutionalDepartmentName": "PHI_RISK",
    "DeviceSerialNumber": "PHI_RISK",
    "StationName": "PHI_RISK",
    "OperatorsName": "PHI_RISK",
    "PhysicianName": "PHI_RISK",
    "ReferringPhysicianName": "PHI_RISK",
    "PerformingPhysicianName": "PHI_RISK",
    "AcquisitionDate": "PHI_RISK",
    "AcquisitionTime": "REVIEW_REQUIRED",
    "SeriesDate": "PHI_RISK",
    "StudyDate": "PHI_RISK",
}

FREETEXT_FIELDS = (
    "SeriesDescription",
    "ProtocolName",
    "SequenceName",
    "PulseSequenceDetails",
)

# Heuristic tokens that may indicate residual PHI in free text
# Note: do not use IGNORECASE with [A-Z]/[a-z] person-name patterns (classes expand).
SUSPICIOUS_RE = re.compile(
    r"("
    r"\b(dr\.?|prof\.?|patient|subject|mrn|ssn|phone)\b|"
    r"\b(mr|ms|mrs)\.|"
    r"\b\d{4}[-/]\d{2}[-/]\d{2}\b|"
    r"@"
    r")",
    re.IGNORECASE,
)

SAFE_FREETEXT_HINTS = re.compile(
    r"(t1|t2|flair|bold|dwi|epi|mp2rage|gre|spin\s*echo|field\s*map|"
    r"rest|movie|fmri|fmap|sbref|diff|localizer|scout|b1|tb1|"
    r"siemens|seq|tse|vfl|ep2d|ep_b|mprage|spc|resolve|fieldmap)",
    re.IGNORECASE,
)

PERSON_LIKE = re.compile(r"\b[A-Z][a-z]{2,}_[A-Z][a-z]{2,}\b")


def log(msg: str) -> None:
    print(msg, flush=True)


def classify_freetext(field: str, value: str) -> str:
    text = str(value).strip()
    if not text:
        return "SAFE"
    # Vendor / sequence technical strings default SAFE
    if SAFE_FREETEXT_HINTS.search(text) and not SUSPICIOUS_RE.search(text):
        return "SAFE"
    if SUSPICIOUS_RE.search(text):
        return "REVIEW_REQUIRED"
    if PERSON_LIKE.search(text) and not SAFE_FREETEXT_HINTS.search(text):
        return "REVIEW_REQUIRED"
    return "SAFE"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="READ-ONLY BIDS sidecar privacy audit.")
    p.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-files", type=int, default=None)
    return p.parse_args()


def write_tsv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def main() -> int:
    args = parse_args()
    bids = args.bids_dir
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if not bids.is_dir():
        log(f"ERROR: --bids-dir missing: {bids}")
        return 2

    json_files = sorted(bids.rglob("*.json"))
    # Exclude derivatives under bids if any
    json_files = [p for p in json_files if "derivatives" not in p.parts]
    max_files = args.max_files
    if args.dry_run and max_files is None:
        max_files = 100
    if max_files is not None:
        json_files = json_files[:max_files]

    log(f"Scanning {len(json_files)} JSON sidecars under {bids}")

    rows: list[dict[str, str]] = []
    class_counts = Counter()
    field_hits = Counter()
    invalid = 0
    freetext_unique: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, list[str]] = defaultdict(list)

    for i, path in enumerate(json_files, 1):
        if i % 500 == 0 or i == len(json_files):
            log(f"  … {i}/{len(json_files)}")
        try:
            rel = str(path.relative_to(bids))
        except ValueError:
            rel = str(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            invalid += 1
            rows.append(
                {
                    "file": rel,
                    "field": "JSON_PARSE",
                    "value": str(exc)[:200],
                    "classification": "PHI_RISK",
                }
            )
            class_counts["PHI_RISK"] += 1
            continue
        if not isinstance(data, dict):
            invalid += 1
            rows.append(
                {
                    "file": rel,
                    "field": "JSON_TYPE",
                    "value": type(data).__name__,
                    "classification": "PHI_RISK",
                }
            )
            class_counts["PHI_RISK"] += 1
            continue

        for field, classification in FORBIDDEN_FIELDS.items():
            if field not in data:
                continue
            val = data[field]
            if val is None or (isinstance(val, str) and not val.strip()):
                continue
            preview = str(val)
            if len(preview) > 200:
                preview = preview[:197] + "..."
            rows.append(
                {
                    "file": rel,
                    "field": field,
                    "value": preview,
                    "classification": classification,
                }
            )
            class_counts[classification] += 1
            field_hits[field] += 1
            if len(examples[field]) < 5:
                examples[field].append(rel)

        for field in FREETEXT_FIELDS:
            if field not in data:
                continue
            val = data[field]
            if val is None:
                continue
            preview = str(val)
            if len(preview) > 200:
                preview = preview[:197] + "..."
            cls = classify_freetext(field, preview)
            # Always record unique values for review tables; emit row if not SAFE
            freetext_unique[field].add(preview)
            if cls != "SAFE":
                rows.append(
                    {
                        "file": rel,
                        "field": field,
                        "value": preview,
                        "classification": cls,
                    }
                )
                class_counts[cls] += 1
                field_hits[field] += 1
                if len(examples[field]) < 5:
                    examples[field].append(f"{rel} :: {preview}")

    # Also emit one SAFE summary row per unique free-text value for documentation
    unique_rows: list[dict[str, str]] = []
    for field, values in sorted(freetext_unique.items()):
        for v in sorted(values):
            cls = classify_freetext(field, v)
            unique_rows.append(
                {
                    "file": "(unique_value)",
                    "field": field,
                    "value": v,
                    "classification": cls,
                }
            )

    tsv_path = out_dir / (
        "bids_sidecar_phi_audit_dryrun.tsv" if args.dry_run else "bids_sidecar_phi_audit.tsv"
    )
    write_tsv(tsv_path, rows, ["file", "field", "value", "classification"])
    unique_path = out_dir / (
        "bids_sidecar_freetext_unique_dryrun.tsv"
        if args.dry_run
        else "bids_sidecar_freetext_unique.tsv"
    )
    write_tsv(unique_path, unique_rows, ["file", "field", "value", "classification"])

    phi_risk_n = class_counts.get("PHI_RISK", 0)
    review_n = class_counts.get("REVIEW_REQUIRED", 0)

    md_path = out_dir / (
        "bids_sidecar_privacy_summary_dryrun.md"
        if args.dry_run
        else "bids_sidecar_privacy_summary.md"
    )
    lines = [
        "# BIDS sidecar privacy audit (READ-ONLY)",
        "",
        f"**Generated (UTC):** {datetime.now(timezone.utc).isoformat()}",
        f"**BIDS dir:** `{bids.resolve()}`",
        f"**Dry-run:** {args.dry_run}",
        "",
        "## Counts",
        "",
        f"- JSON files scanned: **{len(json_files)}**",
        f"- Invalid / non-object JSON: **{invalid}**",
        f"- Findings rows (non-SAFE forbidden/free-text): **{len(rows)}**",
        f"- Classification PHI_RISK: **{phi_risk_n}**",
        f"- Classification REVIEW_REQUIRED: **{review_n}**",
        "",
        "## Forbidden / sensitive field hits",
        "",
        "| Field | Hits | Default classification |",
        "| --- | ---: | --- |",
    ]
    for field, cls in FORBIDDEN_FIELDS.items():
        lines.append(f"| `{field}` | {field_hits.get(field, 0)} | {cls} |")

    lines += [
        "",
        "## Free-text fields",
        "",
        "| Field | Unique values | Notes |",
        "| --- | ---: | --- |",
    ]
    for field in FREETEXT_FIELDS:
        lines.append(
            f"| `{field}` | {len(freetext_unique.get(field, ()))} | "
            f"see `{unique_path.name}` |"
        )

    if any(examples.values()):
        lines += ["", "## Example paths", ""]
        for field, exs in sorted(examples.items()):
            lines.append(f"### `{field}`")
            for e in exs:
                lines.append(f"- `{e}`")

    verdict = "PASS"
    if phi_risk_n > 0 or invalid > 0:
        verdict = "FAIL"
    elif review_n > 0:
        verdict = "PASS_WITH_REVIEW"

    lines += [
        "",
        "## Verdict",
        "",
        f"**{verdict}**",
        "",
        "Interpretation:",
        "- `PASS`: no PHI_RISK keys and no invalid JSON.",
        "- `PASS_WITH_REVIEW`: free-text or PatientSex flagged for manual review.",
        "- `FAIL`: residual direct identifiers or invalid JSON.",
        "",
        "Prior cleaning (`clean_bids_metadata.py`) removed "
        "`InstitutionalDepartmentName` from BIDS sidecars; this audit confirms "
        "current state.",
        "",
        f"TSV findings: `{tsv_path.name}`",
        f"Unique free-text: `{unique_path.name}`",
        "",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "bids_dir": str(bids.resolve()),
        "dry_run": args.dry_run,
        "n_json": len(json_files),
        "invalid": invalid,
        "phi_risk": phi_risk_n,
        "review_required": review_n,
        "field_hits": dict(field_hits),
        "verdict": verdict,
        "tsv": str(tsv_path),
        "summary_md": str(md_path),
    }
    (out_dir / ("bids_sidecar_summary_dryrun.json" if args.dry_run else "bids_sidecar_summary.json")).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    log(f"Wrote {tsv_path}")
    log(f"Wrote {md_path}")
    log(f"Verdict: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
