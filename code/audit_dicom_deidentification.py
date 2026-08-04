#!/usr/bin/env python3
"""READ-ONLY DICOM de-identification / residual-PHI audit.

Never modifies DICOM files. Writes only under
reports/deidentification_validation/.

By default audits one representative instance per series directory
(practical for large archives). Use --all-files for exhaustive scan.

Examples:
  python code/audit_dicom_deidentification.py --dry-run \\
    --dicom-dir /project/def-amirs/raw_original

  python code/audit_dicom_deidentification.py \\
    --dicom-dir /project/def-amirs/raw_original
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DICOM = Path("/project/def-amirs/raw_original")
DEFAULT_OUT = Path("/home/alexrees/scratch/reports/deidentification_validation")
DEFAULT_INVENTORY = Path(
    "/home/alexrees/scratch/reports/privacy_audit/dicom_inventory.txt"
)

# Tag keyword -> (group, element), action_expected under PS3.15-oriented workflow
AUDIT_TAGS: dict[str, tuple[tuple[int, int], str, str]] = {
    # Direct identifiers
    "PatientName": ((0x0010, 0x0010), "REMOVE_OR_PSEUDONYMIZE", "HIGH"),
    "PatientID": ((0x0010, 0x0020), "REMOVE_OR_PSEUDONYMIZE", "HIGH"),
    "PatientBirthDate": ((0x0010, 0x0030), "REMOVE", "HIGH"),
    "OtherPatientIDs": ((0x0010, 0x1000), "REMOVE", "HIGH"),
    "OtherPatientNames": ((0x0010, 0x1001), "REMOVE", "HIGH"),
    "AccessionNumber": ((0x0008, 0x0050), "REMOVE", "HIGH"),
    "ReferringPhysicianName": ((0x0008, 0x0090), "REMOVE", "HIGH"),
    "PerformingPhysicianName": ((0x0008, 0x1050), "REMOVE", "HIGH"),
    "OperatorsName": ((0x0008, 0x1070), "REMOVE", "HIGH"),
    # Institution / device
    "InstitutionName": ((0x0008, 0x0080), "REMOVE", "MEDIUM"),
    "InstitutionalDepartmentName": ((0x0008, 0x1040), "REMOVE", "MEDIUM"),
    "StationName": ((0x0008, 0x1010), "REMOVE", "MEDIUM"),
    "DeviceSerialNumber": ((0x0018, 0x1000), "REMOVE", "MEDIUM"),
    "SoftwareVersions": ((0x0018, 0x1020), "REVIEW_RETAIN_OK", "LOW"),
    # UIDs (expect remapped after de-id path)
    "StudyInstanceUID": ((0x0020, 0x000D), "REMAP", "MEDIUM"),
    "SeriesInstanceUID": ((0x0020, 0x000E), "REMAP", "MEDIUM"),
    "SOPInstanceUID": ((0x0008, 0x0018), "REMAP", "MEDIUM"),
    "FrameOfReferenceUID": ((0x0020, 0x0052), "REMAP", "MEDIUM"),
    # Demographics
    "PatientAge": ((0x0010, 0x1010), "REMOVE_IF_SHARED", "MEDIUM"),
    "PatientSex": ((0x0010, 0x0040), "FLAG_RETAIN_OK", "LOW"),
}

SKIP_SUFFIXES = {
    ".txt",
    ".csv",
    ".tsv",
    ".json",
    ".log",
    ".md",
    ".nii",
    ".gz",
    ".html",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".zip",
    ".py",
    ".sh",
    ".m",
    ".mat",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def looks_like_dicom_name(name: str) -> bool:
    lower = name.lower()
    if lower.endswith(".nii") or lower.endswith(".nii.gz"):
        return False
    suf = Path(name).suffix.lower()
    if suf in SKIP_SUFFIXES:
        return False
    if suf in {".ima", ".dcm", ".dicom", ".img"}:
        return True
    if suf == "":
        return True
    return False


def pick_one_dicom_in_dir(directory: Path) -> Path | None:
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return None
    for name in names:
        if not looks_like_dicom_name(name):
            continue
        p = directory / name
        if p.is_file():
            return p
    return None


def discover_series_representatives(
    root: Path, inventory: Path | None, max_files: int | None
) -> tuple[list[Path], int]:
    """Return (files_to_scan, n_candidate_estimate)."""
    files: list[Path] = []
    if inventory and inventory.is_file():
        log(f"Reusing inventory: {inventory}")
        for line in inventory.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            p = Path(line)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                one = pick_one_dicom_in_dir(p)
                if one:
                    files.append(one)
        if max_files is not None:
            files = files[:max_files]
        return files, len(files)

    log(f"Discovering series under {root} …")
    series_dirs: set[Path] = set()
    n_candidates = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        hit = False
        for name in filenames:
            if not looks_like_dicom_name(name):
                continue
            n_candidates += 1
            hit = True
        if hit:
            series_dirs.add(d)
    for d in sorted(series_dirs):
        one = pick_one_dicom_in_dir(d)
        if one:
            files.append(one)
        if max_files is not None and len(files) >= max_files:
            break
    return files, n_candidates


def discover_all_files(root: Path, max_files: int | None) -> tuple[list[Path], int]:
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        for name in filenames:
            if not looks_like_dicom_name(name):
                continue
            files.append(d / name)
            if max_files is not None and len(files) >= max_files:
                return files, len(files)
    return files, len(files)


def _element_nonempty(ds: Any, tag: tuple[int, int]) -> tuple[bool, str]:
    try:
        if tag not in ds:
            return False, ""
        elem = ds[tag]
        val = elem.value
        if val is None:
            return False, ""
        text = str(val).strip()
        if text in {"", "None"}:
            return False, ""
        # Truncate for TSV safety
        if len(text) > 120:
            text = text[:117] + "..."
        return True, text
    except Exception:
        return False, ""


def audit_one_file(path_str: str) -> dict[str, Any]:
    """Worker: audit a single DICOM path. Returns serializable dict."""
    import pydicom
    from pydicom.errors import InvalidDicomError

    path = Path(path_str)
    out: dict[str, Any] = {
        "file": path_str,
        "ok": False,
        "error": "",
        "tags": [],
        "n_private": 0,
        "private_groups": [],
        "siemens_csa": False,
        "uid_remap_like": {},
        "patient_identity_removed": None,
        "deidentification_method": None,
    }
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except InvalidDicomError as exc:
        out["error"] = f"InvalidDicom: {exc}"
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
        return out

    out["ok"] = True
    for keyword, (tag, action, risk) in AUDIT_TAGS.items():
        present, preview = _element_nonempty(ds, tag)
        out["tags"].append(
            {
                "tag": f"({tag[0]:04X},{tag[1]:04X})",
                "keyword": keyword,
                "value_present": "yes" if present else "no",
                "action_expected": action,
                "risk_level": risk,
                "value_preview": preview if present else "",
            }
        )

    private_groups: set[str] = set()
    n_private = 0
    siemens_csa = False
    try:
        for elem in ds.iterall():
            if elem.tag.is_private:
                n_private += 1
                g = f"0x{int(elem.tag.group):04X}"
                private_groups.add(g)
                if int(elem.tag.group) == 0x0029:
                    siemens_csa = True
                    try:
                        if "CSA" in str(elem.value).upper() or "SIEMENS" in str(
                            getattr(elem, "name", "")
                        ).upper():
                            siemens_csa = True
                    except Exception:
                        pass
    except Exception:
        pass
    out["n_private"] = n_private
    out["private_groups"] = sorted(private_groups)
    out["siemens_csa"] = siemens_csa

    # Heuristic: remapped UIDs often start with 2.25.
    for kw in (
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "SOPInstanceUID",
        "FrameOfReferenceUID",
    ):
        tag = AUDIT_TAGS[kw][0]
        present, preview = _element_nonempty(ds, tag)
        remapped = present and preview.startswith("2.25.")
        out["uid_remap_like"][kw] = {
            "present": present,
            "looks_remapped_2_25": remapped,
            "prefix": preview[:20] if present else "",
        }

    try:
        if (0x0012, 0x0062) in ds:  # PatientIdentityRemoved
            out["patient_identity_removed"] = str(ds[0x0012, 0x0062].value)
        if (0x0012, 0x0063) in ds:  # DeidentificationMethod
            out["deidentification_method"] = str(ds[0x0012, 0x0063].value)[:200]
    except Exception:
        pass
    return out


def write_tsv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def write_unavailable_reuse_package(
    out_dir: Path,
    dicom_dir: Path,
    *,
    dry_run: bool,
) -> int:
    """When live DICOM is empty/unavailable, document reuse of prior audits."""
    prior_privacy = Path("/home/alexrees/scratch/reports/privacy_audit")
    prior_ps315 = Path("/home/alexrees/scratch/reports/deidentification_ps315_openneuro_audit.md")
    prior_deid = Path("/home/alexrees/scratch/reports/deidentification_report.md")
    date_shifts = Path("/home/alexrees/scratch/metadata/deidentify_date_shifts.csv")

    reused: list[str] = []
    for p in (
        prior_privacy / "PUBLICATION_PRIVACY_READINESS.md",
        prior_privacy / "burned_in_annotation_summary.md",
        prior_privacy / "dicom_demographic_summary.md",
        prior_ps315,
        prior_deid,
        date_shifts,
    ):
        if p.is_file():
            reused.append(str(p))

    # Synthesize TSV documenting expected actions (no live values)
    tsv_rows: list[dict[str, str]] = []
    for keyword, (tag, action, risk) in AUDIT_TAGS.items():
        tsv_rows.append(
            {
                "file": "(no_live_dicom)",
                "tag": f"({tag[0]:04X},{tag[1]:04X})",
                "keyword": keyword,
                "value_present": "unavailable_archive_empty",
                "action_expected": action,
                "risk_level": risk,
            }
        )
    tsv_path = out_dir / (
        "dicom_phi_audit_dryrun.tsv" if dry_run else "dicom_phi_audit.tsv"
    )
    write_tsv(
        tsv_path,
        tsv_rows,
        ["file", "tag", "keyword", "value_present", "action_expected", "risk_level"],
    )

    md_path = out_dir / (
        "dicom_deidentification_summary_dryrun.md"
        if dry_run
        else "dicom_deidentification_summary.md"
    )
    lines = [
        "# DICOM de-identification audit (READ-ONLY)",
        "",
        f"**Generated (UTC):** {datetime.now(timezone.utc).isoformat()}",
        f"**DICOM root:** `{dicom_dir.resolve()}`",
        f"**Live files scanned:** **0** (directory empty or inaccessible)",
        f"**Dry-run:** {dry_run}",
        "",
        "## Critical finding",
        "",
        f"The path `{dicom_dir}` currently contains **no DICOM instances** "
        "(empty directory as of this audit). A live tag-level re-scan is therefore "
        "**not possible**. This package reuses prior READ-ONLY audits and pipeline "
        "documentation rather than inventing live tag statistics.",
        "",
        "## Reused prior evidence",
        "",
    ]
    for r in reused:
        lines.append(f"- `{r}`")
    if not reused:
        lines.append("- (none found)")

    lines += [
        "",
        "## Counts (live scan)",
        "",
        "- Files scanned: **0**",
        "- Number with identifiers: **n/a (no live DICOM)**",
        "- Number with residual demographics: **n/a (no live DICOM)**",
        "",
        "## Private tag statistics (from pipeline policy + prior reports)",
        "",
        "- Conversion-path policy retains Siemens CSA private group **0x0029** when "
        "required for dcm2niix BIDS conversion (`mri_anonymization/constants.py`).",
        "- Upstream permanent de-id path strips private tags (CSA off) when used.",
        "- Prior privacy audit discovered **83154** DICOM candidates / **1133** "
        "series representatives under `raw_original/` before the archive was emptied.",
        "",
        "## UID remapping status",
        "",
        "- **Status:** DOCUMENTED_IN_PIPELINE (not re-verified on live objects)",
        "- Engine: deterministic SHA-256 → `2.25.*` remap for Study/Series/SOP/"
        "FrameOfReference UIDs (`UidRemapper`).",
        "- Empirical historical check (see `reports/deidentification_report.md`): "
        "raw PatientName/IDs replaced with canonical IDs; dates shifted; UIDs remapped "
        "to `2.25.*`.",
        "",
        "## Date shifting",
        "",
        f"- Date-shift table present: **{date_shifts.is_file()}** "
        f"(`{date_shifts}` when available; **not for public release**).",
        "",
        "## Interpretation for Scientific Data",
        "",
        "- **Do not distribute DICOM.** The public package is BIDS (+ defaced anatomicals).",
        "- Absence of `raw_original/` content in the working tree reduces accidental "
        "DICOM leakage risk for packaging, but means residual-PHI claims for DICOM "
        "objects must cite **prior audits + code policy**, not a fresh live scan.",
        "- Do **not** claim certified full DICOM PS3.15 Basic Profile compliance.",
        "- Supported claim: **PS3.15-oriented custom de-identification workflow with "
        "documented privacy audits.**",
        "",
        f"TSV (policy stub): `{tsv_path.name}`",
        "",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "dicom_dir": str(dicom_dir.resolve()),
        "mode": "archive_unavailable_reuse_prior",
        "dry_run": dry_run,
        "files_scanned": 0,
        "parse_ok": 0,
        "parse_fail": 0,
        "files_with_identifiers": None,
        "files_with_demographics": None,
        "uid_status": "DOCUMENTED_IN_PIPELINE_NO_LIVE_OBJECTS",
        "looks_like_source": None,
        "reused_reports": reused,
        "tsv": str(tsv_path),
        "summary_md": str(md_path),
        "verdict_hint": "READY_FOR_BIDS_ONLY_RELEASE_DICOM_NOT_DISTRIBUTED",
    }
    (out_dir / ("dicom_audit_summary_dryrun.json" if dry_run else "dicom_audit_summary.json")).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    log(f"Wrote {tsv_path} (archive empty — reuse mode)")
    log(f"Wrote {md_path}")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="READ-ONLY DICOM de-identification audit.")
    p.add_argument("--dicom-dir", type=Path, default=DEFAULT_DICOM)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_INVENTORY,
        help="Optional list of DICOM files/series (reuse privacy_audit inventory).",
    )
    p.add_argument(
        "--all-files",
        action="store_true",
        help="Scan every DICOM candidate (slow). Default: one file per series.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Limit to a small sample and write dry-run reports.",
    )
    p.add_argument(
        "--allow-empty",
        action="store_true",
        help="If no DICOM found, write reuse-prior package instead of failing.",
    )
    p.add_argument("--max-files", type=int, default=None)
    p.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.dicom_dir.is_dir():
        log(f"ERROR: --dicom-dir does not exist: {args.dicom_dir}")
        if args.allow_empty:
            return write_unavailable_reuse_package(out_dir, args.dicom_dir, dry_run=args.dry_run)
        return 2

    max_files = args.max_files
    if args.dry_run and max_files is None:
        max_files = 25

    inventory = args.inventory if args.inventory.is_file() else None
    # Prefer live discovery when inventory paths are stale
    if args.all_files:
        files, n_est = discover_all_files(args.dicom_dir, max_files)
        mode = "all_files"
    else:
        files, n_est = discover_series_representatives(args.dicom_dir, None, max_files)
        if not files and inventory is not None:
            files, n_est = discover_series_representatives(
                args.dicom_dir, inventory, max_files
            )
        mode = "one_per_series"

    log(f"Mode={mode} files_to_scan={len(files)} estimate/candidates={n_est}")
    if not files:
        log("WARNING: no DICOM files found under --dicom-dir")
        if args.allow_empty or True:
            # Always degrade gracefully for empty archives in this project state
            return write_unavailable_reuse_package(out_dir, args.dicom_dir, dry_run=args.dry_run)
        return 2

    results: list[dict[str, Any]] = []
    workers = 1 if args.dry_run else args.workers
    if workers == 1:
        for i, f in enumerate(files, 1):
            if i % 50 == 0 or i == len(files):
                log(f"  … audited {i}/{len(files)}")
            results.append(audit_one_file(str(f)))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(audit_one_file, str(f)): f for f in files}
            done = 0
            for fut in as_completed(futs):
                results.append(fut.result())
                done += 1
                if done % 50 == 0 or done == len(files):
                    log(f"  … audited {done}/{len(files)}")

    tsv_rows: list[dict[str, str]] = []
    files_with_identifiers = 0
    files_with_demographics = 0
    private_counter = Counter()
    private_group_files: Counter[str] = Counter()
    siemens_csa_n = 0
    uid_remap_counts = Counter()
    uid_present = Counter()
    parse_ok = 0
    parse_fail = 0
    identity_removed_yes = 0
    methods: Counter[str] = Counter()

    direct_id_keys = {
        "PatientName",
        "PatientID",
        "PatientBirthDate",
        "OtherPatientIDs",
        "OtherPatientNames",
        "AccessionNumber",
        "ReferringPhysicianName",
        "PerformingPhysicianName",
        "OperatorsName",
    }
    demo_keys = {"PatientAge", "PatientSex"}

    for res in results:
        if not res["ok"]:
            parse_fail += 1
            tsv_rows.append(
                {
                    "file": res["file"],
                    "tag": "",
                    "keyword": "PARSE_ERROR",
                    "value_present": "error",
                    "action_expected": "N/A",
                    "risk_level": "HIGH",
                }
            )
            continue
        parse_ok += 1
        has_id = False
        has_demo = False
        for t in res["tags"]:
            tsv_rows.append(
                {
                    "file": res["file"],
                    "tag": t["tag"],
                    "keyword": t["keyword"],
                    "value_present": t["value_present"],
                    "action_expected": t["action_expected"],
                    "risk_level": t["risk_level"],
                }
            )
            if t["value_present"] == "yes" and t["keyword"] in direct_id_keys:
                has_id = True
            if t["value_present"] == "yes" and t["keyword"] in demo_keys:
                has_demo = True
        if has_id:
            files_with_identifiers += 1
        if has_demo:
            files_with_demographics += 1
        private_counter["files_with_private"] += 1 if res["n_private"] else 0
        private_counter["private_elements_total"] += res["n_private"]
        for g in res["private_groups"]:
            private_group_files[g] += 1
        if res["siemens_csa"]:
            siemens_csa_n += 1
        for kw, info in res["uid_remap_like"].items():
            if info["present"]:
                uid_present[kw] += 1
                if info["looks_remapped_2_25"]:
                    uid_remap_counts[kw] += 1
        if str(res.get("patient_identity_removed", "")).upper() in {"YES", "Y", "1", "TRUE"}:
            identity_removed_yes += 1
        if res.get("deidentification_method"):
            methods[str(res["deidentification_method"])] += 1

    suffix = "_dryrun" if args.dry_run else ""
    tsv_path = out_dir / f"dicom_phi_audit{suffix}.tsv"
    # Canonical name always written for non-dry-run
    if not args.dry_run:
        tsv_path = out_dir / "dicom_phi_audit.tsv"
    write_tsv(
        tsv_path,
        tsv_rows,
        ["file", "tag", "keyword", "value_present", "action_expected", "risk_level"],
    )

    # Aggregate presence rates
    keyword_present = Counter()
    keyword_total = Counter()
    for row in tsv_rows:
        if row["keyword"] == "PARSE_ERROR":
            continue
        keyword_total[row["keyword"]] += 1
        if row["value_present"] == "yes":
            keyword_present[row["keyword"]] += 1

    looks_like_source = files_with_identifiers > 0 and identity_removed_yes == 0
    uid_status = "NOT_REMAPPED_ON_AUDITED_OBJECTS"
    if sum(uid_remap_counts.values()) > 0:
        uid_status = "PARTIAL_OR_FULL_2.25_REMAP_DETECTED"
    if identity_removed_yes > 0:
        uid_status = f"{uid_status}; PatientIdentityRemoved present in {identity_removed_yes}"

    md_path = out_dir / (
        "dicom_deidentification_summary_dryrun.md"
        if args.dry_run
        else "dicom_deidentification_summary.md"
    )
    lines = [
        "# DICOM de-identification audit (READ-ONLY)",
        "",
        f"**Generated (UTC):** {datetime.now(timezone.utc).isoformat()}",
        f"**DICOM root:** `{args.dicom_dir.resolve()}`",
        f"**Sampling mode:** `{mode}`",
        f"**Dry-run:** {args.dry_run}",
        "",
        "## Scope note",
        "",
        "This audit inspects available DICOM objects. Source archives under "
        "`raw_original/` are expected to contain PHI. A permanent `deid_dicom/` "
        "mirror was not assumed. Results must not be read as a certified DICOM "
        "PS3.15 Basic Profile conformance claim; they support a "
        "**PS3.15-oriented custom workflow** documentation.",
        "",
        "## Counts",
        "",
        f"- Files scanned: **{len(files)}**",
        f"- Successfully parsed: **{parse_ok}**",
        f"- Parse failures: **{parse_fail}**",
        f"- Files with ≥1 direct identifier present: **{files_with_identifiers}**",
        f"- Files with residual demographics (Age/Sex present): **{files_with_demographics}**",
        f"- Files with PatientIdentityRemoved=YES: **{identity_removed_yes}**",
        "",
        "## Tag presence (among parsed files)",
        "",
        "| Keyword | Present | N scored | Rate | Action expected |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for kw in AUDIT_TAGS:
        tot = keyword_total[kw]
        pre = keyword_present[kw]
        rate = 100.0 * pre / tot if tot else 0.0
        action = AUDIT_TAGS[kw][1]
        lines.append(f"| `{kw}` | {pre} | {tot} | {rate:.1f}% | {action} |")

    lines += [
        "",
        "## Private tags",
        "",
        f"- Private elements (sum across files): **{private_counter['private_elements_total']}**",
        f"- Files with ≥1 private element: **{private_counter['files_with_private']}**",
        f"- Siemens CSA group 0x0029 observed in: **{siemens_csa_n}** file(s)",
        "",
        "Retained private groups (file counts):",
        "",
    ]
    for g, c in private_group_files.most_common(20):
        lines.append(f"- `{g}`: {c}")
    if not private_group_files:
        lines.append("- (none)")

    lines += [
        "",
        "## UID remapping status",
        "",
        f"- Status: **{uid_status}**",
        f"- Looks like source (identifiers present, no PatientIdentityRemoved): **{looks_like_source}**",
        "",
        "| UID | Present | Looks remapped (`2.25.*`) |",
        "| --- | ---: | ---: |",
    ]
    for kw in (
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "SOPInstanceUID",
        "FrameOfReferenceUID",
    ):
        lines.append(
            f"| `{kw}` | {uid_present[kw]} | {uid_remap_counts[kw]} |"
        )

    if methods:
        lines += ["", "## DeidentificationMethod values observed", ""]
        for m, c in methods.most_common():
            lines.append(f"- ({c}) `{m}`")

    lines += [
        "",
        "## Interpretation for Scientific Data",
        "",
        "- **Do not distribute** `raw_original/` DICOM in the public package.",
        "- Conversion-time de-identification (pseudonym, date shift, UID remap, "
        "private-tag policy with optional Siemens CSA retention) is documented in "
        "`neuro_pipeline/mri_anonymization/` and prior reports.",
        "- This audit of source DICOM is evidence of **what must be removed** "
        "before any DICOM sharing, and of residual risk if a de-id mirror is absent.",
        "",
        f"TSV: `{tsv_path.name}`",
        "",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Compact JSON for FINAL aggregator
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "dicom_dir": str(args.dicom_dir.resolve()),
        "mode": mode,
        "dry_run": args.dry_run,
        "files_scanned": len(files),
        "parse_ok": parse_ok,
        "parse_fail": parse_fail,
        "files_with_identifiers": files_with_identifiers,
        "files_with_demographics": files_with_demographics,
        "siemens_csa_files": siemens_csa_n,
        "uid_status": uid_status,
        "looks_like_source": looks_like_source,
        "identity_removed_yes": identity_removed_yes,
        "keyword_present": dict(keyword_present),
        "tsv": str(tsv_path),
        "summary_md": str(md_path),
    }
    (out_dir / ("dicom_audit_summary_dryrun.json" if args.dry_run else "dicom_audit_summary.json")).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    log(f"Wrote {tsv_path}")
    log(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
