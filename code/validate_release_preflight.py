#!/usr/bin/env python3
"""Pre-flight validation before building the public BIDS release.

READ-ONLY by default. Never modifies bids/, derivatives/, or raw_original/.

Examples:
  python code/validate_release_preflight.py
  python code/validate_release_preflight.py --launch   # apply only if PASS
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd

ROOT = Path("/home/alexrees/scratch")
BIDS = ROOT / "bids"
DEFACING = ROOT / "derivatives" / "defacing"
RELEASE = ROOT / "release_dataset"
REPORTS = ROOT / "reports" / "openneuro_release"
BUILD_SCRIPT = ROOT / "code" / "build_release.py"
AUDIT_TSV = REPORTS / "ANATOMICAL_REPLACEMENT_AUDIT.tsv"
MANIFEST_TSV = REPORTS / "FILE_COPY_MANIFEST.tsv"

OK_STATUSES = {"OK", "READY", "WOULD_REPLACE", "REPLACED", "PLANNED"}
STRUCTURAL_SUFFIXES = ("T1w", "T2w", "FLAIR")
AFFINE_ATOL = 1e-5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("preflight")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-flight validation for build_release.py --apply (read-only)."
    )
    parser.add_argument(
        "--launch",
        action="store_true",
        help="If all checks PASS, execute build_release.py --apply.",
    )
    parser.add_argument("--bids-dir", type=Path, default=BIDS)
    parser.add_argument("--defacing-dir", type=Path, default=DEFACING)
    parser.add_argument("--release-dir", type=Path, default=RELEASE)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS)
    return parser.parse_args()


def modality_from_name(name: str) -> str:
    for suffix in STRUCTURAL_SUFFIXES:
        if name.endswith(f"_{suffix}.nii.gz"):
            return suffix
    return "unknown"


def release_dest_from_original(original: Path, bids_dir: Path) -> str:
    """Expected release-relative path = BIDS path relative to dataset root."""
    try:
        return str(original.resolve().relative_to(bids_dir.resolve()))
    except Exception:
        # Fallback: from sub-* component
        parts = original.parts
        try:
            idx = next(i for i, p in enumerate(parts) if p.startswith("sub-"))
            return str(Path(*parts[idx:]))
        except StopIteration:
            return ""


# ---------------------------------------------------------------------------
# CHECK 1 — Anatomical replacement audit
# ---------------------------------------------------------------------------
def check_anatomical_audit(
    audit_path: Path, bids_dir: Path, defacing_dir: Path
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "check": "anatomical_replacement_audit",
        "planned": 0,
        "successful": 0,
        "missing_replacements": 0,
        "missing_originals": 0,
        "duplicates": 0,
        "ambiguous": 0,
        "unmatched": 0,
    }

    if not audit_path.is_file():
        summary["error"] = f"Missing audit file: {audit_path}"
        return "FAIL", rows, summary

    df = pd.read_csv(audit_path, sep="\t", dtype=str).fillna("")
    required_cols = {"subject", "session", "original_file", "replacement_file", "status"}
    missing_cols = sorted(required_cols - set(df.columns))
    if missing_cols:
        summary["error"] = f"Audit missing columns: {missing_cols}"
        return "FAIL", rows, summary

    summary["planned"] = int(len(df))
    seen_targets: dict[str, int] = {}
    seen_originals: dict[str, int] = {}

    for _, row in df.iterrows():
        original = Path(str(row["original_file"]).strip())
        replacement = Path(str(row["replacement_file"]).strip())
        status_in = str(row["status"]).strip()
        dest = release_dest_from_original(original, bids_dir)
        issues: list[str] = []

        if not dest:
            issues.append("destination_undefined")
            summary["unmatched"] += 1
        else:
            seen_targets[dest] = seen_targets.get(dest, 0) + 1

        seen_originals[str(original)] = seen_originals.get(str(original), 0) + 1

        if not original.is_file():
            issues.append("original_missing")
            summary["missing_originals"] += 1
        if not str(row["replacement_file"]).strip():
            issues.append("replacement_path_empty")
            summary["missing_replacements"] += 1
        elif not replacement.is_file():
            issues.append("replacement_missing")
            summary["missing_replacements"] += 1
        if status_in and status_in not in OK_STATUSES and "MISSING" in status_in.upper():
            issues.append(f"audit_status={status_in}")

        ok = not issues
        if ok:
            summary["successful"] += 1
        out_status = "OK" if ok else "FAIL"
        rows.append(
            {
                "check": "anatomical_replacement_audit",
                "subject": row["subject"],
                "session": row["session"],
                "modality": modality_from_name(original.name),
                "original_file": str(original),
                "replacement_file": str(replacement) if str(row["replacement_file"]).strip() else "",
                "destination": dest,
                "audit_status": status_in,
                "status": out_status,
                "detail": ";".join(issues),
            }
        )

    # Duplicates: same destination or same original planned more than once
    dup_dests = {d for d, c in seen_targets.items() if c > 1}
    dup_origs = {o for o, c in seen_originals.items() if c > 1}
    summary["ambiguous"] = len(dup_dests) + len(dup_origs)
    for r in rows:
        extras: list[str] = []
        if r["destination"] in dup_dests:
            extras.append("duplicate_destination")
        if r["original_file"] in dup_origs:
            extras.append("duplicate_original")
        if extras:
            r["status"] = "FAIL"
            r["detail"] = ";".join([x for x in [r["detail"], *extras] if x])

    summary["duplicates"] = sum(1 for r in rows if "duplicate_" in r["detail"])
    summary["successful"] = sum(1 for r in rows if r["status"] == "OK")

    overall = "PASS" if all(r["status"] == "OK" for r in rows) and rows else "FAIL"
    if not rows:
        overall = "FAIL"
        summary["error"] = "Audit file is empty"
    return overall, rows, summary


# ---------------------------------------------------------------------------
# CHECK 2 — Anatomical image integrity
# ---------------------------------------------------------------------------
def _header_metrics(path: Path) -> dict[str, Any]:
    img = nib.load(str(path))
    zooms = tuple(float(z) for z in img.header.get_zooms())
    affine = np.asarray(img.affine, dtype=float)
    return {
        "shape": tuple(int(x) for x in img.shape),
        "zooms": zooms,
        "affine": affine,
        "axcodes": "".join(nib.aff2axcodes(affine)),
        "dtype": str(img.get_data_dtype()),
        "ndim": int(img.ndim),
    }


def check_anatomical_integrity(
    audit_path: Path, reports_dir: Path
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "check": "anatomical_integrity",
        "compared": 0,
        "pass": 0,
        "fail": 0,
        "skipped": 0,
    }

    if not audit_path.is_file():
        summary["error"] = f"Missing audit file: {audit_path}"
        return "FAIL", rows, summary

    df = pd.read_csv(audit_path, sep="\t", dtype=str).fillna("")
    for _, row in df.iterrows():
        original = Path(str(row["original_file"]).strip())
        replacement = Path(str(row["replacement_file"]).strip())
        subject = row.get("subject", "")
        session = row.get("session", "")
        modality = modality_from_name(original.name)
        record = {
            "participant": subject,
            "session": session,
            "modality": modality,
            "original_path": str(original),
            "defaced_path": str(replacement),
            "shape_match": "n/a",
            "voxel_match": "n/a",
            "affine_match": "n/a",
            "orientation_match": "n/a",
            "dtype_original": "",
            "dtype_defaced": "",
            "status": "FAIL",
            "detail": "",
        }

        if not original.is_file() or not replacement.is_file():
            record["detail"] = "missing_file"
            record["status"] = "FAIL"
            summary["fail"] += 1
            summary["skipped"] += 1
            rows.append(record)
            continue

        try:
            m0 = _header_metrics(original)
            m1 = _header_metrics(replacement)
        except Exception as exc:  # noqa: BLE001
            record["detail"] = f"nibabel_error:{exc}"
            record["status"] = "FAIL"
            summary["fail"] += 1
            rows.append(record)
            continue

        summary["compared"] += 1
        shape_ok = m0["shape"] == m1["shape"]
        voxel_ok = len(m0["zooms"]) == len(m1["zooms"]) and np.allclose(
            m0["zooms"], m1["zooms"], atol=AFFINE_ATOL, rtol=0
        )
        affine_ok = np.allclose(m0["affine"], m1["affine"], atol=AFFINE_ATOL, rtol=0)
        orient_ok = m0["axcodes"] == m1["axcodes"]

        record["shape_match"] = "yes" if shape_ok else "no"
        record["voxel_match"] = "yes" if voxel_ok else "no"
        record["affine_match"] = "yes" if affine_ok else "no"
        record["orientation_match"] = "yes" if orient_ok else "no"
        record["dtype_original"] = m0["dtype"]
        record["dtype_defaced"] = m1["dtype"]

        if shape_ok and voxel_ok and affine_ok:
            record["status"] = "OK"
            summary["pass"] += 1
            if not orient_ok:
                record["detail"] = "orientation_code_differs_but_affine_ok"
        else:
            record["status"] = "FAIL"
            summary["fail"] += 1
            bits = []
            if not shape_ok:
                bits.append(f"shape {m0['shape']}!={m1['shape']}")
            if not voxel_ok:
                bits.append(f"zooms {m0['zooms']}!={m1['zooms']}")
            if not affine_ok:
                bits.append("affine_mismatch")
            record["detail"] = ";".join(bits)

        rows.append(record)

    out = reports_dir / "ANATOMICAL_INTEGRITY_CHECK.tsv"
    pd.DataFrame(rows).to_csv(out, sep="\t", index=False)
    overall = "PASS" if summary["fail"] == 0 and summary["compared"] > 0 else "FAIL"
    if summary["compared"] == 0 and summary["fail"] == 0:
        overall = "FAIL"
        summary["error"] = "No anatomical pairs compared"
    return overall, rows, summary


# ---------------------------------------------------------------------------
# CHECK 3 — JSON sidecar consistency
# ---------------------------------------------------------------------------
def check_json_sidecars(
    audit_path: Path, bids_dir: Path, reports_dir: Path
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "check": "anatomical_json",
        "checked": 0,
        "ok": 0,
        "missing": 0,
        "invalid_name": 0,
    }

    if not audit_path.is_file():
        summary["error"] = f"Missing audit file: {audit_path}"
        return "FAIL", rows, summary

    df = pd.read_csv(audit_path, sep="\t", dtype=str).fillna("")
    for _, row in df.iterrows():
        original = Path(str(row["original_file"]).strip())
        json_path = Path(str(original).removesuffix(".nii.gz") + ".json")
        dest = release_dest_from_original(original, bids_dir)
        if dest.endswith(".nii.gz"):
            dest_json = dest[: -len(".nii.gz")] + ".json"
        else:
            dest_json = ""

        summary["checked"] += 1
        issues: list[str] = []
        if not json_path.is_file():
            issues.append("missing_json")
            summary["missing"] += 1
        # BIDS naming: same stem entities as NIfTI
        if original.name.count("_") < 1 or not any(
            original.name.endswith(f"_{s}.nii.gz") for s in STRUCTURAL_SUFFIXES
        ):
            issues.append("invalid_bids_anat_name")
            summary["invalid_name"] += 1
        if dest_json and Path(dest_json).name != json_path.name:
            # destination JSON must keep same basename
            issues.append("destination_json_name_mismatch")

        # Validate JSON parses when present
        if json_path.is_file():
            try:
                json.loads(json_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                issues.append(f"json_parse_error:{exc}")

        ok = not issues
        if ok:
            summary["ok"] += 1
        rows.append(
            {
                "participant": row.get("subject", ""),
                "session": row.get("session", ""),
                "modality": modality_from_name(original.name),
                "nifti_path": str(original),
                "json_path": str(json_path),
                "release_json_relative": dest_json,
                "json_exists": "yes" if json_path.is_file() else "no",
                "status": "OK" if ok else "FAIL",
                "detail": ";".join(issues),
            }
        )

    # Duplicate JSON basenames under same subject/session/anat would be rare;
    # flag duplicate absolute json paths in the plan.
    counts = Counter(r["json_path"] for r in rows)
    for r in rows:
        if counts[r["json_path"]] > 1:
            r["status"] = "FAIL"
            extra = "duplicate_json_in_plan"
            r["detail"] = f"{r['detail']};{extra}" if r["detail"] else extra

    out = reports_dir / "ANATOMICAL_JSON_CHECK.tsv"
    pd.DataFrame(rows).to_csv(out, sep="\t", index=False)
    overall = "PASS" if all(r["status"] == "OK" for r in rows) and rows else "FAIL"
    return overall, rows, summary


# ---------------------------------------------------------------------------
# CHECK 4 — Release structure (simulate if not built; inspect if present)
# ---------------------------------------------------------------------------
def check_release_structure(
    bids_dir: Path,
    release_dir: Path,
    audit_path: Path,
    manifest_path: Path,
    reports_dir: Path,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "check": "release_structure",
        "mode": "simulate" if not release_dir.is_dir() else "inspect_release",
    }

    required_root = [
        "dataset_description.json",
        "participants.tsv",
        "participants.json",
        "CHANGES",
    ]
    # README or README.md acceptable
    readme_ok_source = (bids_dir / "README").is_file() or (bids_dir / "README.md").is_file()

    def add(item: str, status: str, detail: str = "") -> None:
        rows.append({"item": item, "status": status, "detail": detail})

    # Root files from source (will be copied)
    for name in required_root:
        present = (bids_dir / name).is_file()
        add(
            f"root:{name}",
            "OK" if present else "FAIL",
            "present_in_source" if present else "missing_in_source",
        )
    add(
        "root:README",
        "OK" if readme_ok_source else "FAIL",
        "README or README.md present" if readme_ok_source else "missing",
    )

    # Subject folders
    subjects = sorted(
        p.name for p in bids_dir.iterdir() if p.is_dir() and p.name.startswith("sub-")
    )
    add("subjects", "OK" if subjects else "FAIL", f"n={len(subjects)}")
    invalid_subs = [s for s in subjects if not s.startswith("sub-")]
    add(
        "subject_folder_names",
        "OK" if not invalid_subs else "FAIL",
        "" if not invalid_subs else f"invalid={invalid_subs[:5]}",
    )

    # Expected modality dirs (at least some subjects have them)
    for modality in ("anat", "func", "dwi", "fmap"):
        n = len(list(bids_dir.glob(f"sub-*/ses-*/{modality}")))
        add(f"modality_dirs:{modality}", "OK" if n > 0 else "WARN", f"sessions_with_{modality}={n}")

    # No raw_original in copy manifest
    if manifest_path.is_file():
        man = pd.read_csv(manifest_path, sep="\t", dtype=str).fillna("")
        raw_hits = man[
            man["release_relative_path"].str.contains("raw_original", na=False)
            | man["source_path"].str.contains("/raw_original/", na=False)
        ]
        add(
            "no_raw_original_in_manifest",
            "OK" if raw_hits.empty else "FAIL",
            f"hits={len(raw_hits)}",
        )
    else:
        add("no_raw_original_in_manifest", "FAIL", f"missing_manifest:{manifest_path}")

    # All anatomicals excluded + replaced in plan
    if audit_path.is_file():
        audit = pd.read_csv(audit_path, sep="\t", dtype=str).fillna("")
        n_plan = len(audit)
        n_ok = sum(1 for s in audit["status"] if s in OK_STATUSES)
        add(
            "anatomicals_planned_replaced",
            "OK" if n_plan == n_ok and n_plan > 0 else "FAIL",
            f"planned={n_plan} ok_status={n_ok}",
        )
        # Duplicate T1w destinations
        dests = [
            release_dest_from_original(Path(p), bids_dir)
            for p in audit["original_file"]
        ]
        dup = [d for d, c in Counter(dests).items() if d and c > 1]
        add(
            "no_duplicate_T1w_destinations",
            "OK" if not dup else "FAIL",
            f"duplicates={len(dup)}",
        )
    else:
        add("anatomicals_planned_replaced", "FAIL", "audit_missing")

    # If release already exists, inspect for leftover non-defaced / structure
    if release_dir.is_dir():
        for name in required_root:
            present = (release_dir / name).is_file()
            add(
                f"release_root:{name}",
                "OK" if present else "FAIL",
                "present" if present else "missing",
            )
        readme_rel = (release_dir / "README").is_file() or (
            release_dir / "README.md"
        ).is_file()
        add("release_root:README", "OK" if readme_rel else "FAIL", "")

        # Non-defaced originals must not remain: every structural NIfTI must be
        # one of the planned destinations (already replaced). Compare checksums
        # is heavy; instead ensure count matches plan and no EXTRA anatomicals.
        release_anat = []
        for suffix in STRUCTURAL_SUFFIXES:
            release_anat.extend(release_dir.glob(f"sub-*/ses-*/anat/*_{suffix}.nii.gz"))
        if audit_path.is_file():
            expected = {
                release_dest_from_original(Path(p), bids_dir)
                for p in pd.read_csv(audit_path, sep="\t", dtype=str)["original_file"]
            }
            present = {str(p.relative_to(release_dir)) for p in release_anat}
            extra = sorted(present - expected)
            missing = sorted(expected - present)
            add(
                "release_no_unexpected_anatomicals",
                "OK" if not extra else "FAIL",
                f"extra={len(extra)}",
            )
            add(
                "release_all_defaced_present",
                "OK" if not missing else "FAIL",
                f"missing={len(missing)}",
            )
        # raw_original must not exist under release
        raw_dirs = list(release_dir.rglob("raw_original"))
        add(
            "release_no_raw_original",
            "OK" if not raw_dirs else "FAIL",
            f"hits={len(raw_dirs)}",
        )
    else:
        add(
            "release_dataset_exists",
            "OK",
            "not_built_yet_simulated_from_source_and_dry_run_plan",
        )

    out = reports_dir / "RELEASE_STRUCTURE_CHECK.tsv"
    pd.DataFrame(rows).to_csv(out, sep="\t", index=False)

    # WARN does not fail overall for modality absence edge cases; only FAIL rows
    fails = [r for r in rows if r["status"] == "FAIL"]
    overall = "PASS" if not fails else "FAIL"
    summary["n_fail"] = len(fails)
    summary["n_warn"] = sum(1 for r in rows if r["status"] == "WARN")
    return overall, rows, summary


# ---------------------------------------------------------------------------
# CHECK 5 — BIDS readiness (no validator run)
# ---------------------------------------------------------------------------
def check_bids_readiness(bids_dir: Path) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"check": "bids_readiness"}

    dd_path = bids_dir / "dataset_description.json"
    if not dd_path.is_file():
        rows.append(
            {
                "item": "dataset_description.json",
                "status": "FAIL",
                "detail": "missing",
            }
        )
    else:
        rows.append(
            {"item": "dataset_description.json", "status": "OK", "detail": "present"}
        )
        try:
            data = json.loads(dd_path.read_text(encoding="utf-8"))
            for key in ("BIDSVersion", "DatasetType"):
                if key in data and data[key] not in (None, ""):
                    rows.append(
                        {
                            "item": f"dataset_description.{key}",
                            "status": "OK",
                            "detail": str(data[key]),
                        }
                    )
                else:
                    rows.append(
                        {
                            "item": f"dataset_description.{key}",
                            "status": "FAIL",
                            "detail": "missing",
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "item": "dataset_description.json",
                    "status": "FAIL",
                    "detail": f"parse_error:{exc}",
                }
            )

    part = bids_dir / "participants.tsv"
    if part.is_file():
        try:
            df = pd.read_csv(part, sep="\t", dtype=str)
            ok = "participant_id" in df.columns and len(df) > 0
            rows.append(
                {
                    "item": "participants.tsv",
                    "status": "OK" if ok else "FAIL",
                    "detail": f"rows={len(df)} cols={list(df.columns)}",
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "item": "participants.tsv",
                    "status": "FAIL",
                    "detail": f"parse_error:{exc}",
                }
            )
    else:
        rows.append(
            {"item": "participants.tsv", "status": "FAIL", "detail": "missing"}
        )

    subjects = sorted(
        p.name for p in bids_dir.iterdir() if p.is_dir() and p.name.startswith("sub-")
    )
    bad = [s for s in subjects if not s.startswith("sub-")]
    rows.append(
        {
            "item": "subject_folders",
            "status": "OK" if subjects and not bad else "FAIL",
            "detail": f"n={len(subjects)}",
        }
    )

    overall = "PASS" if all(r["status"] == "OK" for r in rows) else "FAIL"
    summary["n_subjects"] = len(subjects)
    return overall, rows, summary


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def write_preflight_report(
    path: Path,
    *,
    overall: str,
    check_results: dict[str, dict[str, Any]],
    detail_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# Pre-flight release validation",
        "",
        f"**Generated (UTC):** {utc_now()}",
        f"**Overall status:** **{overall}**",
        "",
        "Read-only validation of the dry-run release plan before "
        "`python code/build_release.py --apply`.",
        "",
        "Protected trees (never modified by this script): `bids/`, `derivatives/`, "
        "`raw_original/`.",
        "",
        "## Check summary",
        "",
        "| Check | Status | Notes |",
        "|---|---|---|",
    ]
    for name, info in check_results.items():
        status = info.get("status", "?")
        note = info.get("note", "")
        lines.append(f"| {name} | **{status}** | {note} |")

    lines.extend(["", "## Details", ""])
    for name, info in check_results.items():
        lines.append(f"### {name}")
        lines.append("")
        summary = info.get("summary", {})
        for key, value in summary.items():
            if key in {"check"}:
                continue
            lines.append(f"- **{key}:** {value}")
        lines.append("")

    lines.extend(
        [
            "## Decision",
            "",
        ]
    )
    if overall == "PASS":
        lines.extend(
            [
                "All pre-flight checks passed.",
                "",
                "Safe to execute:",
                "",
                "```bash",
                "python code/build_release.py --apply",
                "```",
                "",
                "After the release is built, run:",
                "",
                "```bash",
                "bids-validator ~/scratch/release_dataset",
                "```",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "One or more checks **FAILED**.",
                "",
                "**Do NOT run** `build_release.py --apply` until failures are resolved.",
                "",
                "Review tables:",
                "",
                "- `ANATOMICAL_INTEGRITY_CHECK.tsv`",
                "- `ANATOMICAL_JSON_CHECK.tsv`",
                "- `RELEASE_STRUCTURE_CHECK.tsv`",
                "- `PREFLIGHT_RELEASE_VALIDATION.tsv`",
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
    reports_dir.mkdir(parents=True, exist_ok=True)

    audit_path = reports_dir / "ANATOMICAL_REPLACEMENT_AUDIT.tsv"
    manifest_path = reports_dir / "FILE_COPY_MANIFEST.tsv"

    log.info("Pre-flight validation (READ-ONLY)")
    log.info("BIDS: %s", bids_dir)
    log.info("Defacing: %s", defacing_dir)
    log.info("Release (target): %s", release_dir)
    log.info("Reports: %s", reports_dir)

    # Safety: refuse to treat protected paths as writable targets for --launch
    protected = {bids_dir, defacing_dir, (ROOT / "derivatives").resolve()}
    for candidate in (ROOT / "raw_original", Path("/project/def-amirs/raw_original")):
        if candidate.exists():
            protected.add(candidate.resolve())

    check_results: dict[str, dict[str, Any]] = {}
    all_detail_rows: list[dict[str, Any]] = []

    # CHECK 1
    log.info("CHECK 1 — Anatomical replacement audit")
    s1, rows1, sum1 = check_anatomical_audit(audit_path, bids_dir, defacing_dir)
    check_results["1_anatomical_replacement_audit"] = {
        "status": s1,
        "summary": sum1,
        "note": (
            f"planned={sum1.get('planned', 0)} successful={sum1.get('successful', 0)} "
            f"missing_repl={sum1.get('missing_replacements', 0)} "
            f"duplicates={sum1.get('duplicates', 0)}"
        ),
    }
    all_detail_rows.extend(rows1)
    log.info("  -> %s", s1)

    # CHECK 2
    log.info("CHECK 2 — Anatomical image integrity (nibabel headers)")
    s2, rows2, sum2 = check_anatomical_integrity(audit_path, reports_dir)
    check_results["2_anatomical_integrity"] = {
        "status": s2,
        "summary": sum2,
        "note": (
            f"compared={sum2.get('compared', 0)} pass={sum2.get('pass', 0)} "
            f"fail={sum2.get('fail', 0)}"
        ),
    }
    for r in rows2:
        all_detail_rows.append(
            {
                "check": "anatomical_integrity",
                "subject": r.get("participant", ""),
                "session": r.get("session", ""),
                "modality": r.get("modality", ""),
                "original_file": r.get("original_path", ""),
                "replacement_file": r.get("defaced_path", ""),
                "destination": "",
                "audit_status": "",
                "status": r.get("status", ""),
                "detail": (
                    f"shape={r.get('shape_match')};voxel={r.get('voxel_match')};"
                    f"affine={r.get('affine_match')};{r.get('detail', '')}"
                ),
            }
        )
    log.info("  -> %s", s2)

    # CHECK 3
    log.info("CHECK 3 — JSON sidecar consistency")
    s3, rows3, sum3 = check_json_sidecars(audit_path, bids_dir, reports_dir)
    check_results["3_anatomical_json"] = {
        "status": s3,
        "summary": sum3,
        "note": (
            f"checked={sum3.get('checked', 0)} ok={sum3.get('ok', 0)} "
            f"missing={sum3.get('missing', 0)}"
        ),
    }
    for r in rows3:
        all_detail_rows.append(
            {
                "check": "anatomical_json",
                "subject": r.get("participant", ""),
                "session": r.get("session", ""),
                "modality": r.get("modality", ""),
                "original_file": r.get("nifti_path", ""),
                "replacement_file": "",
                "destination": r.get("release_json_relative", ""),
                "audit_status": "",
                "status": r.get("status", ""),
                "detail": r.get("detail", ""),
            }
        )
    log.info("  -> %s", s3)

    # CHECK 4
    log.info("CHECK 4 — Release structure validation")
    s4, rows4, sum4 = check_release_structure(
        bids_dir, release_dir, audit_path, manifest_path, reports_dir
    )
    check_results["4_release_structure"] = {
        "status": s4,
        "summary": sum4,
        "note": (
            f"mode={sum4.get('mode')} fail={sum4.get('n_fail', 0)} "
            f"warn={sum4.get('n_warn', 0)}"
        ),
    }
    for r in rows4:
        all_detail_rows.append(
            {
                "check": "release_structure",
                "subject": "",
                "session": "",
                "modality": "",
                "original_file": "",
                "replacement_file": "",
                "destination": "",
                "audit_status": "",
                "status": r.get("status", ""),
                "detail": f"{r.get('item')}:{r.get('detail')}",
            }
        )
    log.info("  -> %s", s4)

    # CHECK 5
    log.info("CHECK 5 — BIDS validation readiness")
    s5, rows5, sum5 = check_bids_readiness(bids_dir)
    check_results["5_bids_readiness"] = {
        "status": s5,
        "summary": sum5,
        "note": f"subjects={sum5.get('n_subjects', 0)}",
    }
    for r in rows5:
        all_detail_rows.append(
            {
                "check": "bids_readiness",
                "subject": "",
                "session": "",
                "modality": "",
                "original_file": "",
                "replacement_file": "",
                "destination": "",
                "audit_status": "",
                "status": r.get("status", ""),
                "detail": f"{r.get('item')}:{r.get('detail')}",
            }
        )
    log.info("  -> %s", s5)

    statuses = [info["status"] for info in check_results.values()]
    overall = "PASS" if statuses and all(s == "PASS" for s in statuses) else "FAIL"

    # Write combined TSV
    preflight_tsv = reports_dir / "PREFLIGHT_RELEASE_VALIDATION.tsv"
    pd.DataFrame(all_detail_rows).to_csv(preflight_tsv, sep="\t", index=False)
    write_preflight_report(
        reports_dir / "PREFLIGHT_RELEASE_VALIDATION.md",
        overall=overall,
        check_results=check_results,
        detail_rows=all_detail_rows,
    )

    print()
    if overall == "PASS":
        print("=" * 50)
        print("RELEASE PREFLIGHT STATUS: PASS")
        print("Safe to execute:")
        print()
        print("python code/build_release.py --apply")
        print()
        print("After apply, run:")
        print("bids-validator ~/scratch/release_dataset")
        print("=" * 50)
    else:
        print("=" * 50)
        print("RELEASE PREFLIGHT STATUS: FAIL")
        print()
        print("Do NOT run build_release.py --apply")
        print()
        print("Review:")
        print("reports/openneuro_release/PREFLIGHT_RELEASE_VALIDATION.md")
        print("=" * 50)

    if args.launch:
        if overall != "PASS":
            log.error("--launch aborted because preflight FAILED")
            return 1
        if release_dir.resolve() in protected:
            log.error("Refuse to launch: release_dir collides with a protected path")
            return 1
        if not BUILD_SCRIPT.is_file():
            log.error("Missing build script: %s", BUILD_SCRIPT)
            return 1
        log.info("Launching: python %s --apply", BUILD_SCRIPT)
        proc = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), "--apply"],
            check=False,
        )
        return int(proc.returncode)

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
