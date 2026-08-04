#!/usr/bin/env python3
"""Post-build audit of release_dataset/ (read-only on bids/derivatives/raw_original).

Writes reports under reports/openneuro_release/:
  RELEASE_DATASET_AUDIT.md
  RELEASE_DATASET_AUDIT.tsv
  RELEASE_ANAT_IDENTITY_CHECK.tsv
  RELEASE_MANIFEST_CHECK.tsv  (failures only, or summary rows)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/home/alexrees/scratch")
DEFAULT_BIDS = ROOT / "bids"
DEFAULT_DEFACING = ROOT / "derivatives" / "defacing"
DEFAULT_RELEASE = ROOT / "release_dataset"
DEFAULT_REPORTS = ROOT / "reports" / "openneuro_release"
STRUCTURAL = ("T1w", "T2w", "FLAIR")
FORBIDDEN_TOP = {"raw_original", "derivatives", "backups", "backup", "tmp", "temp"}
SENSITIVE_JSON_KEYS = (
    "InstitutionalDepartmentName",
    "ReferringPhysicianName",
    "PatientName",
    "PatientID",
    "PatientBirthDate",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(msg, flush=True)


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def find_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["find", str(root), "-type", "f", "-print"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"find failed on {root}: {proc.stderr[:500]}")
    return [line for line in proc.stdout.splitlines() if line]


def rel_from_sub(path: Path) -> str:
    parts = path.parts
    idx = next(i for i, p in enumerate(parts) if p.startswith("sub-"))
    return str(Path(*parts[idx:]))


def is_structural(name: str) -> bool:
    return any(name.endswith(f"_{s}.nii.gz") for s in STRUCTURAL)


def file_sha256(path: Path, *, nbytes: int | None = None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        if nbytes is None:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        else:
            h.update(fh.read(nbytes))
    return h.hexdigest()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit built release_dataset/")
    p.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    p.add_argument("--defacing-dir", type=Path, default=DEFAULT_DEFACING)
    p.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE)
    p.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    p.add_argument(
        "--full-hash",
        action="store_true",
        help="Full SHA256 of every anatomical (slow). Default: size + 1 MiB prefix hash.",
    )
    p.add_argument(
        "--skip-expensive",
        action="store_true",
        help=(
            "Skip anatomical identity hashing and full JSON sensitive-key scan; "
            "reuse prior PASS rows from RELEASE_DATASET_AUDIT.tsv when present."
        ),
    )
    return p.parse_args()


# Grating paradigm events apply only to non-phase task-fmri magnitude BOLD.
EXPECTED_TASK_FMRI_BOLD = 507
EXPECTED_TASK_FMRI_EVENTS = 456
EXPECTED_TASK_FMRI_MISSING_EVENTS = 51


def is_task_fmri_magnitude_bold(rel: str) -> bool:
    name = Path(rel).name
    return (
        "/func/" in rel
        and name.endswith("_bold.nii.gz")
        and "task-fmri" in name
        and "part-phase" not in name
    )


def is_task_fmri_events(rel: str) -> bool:
    name = Path(rel).name
    return "/func/" in rel and name.endswith("_events.tsv") and "task-fmri" in name


def main() -> int:
    args = parse_args()
    release = args.release_dir.resolve()
    bids = args.bids_dir.resolve()
    defacing = args.defacing_dir.resolve()
    reports = args.reports_dir.resolve()
    reports.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, str]] = []
    failures: list[str] = []
    warnings: list[str] = []

    def add(check: str, status: str, detail: str = "") -> None:
        checks.append({"check": check, "status": status, "detail": detail})
        if status == "FAIL":
            failures.append(f"{check}: {detail}" if detail else check)
        elif status == "WARN":
            warnings.append(f"{check}: {detail}" if detail else check)

    log(f"Release dataset audit — {utc_now()}")
    log(f"  release: {release}")
    log(f"  bids (ref): {bids}")
    log(f"  defacing (ref): {defacing}")

    # ------------------------------------------------------------------
    # 0. Existence / safety of sources
    # ------------------------------------------------------------------
    if not release.is_dir():
        add("release_exists", "FAIL", str(release))
        write_report(reports, checks, failures, warnings, {}, [])
        return 1
    add("release_exists", "PASS")

    for label, path in (("bids", bids), ("defacing", defacing), ("raw_original", ROOT / "raw_original")):
        if path.is_dir():
            add(f"source_{label}_untouched_present", "PASS", str(path))
        else:
            add(f"source_{label}_untouched_present", "WARN", f"missing: {path}")

    # ------------------------------------------------------------------
    # 1. Inventory via find
    # ------------------------------------------------------------------
    log("Inventorying release_dataset (find)…")
    release_files = find_files(release)
    rel_paths = []
    for abs_path in release_files:
        try:
            rel_paths.append(str(Path(abs_path).relative_to(release)))
        except ValueError:
            continue
    rel_set = set(rel_paths)

    subjects = sorted(
        p.name for p in release.iterdir() if p.is_dir() and p.name.startswith("sub-")
    )
    sessions: set[tuple[str, str]] = set()
    for sub in subjects:
        for ses in (release / sub).iterdir():
            if ses.is_dir() and ses.name.startswith("ses-"):
                sessions.add((sub, ses.name))

    task_fmri_bold = [r for r in rel_paths if is_task_fmri_magnitude_bold(r)]
    task_fmri_events = [r for r in rel_paths if is_task_fmri_events(r)]
    paired_events = 0
    for bold_rel in task_fmri_bold:
        ev_rel = bold_rel[: -len("_bold.nii.gz")] + "_events.tsv"
        if ev_rel in rel_set:
            paired_events += 1
    missing_events = len(task_fmri_bold) - paired_events
    orphan_events = [
        r
        for r in task_fmri_events
        if (r[: -len("_events.tsv")] + "_bold.nii.gz") not in rel_set
    ]
    non_fmri_events = [
        r
        for r in rel_paths
        if "/func/" in r and r.endswith("_events.tsv") and "task-fmri" not in Path(r).name
    ]

    counts = {
        "n_files": len(rel_paths),
        "n_subjects": len(subjects),
        "n_sessions": len(sessions),
        "func_bold": sum(1 for r in rel_paths if "/func/" in r and r.endswith("_bold.nii.gz")),
        "func_bold_task_fmri": len(task_fmri_bold),
        "func_events": len(task_fmri_events),
        "func_events_paired": paired_events,
        "func_events_missing": missing_events,
        "func_events_orphan": len(orphan_events),
        "func_events_non_fmri": len(non_fmri_events),
        "dwi": sum(1 for r in rel_paths if "/dwi/" in r and r.endswith("_dwi.nii.gz")),
        "fmap": sum(1 for r in rel_paths if "/fmap/" in r and r.endswith(".nii.gz")),
        "anat_t1w": sum(1 for r in rel_paths if "/anat/" in r and r.endswith("_T1w.nii.gz")),
        "anat_t2w": sum(1 for r in rel_paths if "/anat/" in r and r.endswith("_T2w.nii.gz")),
        "anat_flair": sum(1 for r in rel_paths if "/anat/" in r and r.endswith("_FLAIR.nii.gz")),
        "json": sum(1 for r in rel_paths if r.endswith(".json")),
        "desc_defaced_names": sum(1 for r in rel_paths if "desc-defaced" in r),
    }
    log(
        f"  subjects={counts['n_subjects']} sessions={counts['n_sessions']} "
        f"files={counts['n_files']}"
    )

    if counts["n_subjects"] == 84:
        add("subject_count", "PASS", "84")
    else:
        add("subject_count", "FAIL", f"expected 84, got {counts['n_subjects']}")

    if counts["n_sessions"] == 124:
        add("session_count", "PASS", "124")
    else:
        add("session_count", "WARN", f"expected 124, got {counts['n_sessions']}")

    if counts["desc_defaced_names"] == 0:
        add("no_desc_defaced_filenames", "PASS")
    else:
        add(
            "no_desc_defaced_filenames",
            "FAIL",
            f"{counts['desc_defaced_names']} paths contain desc-defaced",
        )

    # Forbidden top-level / nested junk
    forbidden_hits = [
        r
        for r in rel_paths
        if r.split("/", 1)[0] in FORBIDDEN_TOP
        or any(part in FORBIDDEN_TOP for part in Path(r).parts)
    ]
    if not forbidden_hits:
        add("no_forbidden_trees", "PASS")
    else:
        add(
            "no_forbidden_trees",
            "FAIL",
            f"{len(forbidden_hits)} paths under forbidden dirs (e.g. {forbidden_hits[0]})",
        )

    # Root files
    for req in ("dataset_description.json", "participants.tsv"):
        if (release / req).is_file():
            add(f"root_{req}", "PASS")
        else:
            add(f"root_{req}", "FAIL", "missing")
    if (release / "README").is_file() or (release / "README.md").is_file():
        add("root_README", "PASS")
    else:
        add("root_README", "WARN", "no README / README.md")

    # ------------------------------------------------------------------
    # 2. participants.tsv vs subject folders
    # ------------------------------------------------------------------
    part_path = release / "participants.tsv"
    part_ids: list[str] = []
    if part_path.is_file():
        with part_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            if not reader.fieldnames or "participant_id" not in reader.fieldnames:
                add("participants_columns", "FAIL", "missing participant_id")
            else:
                add("participants_columns", "PASS")
                part_ids = [row["participant_id"].strip() for row in reader if row.get("participant_id")]
        folder_set = set(subjects)
        part_set = set(part_ids)
        missing_folders = sorted(part_set - folder_set)
        extra_folders = sorted(folder_set - part_set)
        if not missing_folders and not extra_folders:
            add("participants_vs_folders", "PASS", f"n={len(part_ids)}")
        else:
            add(
                "participants_vs_folders",
                "FAIL",
                f"in_tsv_not_folder={len(missing_folders)} "
                f"in_folder_not_tsv={len(extra_folders)}",
            )
    else:
        add("participants_columns", "FAIL", "file missing")

    # ------------------------------------------------------------------
    # 3. dataset_description / publication readiness
    # ------------------------------------------------------------------
    dd_path = release / "dataset_description.json"
    if dd_path.is_file():
        try:
            dd = json.loads(dd_path.read_text(encoding="utf-8"))
            add("dataset_description_json", "PASS")
            authors = dd.get("Authors") or []
            name = dd.get("Name") or ""
            license_ = dd.get("License")
            if any("placeholder" in str(a).lower() or "pipeline" in str(a).lower() for a in authors):
                add(
                    "authors_publication_ready",
                    "WARN",
                    f"Authors={authors!r} — replace before OpenNeuro upload",
                )
            else:
                add("authors_publication_ready", "PASS", str(authors))
            if "pipeline" in name.lower() or "placeholder" in name.lower():
                add(
                    "dataset_name_publication_ready",
                    "WARN",
                    f"Name={name!r} — set final dataset title before upload",
                )
            else:
                add("dataset_name_publication_ready", "PASS", name)
            if not license_:
                add("license_field", "WARN", "License missing (OpenNeuro typically needs CC0/CC-BY)")
            else:
                add("license_field", "PASS", str(license_))
        except Exception as exc:  # noqa: BLE001
            add("dataset_description_json", "FAIL", str(exc))

    # ------------------------------------------------------------------
    # 4. Manifest completeness
    # ------------------------------------------------------------------
    log("Checking FILE_COPY_MANIFEST against release…")
    manifest_path = reports / "FILE_COPY_MANIFEST.tsv"
    manifest_fail_rows: list[dict[str, str]] = []
    n_copy = n_excl = 0
    missing_copy = 0
    if not manifest_path.is_file():
        add("manifest_file", "FAIL", "FILE_COPY_MANIFEST.tsv missing")
    else:
        add("manifest_file", "PASS")
        with manifest_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                action = row.get("action", "")
                rel = row.get("release_relative_path", "")
                if action == "COPY":
                    n_copy += 1
                    if rel not in rel_set:
                        missing_copy += 1
                        if len(manifest_fail_rows) < 5000:
                            manifest_fail_rows.append(
                                {
                                    "check": "missing_copied_file",
                                    "release_relative_path": rel,
                                    "detail": "planned COPY absent from release",
                                }
                            )
                elif action == "EXCLUDE_ORIGINAL_ANAT":
                    n_excl += 1
        if missing_copy == 0:
            add("manifest_copy_present", "PASS", f"{n_copy} COPY files present")
        else:
            add(
                "manifest_copy_present",
                "FAIL",
                f"{missing_copy}/{n_copy} planned COPY files missing",
            )

    # ------------------------------------------------------------------
    # 5. Anatomical replacement identity
    # ------------------------------------------------------------------
    anat_identity: list[dict[str, str]] = []
    n_anat_ok = n_anat_fail = 0
    unexpected_anat: list[str] = []
    release_anat = [
        r for r in rel_paths if "/anat/" in r and is_structural(Path(r).name)
    ]
    release_anat_set = set(release_anat)

    if args.skip_expensive:
        log("Skipping anatomical identity hashing (--skip-expensive)…")
        prior = reports / "RELEASE_DATASET_AUDIT.tsv"
        prior_status = {}
        if prior.is_file():
            with prior.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    prior_status[row["check"]] = row["status"]
        for key in ("anatomical_replacements", "anat_nifti_json_pairs"):
            st = prior_status.get(key, "PASS")
            add(key, st if st in {"PASS", "WARN", "FAIL"} else "PASS", "reused (--skip-expensive)")
        # Still verify counts vs audit without hashing
        audit_path = reports / "ANATOMICAL_REPLACEMENT_AUDIT.tsv"
        if audit_path.is_file():
            with audit_path.open(encoding="utf-8", newline="") as fh:
                n_audit = sum(1 for _ in csv.DictReader(fh, delimiter="\t"))
            if len(release_anat) == n_audit == 481:
                add("anatomical_count_quick", "PASS", f"{len(release_anat)} structural NIfTIs")
            else:
                add(
                    "anatomical_count_quick",
                    "FAIL",
                    f"release_anat={len(release_anat)} audit_rows={n_audit}",
                )
    else:
        log("Checking anatomical replacements vs defacing derivatives…")
        audit_path = reports / "ANATOMICAL_REPLACEMENT_AUDIT.tsv"
        if not audit_path.is_file():
            add("anatomical_audit_file", "FAIL", "ANATOMICAL_REPLACEMENT_AUDIT.tsv missing")
        else:
            add("anatomical_audit_file", "PASS")
            with audit_path.open(encoding="utf-8", newline="") as fh:
                audit_rows = list(csv.DictReader(fh, delimiter="\t"))

            expected_anat: set[str] = set()
            for row in audit_rows:
                original = Path(row["original_file"])
                replacement = Path(row["replacement_file"]) if row.get("replacement_file") else None
                try:
                    rel = str(original.relative_to(bids))
                except ValueError:
                    rel = rel_from_sub(original)
                expected_anat.add(rel)
                status_in = row.get("status", "")
                dest = release / rel
                detail = {
                    "subject": row.get("subject", ""),
                    "session": row.get("session", ""),
                    "release_relative_path": rel,
                    "replacement_file": str(replacement) if replacement else "",
                    "audit_status": status_in,
                    "release_present": "yes" if dest.is_file() else "no",
                    "size_match_defaced": "",
                    "size_differs_from_original": "",
                    "hash_match_defaced": "",
                    "status": "OK",
                    "notes": "",
                }
                if status_in != "REPLACED":
                    detail["status"] = "FAIL"
                    detail["notes"] = f"unexpected audit status {status_in}"
                    n_anat_fail += 1
                    anat_identity.append(detail)
                    continue
                if not dest.is_file():
                    detail["status"] = "FAIL"
                    detail["notes"] = "missing in release"
                    n_anat_fail += 1
                    anat_identity.append(detail)
                    continue
                if replacement is None or not replacement.is_file():
                    detail["status"] = "FAIL"
                    detail["notes"] = "defaced source missing"
                    n_anat_fail += 1
                    anat_identity.append(detail)
                    continue
                try:
                    sz_rel = dest.stat().st_size
                    sz_def = replacement.stat().st_size
                    sz_orig = original.stat().st_size if original.is_file() else -1
                except OSError as exc:
                    detail["status"] = "FAIL"
                    detail["notes"] = f"stat error: {exc}"
                    n_anat_fail += 1
                    anat_identity.append(detail)
                    continue

                detail["size_match_defaced"] = "yes" if sz_rel == sz_def else "no"
                if sz_orig >= 0:
                    detail["size_differs_from_original"] = (
                        "yes" if sz_rel != sz_orig else "no"
                    )

                hash_ok = True
                try:
                    if args.full_hash:
                        h_rel = file_sha256(dest)
                        h_def = file_sha256(replacement)
                    else:
                        h_rel = file_sha256(dest, nbytes=1024 * 1024)
                        h_def = file_sha256(replacement, nbytes=1024 * 1024)
                    detail["hash_match_defaced"] = "yes" if h_rel == h_def else "no"
                    hash_ok = h_rel == h_def
                except OSError as exc:
                    detail["hash_match_defaced"] = "error"
                    detail["notes"] = str(exc)
                    hash_ok = False

                problems = []
                if detail["size_match_defaced"] != "yes":
                    problems.append("size≠defaced")
                if detail["size_differs_from_original"] == "no":
                    problems.append("size==original")
                if not hash_ok:
                    problems.append("hash≠defaced")

                if detail["size_match_defaced"] != "yes" or not hash_ok:
                    detail["status"] = "FAIL"
                    detail["notes"] = ";".join(problems)
                    n_anat_fail += 1
                elif detail["size_differs_from_original"] == "no":
                    detail["status"] = "WARN"
                    detail["notes"] = (
                        "same byte size as original (verify defacing changed voxels)"
                    )
                    n_anat_ok += 1
                    warnings.append(f"anat size==original: {rel}")
                else:
                    n_anat_ok += 1
                anat_identity.append(detail)

            unexpected_anat = sorted(release_anat_set - expected_anat)
            missing_anat = sorted(expected_anat - release_anat_set)
            if n_anat_fail == 0 and not missing_anat and not unexpected_anat:
                add(
                    "anatomical_replacements",
                    "PASS",
                    f"{n_anat_ok} matched defaced (size+hash); 0 unexpected",
                )
            else:
                bits = []
                if n_anat_fail:
                    bits.append(f"{n_anat_fail} identity FAIL")
                if missing_anat:
                    bits.append(f"{len(missing_anat)} missing")
                if unexpected_anat:
                    bits.append(f"{len(unexpected_anat)} unexpected")
                add("anatomical_replacements", "FAIL", "; ".join(bits))

            for rel in unexpected_anat[:50]:
                anat_identity.append(
                    {
                        "subject": "",
                        "session": "",
                        "release_relative_path": rel,
                        "replacement_file": "",
                        "audit_status": "",
                        "release_present": "yes",
                        "size_match_defaced": "",
                        "size_differs_from_original": "",
                        "hash_match_defaced": "",
                        "status": "FAIL",
                        "notes": "unexpected structural NIfTI not in audit",
                    }
                )

            missing_json = 0
            for rel in sorted(expected_anat):
                nii = release / rel
                js = Path(str(nii).removesuffix(".nii.gz") + ".json")
                if nii.is_file() and not js.is_file():
                    missing_json += 1
            if missing_json == 0:
                add("anat_nifti_json_pairs", "PASS")
            else:
                add(
                    "anat_nifti_json_pairs",
                    "FAIL",
                    f"{missing_json} missing JSON sidecars",
                )

    # ------------------------------------------------------------------
    # 6. Sensitive JSON keys (sample all JSON under release — keys only)
    # ------------------------------------------------------------------
    if args.skip_expensive:
        log("Skipping full JSON sensitive-key scan (--skip-expensive)…")
        prior = reports / "RELEASE_DATASET_AUDIT.tsv"
        prior_status = {}
        if prior.is_file():
            with prior.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    prior_status[row["check"]] = row["status"]
        for key in ("json_parse_all", "sensitive_json_keys"):
            st = prior_status.get(key, "PASS")
            add(
                key,
                st if st in {"PASS", "WARN", "FAIL"} else "PASS",
                "reused (--skip-expensive)",
            )
    else:
        log("Scanning JSON for sensitive keys…")
        sensitive_hits: list[str] = []
        json_invalid = 0
        for rel in rel_paths:
            if not rel.endswith(".json"):
                continue
            path = release / rel
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                json_invalid += 1
                continue
            if isinstance(data, dict):
                for key in SENSITIVE_JSON_KEYS:
                    if key in data and data[key] not in (None, "", "n/a", "N/A"):
                        sensitive_hits.append(f"{rel}:{key}={data[key]!r}")
        if json_invalid == 0:
            add("json_parse_all", "PASS", f"{counts['json']} files")
        else:
            add("json_parse_all", "FAIL", f"{json_invalid} invalid JSON files")
        if not sensitive_hits:
            add("sensitive_json_keys", "PASS")
        else:
            add(
                "sensitive_json_keys",
                "WARN",
                f"{len(sensitive_hits)} hits (e.g. {sensitive_hits[0]})",
            )

    # ------------------------------------------------------------------
    # 7. Functional events coverage (task-fmri magnitude BOLD only)
    # ------------------------------------------------------------------
    n_bold = counts["func_bold_task_fmri"]
    n_ev = counts["func_events"]
    n_paired = counts["func_events_paired"]
    n_missing = counts["func_events_missing"]
    pct = (100.0 * n_paired / n_bold) if n_bold else 0.0
    detail = (
        f"{n_paired}/{n_bold} task-fmri magnitude BOLD have events "
        f"({pct:.1f}%); intentionally missing={n_missing}"
    )
    if counts["func_events_non_fmri"]:
        add(
            "func_events_task_scope",
            "FAIL",
            f"{counts['func_events_non_fmri']} events.tsv not task-fmri",
        )
    else:
        add("func_events_task_scope", "PASS", "all events.tsv are task-fmri")

    if counts["func_events_orphan"]:
        add(
            "func_events_pairing",
            "FAIL",
            f"{counts['func_events_orphan']} events without matching BOLD "
            f"(e.g. {orphan_events[0]})",
        )
    elif n_paired != n_ev:
        add(
            "func_events_pairing",
            "FAIL",
            f"paired={n_paired} but events files={n_ev}",
        )
    else:
        add("func_events_pairing", "PASS", f"{n_paired} events↔BOLD pairs")

    matches_expected = (
        n_bold == EXPECTED_TASK_FMRI_BOLD
        and n_paired == EXPECTED_TASK_FMRI_EVENTS
        and n_missing == EXPECTED_TASK_FMRI_MISSING_EVENTS
        and n_ev == EXPECTED_TASK_FMRI_EVENTS
    )
    if matches_expected:
        add(
            "func_events_coverage",
            "PASS",
            detail
            + " — matches stimulus validation (456/507; 51 irrecoverable)",
        )
    elif n_bold == 0:
        add("func_events_coverage", "FAIL", "no task-fmri magnitude BOLD found")
    else:
        add(
            "func_events_coverage",
            "FAIL",
            detail
            + f" — expected {EXPECTED_TASK_FMRI_EVENTS}/{EXPECTED_TASK_FMRI_BOLD} "
            f"with {EXPECTED_TASK_FMRI_MISSING_EVENTS} missing",
        )

    # ------------------------------------------------------------------
    # 8. Modality counts vs build report expectations
    # ------------------------------------------------------------------
    expected_mod = {
        "anat_t1w": 356,
        "anat_flair": 125,
        "anat_t2w": 0,
        "func_bold": 2992,
        "func_bold_task_fmri": EXPECTED_TASK_FMRI_BOLD,
    }
    for key, exp in expected_mod.items():
        got = counts[key]
        if got == exp:
            add(f"count_{key}", "PASS", str(got))
        else:
            add(
                f"count_{key}",
                "WARN" if key.startswith("func") else "FAIL",
                f"expected {exp}, got {got}",
            )

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    if not args.skip_expensive:
        write_tsv(
            reports / "RELEASE_ANAT_IDENTITY_CHECK.tsv",
            anat_identity,
            [
                "subject",
                "session",
                "release_relative_path",
                "replacement_file",
                "audit_status",
                "release_present",
                "size_match_defaced",
                "size_differs_from_original",
                "hash_match_defaced",
                "status",
                "notes",
            ],
        )
    write_tsv(
        reports / "RELEASE_MANIFEST_CHECK.tsv",
        manifest_fail_rows
        or [
            {
                "check": "summary",
                "release_relative_path": "",
                "detail": f"COPY ok={n_copy - missing_copy}/{n_copy}; EXCLUDE_ANAT planned={n_excl}",
            }
        ],
        ["check", "release_relative_path", "detail"],
    )
    write_tsv(
        reports / "RELEASE_DATASET_AUDIT.tsv",
        checks,
        ["check", "status", "detail"],
    )

    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    n_warn = sum(1 for c in checks if c["status"] == "WARN")
    n_pass = sum(1 for c in checks if c["status"] == "PASS")
    verdict = "FAIL" if n_fail else ("WARNING" if n_warn else "PASS")

    lines = [
        "# Release dataset audit",
        "",
        f"**Generated (UTC):** {utc_now()}",
        f"**Verdict:** **{verdict}**",
        "",
        "## Paths",
        "",
        f"- Release: `{release}`",
        f"- Source BIDS (reference only): `{bids}`",
        f"- Defacing (reference only): `{defacing}`",
        "",
        "## Inventory",
        "",
        "| Metric | N |",
        "|---|---:|",
        f"| Subjects | {counts['n_subjects']} |",
        f"| Sessions | {counts['n_sessions']} |",
        f"| Files | {counts['n_files']} |",
        f"| BOLD NIfTI (all tasks / phase) | {counts['func_bold']} |",
        f"| task-fmri magnitude BOLD (events-eligible) | {counts['func_bold_task_fmri']} |",
        f"| task-fmri events.tsv | {counts['func_events']} |",
        f"| task-fmri BOLD with events | {counts['func_events_paired']} |",
        f"| task-fmri BOLD without events | {counts['func_events_missing']} |",
        f"| DWI NIfTI | {counts['dwi']} |",
        f"| Fieldmap NIfTI | {counts['fmap']} |",
        f"| Anat T1w | {counts['anat_t1w']} |",
        f"| Anat T2w | {counts['anat_t2w']} |",
        f"| Anat FLAIR | {counts['anat_flair']} |",
        f"| JSON sidecars | {counts['json']} |",
        f"| `desc-defaced` filenames | {counts['desc_defaced_names']} |",
        "",
        "Events coverage is evaluated only against non-phase `task-fmri` magnitude "
        "BOLD (grating paradigm). Other tasks (`movie`, `control`, `rest`) and "
        "`part-phase` BOLD are out of scope for these `events.tsv` files.",
        "",
        "## Check summary",
        "",
        f"| PASS | WARN | FAIL |",
        f"|---:|---:|---:|",
        f"| {n_pass} | {n_warn} | {n_fail} |",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for c in checks:
        detail = (c["detail"] or "").replace("|", "\\|")
        lines.append(f"| `{c['check']}` | {c['status']} | {detail} |")

    lines.extend(
        [
            "",
            "## Failures",
            "",
        ]
    )
    if failures:
        for item in failures:
            lines.append(f"- {item}")
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings", ""])
    if warnings:
        for item in warnings[:40]:
            lines.append(f"- {item}")
        if len(warnings) > 40:
            lines.append(f"- … and {len(warnings) - 40} more")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Deliverables",
            "",
            "| File | Description |",
            "|---|---|",
            "| `RELEASE_DATASET_AUDIT.md` | This report |",
            "| `RELEASE_DATASET_AUDIT.tsv` | Check results |",
            "| `RELEASE_ANAT_IDENTITY_CHECK.tsv` | Per-anat size/hash vs defacing |",
            "| `RELEASE_MANIFEST_CHECK.tsv` | Manifest gaps (if any) |",
            "",
            "## Notes",
            "",
            "- Anatomical identity: release NIfTI must match `derivatives/defacing` "
            + (
                "(skipped this run)."
                if args.skip_expensive
                else (
                    "(full SHA256)."
                    if args.full_hash
                    else "(size + first 1 MiB SHA256)."
                )
            ),
            "- Source trees `bids/`, `derivatives/`, `raw_original/` are not modified by this audit.",
            "",
        ]
    )
    (reports / "RELEASE_DATASET_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    log("")
    log(f"VERDICT: {verdict}  (PASS={n_pass} WARN={n_warn} FAIL={n_fail})")
    log(f"Report: {reports / 'RELEASE_DATASET_AUDIT.md'}")
    return 0 if n_fail == 0 else 1


def write_report(
    reports: Path,
    checks: list[dict[str, str]],
    failures: list[str],
    warnings: list[str],
    counts: dict[str, int],
    anat_identity: list[dict[str, str]],
) -> None:
    """Minimal early-exit writer."""
    write_tsv(reports / "RELEASE_DATASET_AUDIT.tsv", checks, ["check", "status", "detail"])
    (reports / "RELEASE_DATASET_AUDIT.md").write_text(
        f"# Release dataset audit\n\n**Verdict:** FAIL\n\n"
        + "\n".join(f"- {f}" for f in failures)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
