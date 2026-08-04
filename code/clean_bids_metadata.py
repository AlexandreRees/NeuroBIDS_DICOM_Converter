#!/usr/bin/env python3
"""Safe BIDS JSON metadata hygiene for Scientific Data publication readiness.

Never modifies NIfTI or TSV files. JSON sidecars are never overwritten in place
without a prior backup of each file that will change.

Modes:
  --dry-run   Scan and report only (default if neither flag is given with --dry-run required explicitly OR --apply).
  --apply     Backup then remove administrative / identifying fields.

Examples:
  python code/clean_bids_metadata.py --bids-dir /home/alexrees/scratch/bids --dry-run
  python code/clean_bids_metadata.py --bids-dir /home/alexrees/scratch/bids --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Field policy
# ---------------------------------------------------------------------------

REMOVE_FIELDS: list[str] = [
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
]

# Documented for reports / validation — never removed by this script.
KEEP_FIELDS: list[str] = [
    "Manufacturer",
    "ManufacturersModelName",
    "MagneticFieldStrength",
    "ProtocolName",
    "SeriesDescription",
    "SequenceName",
    "PulseSequenceDetails",
    "ScanningSequence",
    "RepetitionTime",
    "EchoTime",
    "FlipAngle",
    "SliceThickness",
    "SpacingBetweenSlices",
    "PhaseEncodingDirection",
    "TotalReadoutTime",
]

REMOVE_SET = frozenset(REMOVE_FIELDS)
KEEP_SET = frozenset(KEEP_FIELDS)

# Safety: refuse to remove anything listed as scientifically useful.
assert REMOVE_SET.isdisjoint(KEEP_SET), "REMOVE_FIELDS and KEEP_FIELDS overlap"


def _value_for_tsv(value: Any) -> str:
    """Serialize a JSON value for TSV reporting (single-line, truncated)."""
    try:
        text = json.dumps(value, ensure_ascii=False)
    except TypeError:
        text = str(value)
    text = text.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    if len(text) > 200:
        return text[:197] + "..."
    return text


def scan_json_sidecars(bids_dir: Path) -> list[Path]:
    """Return sorted list of all ``*.json`` files under *bids_dir* (recursive).

    Uses ``os.walk`` for better performance on Lustre than ``Path.rglob``.
    """
    import os

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(bids_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.endswith(".json"):
                found.append(Path(dirpath) / name)
        if len(found) and len(found) % 1000 == 0:
            print(f"  … indexed {len(found)} JSON paths", flush=True)
    found.sort()
    return found


def iter_process_sidecars(
    bids_dir: Path,
) -> tuple[int, list[tuple[Path, list[tuple[str, Any]]]]]:
    """Walk BIDS once: return (n_scanned, planned modifications)."""
    import os

    planned: list[tuple[Path, list[tuple[str, Any]]]] = []
    n_scanned = 0
    for dirpath, dirnames, filenames in os.walk(bids_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.endswith(".json"):
                continue
            path = Path(dirpath) / name
            n_scanned += 1
            if n_scanned % 500 == 0:
                print(
                    f"  … scanned {n_scanned} JSON files "
                    f"({len(planned)} with target fields)",
                    flush=True,
                )
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                print(f"WARNING: skipping unreadable JSON {path}: {exc}", flush=True)
                continue
            if not isinstance(data, dict):
                print(f"WARNING: skipping non-object JSON {path}", flush=True)
                continue
            found = find_removable_fields(data)
            if found:
                planned.append((path, found))
    planned.sort(key=lambda item: str(item[0]))
    return n_scanned, planned


def find_removable_fields(
    data: dict[str, Any],
) -> list[tuple[str, Any]]:
    """Return ``(field, value)`` pairs present in REMOVE_FIELDS."""
    found: list[tuple[str, Any]] = []
    for field in REMOVE_FIELDS:
        if field in data:
            found.append((field, data[field]))
    return found


def write_tsv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def backup_path_for(json_path: Path, bids_dir: Path, backup_root: Path) -> Path:
    """Mirror relative path under backup_root."""
    rel = json_path.relative_to(bids_dir)
    return backup_root / rel


def validate_all_json(paths: list[Path]) -> list[str]:
    """Return list of error messages for files that are not valid JSON objects."""
    errors: list[str] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: JSON parse failed ({exc})")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path}: root is not a JSON object")
    return errors


def build_summary(
    *,
    mode: str,
    bids_dir: Path,
    backup_root: Path | None,
    n_scanned: int,
    n_modified: int,
    n_with_findings: int,
    fields_removed_counts: dict[str, int],
    example_files: list[str],
    validation_errors: list[str],
) -> str:
    today = date.today().isoformat()
    lines = [
        "# BIDS metadata cleaning summary",
        "",
        f"**Date:** {today}",
        f"**Mode:** `{mode}`",
        f"**BIDS directory:** `{bids_dir}`",
        "",
        "## Purpose",
        "",
        "Publication-readiness metadata hygiene for Scientific Data submission. "
        "Administrative or potentially identifying sidecar fields are removed while "
        "scientifically relevant MRI acquisition parameters are preserved.",
        "",
        "## Counts",
        "",
        f"- JSON files scanned: **{n_scanned}**",
        f"- JSON files with target fields present: **{n_with_findings}**",
        f"- JSON files modified: **{n_modified}**"
        + (" (dry-run: none written)" if mode == "dry-run" else ""),
        "",
        "## Removed fields (policy)",
        "",
    ]
    for field in REMOVE_FIELDS:
        count = fields_removed_counts.get(field, 0)
        lines.append(f"- `{field}` — occurrences removed/proposed: **{count}**")

    lines += [
        "",
        "## Preserved acquisition fields (never removed by this script)",
        "",
    ]
    for field in KEEP_FIELDS:
        lines.append(f"- `{field}`")

    if backup_root is not None:
        lines += [
            "",
            "## Backup",
            "",
            f"Original JSON files copied to: `{backup_root}`",
        ]

    lines += [
        "",
        "## Example files changed (or proposed)",
        "",
    ]
    if example_files:
        for ex in example_files[:25]:
            lines.append(f"- `{ex}`")
        if len(example_files) > 25:
            lines.append(f"- … and {len(example_files) - 25} more")
    else:
        lines.append("_None._")

    lines += [
        "",
        "## Validation",
        "",
    ]
    if mode == "apply":
        if validation_errors:
            lines.append("**FAIL** — invalid JSON detected after cleaning:")
            for err in validation_errors:
                lines.append(f"- {err}")
        else:
            lines.append(
                "All scanned JSON sidecars remain valid JSON objects after cleaning. "
                "No NIfTI or TSV files were modified."
            )
    else:
        lines.append(
            "Dry-run only — no files written. NIfTI and TSV files were not touched."
        )

    lines += [
        "",
        "## Statement",
        "",
        "> Metadata cleaning was limited to potential administrative or identifying "
        "fields and did not alter MRI acquisition parameters.",
        "",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    return "\n".join(lines)


def run(
    *,
    bids_dir: Path,
    reports_dir: Path,
    backup_root: Path,
    apply: bool,
) -> int:
    if apply and not bids_dir.is_dir():
        print(f"ERROR: BIDS directory not found: {bids_dir}", file=sys.stderr)
        return 2

    print(f"Scanning JSON sidecars under {bids_dir} …", flush=True)
    n_scanned, planned = iter_process_sidecars(bids_dir)
    print(
        f"Scan complete: scanned={n_scanned} with_targets={len(planned)}",
        flush=True,
    )

    before_rows: list[dict[str, str]] = []
    field_counts: dict[str, int] = {f: 0 for f in REMOVE_FIELDS}

    for path, found in planned:
        rel = str(path.relative_to(bids_dir))
        for field, value in found:
            field_counts[field] = field_counts.get(field, 0) + 1
            before_rows.append(
                {
                    "file": rel,
                    "field_found": field,
                    "value": _value_for_tsv(value),
                    "action": "REMOVE" if apply else "WOULD_REMOVE",
                }
            )

    before_tsv = reports_dir / "bids_metadata_cleaning_before.tsv"
    write_tsv(
        before_tsv,
        before_rows,
        ["file", "field_found", "value", "action"],
    )
    print(f"Wrote {before_tsv} ({len(before_rows)} row(s))")

    n_with_findings = len(planned)
    example_files = [str(p.relative_to(bids_dir)) for p, _ in planned]
    n_modified = 0
    validation_errors: list[str] = []

    if not apply:
        print(
            f"DRY-RUN: scanned={n_scanned} files_with_targets={n_with_findings} "
            f"field_occurrences={len(before_rows)}"
        )
        after_rows = [
            {
                "metric": "json_files_scanned",
                "value": str(n_scanned),
            },
            {
                "metric": "json_files_with_target_fields",
                "value": str(n_with_findings),
            },
            {
                "metric": "json_files_modified",
                "value": "0",
            },
            {
                "metric": "field_occurrences_proposed_for_removal",
                "value": str(len(before_rows)),
            },
            {
                "metric": "mode",
                "value": "dry-run",
            },
        ]
        for field, count in field_counts.items():
            after_rows.append(
                {"metric": f"proposed_remove_count:{field}", "value": str(count)}
            )
        for ex in example_files[:20]:
            after_rows.append({"metric": "example_file_proposed", "value": ex})

        after_tsv = reports_dir / "bids_metadata_cleaning_after.tsv"
        write_tsv(after_tsv, after_rows, ["metric", "value"])
        print(f"Wrote {after_tsv}")

        summary = build_summary(
            mode="dry-run",
            bids_dir=bids_dir,
            backup_root=None,
            n_scanned=n_scanned,
            n_modified=0,
            n_with_findings=n_with_findings,
            fields_removed_counts=field_counts,
            example_files=example_files,
            validation_errors=[],
        )
        summary_path = reports_dir / "BIDS_METADATA_CLEANING_SUMMARY.md"
        summary_path.write_text(summary, encoding="utf-8")
        print(f"Wrote {summary_path}")
        return 0

    # ------------------------------------------------------------------ apply
    print(f"APPLY: backing up {n_with_findings} JSON file(s) to {backup_root}")
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "BACKUP_README.txt").write_text(
        "Original BIDS JSON sidecars before metadata cleaning.\n"
        f"Source: {bids_dir}\n"
        f"Created (UTC): {datetime.now(timezone.utc).isoformat()}\n"
        "Restore by copying files back to their relative paths under the BIDS root.\n",
        encoding="utf-8",
    )

    for path, found in planned:
        dest = backup_path_for(path, bids_dir, backup_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Copy original bytes unchanged
        dest.write_bytes(path.read_bytes())

        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print(f"ERROR: unexpected non-object after backup: {path}", file=sys.stderr)
            return 1
        for field, _ in found:
            if field in KEEP_SET:
                print(
                    f"ERROR: refusing to remove KEEP field {field} in {path}",
                    file=sys.stderr,
                )
                return 1
            data.pop(field, None)

        path.write_text(
            json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        n_modified += 1

    print(f"Modified {n_modified} JSON sidecar(s)")

    # Validation: all JSON under bids still parse (full rescan)
    print("Validating all JSON sidecars remain valid…", flush=True)
    all_json = scan_json_sidecars(bids_dir)
    validation_errors = validate_all_json(all_json)
    if validation_errors:
        print("ERROR: JSON validation failed after cleaning:", file=sys.stderr)
        for err in validation_errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    print("Validation OK — all JSON files parse as objects.")

    after_rows = [
        {"metric": "json_files_scanned", "value": str(n_scanned)},
        {"metric": "json_files_with_target_fields", "value": str(n_with_findings)},
        {"metric": "json_files_modified", "value": str(n_modified)},
        {"metric": "field_occurrences_removed", "value": str(len(before_rows))},
        {"metric": "mode", "value": "apply"},
        {"metric": "backup_root", "value": str(backup_root)},
        {"metric": "validation_errors", "value": "0"},
    ]
    for field, count in field_counts.items():
        after_rows.append({"metric": f"removed_count:{field}", "value": str(count)})
    for ex in example_files[:20]:
        after_rows.append({"metric": "example_file_changed", "value": ex})

    after_tsv = reports_dir / "bids_metadata_cleaning_after.tsv"
    write_tsv(after_tsv, after_rows, ["metric", "value"])
    print(f"Wrote {after_tsv}")

    summary = build_summary(
        mode="apply",
        bids_dir=bids_dir,
        backup_root=backup_root,
        n_scanned=n_scanned,
        n_modified=n_modified,
        n_with_findings=n_with_findings,
        fields_removed_counts=field_counts,
        example_files=example_files,
        validation_errors=validation_errors,
    )
    summary_path = reports_dir / "BIDS_METADATA_CLEANING_SUMMARY.md"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"Wrote {summary_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Safe BIDS JSON metadata cleaning (administrative / identifying fields only)."
        )
    )
    p.add_argument(
        "--bids-dir",
        type=Path,
        required=True,
        help="Path to BIDS dataset root (e.g. /home/alexrees/scratch/bids)",
    )
    p.add_argument(
        "--reports-dir",
        type=Path,
        default=Path.home() / "scratch" / "reports",
        help="Directory for TSV/MD reports (default: ~/scratch/reports)",
    )
    p.add_argument(
        "--backup-dir",
        type=Path,
        default=Path.home() / "scratch" / "bids_metadata_backup_before_cleaning",
        help=(
            "Backup root for original JSON files when using --apply "
            "(default: ~/scratch/bids_metadata_backup_before_cleaning)"
        ),
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report proposed removals only; do not modify any files",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Backup then remove target fields from JSON sidecars",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bids_dir = args.bids_dir.expanduser().resolve()
    reports_dir = args.reports_dir.expanduser().resolve()
    backup_root = args.backup_dir.expanduser().resolve()

    # Safety: never write backups or reports inside bids unintentionally as dataset files
    # (reports live outside by default). Refuse apply if backup is inside bids.
    if args.apply:
        try:
            backup_root.relative_to(bids_dir)
            print(
                "ERROR: --backup-dir must not be inside --bids-dir",
                file=sys.stderr,
            )
            return 2
        except ValueError:
            pass

    return run(
        bids_dir=bids_dir,
        reports_dir=reports_dir,
        backup_root=backup_root,
        apply=bool(args.apply),
    )


if __name__ == "__main__":
    raise SystemExit(main())
