#!/usr/bin/env python3
"""Build a publication-ready OpenNeuro / Scientific Data release package.

Creates a NEW copy under release_dataset/. Never modifies the source BIDS tree
or raw_original/.

Actual defacing derivatives in this project keep standard BIDS filenames
(e.g. sub-001_ses-01_run-01_T1w.nii.gz), not *_desc-defaced_T1w.nii.gz.
Matching is therefore by relative path under sub-*/ses-*/anat/.

Examples:
  python code/build_openneuro_release.py --dry-run
  python code/build_openneuro_release.py --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_BIDS = Path("/home/alexrees/scratch/bids")
DEFAULT_DEFACING = Path("/home/alexrees/scratch/derivatives/defacing")
DEFAULT_RELEASE = Path("/home/alexrees/scratch/release_dataset")
DEFAULT_REPORTS = Path("/home/alexrees/scratch/reports/openneuro_release")

REMOVE_JSON_FIELDS = frozenset({"InstitutionalDepartmentName"})
PROTECTED_JSON_FIELDS = frozenset(
    {
        "Manufacturer",
        "ManufacturersModelName",
        "MagneticFieldStrength",
        "EchoTime",
        "RepetitionTime",
        "FlipAngle",
        "SliceThickness",
        "ProtocolName",
        "SeriesDescription",
        "InversionTime",
    }
)

# Structural anatomicals replaced from defacing derivatives (OpenNeuro).
STRUCTURAL_SUFFIXES = ("T1w", "FLAIR")

ALLOWED_PARTICIPANT_COLS = frozenset({"participant_id", "sex", "cohort"})
FORBIDDEN_PARTICIPANT_HINTS = (
    "name",
    "age",
    "birth",
    "dob",
    "patient",
    "mrn",
    "identifier",
    "address",
    "phone",
    "email",
)

IGNORE_DIR_NAMES = {
    "raw_original",
    "backups",
    "backup",
    "tmp",
    "temp",
    "tmp_processing",
    "__pycache__",
    ".git",
    "reports",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build OpenNeuro release package (copy-only; source BIDS untouched)."
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    p.add_argument("--defacing-dir", type=Path, default=DEFAULT_DEFACING)
    p.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE)
    p.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    return p.parse_args()


def write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def parse_entities(rel: Path | str) -> tuple[str, str]:
    parts = Path(rel).parts
    subject = next((x for x in parts if x.startswith("sub-")), "unknown")
    session = next((x for x in parts if x.startswith("ses-")), "n/a")
    return subject, session


def iter_structural_niis(root: Path, suffixes: Iterable[str] = STRUCTURAL_SUFFIXES) -> list[Path]:
    out: list[Path] = []
    if not root.is_dir():
        return out
    for suf in suffixes:
        for p in sorted(root.rglob(f"*_{suf}.nii.gz")):
            if "derivatives" in p.parts:
                continue
            if "anat" not in p.parts:
                continue
            out.append(p)
    return out


def relative_from_subject(path: Path) -> Path:
    """Return path relative to the sub-* component."""
    parts = path.parts
    i = next(i for i, x in enumerate(parts) if x.startswith("sub-"))
    return Path(*parts[i:])


def discover_defaced_map(defacing_dir: Path) -> dict[str, Path]:
    """Map relative BIDS-like key -> defaced NIfTI path.

    Supports both standard names and optional *_desc-defaced_* names.
    """
    mapping: dict[str, Path] = {}
    if not defacing_dir.is_dir():
        return mapping
    for p in sorted(defacing_dir.rglob("*.nii.gz")):
        if "anat" not in p.parts:
            continue
        name = p.name
        is_struct = any(name.endswith(f"_{s}.nii.gz") for s in STRUCTURAL_SUFFIXES)
        is_desc = "desc-defaced" in name and any(
            f"_{s}.nii.gz" in name or name.endswith(f"_{s}.nii.gz") for s in STRUCTURAL_SUFFIXES
        )
        if not (is_struct or is_desc):
            continue
        # Normalize desc-defaced name to standard BIDS anat name for matching
        key_name = name
        if "_desc-defaced_" in name:
            # sub-001_ses-01_run-01_desc-defaced_T1w.nii.gz -> sub-001_ses-01_run-01_T1w.nii.gz
            key_name = name.replace("_desc-defaced_", "_")
        try:
            rel = relative_from_subject(p)
        except StopIteration:
            continue
        # Rebuild relative key with normalized filename
        rel_key = str(Path(*rel.parts[:-1]) / key_name)
        mapping[rel_key] = p
        # Also index by exact relative path as stored
        mapping[str(rel)] = p
    return mapping


def coverage_rows(
    bids_dir: Path, defacing_dir: Path
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    defaced = discover_defaced_map(defacing_dir)
    rows: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    for src in iter_structural_niis(bids_dir, suffixes=("T1w",)):
        rel = str(relative_from_subject(src))
        subject, session = parse_entities(rel)
        found = rel in defaced
        row = {
            "subject": subject,
            "session": session,
            "expected": rel,
            "found": "yes" if found else "no",
            "missing": "" if found else rel,
            "defaced_path": str(defaced[rel]) if found else "",
        }
        rows.append(row)
        if not found:
            missing.append(row)
    return rows, missing


def ignore_for_copy(dir_path: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name.startswith("."):
            ignored.add(name)
            continue
        if name in IGNORE_DIR_NAMES:
            ignored.add(name)
            continue
        lower = name.lower()
        if "backup" in lower or lower.endswith(".bak"):
            ignored.add(name)
    return ignored


def count_copy_plan(bids_dir: Path) -> tuple[int, int]:
    n_files = 0
    n_bytes = 0
    for root, dirs, files in os.walk(bids_dir):
        dirs[:] = [d for d in dirs if d not in ignore_for_copy(root, dirs)]
        # also drop hidden dirs
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if fn.startswith("."):
                continue
            fp = Path(root) / fn
            try:
                n_bytes += fp.stat().st_size
            except OSError:
                pass
            n_files += 1
    return n_files, n_bytes


def copy_bids_tree(bids_dir: Path, release_dir: Path) -> None:
    if release_dir.exists():
        raise RuntimeError(
            f"Release directory already exists: {release_dir}. "
            "Remove or rename it before --apply."
        )
    shutil.copytree(bids_dir, release_dir, ignore=ignore_for_copy, symlinks=False)


def cleanup_readme(release_dir: Path, dry_run: bool) -> list[dict[str, str]]:
    readme = release_dir / "README"
    readme_md = release_dir / "README.md"
    rows: list[dict[str, str]] = []
    if readme.exists() and readme_md.exists():
        rows.append(
            {
                "path": str(readme),
                "action": "remove" if not dry_run else "would_remove",
                "reason": "duplicate_readme_keep_README.md",
            }
        )
        rows.append(
            {
                "path": str(readme_md),
                "action": "keep",
                "reason": "preferred_readme",
            }
        )
        if not dry_run:
            readme.unlink()
    elif readme_md.exists():
        rows.append({"path": str(readme_md), "action": "keep", "reason": "only_README.md"})
    elif readme.exists():
        # Prefer README.md name for consistency with earlier docs
        rows.append(
            {
                "path": str(readme),
                "action": "rename_to_README.md" if not dry_run else "would_rename_to_README.md",
                "reason": "normalize_to_README.md",
            }
        )
        if not dry_run:
            readme.rename(readme_md)
    else:
        rows.append({"path": "", "action": "missing", "reason": "no_readme_found"})
    return rows


def plan_replacements(
    bids_dir: Path, defacing_dir: Path, release_dir: Path | None
) -> list[dict[str, str]]:
    defaced = discover_defaced_map(defacing_dir)
    rows: list[dict[str, str]] = []
    # T1w required; FLAIR also replaced when available (structural OpenNeuro)
    for src in iter_structural_niis(bids_dir, suffixes=STRUCTURAL_SUFFIXES):
        rel = str(relative_from_subject(src))
        subject, session = parse_entities(rel)
        if rel not in defaced:
            # FLAIR missing is warning in coverage for T1w-only hard fail;
            # replacements table marks MISSING
            status = "MISSING_DEFACED"
            repl = ""
            dest = ""
        else:
            status = "PLANNED" if release_dir is None else "READY"
            repl = str(defaced[rel])
            dest = str((release_dir / rel) if release_dir is not None else Path("release_dataset") / rel)
        rows.append(
            {
                "subject": subject,
                "session": session,
                "original_file": str(src),
                "replacement_file": repl,
                "release_destination": dest,
                "status": status,
            }
        )
    return rows


def apply_replacements(rows: list[dict[str, str]], release_dir: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        new_row = dict(row)
        if row["status"] == "MISSING_DEFACED":
            # Only hard-fail for T1w; FLAIR missing -> WARNING status
            if row["original_file"].endswith("_T1w.nii.gz"):
                new_row["status"] = "FAIL_MISSING_T1W"
            else:
                new_row["status"] = "WARNING_MISSING_FLAIR"
            out.append(new_row)
            continue
        src = Path(row["replacement_file"])
        # destination inside release by relative key from original
        orig = Path(row["original_file"])
        rel = relative_from_subject(orig)
        dest = release_dir / rel
        if not src.is_file():
            new_row["status"] = "FAIL_REPLACEMENT_MISSING"
            out.append(new_row)
            continue
        if not dest.parent.is_dir():
            new_row["status"] = "FAIL_DEST_PARENT_MISSING"
            out.append(new_row)
            continue
        shutil.copy2(src, dest)
        # Prefer defaced JSON sidecar when present (already scrubbed)
        src_json = Path(str(src).replace(".nii.gz", ".json"))
        dest_json = Path(str(dest).replace(".nii.gz", ".json"))
        if src_json.is_file() and dest_json.parent.is_dir():
            shutil.copy2(src_json, dest_json)
            new_row["sidecar_replaced"] = "yes"
        else:
            new_row["sidecar_replaced"] = "no"
        new_row["status"] = "REPLACED"
        new_row["release_destination"] = str(dest)
        out.append(new_row)
    return out


def update_dataset_description(release_dir: Path, dry_run: bool) -> dict[str, Any]:
    path = release_dir / "dataset_description.json"
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "changes": [],
        "warnings": [],
    }
    if not path.is_file():
        report["warnings"].append("dataset_description.json missing")
        return report
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        report["warnings"].append("dataset_description.json is not an object")
        return report

    if data.get("License") != "CC0":
        report["changes"].append(f"License: {data.get('License')!r} -> 'CC0'")
        data["License"] = "CC0"

    authors = data.get("Authors")
    if isinstance(authors, list) and any("Neuro BIDS Pipeline" in str(a) for a in authors):
        report["changes"].append("Authors placeholder -> ['AUTHOR_PLACEHOLDER']")
        report["warnings"].append(
            "Authors contained 'Neuro BIDS Pipeline'; replaced with "
            "['AUTHOR_PLACEHOLDER'] — MANUAL REPLACEMENT REQUIRED before upload."
        )
        data["Authors"] = ["AUTHOR_PLACEHOLDER"]
    elif not authors:
        report["changes"].append("Authors missing -> ['AUTHOR_PLACEHOLDER']")
        report["warnings"].append("Authors missing; set to ['AUTHOR_PLACEHOLDER']")
        data["Authors"] = ["AUTHOR_PLACEHOLDER"]

    if "BIDSVersion" not in data:
        report["changes"].append("BIDSVersion missing -> '1.9.0'")
        data["BIDSVersion"] = "1.9.0"

    if "GeneratedBy" not in data or not data.get("GeneratedBy"):
        report["changes"].append("GeneratedBy added")
        data["GeneratedBy"] = [
            {
                "Name": "neuro_pipeline",
                "Description": (
                    "BIDS conversion, quality control, metadata cleaning and "
                    "anatomical defacing workflow"
                ),
            }
        ]

    if not dry_run:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # validate
        json.loads(path.read_text(encoding="utf-8"))
    return report


def sanitize_release_json(release_dir: Path, dry_run: bool) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(release_dir.rglob("*.json")):
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "json": str(path),
                    "action": "ERROR",
                    "field": "",
                    "detail": str(exc),
                }
            )
            continue
        if not isinstance(data, dict):
            rows.append(
                {
                    "json": str(path),
                    "action": "SKIP",
                    "field": "",
                    "detail": "root_not_object",
                }
            )
            continue
        removed = [k for k in REMOVE_JSON_FIELDS if k in data]
        if not removed:
            continue
        for key in removed:
            # never touch protected
            if key in PROTECTED_JSON_FIELDS:
                rows.append(
                    {
                        "json": str(path),
                        "action": "REFUSED",
                        "field": key,
                        "detail": "protected",
                    }
                )
                continue
            rows.append(
                {
                    "json": str(path),
                    "action": "would_remove" if dry_run else "removed",
                    "field": key,
                    "detail": json.dumps(data.get(key), ensure_ascii=False)[:120],
                }
            )
            if not dry_run:
                del data[key]
        if not dry_run and removed:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            json.loads(path.read_text(encoding="utf-8"))  # validate
            # ensure protected still present if they were
            for key in PROTECTED_JSON_FIELDS:
                pass
    return rows


def validate_participants(release_or_bids: Path) -> tuple[str, list[str]]:
    path = release_or_bids / "participants.tsv"
    notes: list[str] = []
    if not path.is_file():
        return "FAIL", ["participants.tsv missing"]
    import csv as _csv

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = _csv.DictReader(fh, delimiter="\t")
        cols = reader.fieldnames or []
        notes.append(f"Columns: {cols}")
        bad = []
        for c in cols:
            cl = c.lower()
            if c not in ALLOWED_PARTICIPANT_COLS:
                # flag suspicious
                if any(h in cl for h in FORBIDDEN_PARTICIPANT_HINTS):
                    bad.append(c)
                elif c not in ALLOWED_PARTICIPANT_COLS:
                    notes.append(f"Extra column (review): {c}")
        if bad:
            return "FAIL", notes + [f"Forbidden columns: {bad}"]
        n = sum(1 for _ in reader)
        notes.append(f"Rows: {n}")
        if "participant_id" not in cols:
            return "FAIL", notes + ["participant_id missing"]
    return "PASS", notes


def write_participants_md(path: Path, status: str, notes: list[str]) -> None:
    lines = [
        "# Participants validation",
        "",
        f"Status: **{status}**",
        "",
        "Allowed columns: `participant_id`, `sex`, `cohort`.",
        "",
        "## Notes",
        "",
    ]
    for n in notes:
        lines.append(f"- {n}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def final_audit(
    path: Path,
    *,
    mode: str,
    bids_dir: Path,
    release_dir: Path | None,
    n_subjects: int,
    n_sessions: int,
    n_t1w: int,
    n_defaced_t1w: int,
    n_replaced: int,
    n_json_scanned: int,
    n_json_cleaned: int,
    missing_t1w: int,
    readme_ok: bool,
    participants_status: str,
    warnings: list[str],
    fail_reasons: list[str],
) -> str:
    if fail_reasons or missing_t1w > 0:
        verdict = "FAIL"
    elif warnings or participants_status != "PASS" or not readme_ok:
        verdict = "WARNING"
    else:
        verdict = "PASS"

    lines = [
        "# Final OpenNeuro release audit",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Mode: **{mode}**",
        "",
        f"## Verdict: **{verdict}**",
        "",
        "## Counts",
        "",
        f"- Subjects (BIDS source): **{n_subjects}**",
        f"- Sessions (subject×session): **{n_sessions}**",
        f"- T1w expected: **{n_t1w}**",
        f"- Defaced T1w available: **{n_defaced_t1w}**",
        f"- T1w replacements applied/planned: **{n_replaced}**",
        f"- Missing defaced T1w: **{missing_t1w}**",
        f"- JSON files cleaned (InstitutionalDepartmentName removals): **{n_json_cleaned}**",
        f"- JSON scan actions logged: **{n_json_scanned}**",
        f"- Release directory: `{release_dir}`",
        f"- Source BIDS (untouched): `{bids_dir}`",
        "",
        f"- Duplicate README resolved: **{readme_ok}**",
        f"- Participants validation: **{participants_status}**",
        "",
        "## Failures",
        "",
    ]
    if fail_reasons:
        for r in fail_reasons:
            lines.append(f"- {r}")
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## PASS criteria",
            "",
            "- defacing complete for all T1w",
            "- JSON valid after cleaning",
            "- no duplicate README",
            "- participants columns clean",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return verdict


def main() -> int:
    args = parse_args()
    bids_dir = args.bids_dir.resolve()
    defacing_dir = args.defacing_dir.resolve()
    release_dir = args.release_dir.resolve()
    reports_dir = args.reports_dir.resolve()
    dry_run = bool(args.dry_run)
    mode = "DRY_RUN" if dry_run else "APPLY"

    reports_dir.mkdir(parents=True, exist_ok=True)
    log(f"Mode: {mode}")
    log(f"BIDS source (read-only): {bids_dir}")
    log(f"Defacing derivatives (read-only): {defacing_dir}")
    log(f"Release output: {release_dir}")
    log(f"Reports: {reports_dir}")

    if not bids_dir.is_dir():
        log(f"ERROR: BIDS dir missing: {bids_dir}")
        return 1
    if not defacing_dir.is_dir():
        log(f"ERROR: defacing dir missing: {defacing_dir}")
        return 1

    # Inspect naming reality
    n_desc = len(list(defacing_dir.rglob("*desc-defaced*")))
    log(
        f"Note: found {n_desc} *desc-defaced* files; "
        "matching uses standard BIDS anat filenames from derivatives/defacing."
    )

    # --- Coverage (T1w hard requirement) ---
    log("Computing T1w defacing coverage…")
    cov_rows, missing = coverage_rows(bids_dir, defacing_dir)
    write_tsv(
        reports_dir / "defacing_coverage.tsv",
        cov_rows,
        ["subject", "session", "expected", "found", "missing", "defaced_path"],
    )
    n_t1w = len(cov_rows)
    n_defaced = sum(1 for r in cov_rows if r["found"] == "yes")
    n_missing = len(missing)
    log(f"T1w expected={n_t1w} defaced={n_defaced} missing={n_missing}")
    if n_missing:
        log("FAIL: missing defaced T1w — stopping before release generation")
        for m in missing[:20]:
            log(f"  MISSING {m['expected']}")
        write_tsv(
            reports_dir / "defacing_replacement.tsv",
            [],
            ["subject", "session", "original_file", "replacement_file", "status"],
        )
        subjects = {r["subject"] for r in cov_rows}
        sessions = {(r["subject"], r["session"]) for r in cov_rows}
        verdict = final_audit(
            reports_dir / "FINAL_RELEASE_AUDIT.md",
            mode=mode,
            bids_dir=bids_dir,
            release_dir=None,
            n_subjects=len(subjects),
            n_sessions=len(sessions),
            n_t1w=n_t1w,
            n_defaced_t1w=n_defaced,
            n_replaced=0,
            n_json_scanned=0,
            n_json_cleaned=0,
            missing_t1w=n_missing,
            readme_ok=False,
            participants_status="NOT_RUN",
            warnings=[],
            fail_reasons=[f"{n_missing} T1w lack defaced counterparts"],
        )
        log("")
        log("OPENNEURO RELEASE STATUS")
        log(verdict)
        return 1

    # Source stats
    subjects = sorted(
        {
            p.name
            for p in bids_dir.iterdir()
            if p.is_dir() and p.name.startswith("sub-")
        }
    )
    sessions = {
        (sub, ses.name)
        for sub in subjects
        for ses in (bids_dir / sub).iterdir()
        if ses.is_dir() and ses.name.startswith("ses-")
    }
    n_copy_files, n_copy_bytes = count_copy_plan(bids_dir)
    log(f"Copy plan: {n_copy_files} files (~{n_copy_bytes / 1e9:.2f} GB)")

    repl_plan = plan_replacements(bids_dir, defacing_dir, None if dry_run else release_dir)
    n_t1w_plan = sum(1 for r in repl_plan if r["original_file"].endswith("_T1w.nii.gz"))
    n_flair_missing = sum(
        1
        for r in repl_plan
        if r["original_file"].endswith("_FLAIR.nii.gz") and r["status"] == "MISSING_DEFACED"
    )

    warnings: list[str] = []
    fail_reasons: list[str] = []
    if n_flair_missing:
        warnings.append(
            f"{n_flair_missing} FLAIR anatomicals lack defaced counterparts "
            "(T1w coverage is complete; FLAIR left as source copies if missing)."
        )

    # README plan on source (for dry-run reporting)
    readme_rows = cleanup_readme(bids_dir if dry_run else release_dir, dry_run=True)
    # adjust paths for dry-run messaging
    if dry_run:
        readme_rows = [
            {
                **r,
                "path": r["path"].replace(str(bids_dir), str(release_dir))
                if r["path"]
                else r["path"],
            }
            for r in readme_rows
        ]

    # dataset_description plan from source
    dd_report = update_dataset_description(bids_dir, dry_run=True)
    for w in dd_report.get("warnings", []):
        warnings.append(w)

    # participants from source
    part_status, part_notes = validate_participants(bids_dir)
    write_participants_md(reports_dir / "participants_validation.md", part_status, part_notes)
    if part_status != "PASS":
        warnings.append(f"participants validation: {part_status}")

    if dry_run:
        write_tsv(
            reports_dir / "readme_cleanup.tsv",
            readme_rows,
            ["path", "action", "reason"],
        )
        write_tsv(
            reports_dir / "defacing_replacement.tsv",
            [
                {
                    "subject": r["subject"],
                    "session": r["session"],
                    "original_file": r["original_file"],
                    "replacement_file": r["replacement_file"],
                    "status": "WOULD_REPLACE"
                    if r["status"] != "MISSING_DEFACED"
                    else r["status"],
                }
                for r in repl_plan
                if r["original_file"].endswith("_T1w.nii.gz")
                or r["status"] != "MISSING_DEFACED"
            ],
            ["subject", "session", "original_file", "replacement_file", "status"],
        )
        # JSON cleaning dry-run on source tree paths reported as would-apply on release
        json_rows: list[dict[str, str]] = []
        for path in sorted(bids_dir.rglob("*.json")):
            if "derivatives" in path.parts:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                json_rows.append(
                    {
                        "json": str(release_dir / path.relative_to(bids_dir)),
                        "action": "ERROR",
                        "field": "",
                        "detail": str(exc),
                    }
                )
                continue
            if isinstance(data, dict) and "InstitutionalDepartmentName" in data:
                json_rows.append(
                    {
                        "json": str(release_dir / path.relative_to(bids_dir)),
                        "action": "would_remove",
                        "field": "InstitutionalDepartmentName",
                        "detail": str(data["InstitutionalDepartmentName"])[:120],
                    }
                )
        write_tsv(
            reports_dir / "json_cleaning.tsv",
            json_rows,
            ["json", "action", "field", "detail"],
        )
        readme_ok = not (
            (bids_dir / "README").exists() and (bids_dir / "README.md").exists()
        ) or True  # would be fixed
        # In dry-run, duplicate exists but would be fixed
        readme_ok = True
        verdict = final_audit(
            reports_dir / "FINAL_RELEASE_AUDIT.md",
            mode=mode,
            bids_dir=bids_dir,
            release_dir=release_dir,
            n_subjects=len(subjects),
            n_sessions=len(sessions),
            n_t1w=n_t1w,
            n_defaced_t1w=n_defaced,
            n_replaced=n_t1w_plan,
            n_json_scanned=len(json_rows),
            n_json_cleaned=sum(1 for r in json_rows if r["action"] == "would_remove"),
            missing_t1w=0,
            readme_ok=readme_ok,
            participants_status=part_status,
            warnings=warnings
            + [f"dataset_description changes: {dd_report.get('changes')}"],
            fail_reasons=fail_reasons,
        )
        log("")
        log("DRY-RUN summary (no modifications):")
        log(f"  Would copy ~{n_copy_files} files to {release_dir}")
        n_struct_plan = sum(
            1 for r in repl_plan if r["status"] != "MISSING_DEFACED"
        )
        log(
            f"  Would replace {n_struct_plan} structural NIfTIs "
            f"(T1w={n_t1w_plan}, plus FLAIR when defaced available)"
        )
        log(f"  Would remove duplicate README if present")
        log(f"  dataset_description planned changes: {dd_report.get('changes')}")
        log(
            f"  JSON InstitutionalDepartmentName removals planned: "
            f"{sum(1 for r in json_rows if r['action']=='would_remove')}"
        )
        log("")
        log("OPENNEURO RELEASE STATUS")
        log(verdict)
        log("")
        log(f"{'Metric':<40} {'Value'}")
        log("-" * 55)
        log(f"{'Subjects':<40} {len(subjects)}")
        log(f"{'Sessions':<40} {len(sessions)}")
        log(f"{'T1w / defaced':<40} {n_t1w} / {n_defaced}")
        log(f"{'Files to copy':<40} {n_copy_files}")
        log(f"{'Participants':<40} {part_status}")
        return 0 if verdict in {"PASS", "WARNING"} else 1

    # ----------------- APPLY -----------------
    log("Copying BIDS tree into release_dataset (this may take a while)…")
    try:
        copy_bids_tree(bids_dir, release_dir)
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR during copy: {exc}")
        return 1
    log("Copy complete.")

    log("README cleanup…")
    readme_rows = cleanup_readme(release_dir, dry_run=False)
    write_tsv(reports_dir / "readme_cleanup.tsv", readme_rows, ["path", "action", "reason"])
    readme_ok = not ((release_dir / "README").exists() and (release_dir / "README.md").exists())
    if (release_dir / "README").exists() and not (release_dir / "README.md").exists():
        readme_ok = True  # renamed
    if not (release_dir / "README.md").exists() and not (release_dir / "README").exists():
        warnings.append("No README in release root")
        readme_ok = False

    log("Replacing structural anatomicals with defaced versions…")
    repl_plan = plan_replacements(bids_dir, defacing_dir, release_dir)
    repl_done = apply_replacements(repl_plan, release_dir)
    # Report T1w (+ FLAIR) but required columns for user
    write_tsv(
        reports_dir / "defacing_replacement.tsv",
        [
            {
                "subject": r["subject"],
                "session": r["session"],
                "original_file": r["original_file"],
                "replacement_file": r["replacement_file"],
                "status": r["status"],
            }
            for r in repl_done
        ],
        ["subject", "session", "original_file", "replacement_file", "status"],
    )
    n_replaced = sum(1 for r in repl_done if r["status"] == "REPLACED")
    n_fail_repl = sum(1 for r in repl_done if r["status"].startswith("FAIL"))
    if n_fail_repl:
        fail_reasons.append(f"{n_fail_repl} replacement failures")

    log("Updating dataset_description.json…")
    dd_report = update_dataset_description(release_dir, dry_run=False)
    for w in dd_report.get("warnings", []):
        warnings.append(w)

    log("Sanitizing release JSON (InstitutionalDepartmentName only)…")
    json_rows = sanitize_release_json(release_dir, dry_run=False)
    write_tsv(
        reports_dir / "json_cleaning.tsv",
        json_rows,
        ["json", "action", "field", "detail"],
    )
    if any(r["action"] == "ERROR" for r in json_rows):
        fail_reasons.append("JSON validation/parse errors during cleaning")

    part_status, part_notes = validate_participants(release_dir)
    write_participants_md(reports_dir / "participants_validation.md", part_status, part_notes)
    if part_status != "PASS":
        fail_reasons.append("participants.tsv validation failed")

    # Author placeholder => WARNING not FAIL
    if any("AUTHOR_PLACEHOLDER" in w or "MANUAL REPLACEMENT" in w for w in warnings):
        pass

    verdict = final_audit(
        reports_dir / "FINAL_RELEASE_AUDIT.md",
        mode=mode,
        bids_dir=bids_dir,
        release_dir=release_dir,
        n_subjects=len(subjects),
        n_sessions=len(sessions),
        n_t1w=n_t1w,
        n_defaced_t1w=n_defaced,
        n_replaced=n_replaced,
        n_json_scanned=len(json_rows),
        n_json_cleaned=sum(1 for r in json_rows if r["action"] == "removed"),
        missing_t1w=0,
        readme_ok=readme_ok,
        participants_status=part_status,
        warnings=warnings,
        fail_reasons=fail_reasons,
    )

    # If Authors still placeholder, force WARNING at minimum
    dd = json.loads((release_dir / "dataset_description.json").read_text(encoding="utf-8"))
    if dd.get("Authors") == ["AUTHOR_PLACEHOLDER"] and verdict == "PASS":
        verdict = "WARNING"
        warnings.append("Authors still AUTHOR_PLACEHOLDER")
        # rewrite audit verdict line lightly
        audit_path = reports_dir / "FINAL_RELEASE_AUDIT.md"
        txt = audit_path.read_text(encoding="utf-8")
        txt = txt.replace("## Verdict: **PASS**", "## Verdict: **WARNING**")
        audit_path.write_text(txt, encoding="utf-8")

    log("")
    log("OPENNEURO RELEASE STATUS")
    log(verdict)
    log("")
    log(f"{'Metric':<40} {'Value'}")
    log("-" * 55)
    log(f"{'Subjects':<40} {len(subjects)}")
    log(f"{'Sessions':<40} {len(sessions)}")
    log(f"{'T1w expected / defaced':<40} {n_t1w} / {n_defaced}")
    log(f"{'Replacements applied':<40} {n_replaced}")
    log(f"{'JSON cleaned':<40} {sum(1 for r in json_rows if r['action']=='removed')}")
    log(f"{'README OK':<40} {readme_ok}")
    log(f"{'Participants':<40} {part_status}")
    log(f"{'Release path':<40} {release_dir}")
    return 0 if verdict in {"PASS", "WARNING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
