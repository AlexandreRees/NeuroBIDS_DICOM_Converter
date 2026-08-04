#!/usr/bin/env python3
"""Reproducible BIDS public release builder (OpenNeuro / Scientific Data).

Creates a SEPARATE release candidate under release_dataset/.
Never modifies bids/, derivatives/, or raw_original/.

Anatomical NIfTIs (*_T1w / *_T2w / *_FLAIR) are excluded from the copied
tree and replaced by validated defaced files from derivatives/defacing,
keeping standard BIDS filenames (not *_desc-defaced_*).

Examples:
  python code/build_release.py --dry-run
  python code/build_release.py --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_BIDS = Path("/home/alexrees/scratch/bids")
DEFAULT_DEFACING = Path("/home/alexrees/scratch/derivatives/defacing")
DEFAULT_RELEASE = Path("/home/alexrees/scratch/release_dataset")
DEFAULT_REPORTS = Path("/home/alexrees/scratch/reports/openneuro_release")

STRUCTURAL_SUFFIXES = ("T1w", "T2w", "FLAIR")

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
    "derivatives",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a public BIDS release with defaced anatomicals "
            "(never modifies source bids/)."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan copy/replacements and write reports; do not create release_dataset.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Copy BIDS to release_dataset and replace anatomicals with defaced files.",
    )
    parser.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    parser.add_argument("--defacing-dir", type=Path, default=DEFAULT_DEFACING)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    return parser.parse_args()


def write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def is_structural_nifti(name: str) -> bool:
    return any(name.endswith(f"_{suffix}.nii.gz") for suffix in STRUCTURAL_SUFFIXES)


def relative_from_subject(path: Path) -> Path:
    parts = path.parts
    index = next(i for i, part in enumerate(parts) if part.startswith("sub-"))
    return Path(*parts[index:])


def parse_entities(rel: Path | str) -> tuple[str, str]:
    parts = Path(rel).parts
    subject = next((p for p in parts if p.startswith("sub-")), "unknown")
    session = next((p for p in parts if p.startswith("ses-")), "n/a")
    return subject, session


def ignore_for_copy(dir_path: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name.startswith("."):
            # keep .bidsignore
            if name != ".bidsignore":
                ignored.add(name)
            continue
        if name in IGNORE_DIR_NAMES:
            ignored.add(name)
            continue
        lower = name.lower()
        if "backup" in lower or lower.endswith(".bak"):
            ignored.add(name)
            continue
        # Exclude original structural anatomicals from the release copy.
        if is_structural_nifti(name):
            ignored.add(name)
    return ignored


def discover_defaced_map(defacing_dir: Path) -> dict[str, Path]:
    """Map subject-relative BIDS anat path -> defaced NIfTI."""
    mapping: dict[str, Path] = {}
    if not defacing_dir.is_dir():
        return mapping
    for path in sorted(defacing_dir.rglob("*.nii.gz")):
        if "anat" not in path.parts:
            continue
        name = path.name
        key_name = name
        if "_desc-defaced_" in name:
            key_name = name.replace("_desc-defaced_", "_")
        if not is_structural_nifti(key_name):
            continue
        try:
            rel = relative_from_subject(path)
        except StopIteration:
            continue
        rel_key = str(Path(*rel.parts[:-1]) / key_name)
        mapping[rel_key] = path
        mapping[str(rel)] = path
    return mapping


def iter_source_structural(bids_dir: Path) -> list[Path]:
    found: list[Path] = []
    for suffix in STRUCTURAL_SUFFIXES:
        for path in sorted(bids_dir.rglob(f"*_{suffix}.nii.gz")):
            if "anat" not in path.parts:
                continue
            if "derivatives" in path.parts:
                continue
            found.append(path)
    return found


def plan_anatomical_replacements(
    bids_dir: Path, defacing_dir: Path
) -> list[dict[str, str]]:
    defaced = discover_defaced_map(defacing_dir)
    rows: list[dict[str, str]] = []
    for original in iter_source_structural(bids_dir):
        rel = str(relative_from_subject(original))
        subject, session = parse_entities(rel)
        replacement = defaced.get(rel)
        if replacement is None:
            status = "MISSING_DEFACED"
            replacement_file = ""
        else:
            status = "READY"
            replacement_file = str(replacement)
        rows.append(
            {
                "subject": subject,
                "session": session,
                "modality": next(
                    s for s in STRUCTURAL_SUFFIXES if original.name.endswith(f"_{s}.nii.gz")
                ),
                "original_file": str(original),
                "replacement_file": replacement_file,
                "release_relative_path": rel,
                "status": status,
            }
        )
    return rows


def build_copy_manifest(bids_dir: Path, *, include_bytes: bool = False) -> list[dict[str, str]]:
    """Enumerate files that would be copied into the release (post-ignore).

    Uses a single `find` pass for speed on large Lustre trees. Byte sizes are
    optional (expensive); dry-run defaults to omitting them.
    """
    rows: list[dict[str, str]] = []
    # Find all files once; classify in Python.
    proc = subprocess.run(
        ["find", str(bids_dir), "-type", "f", "-print"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"find failed: {proc.stderr[:500]}")

    skip_parts = IGNORE_DIR_NAMES | {".git"}
    for line in proc.stdout.splitlines():
        if not line:
            continue
        src = Path(line)
        try:
            rel = src.relative_to(bids_dir)
        except ValueError:
            continue
        parts = set(rel.parts)
        if parts & skip_parts:
            continue
        # Hidden files/dirs except root .bidsignore
        if any(part.startswith(".") and part != ".bidsignore" for part in rel.parts):
            continue
        name = src.name
        if is_structural_nifti(name) and "anat" in rel.parts:
            action = "EXCLUDE_ORIGINAL_ANAT"
        else:
            action = "COPY"
        subject, session = parse_entities(rel)
        size = ""
        if include_bytes:
            try:
                size = str(src.stat().st_size)
            except OSError:
                size = "0"
        rows.append(
            {
                "subject": subject,
                "session": session,
                "source_path": str(src),
                "release_relative_path": str(rel),
                "action": action,
                "bytes": size,
            }
        )
    rows.sort(key=lambda r: r["release_relative_path"])
    return rows

def copy_bids_tree(bids_dir: Path, release_dir: Path) -> None:
    if release_dir.exists():
        raise RuntimeError(
            f"Release directory already exists: {release_dir}. "
            "Remove or rename it before --apply (source bids/ will not be touched)."
        )
    shutil.copytree(bids_dir, release_dir, ignore=ignore_for_copy, symlinks=False)


def apply_replacements(
    rows: list[dict[str, str]], release_dir: Path
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        updated = dict(row)
        if row["status"] == "MISSING_DEFACED":
            updated["status"] = "FAIL_MISSING_DEFACED"
            out.append(updated)
            continue
        src = Path(row["replacement_file"])
        dest = release_dir / row["release_relative_path"]
        if not src.is_file():
            updated["status"] = "FAIL_REPLACEMENT_MISSING"
            out.append(updated)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        # Prefer defaced JSON if present; otherwise keep copied source JSON.
        src_json = Path(str(src).removesuffix(".nii.gz") + ".json")
        dest_json = Path(str(dest).removesuffix(".nii.gz") + ".json")
        if src_json.is_file():
            shutil.copy2(src_json, dest_json)
            updated["json_source"] = "defacing"
        elif dest_json.is_file():
            updated["json_source"] = "bids_copy"
        else:
            updated["json_source"] = "MISSING"
            updated["status"] = "FAIL_MISSING_JSON"
            out.append(updated)
            continue
        updated["status"] = "REPLACED"
        out.append(updated)
    return out


def validate_release(
    release_dir: Path,
    replacement_rows: list[dict[str, str]],
    bids_dir: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "no_nondefaced_anatomicals": True,
        "all_expected_defaced_present": True,
        "nifti_json_pairs_ok": True,
        "json_validity": True,
        "participants_ok": True,
        "bids_validator": "NOT_RUN",
        "warnings": [],
        "failures": [],
    }

    # 1) No original non-defaced anatomicals should remain as the only copy —
    #    every structural NIfTI in release must have been replaced (status REPLACED)
    #    and exist on disk.
    remaining_struct = []
    for suffix in STRUCTURAL_SUFFIXES:
        remaining_struct.extend(release_dir.rglob(f"*_{suffix}.nii.gz"))
    remaining_struct = [p for p in remaining_struct if "anat" in p.parts]

    expected_rel = {
        r["release_relative_path"]
        for r in replacement_rows
        if r["status"] in {"REPLACED", "READY"}
    }
    present_rel = {str(relative_from_subject(p)) for p in remaining_struct}

    missing_on_disk = sorted(expected_rel - present_rel)
    unexpected = sorted(present_rel - expected_rel)
    if missing_on_disk:
        result["all_expected_defaced_present"] = False
        result["failures"].append(
            f"{len(missing_on_disk)} expected defaced anatomicals missing in release"
        )
    if unexpected:
        result["warnings"].append(
            f"{len(unexpected)} unexpected structural NIfTIs in release"
        )

    fail_missing = [r for r in replacement_rows if "MISSING" in r["status"] or r["status"].startswith("FAIL")]
    if fail_missing:
        result["all_expected_defaced_present"] = False
        result["failures"].append(
            f"{len(fail_missing)} anatomical replacements failed or missing"
        )

    # 2) NIfTI/JSON pairs for anatomicals
    for path in remaining_struct:
        sidecar = Path(str(path).removesuffix(".nii.gz") + ".json")
        if not sidecar.is_file():
            result["nifti_json_pairs_ok"] = False
            result["failures"].append(f"Missing JSON for {path.relative_to(release_dir)}")

    # 3) JSON validity (sample all release JSON)
    json_errors = 0
    for path in release_dir.rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            json_errors += 1
            result["failures"].append(f"Invalid JSON {path.relative_to(release_dir)}: {exc}")
    if json_errors:
        result["json_validity"] = False

    # 4) participants.tsv
    participants = release_dir / "participants.tsv"
    if not participants.is_file():
        result["participants_ok"] = False
        result["failures"].append("participants.tsv missing")
    else:
        with participants.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            cols = reader.fieldnames or []
            if "participant_id" not in cols:
                result["participants_ok"] = False
                result["failures"].append("participants.tsv lacks participant_id")
            n_rows = sum(1 for _ in reader)
            if n_rows == 0:
                result["participants_ok"] = False
                result["failures"].append("participants.tsv has no rows")

    # 5) Required root files
    for required in ("dataset_description.json", "participants.tsv"):
        if not (release_dir / required).is_file():
            result["failures"].append(f"Missing root file: {required}")
    if not (release_dir / "README").is_file() and not (release_dir / "README.md").is_file():
        result["warnings"].append("No README / README.md in release root")

    # 6) Optional bids-validator
    validator = shutil.which("bids-validator")
    if validator:
        try:
            proc = subprocess.run(
                [validator, str(release_dir), "--json"],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            result["bids_validator"] = (
                "PASS" if proc.returncode == 0 else f"FAIL(exit={proc.returncode})"
            )
            if proc.returncode != 0:
                result["warnings"].append(
                    "bids-validator reported issues (see validator stdout/stderr in logs)"
                )
                (release_dir.parent / "reports" / "openneuro_release").mkdir(
                    parents=True, exist_ok=True
                )
        except Exception as exc:  # noqa: BLE001
            result["bids_validator"] = f"ERROR: {exc}"
            result["warnings"].append(str(exc))
    else:
        # Try npx as a soft check
        npx = shutil.which("npx")
        if npx:
            try:
                proc = subprocess.run(
                    ["npx", "--yes", "bids-validator@1.14.10", str(release_dir), "--json"],
                    capture_output=True,
                    text=True,
                    timeout=900,
                    check=False,
                )
                result["bids_validator"] = (
                    "PASS" if proc.returncode == 0 else f"WARN/FAIL(exit={proc.returncode})"
                )
                if proc.returncode != 0:
                    result["warnings"].append(
                        "npx bids-validator returned non-zero "
                        "(compatibility check; review before upload)"
                    )
            except Exception as exc:  # noqa: BLE001
                result["bids_validator"] = f"NOT_AVAILABLE ({exc})"
                result["warnings"].append(
                    "bids-validator not executed; install bids-validator for full check"
                )
        else:
            result["bids_validator"] = "NOT_AVAILABLE"
            result["warnings"].append(
                "bids-validator not found on PATH; structural/manual checks only"
            )

    # 7) Confirm source trees untouched (mtime sanity: paths still exist)
    if not bids_dir.is_dir():
        result["failures"].append("Source bids/ missing after build")
    result["no_nondefaced_anatomicals"] = (
        result["all_expected_defaced_present"] and not fail_missing
    )
    return result


def count_modalities(root: Path) -> dict[str, int]:
    counts = {
        "func_bold_nii": len(list(root.glob("sub-*/ses-*/func/*_bold.nii.gz"))),
        "func_events": len(list(root.glob("sub-*/ses-*/func/*_events.tsv"))),
        "dwi_nii": len(list(root.glob("sub-*/ses-*/dwi/*_dwi.nii.gz"))),
        "fmap_nii": len(list(root.glob("sub-*/ses-*/fmap/*.nii.gz"))),
        "anat_t1w": len(list(root.glob("sub-*/ses-*/anat/*_T1w.nii.gz"))),
        "anat_t2w": len(list(root.glob("sub-*/ses-*/anat/*_T2w.nii.gz"))),
        "anat_flair": len(list(root.glob("sub-*/ses-*/anat/*_FLAIR.nii.gz"))),
    }
    return counts


def dataset_size_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return total


def write_release_report(
    path: Path,
    *,
    mode: str,
    bids_dir: Path,
    defacing_dir: Path,
    release_dir: Path,
    n_subjects: int,
    n_sessions: int,
    replacement_rows: list[dict[str, str]],
    manifest_rows: list[dict[str, str]],
    modality_counts: dict[str, int],
    validation: dict[str, Any] | None,
    release_bytes: int | None,
) -> None:
    n_ready = sum(1 for r in replacement_rows if r["status"] in {"READY", "REPLACED"})
    n_missing = sum(
        1 for r in replacement_rows if "MISSING" in r["status"] or r["status"].startswith("FAIL")
    )
    by_mod = Counter(r["modality"] for r in replacement_rows)
    by_status = Counter(r["status"] for r in replacement_rows)
    n_copy = sum(1 for r in manifest_rows if r["action"] == "COPY")
    n_excl = sum(1 for r in manifest_rows if r["action"] == "EXCLUDE_ORIGINAL_ANAT")

    lines = [
        "# Public BIDS release build report",
        "",
        f"**Generated (UTC):** {utc_now()}",
        f"**Mode:** `{mode}`",
        "",
        "## Paths",
        "",
        f"- Source BIDS (never modified): `{bids_dir}`",
        f"- Defacing derivatives (never modified): `{defacing_dir}`",
        f"- Release output: `{release_dir}`"
        + (" *(not created in dry-run)*" if mode == "DRY_RUN" else ""),
        "",
        "## Dataset summary",
        "",
        f"| Metric | Value |",
        f"|---|---:|",
        f"| Subjects | {n_subjects} |",
        f"| Sessions | {n_sessions} |",
        f"| Files planned to copy | {n_copy} |",
        f"| Original anatomicals excluded | {n_excl} |",
        f"| Anatomical replacements ready/applied | {n_ready} |",
        f"| Anatomical replacements missing/failed | {n_missing} |",
    ]
    if release_bytes is not None:
        lines.append(f"| Release dataset size | {release_bytes / 1e9:.2f} GB |")
    lines.extend(
        [
            f"| Functional BOLD NIfTI | {modality_counts.get('func_bold_nii', 0)} |",
            f"| Functional events.tsv | {modality_counts.get('func_events', 0)} |",
            f"| DWI NIfTI | {modality_counts.get('dwi_nii', 0)} |",
            f"| Fieldmap NIfTI | {modality_counts.get('fmap_nii', 0)} |",
            f"| Anat T1w (source inventory) | {by_mod.get('T1w', 0)} |",
            f"| Anat T2w (source inventory) | {by_mod.get('T2w', 0)} |",
            f"| Anat FLAIR (source inventory) | {by_mod.get('FLAIR', 0)} |",
            "",
            "## Anatomical replacement status",
            "",
            "| Status | N |",
            "|---|---:|",
        ]
    )
    for status, count in sorted(by_status.items()):
        lines.append(f"| `{status}` | {count} |")

    lines.extend(["", "## Validation", ""])
    if validation is None:
        lines.append("Dry-run: full release-tree validation deferred until `--apply`.")
        lines.append("")
        lines.append("Pre-flight checks:")
        lines.append(f"- All source anatomicals have defaced counterparts: **{n_missing == 0}**")
        lines.append(
            f"- participants.tsv present in source: "
            f"**{(bids_dir / 'participants.tsv').is_file()}**"
        )
        lines.append(
            f"- dataset_description.json present: "
            f"**{(bids_dir / 'dataset_description.json').is_file()}**"
        )
    else:
        lines.append("| Check | Result |")
        lines.append("|---|---|")
        lines.append(
            f"| No failed anatomical replacements | "
            f"{'PASS' if validation['all_expected_defaced_present'] else 'FAIL'} |"
        )
        lines.append(
            f"| NIfTI/JSON pairs for anatomicals | "
            f"{'PASS' if validation['nifti_json_pairs_ok'] else 'FAIL'} |"
        )
        lines.append(
            f"| JSON validity | {'PASS' if validation['json_validity'] else 'FAIL'} |"
        )
        lines.append(
            f"| participants.tsv | {'PASS' if validation['participants_ok'] else 'FAIL'} |"
        )
        lines.append(f"| BIDS validator | {validation['bids_validator']} |")
        lines.extend(["", "### Failures", ""])
        if validation["failures"]:
            for item in validation["failures"]:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines.extend(["", "### Warnings", ""])
        if validation["warnings"]:
            for item in validation["warnings"]:
                lines.append(f"- {item}")
        else:
            lines.append("- None")

    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- `bids/` was not modified.",
            "- `derivatives/` was not modified.",
            "- `raw_original/` was not modified.",
            "",
            "## Deliverables",
            "",
            "| File | Description |",
            "|---|---|",
            "| `ANATOMICAL_REPLACEMENT_AUDIT.tsv` | Per-anatomical original → defaced mapping |",
            "| `FILE_COPY_MANIFEST.tsv` | Copy / exclude plan |",
            "| `RELEASE_BUILD_REPORT.md` | This report |",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    # Hard safety: refuse to write into protected trees
    protected = {
        bids_dir.resolve(),
        defacing_dir.resolve(),
        Path("/home/alexrees/scratch/derivatives").resolve(),
    }
    for candidate in (
        Path("/home/alexrees/scratch/raw_original"),
        Path("/project/def-amirs/raw_original"),
    ):
        if candidate.exists():
            protected.add(candidate.resolve())
    if release_dir.resolve() in protected:
        log(f"ERROR: refuse to use protected path as release_dir: {release_dir}")
        return 1
    if not bids_dir.is_dir():
        log(f"ERROR: BIDS dir missing: {bids_dir}")
        return 1
    if not defacing_dir.is_dir():
        log(f"ERROR: defacing dir missing: {defacing_dir}")
        return 1

    subjects = sorted(
        p.name for p in bids_dir.iterdir() if p.is_dir() and p.name.startswith("sub-")
    )
    sessions = {
        (sub, ses.name)
        for sub in subjects
        for ses in (bids_dir / sub).iterdir()
        if ses.is_dir() and ses.name.startswith("ses-")
    }
    modality_counts = count_modalities(bids_dir)

    log("Planning anatomical replacements…")
    replacement_rows = plan_anatomical_replacements(bids_dir, defacing_dir)
    n_ready = sum(1 for r in replacement_rows if r["status"] == "READY")
    n_missing = sum(1 for r in replacement_rows if r["status"] == "MISSING_DEFACED")
    log(f"  Anatomicals: {len(replacement_rows)}  ready={n_ready}  missing={n_missing}")

    log("Building file copy manifest…")
    manifest_rows = build_copy_manifest(bids_dir, include_bytes=False)
    n_copy = sum(1 for r in manifest_rows if r["action"] == "COPY")
    n_excl = sum(1 for r in manifest_rows if r["action"] == "EXCLUDE_ORIGINAL_ANAT")
    log(f"  Manifest: copy={n_copy} exclude_anat={n_excl}")

    # Always write planning audits (dry-run and apply)
    audit_rows = [
        {
            "subject": r["subject"],
            "session": r["session"],
            "original_file": r["original_file"],
            "replacement_file": r["replacement_file"],
            "status": ("WOULD_REPLACE" if dry_run and r["status"] == "READY" else r["status"]),
        }
        for r in replacement_rows
    ]
    write_tsv(
        reports_dir / "ANATOMICAL_REPLACEMENT_AUDIT.tsv",
        audit_rows,
        ["subject", "session", "original_file", "replacement_file", "status"],
    )
    write_tsv(
        reports_dir / "FILE_COPY_MANIFEST.tsv",
        manifest_rows,
        [
            "subject",
            "session",
            "source_path",
            "release_relative_path",
            "action",
            "bytes",
        ],
    )

    validation: dict[str, Any] | None = None
    release_bytes: int | None = None
    applied_rows = replacement_rows

    if dry_run:
        write_release_report(
            reports_dir / "RELEASE_BUILD_REPORT.md",
            mode=mode,
            bids_dir=bids_dir,
            defacing_dir=defacing_dir,
            release_dir=release_dir,
            n_subjects=len(subjects),
            n_sessions=len(sessions),
            replacement_rows=replacement_rows,
            manifest_rows=manifest_rows,
            modality_counts=modality_counts,
            validation=None,
            release_bytes=None,
        )
        log("")
        log("DRY-RUN complete — no release_dataset created; source trees untouched.")
        log(f"  Would copy {n_copy} files to {release_dir}")
        log(f"  Would exclude {n_excl} original anatomical NIfTIs")
        log(f"  Would replace {n_ready} anatomicals with defaced derivatives")
        if n_missing:
            log(f"  WARNING: {n_missing} anatomicals lack defaced counterparts")
        log("")
        log("Re-run with --apply after confirmation to build the release.")
        log("")
        log("PUBLIC RELEASE BUILD COMPLETE")
        log("")
        log(f"Subjects: {len(subjects)}")
        log(f"Sessions: {len(sessions)}")
        log(f"Defaced anatomical replacements: {n_ready} planned ({n_missing} missing)")
        log("BIDS validation: NOT_RUN (dry-run)")
        log(f"Warnings: {n_missing} missing defaced anatomicals" if n_missing else "Warnings: none")
        return 0 if n_missing == 0 else 1

    # ----------------- APPLY -----------------
    if n_missing:
        log(
            f"ERROR: refusing --apply while {n_missing} anatomicals lack defaced "
            "counterparts. Fix coverage or re-run after updating derivatives/defacing."
        )
        write_release_report(
            reports_dir / "RELEASE_BUILD_REPORT.md",
            mode=mode,
            bids_dir=bids_dir,
            defacing_dir=defacing_dir,
            release_dir=release_dir,
            n_subjects=len(subjects),
            n_sessions=len(sessions),
            replacement_rows=replacement_rows,
            manifest_rows=manifest_rows,
            modality_counts=modality_counts,
            validation={
                "all_expected_defaced_present": False,
                "nifti_json_pairs_ok": False,
                "json_validity": True,
                "participants_ok": True,
                "bids_validator": "NOT_RUN",
                "warnings": [],
                "failures": [f"{n_missing} missing defaced anatomicals"],
            },
            release_bytes=None,
        )
        log("")
        log("PUBLIC RELEASE BUILD COMPLETE")
        log("")
        log(f"Subjects: {len(subjects)}")
        log(f"Sessions: {len(sessions)}")
        log(f"Defaced anatomical replacements: 0 (aborted)")
        log("BIDS validation: FAIL (missing defaced sources)")
        log(f"Warnings: {n_missing} missing defaced anatomicals")
        return 1

    log("Copying BIDS tree into release_dataset (excluding original anatomicals)…")
    try:
        copy_bids_tree(bids_dir, release_dir)
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR during copy: {exc}")
        return 1
    log("Copy complete.")

    log("Installing defaced anatomicals under standard BIDS names…")
    applied_rows = apply_replacements(replacement_rows, release_dir)
    write_tsv(
        reports_dir / "ANATOMICAL_REPLACEMENT_AUDIT.tsv",
        [
            {
                "subject": r["subject"],
                "session": r["session"],
                "original_file": r["original_file"],
                "replacement_file": r["replacement_file"],
                "status": r["status"],
            }
            for r in applied_rows
        ],
        ["subject", "session", "original_file", "replacement_file", "status"],
    )
    n_replaced = sum(1 for r in applied_rows if r["status"] == "REPLACED")
    log(f"  Replaced: {n_replaced}")

    log("Running validation checks…")
    validation = validate_release(release_dir, applied_rows, bids_dir)
    release_bytes = dataset_size_bytes(release_dir)
    release_modality = count_modalities(release_dir)

    write_release_report(
        reports_dir / "RELEASE_BUILD_REPORT.md",
        mode=mode,
        bids_dir=bids_dir,
        defacing_dir=defacing_dir,
        release_dir=release_dir,
        n_subjects=len(subjects),
        n_sessions=len(sessions),
        replacement_rows=applied_rows,
        manifest_rows=manifest_rows,
        modality_counts=release_modality,
        validation=validation,
        release_bytes=release_bytes,
    )

    n_warn = len(validation.get("warnings", []))
    n_fail = len(validation.get("failures", []))
    bids_status = validation.get("bids_validator", "NOT_RUN")
    overall = "PASS" if n_fail == 0 else "FAIL"

    log("")
    log("PUBLIC RELEASE BUILD COMPLETE")
    log("")
    log(f"Subjects: {len(subjects)}")
    log(f"Sessions: {len(sessions)}")
    log(f"Defaced anatomical replacements: {n_replaced}")
    log(f"BIDS validation: {bids_status} (overall checks: {overall})")
    log(
        f"Warnings: {n_warn}"
        + (f" — {'; '.join(validation['warnings'][:3])}" if validation["warnings"] else "")
    )
    if validation["failures"]:
        log("Failures:")
        for item in validation["failures"][:10]:
            log(f"  - {item}")
    log(f"Release path: {release_dir}")
    log(f"Reports: {reports_dir}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
