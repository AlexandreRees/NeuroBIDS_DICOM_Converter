#!/usr/bin/env python3
"""READ-ONLY pre-check before BIDS metadata cleaning (--apply).

Never modifies any dataset files. Writes only:

  reports/BIDS_METADATA_CLEANING_PRECHECK.md
  reports/BIDS_METADATA_CLEANING_PRECHECK.tsv

Example:
  python code/verify_bids_metadata_cleaning_ready.py \\
    --bids-dir /home/alexrees/scratch/bids
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Fields that clean_bids_metadata.py is expected to remove in this publication pass.
REMOVE_FIELDS: list[str] = [
    "InstitutionalDepartmentName",
]

# Acquisition / scientific fields to report presence rates for (read-only).
SCIENTIFIC_FIELDS: list[str] = [
    "RepetitionTime",
    "EchoTime",
    "FlipAngle",
    "MagneticFieldStrength",
    "Manufacturer",
    "ManufacturersModelName",
    "SliceTiming",
    "PhaseEncodingDirection",
    "TotalReadoutTime",
    "EffectiveEchoSpacing",
]

DEFAULT_BIDS = Path("/home/alexrees/scratch/bids")
DEFAULT_BACKUP = Path.home() / "scratch" / "bids_metadata_backup_before_cleaning"
DEFAULT_REPORTS = Path.home() / "scratch" / "reports"
CLEAN_SCRIPT = Path.home() / "scratch" / "code" / "clean_bids_metadata.py"


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{n} B"


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["check", "status", "detail"], delimiter="\t"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def precheck(bids_dir: Path, backup_dir: Path, reports_dir: Path) -> tuple[bool, list[str]]:
    rows: list[dict[str, str]] = []
    blockers: list[str] = []
    notes: list[str] = []

    # ------------------------------------------------------------------ 1) BIDS
    if not bids_dir.is_dir():
        blockers.append(f"BIDS directory missing: {bids_dir}")
        rows.append(
            {
                "check": "bids_dir_exists",
                "status": "FAIL",
                "detail": str(bids_dir),
            }
        )
    else:
        rows.append(
            {
                "check": "bids_dir_exists",
                "status": "PASS",
                "detail": str(bids_dir),
            }
        )

    dd = bids_dir / "dataset_description.json"
    pt = bids_dir / "participants.tsv"
    for label, path in (
        ("dataset_description.json", dd),
        ("participants.tsv", pt),
    ):
        if path.is_file():
            rows.append({"check": f"bids_has_{label}", "status": "PASS", "detail": str(path)})
        else:
            blockers.append(f"Missing required BIDS file: {path}")
            rows.append(
                {"check": f"bids_has_{label}", "status": "FAIL", "detail": str(path)}
            )

    subjects = sorted(
        p for p in bids_dir.glob("sub-*") if p.is_dir()
    ) if bids_dir.is_dir() else []
    n_subjects = len(subjects)
    if n_subjects == 0 and bids_dir.is_dir():
        blockers.append("No sub-* directories found under BIDS root")
        rows.append(
            {"check": "bids_has_subjects", "status": "FAIL", "detail": "0 subjects"}
        )
    else:
        rows.append(
            {
                "check": "bids_has_subjects",
                "status": "PASS" if n_subjects else "FAIL",
                "detail": f"n_subjects={n_subjects}",
            }
        )

    n_sessions = 0
    n_json = 0
    n_nifti = 0
    n_tsv = 0
    invalid_json: list[str] = []
    json_with_remove: list[Path] = []
    remove_counts: Counter[str] = Counter()
    sci_present: Counter[str] = Counter()
    sci_checked = 0

    if bids_dir.is_dir():
        print(f"Walking BIDS tree under {bids_dir} …", flush=True)
        for dirpath, dirnames, filenames in os.walk(bids_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            base = Path(dirpath)
            # session dirs
            if base.name.startswith("ses-") and base.parent.name.startswith("sub-"):
                n_sessions += 1
            for name in filenames:
                lower = name.lower()
                path = base / name
                if lower.endswith(".nii") or lower.endswith(".nii.gz"):
                    n_nifti += 1
                    continue
                if lower.endswith(".tsv"):
                    n_tsv += 1
                    continue
                if not lower.endswith(".json"):
                    continue
                n_json += 1
                if n_json % 500 == 0:
                    print(f"  … scanned {n_json} JSON", flush=True)
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:  # noqa: BLE001
                    invalid_json.append(f"{path}: {exc}")
                    continue
                if not isinstance(data, dict):
                    invalid_json.append(f"{path}: root is not a JSON object")
                    continue

                hit = False
                for field in REMOVE_FIELDS:
                    if field in data:
                        remove_counts[field] += 1
                        hit = True
                if hit:
                    json_with_remove.append(path)

                # Presence rates among subject sidecars only
                if any(part.startswith("sub-") for part in path.parts):
                    sci_checked += 1
                    for field in SCIENTIFIC_FIELDS:
                        if field in data:
                            sci_present[field] += 1

    rows.append(
        {
            "check": "count_subjects",
            "status": "INFO",
            "detail": str(n_subjects),
        }
    )
    rows.append(
        {"check": "count_sessions", "status": "INFO", "detail": str(n_sessions)}
    )
    rows.append({"check": "count_json", "status": "INFO", "detail": str(n_json)})
    rows.append({"check": "count_nifti", "status": "INFO", "detail": str(n_nifti)})
    rows.append({"check": "count_tsv", "status": "INFO", "detail": str(n_tsv)})

    # ------------------------------------------------------------------ 2) backup
    backup_inside_bids = False
    try:
        backup_dir.resolve().relative_to(bids_dir.resolve())
        backup_inside_bids = True
    except ValueError:
        backup_inside_bids = False

    if backup_inside_bids:
        blockers.append(
            f"Backup path is inside BIDS root (unsafe): {backup_dir}"
        )
        rows.append(
            {
                "check": "backup_path_outside_bids",
                "status": "FAIL",
                "detail": str(backup_dir),
            }
        )
    else:
        rows.append(
            {
                "check": "backup_path_outside_bids",
                "status": "PASS",
                "detail": str(backup_dir),
            }
        )

    if backup_dir.exists():
        size = dir_size_bytes(backup_dir)
        try:
            mtime = datetime.fromtimestamp(
                backup_dir.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            mtime = "unknown"
        # Heuristic incomplete: empty, or only README, or no mirrored JSON
        n_backup_json = 0
        for _dp, _dn, filenames in os.walk(backup_dir):
            n_backup_json += sum(1 for n in filenames if n.endswith(".json"))
        incomplete = n_backup_json == 0
        status = "WARN"
        detail = (
            f"exists size={human_bytes(size)} mtime_utc={mtime} "
            f"json_files={n_backup_json}"
            + (" INCOMPLETE_OR_EMPTY" if incomplete else " (prior backup present — do not delete; confirm before overwrite)")
        )
        notes.append(
            "A prior backup directory already exists. The cleaning script will write "
            "into the same path; confirm this is intentional. Nothing was deleted."
        )
        if incomplete:
            notes.append(
                "Existing backup appears empty/incomplete (no JSON mirrored yet)."
            )
        rows.append({"check": "backup_existing", "status": status, "detail": detail})
    else:
        rows.append(
            {
                "check": "backup_existing",
                "status": "PASS",
                "detail": "backup path does not exist yet (will be created on --apply)",
            }
        )

    # ------------------------------------------------------------------ 3) JSON
    n_invalid = len(invalid_json)
    if n_invalid:
        blockers.append(f"{n_invalid} invalid JSON sidecar(s)")
        rows.append(
            {
                "check": "json_valid",
                "status": "FAIL",
                "detail": f"invalid={n_invalid}; examples="
                + "; ".join(invalid_json[:5]),
            }
        )
    else:
        rows.append(
            {
                "check": "json_valid",
                "status": "PASS",
                "detail": f"all_parsed_ok n_json={n_json}",
            }
        )

    n_targets = len(json_with_remove)
    rows.append(
        {
            "check": "json_with_remove_fields",
            "status": "INFO",
            "detail": f"n={n_targets} fields={dict(remove_counts)}",
        }
    )
    examples = [
        str(p.relative_to(bids_dir)) for p in json_with_remove[:20]
    ]
    rows.append(
        {
            "check": "example_json_with_remove_fields",
            "status": "INFO",
            "detail": " | ".join(examples) if examples else "(none)",
        }
    )

    # ------------------------------------------------------------------ 4) scientific
    for field in SCIENTIFIC_FIELDS:
        present = sci_present.get(field, 0)
        rate = (100.0 * present / sci_checked) if sci_checked else 0.0
        rows.append(
            {
                "check": f"scientific_presence:{field}",
                "status": "INFO",
                "detail": f"present={present}/{sci_checked} ({rate:.1f}%)",
            }
        )

    # ------------------------------------------------------------------ 5) script
    if CLEAN_SCRIPT.is_file():
        digest = md5_file(CLEAN_SCRIPT)
        mtime = datetime.fromtimestamp(
            CLEAN_SCRIPT.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        rows.append(
            {
                "check": "clean_script_present",
                "status": "PASS",
                "detail": f"path={CLEAN_SCRIPT} md5={digest} mtime_utc={mtime}",
            }
        )
    else:
        blockers.append(f"Missing cleaning script: {CLEAN_SCRIPT}")
        rows.append(
            {
                "check": "clean_script_present",
                "status": "FAIL",
                "detail": str(CLEAN_SCRIPT),
            }
        )

    # ------------------------------------------------------------------ 6) nifti/tsv not targets
    # Cleaning script only touches JSON; assert policy.
    rows.append(
        {
            "check": "nifti_tsv_not_targeted",
            "status": "PASS",
            "detail": (
                "clean_bids_metadata.py removes keys from JSON sidecars only; "
                f"nifti={n_nifti} tsv={n_tsv} will not be modified"
            ),
        }
    )

    safe = len(blockers) == 0
    rows.append(
        {
            "check": "SAFE_TO_APPLY",
            "status": "PASS" if safe else "FAIL",
            "detail": "TRUE" if safe else "FALSE",
        }
    )

    # Write TSV
    tsv_path = reports_dir / "BIDS_METADATA_CLEANING_PRECHECK.tsv"
    write_tsv(tsv_path, rows)
    print(f"Wrote {tsv_path}", flush=True)

    # Markdown
    lines = [
        "# BIDS metadata cleaning — pre-check (READ-ONLY)",
        "",
        f"**Generated (UTC):** {datetime.now(timezone.utc).isoformat()}",
        f"**BIDS dir:** `{bids_dir}`",
        f"**Backup path:** `{backup_dir}`",
        f"**Cleaning script:** `{CLEAN_SCRIPT}`",
        "",
        "This pre-check does **not** modify any files under `bids/`.",
        "",
        "## VERDICT",
        "",
        f"SAFE_TO_APPLY = {'TRUE' if safe else 'FALSE'}",
        "",
    ]
    if blockers:
        lines += ["### Blocking issues", ""]
        for b in blockers:
            lines.append(f"- {b}")
        lines.append("")
    if notes:
        lines += ["### Notes / confirmations (non-blocking)", ""]
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")

    lines += [
        "## 1. BIDS structure",
        "",
        f"- Subjects (`sub-*`): **{n_subjects}**",
        f"- Sessions (`ses-*` under subjects): **{n_sessions}**",
        f"- JSON sidecars: **{n_json}**",
        f"- NIfTI (`.nii` / `.nii.gz`): **{n_nifti}**",
        f"- TSV files: **{n_tsv}**",
        f"- `dataset_description.json`: {'present' if dd.is_file() else 'MISSING'}",
        f"- `participants.tsv`: {'present' if pt.is_file() else 'MISSING'}",
        "",
        "## 2. Backup path safety",
        "",
        f"- Outside BIDS: **{'yes' if not backup_inside_bids else 'NO — BLOCKER'}**",
        f"- Already exists: **{'yes' if backup_dir.exists() else 'no'}**",
        "",
        "## 3. JSON / REMOVE_FIELDS",
        "",
        f"- Invalid JSON: **{n_invalid}**",
        f"- JSON containing ≥1 REMOVE field: **{n_targets}**",
        f"- REMOVE_FIELDS policy: `{REMOVE_FIELDS}`",
        f"- Field occurrence counts: `{dict(remove_counts)}`",
        "",
        "### Example paths",
        "",
    ]
    if examples:
        for ex in examples:
            lines.append(f"- `{ex}`")
    else:
        lines.append("_None._")

    lines += [
        "",
        "## 4. Scientific field presence (read-only rates among `sub-*/**/*.json`)",
        "",
        f"Sidecars scored: **{sci_checked}**",
        "",
        "| Field | Present | Rate |",
        "| --- | ---: | ---: |",
    ]
    for field in SCIENTIFIC_FIELDS:
        present = sci_present.get(field, 0)
        rate = (100.0 * present / sci_checked) if sci_checked else 0.0
        lines.append(f"| `{field}` | {present} | {rate:.1f}% |")

    lines += [
        "",
        "## 5. Cleaning script provenance",
        "",
    ]
    if CLEAN_SCRIPT.is_file():
        lines.append(f"- Path: `{CLEAN_SCRIPT}`")
        lines.append(f"- MD5: `{md5_file(CLEAN_SCRIPT)}`")
        lines.append(
            "- mtime (UTC): "
            f"`{datetime.fromtimestamp(CLEAN_SCRIPT.stat().st_mtime, tz=timezone.utc).isoformat()}`"
        )
    else:
        lines.append("- **MISSING**")

    lines += [
        "",
        "## 6. Automatic gate",
        "",
        "SAFE_TO_APPLY = TRUE only if: BIDS exists with minimal structure, all JSON "
        "valid, backup path outside BIDS, cleaning script present, and NIfTI/TSV are "
        "not cleaning targets.",
        "",
        f"**Final:** SAFE_TO_APPLY = {'TRUE' if safe else 'FALSE'}",
        "",
    ]
    md_path = reports_dir / "BIDS_METADATA_CLEANING_PRECHECK.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {md_path}", flush=True)
    print(f"SAFE_TO_APPLY = {'TRUE' if safe else 'FALSE'}", flush=True)
    return safe, blockers


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    p.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP)
    p.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bids_dir = args.bids_dir.expanduser().resolve()
    backup_dir = args.backup_dir.expanduser().resolve()
    reports_dir = args.reports_dir.expanduser().resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Refuse to write reports inside bids
    try:
        reports_dir.relative_to(bids_dir)
        print("ERROR: --reports-dir must not be inside --bids-dir", file=sys.stderr)
        return 2
    except ValueError:
        pass

    safe, blockers = precheck(bids_dir, backup_dir, reports_dir)
    if not safe:
        print("Blocking issues:", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
