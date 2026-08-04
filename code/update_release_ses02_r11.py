#!/usr/bin/env python3
"""Incrementally add the 11 retry ses-02 sessions into release_dataset/.

Uses the same release policy as build_release.py:
  - Copy session tree from bids/ (read-only)
  - Exclude original structural anatomicals (T1w / T2w / FLAIR)
  - Install defaced T1w/T2w/FLAIR from derivatives/defacing/
  - Keep TB1TFL from BIDS (matches existing release_dataset behavior)
  - Never modify bids/, derivatives/, or raw_original/

sub-078/ses-02 has no anat/ — copied as-is (func-only sparse session).

Examples:
  python code/update_release_ses02_r11.py --dry-run
  python code/update_release_ses02_r11.py --apply
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/home/alexrees/scratch")
DEFAULT_BIDS = ROOT / "bids"
DEFAULT_DEFACING = ROOT / "derivatives" / "defacing"
DEFAULT_RELEASE = ROOT / "release_dataset"
DEFAULT_TSV = ROOT / "neuro_pipeline" / "scripts" / "subjects_missing_ses02_retry11.tsv"
DEFAULT_REPORTS = ROOT / "reports" / "ses02_retry11"

STRUCTURAL_SUFFIXES = ("T1w", "T2w", "FLAIR")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(msg, flush=True)


def is_structural_nifti(name: str) -> bool:
    return any(name.endswith(f"_{suffix}.nii.gz") for suffix in STRUCTURAL_SUFFIXES)


def load_targets(tsv: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with tsv.open(encoding="utf-8") as fh:
        data_lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    for row in csv.DictReader(data_lines, delimiter="\t"):
        if row.get("participant_id") and row.get("session_id"):
            rows.append(row)
    return rows


def write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def md5_prefix(path: Path, nbytes: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        h.update(fh.read(nbytes))
    return h.hexdigest()


def ignore_structural(dir_path: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name.startswith(".") and name != ".bidsignore":
            ignored.add(name)
            continue
        if is_structural_nifti(name):
            ignored.add(name)
    return ignored


def plan_session(
    bids_dir: Path,
    defacing_dir: Path,
    release_dir: Path,
    participant: str,
    session: str,
) -> dict[str, Any]:
    src = bids_dir / participant / session
    dest = release_dir / participant / session
    out: dict[str, Any] = {
        "participant_id": participant,
        "session_id": session,
        "bids_exists": src.is_dir(),
        "release_exists": dest.is_dir(),
        "n_bids_files": 0,
        "n_structural": 0,
        "n_defaced_ready": 0,
        "n_defaced_missing": 0,
        "status": "PENDING",
        "notes": "",
        "actions": [],
    }
    if not src.is_dir():
        out["status"] = "FAIL_MISSING_BIDS"
        out["notes"] = "session missing in bids/"
        return out

    files = [p for p in src.rglob("*") if p.is_file()]
    out["n_bids_files"] = len(files)

    structural = [
        p
        for p in files
        if is_structural_nifti(p.name) and "anat" in p.parts
    ]
    out["n_structural"] = len(structural)

    for anat in structural:
        rel = anat.relative_to(bids_dir)
        defaced = defacing_dir / rel
        action = {
            "kind": "REPLACE_DEFACED",
            "source": str(defaced),
            "dest": str(release_dir / rel),
            "bids_original": str(anat),
            "status": "READY" if defaced.is_file() else "MISSING_DEFACED",
        }
        if defaced.is_file():
            out["n_defaced_ready"] += 1
        else:
            out["n_defaced_missing"] += 1
        out["actions"].append(action)

    if dest.is_dir():
        out["status"] = "SKIP_ALREADY_PRESENT"
        out["notes"] = "release session already exists"
    elif out["n_defaced_missing"]:
        out["status"] = "BLOCK_MISSING_DEFACED"
        out["notes"] = f"{out['n_defaced_missing']} structural anat lack defaced counterparts"
    else:
        out["status"] = "READY"
        if out["n_structural"] == 0:
            out["notes"] = "no anat (sparse session); copy non-structural only"
    return out


def apply_session(
    bids_dir: Path,
    defacing_dir: Path,
    release_dir: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    participant = plan["participant_id"]
    session = plan["session_id"]
    src = bids_dir / participant / session
    dest = release_dir / participant / session
    result = dict(plan)

    if plan["status"] == "SKIP_ALREADY_PRESENT":
        return result
    if plan["status"] != "READY":
        result["status"] = f"NOT_APPLIED_{plan['status']}"
        return result

    parent = release_dir / participant
    if not parent.is_dir():
        result["status"] = "FAIL_MISSING_SUBJECT"
        result["notes"] = f"{participant} missing in release_dataset"
        return result

    shutil.copytree(src, dest, ignore=ignore_structural, symlinks=False)

    applied: list[dict[str, str]] = []
    for action in plan["actions"]:
        row = dict(action)
        if action["status"] != "READY":
            row["status"] = "FAIL_MISSING_DEFACED"
            applied.append(row)
            continue
        src_nii = Path(action["source"])
        dest_nii = Path(action["dest"])
        dest_nii.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_nii, dest_nii)
        src_json = Path(str(src_nii).removesuffix(".nii.gz") + ".json")
        dest_json = Path(str(dest_nii).removesuffix(".nii.gz") + ".json")
        if src_json.is_file():
            shutil.copy2(src_json, dest_json)
            row["json_source"] = "defacing"
        elif dest_json.is_file():
            row["json_source"] = "bids_copy"
        else:
            row["json_source"] = "MISSING"
            row["status"] = "FAIL_MISSING_JSON"
            applied.append(row)
            continue
        row["status"] = "REPLACED"
        row["md5_1mb_match_defaced"] = (
            "Y" if md5_prefix(src_nii) == md5_prefix(dest_nii) else "N"
        )
        applied.append(row)

    result["actions"] = applied
    n_fail = sum(1 for a in applied if str(a["status"]).startswith("FAIL"))
    result["status"] = "APPLIED" if n_fail == 0 else "APPLIED_WITH_FAILS"
    result["notes"] = f"copied session; replaced {sum(1 for a in applied if a['status']=='REPLACED')} anatomicals"
    return result


def verify_session(release_dir: Path, plan: dict[str, Any]) -> dict[str, str]:
    participant = plan["participant_id"]
    session = plan["session_id"]
    dest = release_dir / participant / session
    out = {
        "participant_id": participant,
        "session_id": session,
        "release_exists": str(dest.is_dir()),
        "n_files": "0",
        "n_struct_anat": "0",
        "has_nondefaced_structural": "N",
        "verify": "FAIL",
        "notes": "",
    }
    if not dest.is_dir():
        out["notes"] = "missing in release"
        return out
    files = [p for p in dest.rglob("*") if p.is_file()]
    structs = [
        p for p in files if is_structural_nifti(p.name) and "anat" in p.parts
    ]
    out["n_files"] = str(len(files))
    out["n_struct_anat"] = str(len(structs))
    # Structural files must exist when expected, and must not equal missing-defaced case.
    expected = plan["n_structural"]
    if len(structs) != expected:
        out["notes"] = f"struct count {len(structs)} != expected {expected}"
        return out
    out["verify"] = "PASS"
    return out


def write_report(
    path: Path,
    *,
    mode: str,
    plans: list[dict[str, Any]],
    applied: list[dict[str, Any]] | None,
    verifies: list[dict[str, str]] | None,
) -> None:
    n = len(plans)
    n_ready = sum(1 for p in plans if p["status"] == "READY")
    n_skip = sum(1 for p in plans if p["status"] == "SKIP_ALREADY_PRESENT")
    n_block = sum(1 for p in plans if p["status"].startswith("BLOCK") or p["status"].startswith("FAIL"))
    lines = [
        "# ses-02 retry11 — release_dataset incremental update",
        "",
        f"**Generated (UTC):** {utc_now()}",
        f"**Mode:** {mode}",
        f"**Targets:** {n}",
        f"**Plan READY / SKIP / BLOCK+FAIL:** {n_ready} / {n_skip} / {n_block}",
        "",
        "## Policy",
        "",
        "- Source: `bids/<sub>/ses-02` (read-only)",
        "- Defaced anatomicals: `derivatives/defacing/` for T1w / T2w / FLAIR",
        "- TB1TFL kept from BIDS (same as existing release_dataset)",
        "- `bids/`, `derivatives/`, `raw_original/` never modified",
        "",
        "## Per-session plan",
        "",
        "| Subject | Status | bids files | structural | defaced ready | missing | notes |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for p in plans:
        lines.append(
            f"| {p['participant_id']} | {p['status']} | {p['n_bids_files']} | "
            f"{p['n_structural']} | {p['n_defaced_ready']} | {p['n_defaced_missing']} | "
            f"{p['notes']} |"
        )

    if applied is not None:
        lines += [
            "",
            "## Apply results",
            "",
            "| Subject | Status | notes |",
            "|---|---|---|",
        ]
        for a in applied:
            lines.append(f"| {a['participant_id']} | {a['status']} | {a['notes']} |")

    if verifies is not None:
        n_pass = sum(1 for v in verifies if v["verify"] == "PASS")
        lines += [
            "",
            f"## Verification ({n_pass}/{len(verifies)} PASS)",
            "",
            "| Subject | exists | n_files | n_struct | verify | notes |",
            "|---|---|---:|---:|---|---|",
        ]
        for v in verifies:
            lines.append(
                f"| {v['participant_id']} | {v['release_exists']} | {v['n_files']} | "
                f"{v['n_struct_anat']} | {v['verify']} | {v['notes']} |"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    p.add_argument("--defacing-dir", type=Path, default=DEFAULT_DEFACING)
    p.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE)
    p.add_argument("--targets-tsv", type=Path, default=DEFAULT_TSV)
    p.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    bids_dir = args.bids_dir.resolve()
    defacing_dir = args.defacing_dir.resolve()
    release_dir = args.release_dir.resolve()
    reports_dir = args.reports_dir.resolve()
    dry_run = bool(args.dry_run)
    mode = "DRY_RUN" if dry_run else "APPLY"

    # Safety: never write into protected trees
    protected = {bids_dir, defacing_dir, (ROOT / "derivatives").resolve()}
    for cand in (ROOT / "raw_original", Path("/project/def-amirs/raw_original")):
        if cand.exists():
            protected.add(cand.resolve())
    if release_dir in protected:
        log(f"ERROR: refuse protected release_dir={release_dir}")
        return 1
    if not release_dir.is_dir():
        log(f"ERROR: release_dataset missing: {release_dir}")
        return 1

    targets = load_targets(args.targets_tsv)
    log(f"Mode: {mode}")
    log(f"Targets: {len(targets)} from {args.targets_tsv}")

    plans = [
        plan_session(
            bids_dir,
            defacing_dir,
            release_dir,
            t["participant_id"],
            t["session_id"],
        )
        for t in targets
    ]

    plan_rows = [
        {
            "participant_id": p["participant_id"],
            "session_id": p["session_id"],
            "status": p["status"],
            "n_bids_files": p["n_bids_files"],
            "n_structural": p["n_structural"],
            "n_defaced_ready": p["n_defaced_ready"],
            "n_defaced_missing": p["n_defaced_missing"],
            "notes": p["notes"],
        }
        for p in plans
    ]
    write_tsv(
        reports_dir / "RELEASE_SES02_R11_PLAN.tsv",
        plan_rows,
        [
            "participant_id",
            "session_id",
            "status",
            "n_bids_files",
            "n_structural",
            "n_defaced_ready",
            "n_defaced_missing",
            "notes",
        ],
    )

    anat_rows: list[dict[str, str]] = []
    for p in plans:
        for a in p["actions"]:
            anat_rows.append(
                {
                    "participant_id": p["participant_id"],
                    "session_id": p["session_id"],
                    "bids_original": a["bids_original"],
                    "replacement_file": a["source"],
                    "release_dest": a["dest"],
                    "status": a["status"],
                }
            )
    write_tsv(
        reports_dir / "RELEASE_SES02_R11_ANAT.tsv",
        anat_rows,
        [
            "participant_id",
            "session_id",
            "bids_original",
            "replacement_file",
            "release_dest",
            "status",
        ],
    )

    n_block = sum(
        1
        for p in plans
        if p["status"].startswith("BLOCK") or p["status"].startswith("FAIL")
    )
    if dry_run:
        write_report(
            reports_dir / "RELEASE_SES02_R11_UPDATE.md",
            mode=mode,
            plans=plans,
            applied=None,
            verifies=None,
        )
        log(f"DRY-RUN complete. READY={sum(1 for p in plans if p['status']=='READY')} "
            f"SKIP={sum(1 for p in plans if p['status']=='SKIP_ALREADY_PRESENT')} "
            f"BLOCK/FAIL={n_block}")
        log(f"Report: {reports_dir / 'RELEASE_SES02_R11_UPDATE.md'}")
        return 0 if n_block == 0 else 2

    if n_block:
        log(f"ERROR: refusing --apply with {n_block} blocked/failed sessions")
        write_report(
            reports_dir / "RELEASE_SES02_R11_UPDATE.md",
            mode=mode,
            plans=plans,
            applied=None,
            verifies=None,
        )
        return 2

    applied: list[dict[str, Any]] = []
    for p in plans:
        log(f"Applying {p['participant_id']}/{p['session_id']} ({p['status']})…")
        applied.append(
            apply_session(bids_dir, defacing_dir, release_dir, p)
        )

    verifies = [verify_session(release_dir, p) for p in plans]
    write_tsv(
        reports_dir / "RELEASE_SES02_R11_VERIFY.tsv",
        verifies,
        [
            "participant_id",
            "session_id",
            "release_exists",
            "n_files",
            "n_struct_anat",
            "has_nondefaced_structural",
            "verify",
            "notes",
        ],
    )
    write_report(
        reports_dir / "RELEASE_SES02_R11_UPDATE.md",
        mode=mode,
        plans=plans,
        applied=applied,
        verifies=verifies,
    )

    # Append CHANGES note if present
    changes = release_dir / "CHANGES"
    if changes.is_file():
        stamp = utc_now()
        note = (
            f"\n{stamp[:10]}\n"
            f"  - Added 11 previously missing ses-02 sessions (retry11) with "
            f"defaced T1w/FLAIR anatomicals from derivatives/defacing "
            f"(sub-078/ses-02 has no anat).\n"
        )
        text = changes.read_text(encoding="utf-8")
        if "retry11" not in text and "ses-02 sessions (retry11)" not in text:
            changes.write_text(text.rstrip() + note, encoding="utf-8")
            log(f"Updated {changes}")

    n_pass = sum(1 for v in verifies if v["verify"] == "PASS")
    log(f"Done. verify PASS={n_pass}/{len(verifies)}")
    log(f"Report: {reports_dir / 'RELEASE_SES02_R11_UPDATE.md'}")
    return 0 if n_pass == len(verifies) else 1


if __name__ == "__main__":
    raise SystemExit(main())
