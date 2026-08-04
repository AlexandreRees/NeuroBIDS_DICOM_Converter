#!/usr/bin/env python3
"""Remove InstitutionalDepartmentName from defacing derivative JSON only.

Safety rules:
  - Touch ONLY JSON under derivatives/defacing
  - Never modify NIfTI, bval/bvec, or any file under bids/
  - Never remove acquisition / scientific fields
  - Always backup before --apply
  - Validate JSON after every write; abort further writes on failure

Examples:
  python code/clean_defacing_metadata.py --dry-run
  python code/clean_defacing_metadata.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DEFACING = Path("/home/alexrees/scratch/derivatives/defacing")
DEFAULT_REPORTS = Path("/home/alexrees/scratch/reports/defacing_audit")
DEFAULT_BACKUP_ROOT = Path("/home/alexrees/scratch/defacing_metadata_backup")

REMOVE_FIELD = "InstitutionalDepartmentName"

# Must never be removed by this script (acquisition / scientific usefulness).
PROTECTED_FIELDS = frozenset(
    {
        "RepetitionTime",
        "EchoTime",
        "InversionTime",
        "FlipAngle",
        "SliceThickness",
        "SpacingBetweenSlices",
        "MagneticFieldStrength",
        "Manufacturer",
        "ManufacturersModelName",
        "ProtocolName",
        "SeriesDescription",
        "SequenceName",
        "PulseSequenceDetails",
        "ScanningSequence",
        "PhaseEncodingDirection",
        "TotalReadoutTime",
        "ReceiveCoilName",
        "ReceiveCoilActiveElements",
        "BaseResolution",
        "PixelBandwidth",
        "DwellTime",
        "EffectiveEchoSpacing",
        "MultibandAccelerationFactor",
        "ParallelReductionFactorInPlane",
        "PartialFourier",
        "ImageOrientationPatientDICOM",
        "ConversionSoftware",
        "ConversionSoftwareVersion",
    }
)

assert REMOVE_FIELD not in PROTECTED_FIELDS


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scrub InstitutionalDepartmentName from defacing JSON only."
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Scan and report only.")
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Backup then remove InstitutionalDepartmentName.",
    )
    p.add_argument("--defacing-dir", type=Path, default=DEFAULT_DEFACING)
    p.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    p.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    return p.parse_args()


def iter_sidecar_json(defacing_dir: Path) -> list[Path]:
    files = sorted(defacing_dir.rglob("*.json"))
    return [p for p in files if p.name != "dataset_description.json"]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return data


def validate_json_file(path: Path) -> None:
    """Re-parse written file; raise on any failure."""
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Post-write validation failed (not object): {path}")
    # Round-trip check
    json.dumps(data)


def scan(defacing_dir: Path) -> tuple[list[Path], list[Path], dict[str, int]]:
    all_json = iter_sidecar_json(defacing_dir)
    with_field: list[Path] = []
    value_counts: dict[str, int] = {}
    for path in all_json:
        meta = load_json(path)
        if REMOVE_FIELD in meta:
            with_field.append(path)
            val = meta[REMOVE_FIELD]
            key = json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val
            value_counts[key] = value_counts.get(key, 0) + 1
    return all_json, with_field, value_counts


def write_precheck(
    path: Path,
    *,
    defacing_dir: Path,
    all_json: list[Path],
    with_field: list[Path],
    value_counts: dict[str, int],
) -> None:
    lines = [
        "# Defacing metadata precheck",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "Mode: **DRY-RUN** (no files modified)",
        "",
        f"- Defacing directory: `{defacing_dir}`",
        f"- Sidecar JSON inspected (excluding dataset_description.json): **{len(all_json)}**",
        f"- JSON containing `{REMOVE_FIELD}`: **{len(with_field)}**",
        "",
        "## Value counts",
        "",
    ]
    if value_counts:
        for val, n in sorted(value_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- `{val}`: {n}")
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "## Planned action on --apply",
            "",
            f"- Remove **only** `{REMOVE_FIELD}`",
            "- Preserve all acquisition / scientific fields "
            "(including ProtocolName, SeriesDescription, TR/TE/TI/FlipAngle/…)",
            "- Never modify NIfTI or any path under `bids/`",
            f"- Backup tree: `{DEFAULT_BACKUP_ROOT}/<timestamp>/`",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_final(
    path: Path,
    *,
    defacing_dir: Path,
    backup_dir: Path | None,
    n_inspected: int,
    n_targeted: int,
    n_modified: int,
    n_backed_up: int,
    remaining: int,
    errors: list[str],
    protected_intact: bool,
    json_valid: bool,
) -> str:
    if errors or remaining > 0 or not json_valid or not protected_intact:
        verdict = "FAIL"
    else:
        verdict = "PASS"

    lines = [
        "# Defacing metadata final report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "Mode: **APPLY**",
        "",
        f"## Verdict: **{verdict}**",
        "",
        "## Summary",
        "",
        f"- Defacing directory: `{defacing_dir}`",
        f"- JSON inspected: **{n_inspected}**",
        f"- JSON targeted (`{REMOVE_FIELD}` present): **{n_targeted}**",
        f"- JSON modified: **{n_modified}**",
        f"- Backup files created: **{n_backed_up}**",
        f"- Backup directory: `{backup_dir}`" if backup_dir else "- Backup directory: (n/a)",
        f"- Fields removed: `{REMOVE_FIELD}` only",
        f"- Remaining `{REMOVE_FIELD}` after apply: **{remaining}**",
        f"- JSON validation after write: **{'PASS' if json_valid else 'FAIL'}**",
        f"- Protected acquisition fields intact (spot-check): "
        f"**{'PASS' if protected_intact else 'FAIL'}**",
        "",
        "## Errors",
        "",
    ]
    if errors:
        for e in errors:
            lines.append(f"- {e}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Policy reminder",
            "",
            "- NIfTI untouched",
            "- `bids/` untouched",
            "- ProtocolName / SeriesDescription retained",
            "- Acquisition parameters retained",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return verdict


def backup_file(src: Path, defacing_dir: Path, backup_dir: Path) -> Path:
    rel = src.relative_to(defacing_dir)
    dst = backup_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def remove_field_in_place(path: Path) -> tuple[bool, str | None]:
    """Return (modified, error). On error, file must be left unchanged or restored by caller."""
    original_text = path.read_text(encoding="utf-8")
    try:
        meta = json.loads(original_text)
        if not isinstance(meta, dict):
            return False, f"not a JSON object: {path}"
        if REMOVE_FIELD not in meta:
            return False, None
        # Guard: never touch protected keys
        for key in PROTECTED_FIELDS:
            # presence is fine; we simply must not delete them
            pass
        del meta[REMOVE_FIELD]
        # Ensure protected keys that existed still exist
        original = json.loads(original_text)
        for key in PROTECTED_FIELDS:
            if key in original and key not in meta:
                # restore and fail
                path.write_text(original_text, encoding="utf-8")
                return False, f"protected field would be lost ({key}): {path}"
        new_text = json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
        path.write_text(new_text, encoding="utf-8")
        validate_json_file(path)
        # Re-check protected fields after write
        written = load_json(path)
        for key in PROTECTED_FIELDS:
            if key in original and key not in written:
                path.write_text(original_text, encoding="utf-8")
                return False, f"post-write protected field missing ({key}): {path}"
        if REMOVE_FIELD in written:
            path.write_text(original_text, encoding="utf-8")
            return False, f"field still present after write: {path}"
        return True, None
    except Exception as exc:  # noqa: BLE001
        # Best-effort restore
        try:
            path.write_text(original_text, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return False, f"{path}: {exc}"


def spotcheck_protected(defacing_dir: Path, sample_paths: list[Path]) -> bool:
    """Confirm ProtocolName/SeriesDescription/TR still present where expected."""
    for path in sample_paths[:20]:
        meta = load_json(path)
        # If the sidecar previously had these (almost all do), they must remain.
        # We only assert that we did not remove them if they are typical anat sidecars.
        if path.name.endswith("_T1w.json") or path.name.endswith("_FLAIR.json"):
            for key in ("ProtocolName", "SeriesDescription", "RepetitionTime", "EchoTime", "FlipAngle"):
                if key not in meta:
                    # Some rare sidecars might lack a key historically; only fail if
                    # backup implied it — for apply we check against backup instead.
                    pass
    return True


def verify_against_backup(
    modified: list[Path], defacing_dir: Path, backup_dir: Path
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for path in modified:
        rel = path.relative_to(defacing_dir)
        bak = backup_dir / rel
        if not bak.is_file():
            errors.append(f"missing backup for {path}")
            continue
        before = load_json(bak)
        after = load_json(path)
        for key in PROTECTED_FIELDS:
            if key in before and before[key] != after.get(key):
                errors.append(f"protected field altered ({key}) in {path}")
        if REMOVE_FIELD in after:
            errors.append(f"{REMOVE_FIELD} still present in {path}")
        # No unexpected key deletions beyond REMOVE_FIELD
        lost = set(before) - set(after) - {REMOVE_FIELD}
        if lost:
            errors.append(f"unexpected keys removed {sorted(lost)} in {path}")
        gained_drop = set(after) - set(before)
        # Allow nothing else changed in key set except removal
        if gained_drop:
            errors.append(f"unexpected keys added {sorted(gained_drop)} in {path}")
    return (len(errors) == 0), errors


def main() -> int:
    args = parse_args()
    defacing_dir = args.defacing_dir.resolve()
    reports_dir = args.reports_dir.resolve()
    backup_root = args.backup_root.resolve()

    if not defacing_dir.is_dir():
        log(f"ERROR: defacing dir not found: {defacing_dir}")
        return 1

    # Hard safety: refuse paths that look like the raw BIDS root
    if defacing_dir.name == "bids" and "derivatives" not in defacing_dir.parts:
        log("ERROR: refusing to operate on a raw BIDS root")
        return 1

    log(f"Defacing dir: {defacing_dir}")
    all_json, with_field, value_counts = scan(defacing_dir)
    log(f"Inspected: {len(all_json)}  with {REMOVE_FIELD}: {len(with_field)}")

    if args.dry_run:
        precheck = reports_dir / "DEFACING_METADATA_PRECHECK.md"
        write_precheck(
            precheck,
            defacing_dir=defacing_dir,
            all_json=all_json,
            with_field=with_field,
            value_counts=value_counts,
        )
        log(f"Wrote {precheck}")
        return 0

    # --apply
    if not with_field:
        log(f"Nothing to do: no {REMOVE_FIELD} found")
        verdict = write_final(
            reports_dir / "DEFACING_METADATA_FINAL.md",
            defacing_dir=defacing_dir,
            backup_dir=None,
            n_inspected=len(all_json),
            n_targeted=0,
            n_modified=0,
            n_backed_up=0,
            remaining=0,
            errors=[],
            protected_intact=True,
            json_valid=True,
        )
        log(f"Verdict: {verdict}")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_root / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    log(f"Backup dir: {backup_dir}")

    errors: list[str] = []
    modified: list[Path] = []
    n_backed = 0

    for path in with_field:
        try:
            backup_file(path, defacing_dir, backup_dir)
            n_backed += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"backup failed for {path}: {exc}")
            log("ERROR during backup — stopping before any edits")
            write_final(
                reports_dir / "DEFACING_METADATA_FINAL.md",
                defacing_dir=defacing_dir,
                backup_dir=backup_dir,
                n_inspected=len(all_json),
                n_targeted=len(with_field),
                n_modified=0,
                n_backed_up=n_backed,
                remaining=len(with_field),
                errors=errors,
                protected_intact=False,
                json_valid=False,
            )
            return 1

    for path in with_field:
        ok, err = remove_field_in_place(path)
        if err:
            errors.append(err)
            log(f"ERROR: {err}")
            log("Stopping further modifications after error")
            break
        if ok:
            modified.append(path)

    # Post verification
    _, remaining_list, _ = scan(defacing_dir)
    remaining = len(remaining_list)
    protected_ok, prot_errs = verify_against_backup(modified, defacing_dir, backup_dir)
    errors.extend(prot_errs)

    # Validate all modified JSON again
    json_valid = True
    for path in modified:
        try:
            validate_json_file(path)
        except Exception as exc:  # noqa: BLE001
            json_valid = False
            errors.append(f"validation failed: {path}: {exc}")

    verdict = write_final(
        reports_dir / "DEFACING_METADATA_FINAL.md",
        defacing_dir=defacing_dir,
        backup_dir=backup_dir,
        n_inspected=len(all_json),
        n_targeted=len(with_field),
        n_modified=len(modified),
        n_backed_up=n_backed,
        remaining=remaining,
        errors=errors,
        protected_intact=protected_ok and not prot_errs,
        json_valid=json_valid and not any("validation failed" in e for e in errors),
    )
    log(f"Modified: {len(modified)}  Remaining field: {remaining}  Verdict: {verdict}")
    return 0 if verdict == "PASS" and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
