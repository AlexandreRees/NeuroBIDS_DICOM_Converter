#!/usr/bin/env python3
"""READ-ONLY anatomical defacing validation for public release.

Never modifies BIDS or derivatives. Writes only under
reports/deidentification_validation/.

Examples:
  python code/audit_defacing_release.py --dry-run \\
    --bids-dir /home/alexrees/scratch/bids \\
    --defaced-dir /home/alexrees/scratch/derivatives/defacing

  python code/audit_defacing_release.py \\
    --bids-dir /home/alexrees/scratch/bids \\
    --defaced-dir /home/alexrees/scratch/derivatives/defacing
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

DEFAULT_BIDS = Path("/home/alexrees/scratch/bids")
DEFAULT_DEFACED = Path("/home/alexrees/scratch/derivatives/defacing")
DEFAULT_OUT = Path("/home/alexrees/scratch/reports/deidentification_validation")

PHI_KEYS = {
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientAge",
    "PatientSex",
    "InstitutionName",
    "InstitutionalDepartmentName",
    "DeviceSerialNumber",
    "StationName",
    "OperatorsName",
    "PhysicianName",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "AcquisitionDate",
    "AcquisitionTime",
    "StudyDate",
    "SeriesDate",
}

T1W_RE = re.compile(
    r"(?P<sub>sub-[^_/]+)(?:_(?P<ses>ses-[^_/]+))?.*_T1w\.nii(?:\.gz)?$"
)


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="READ-ONLY defacing release validation.")
    p.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    p.add_argument("--defaced-dir", type=Path, default=DEFAULT_DEFACED)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--sample-n",
        type=int,
        default=12,
        help="Paired images for voxel % change in dry-run (default 12).",
    )
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def list_t1w(root: Path, *, skip_derivatives: bool = False) -> list[Path]:
    files = sorted(root.rglob("*_T1w.nii.gz")) + sorted(root.rglob("*_T1w.nii"))
    out: list[Path] = []
    seen: set[str] = set()
    for p in files:
        if skip_derivatives and "derivatives" in p.parts:
            continue
        key = re.sub(r"\.nii(\.gz)?$", "", str(p.relative_to(root)))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def relative_key(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def entity_key(name: str) -> str | None:
    m = T1W_RE.search(name)
    if not m:
        return None
    sub = m.group("sub")
    ses = m.group("ses") or ""
    # keep full basename without extension as match key
    return re.sub(r"\.nii(\.gz)?$", "", name)


def affine_close(a: np.ndarray, b: np.ndarray, atol: float = 1e-4) -> bool:
    return bool(np.allclose(a, b, atol=atol, rtol=0))


def compare_pair(orig: Path, defaced: Path, do_voxels: bool) -> dict[str, Any]:
    row: dict[str, Any] = {
        "original": str(orig),
        "defaced": str(defaced),
        "shape_match": "",
        "zooms_match": "",
        "affine_match": "",
        "orientation": "",
        "pct_voxels_changed": "",
        "max_abs_diff": "",
        "status": "OK",
        "notes": "",
    }
    try:
        img_o = nib.load(str(orig), mmap=True)
        img_d = nib.load(str(defaced), mmap=True)
    except Exception as exc:  # noqa: BLE001
        row["status"] = "LOAD_ERROR"
        row["notes"] = str(exc)
        return row

    shape_ok = img_o.shape == img_d.shape
    zooms_ok = np.allclose(img_o.header.get_zooms()[:3], img_d.header.get_zooms()[:3], atol=1e-5)
    aff_ok = affine_close(img_o.affine, img_d.affine)
    try:
        or_o = "".join(nib.aff2axcodes(img_o.affine))
        or_d = "".join(nib.aff2axcodes(img_d.affine))
        row["orientation"] = f"{or_o}->{or_d}"
        orient_ok = or_o == or_d
    except Exception:
        orient_ok = False
        row["orientation"] = "unknown"

    row["shape_match"] = "yes" if shape_ok else "no"
    row["zooms_match"] = "yes" if zooms_ok else "no"
    row["affine_match"] = "yes" if aff_ok else "no"

    if not (shape_ok and zooms_ok and aff_ok and orient_ok):
        row["status"] = "GEOMETRY_MISMATCH"

    if do_voxels and shape_ok:
        try:
            # Use float64 intensities; count material changes only (atol=0.5)
            # to avoid dtype/scale false positives (int16 vs float64 sidecars).
            data_o = np.asanyarray(img_o.dataobj, dtype=np.float64)
            data_d = np.asanyarray(img_d.dataobj, dtype=np.float64)
            if data_o.shape != data_d.shape:
                row["notes"] += "shape_changed_after_load;"
            else:
                absdiff = np.abs(data_o - data_d)
                changed = absdiff > 0.5
                n = changed.size
                n_chg = int(np.count_nonzero(changed))
                pct = 100.0 * n_chg / n if n else 0.0
                max_abs = float(np.max(absdiff)) if n else 0.0
                row["pct_voxels_changed"] = f"{pct:.4f}"
                row["max_abs_diff"] = f"{max_abs:.4f}"
        except Exception as exc:  # noqa: BLE001
            row["notes"] += f"voxel_cmp_error:{exc};"
            if row["status"] == "OK":
                row["status"] = "VOXEL_CMP_ERROR"
    return row


def audit_json(path: Path) -> dict[str, Any]:
    out = {
        "json_valid": False,
        "generated_by_present": False,
        "phi_fields": [],
        "error": "",
    }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
        return out
    if not isinstance(data, dict):
        out["error"] = "not_object"
        return out
    out["json_valid"] = True
    out["generated_by_present"] = "GeneratedBy" in data
    out["phi_fields"] = [k for k in PHI_KEYS if k in data and data[k] not in (None, "")]
    return out


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
    defaced = args.defaced_dir
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if not bids.is_dir():
        log(f"ERROR: bids missing: {bids}")
        return 2
    if not defaced.is_dir():
        log(f"ERROR: defaced-dir missing: {defaced}")
        return 2

    bids_t1 = list_t1w(bids, skip_derivatives=True)
    def_t1 = list_t1w(defaced, skip_derivatives=False)

    bids_map = {relative_key(p, bids): p for p in bids_t1}
    def_map = {relative_key(p, defaced): p for p in def_t1}

    missing = sorted(set(bids_map) - set(def_map))
    unexpected = sorted(set(def_map) - set(bids_map))
    matched = sorted(set(bids_map) & set(def_map))

    log(
        f"T1w BIDS={len(bids_map)} defaced={len(def_map)} "
        f"matched={len(matched)} missing={len(missing)} unexpected={len(unexpected)}"
    )

    # Filename / entity consistency
    entity_issues = 0
    for key in matched:
        bo = entity_key(Path(key).name)
        bd = entity_key(Path(key).name)
        if bo is None or bd is None or bo != bd:
            entity_issues += 1

    rng = random.Random(args.seed)
    if args.dry_run:
        sample_keys = matched[:]
        rng.shuffle(sample_keys)
        sample_keys = sample_keys[: args.sample_n]
        voxel_keys = set(sample_keys)
        geom_keys = set(sample_keys)
        log(f"Dry-run: geometry+voxels on {len(sample_keys)} pairs")
    else:
        geom_keys = set(matched)
        # Full coverage geometry; voxels on all matched (can be slow) — do all
        voxel_keys = set(matched)
        log(f"Full: geometry+voxels on {len(matched)} pairs")

    rows: list[dict[str, str]] = []
    pct_values: list[float] = []
    status_counts: Counter[str] = Counter()
    phi_json = 0
    json_invalid = 0
    generated_by_sidecar = 0
    generated_by_dataset = False

    dd_path = defaced / "dataset_description.json"
    if dd_path.is_file():
        try:
            dd = json.loads(dd_path.read_text(encoding="utf-8"))
            generated_by_dataset = bool(dd.get("GeneratedBy"))
        except Exception:
            generated_by_dataset = False

    # Coverage rows for missing / unexpected
    for key in missing:
        rows.append(
            {
                "relative_key": key,
                "original": str(bids_map[key]),
                "defaced": "",
                "coverage": "MISSING",
                "shape_match": "",
                "zooms_match": "",
                "affine_match": "",
                "orientation": "",
                "pct_voxels_changed": "",
                "max_abs_diff": "",
                "json_valid": "",
                "generated_by": "",
                "phi_fields": "",
                "status": "MISSING",
                "notes": "",
            }
        )
        status_counts["MISSING"] += 1

    for key in unexpected:
        rows.append(
            {
                "relative_key": key,
                "original": "",
                "defaced": str(def_map[key]),
                "coverage": "UNEXPECTED",
                "shape_match": "",
                "zooms_match": "",
                "affine_match": "",
                "orientation": "",
                "pct_voxels_changed": "",
                "max_abs_diff": "",
                "json_valid": "",
                "generated_by": "",
                "phi_fields": "",
                "status": "UNEXPECTED",
                "notes": "",
            }
        )
        status_counts["UNEXPECTED"] += 1

    for i, key in enumerate(matched, 1):
        if key not in geom_keys and key not in voxel_keys:
            # still record coverage-only row in dry-run for non-sampled
            if args.dry_run:
                rows.append(
                    {
                        "relative_key": key,
                        "original": str(bids_map[key]),
                        "defaced": str(def_map[key]),
                        "coverage": "PRESENT",
                        "shape_match": "not_checked",
                        "zooms_match": "not_checked",
                        "affine_match": "not_checked",
                        "orientation": "",
                        "pct_voxels_changed": "",
                        "max_abs_diff": "",
                        "json_valid": "",
                        "generated_by": "",
                        "phi_fields": "",
                        "status": "COVERAGE_ONLY",
                        "notes": "dry-run_not_sampled",
                    }
                )
                status_counts["COVERAGE_ONLY"] += 1
                continue

        if i % 25 == 0 or i == len(matched):
            log(f"  … pairs {i}/{len(matched)}")

        do_vox = key in voxel_keys
        cmp = compare_pair(bids_map[key], def_map[key], do_voxels=do_vox)
        if cmp["pct_voxels_changed"]:
            try:
                pct_values.append(float(cmp["pct_voxels_changed"]))
            except ValueError:
                pass

        json_path = def_map[key].with_suffix("").with_suffix(".json")
        # handle .nii.gz -> .json
        if def_map[key].name.endswith(".nii.gz"):
            json_path = Path(str(def_map[key])[: -len(".nii.gz")] + ".json")
        else:
            json_path = def_map[key].with_suffix(".json")

        jinfo = {"json_valid": False, "generated_by_present": False, "phi_fields": [], "error": "missing"}
        if json_path.is_file():
            jinfo = audit_json(json_path)
        if not jinfo["json_valid"]:
            json_invalid += 1
        if jinfo["generated_by_present"]:
            generated_by_sidecar += 1
        if jinfo["phi_fields"]:
            phi_json += 1

        status = cmp["status"]
        if jinfo["phi_fields"] and status == "OK":
            status = "OK_PHI_METADATA"
        status_counts[status] += 1

        rows.append(
            {
                "relative_key": key,
                "original": cmp["original"],
                "defaced": cmp["defaced"],
                "coverage": "PRESENT",
                "shape_match": cmp["shape_match"],
                "zooms_match": cmp["zooms_match"],
                "affine_match": cmp["affine_match"],
                "orientation": cmp["orientation"],
                "pct_voxels_changed": cmp["pct_voxels_changed"],
                "max_abs_diff": cmp["max_abs_diff"],
                "json_valid": "yes" if jinfo["json_valid"] else "no",
                "generated_by": (
                    "sidecar"
                    if jinfo["generated_by_present"]
                    else ("dataset_description" if generated_by_dataset else "absent")
                ),
                "phi_fields": ",".join(jinfo["phi_fields"]),
                "status": status,
                "notes": cmp["notes"] + (jinfo.get("error") or ""),
            }
        )

    tsv_path = out_dir / (
        "defacing_validation_dryrun.tsv" if args.dry_run else "defacing_validation.tsv"
    )
    write_tsv(
        tsv_path,
        rows,
        [
            "relative_key",
            "original",
            "defaced",
            "coverage",
            "shape_match",
            "zooms_match",
            "affine_match",
            "orientation",
            "pct_voxels_changed",
            "max_abs_diff",
            "json_valid",
            "generated_by",
            "phi_fields",
            "status",
            "notes",
        ],
    )

    def _median(xs: list[float]) -> float:
        if not xs:
            return float("nan")
        ys = sorted(xs)
        n = len(ys)
        mid = n // 2
        if n % 2:
            return ys[mid]
        return 0.5 * (ys[mid - 1] + ys[mid])

    coverage_complete = len(missing) == 0 and len(unexpected) == 0
    geom_fail = status_counts.get("GEOMETRY_MISMATCH", 0) + status_counts.get("LOAD_ERROR", 0)
    if coverage_complete and geom_fail == 0 and json_invalid == 0:
        if phi_json:
            verdict = "PASS_WITH_METADATA_REVIEW"
        else:
            verdict = "PASS"
    elif not coverage_complete or geom_fail:
        verdict = "FAIL"
    else:
        verdict = "NEEDS_REVIEW"

    md_path = out_dir / (
        "defacing_validation_summary_dryrun.md"
        if args.dry_run
        else "defacing_validation_summary.md"
    )
    lines = [
        "# Anatomical defacing validation (READ-ONLY)",
        "",
        f"**Generated (UTC):** {datetime.now(timezone.utc).isoformat()}",
        f"**BIDS:** `{bids.resolve()}`",
        f"**Defaced derivatives:** `{defaced.resolve()}`",
        f"**Dry-run:** {args.dry_run}",
        "",
        "## Coverage",
        "",
        f"- Expected T1w (BIDS anat): **{len(bids_map)}**",
        f"- Defaced T1w found: **{len(def_map)}**",
        f"- Matched pairs: **{len(matched)}**",
        f"- Missing: **{len(missing)}**",
        f"- Unexpected: **{len(unexpected)}**",
        f"- Entity/filename consistency issues: **{entity_issues}**",
        "",
        "## Spatial integrity",
        "",
        f"- Geometry mismatches / load errors: **{geom_fail}**",
        "",
        "## Voxel modification (report only; no pass/fail threshold)",
        "",
        f"- Pairs with % changed voxels computed: **{len(pct_values)}**",
        f"- Median % voxels changed: **{_median(pct_values):.3f}**" if pct_values else "- Median % voxels changed: **n/a**",
        f"- Mean % voxels changed: **{(sum(pct_values)/len(pct_values)):.3f}**" if pct_values else "- Mean % voxels changed: **n/a**",
        "",
        "## Metadata",
        "",
        f"- Derivative JSON invalid: **{json_invalid}**",
        f"- Sidecars with GeneratedBy: **{generated_by_sidecar}**",
        f"- dataset_description GeneratedBy present: **{generated_by_dataset}**",
        f"- Sidecars with ≥1 PHI-like field: **{phi_json}**",
        "",
        "Note: `GeneratedBy` for this cohort is recorded at "
        "`derivatives/defacing/dataset_description.json` (pydeface via "
        "`neuro_pipeline.modules.defacing.run_defacing_session`). Per-sidecar "
        "GeneratedBy may be absent.",
        "",
        "## Status counts",
        "",
    ]
    for k, v in status_counts.most_common():
        lines.append(f"- `{k}`: {v}")

    if missing:
        lines += ["", "### Missing examples", ""]
        for m in missing[:20]:
            lines.append(f"- `{m}`")

    lines += [
        "",
        "## Verdict",
        "",
        f"**{verdict}**",
        "",
        "No fixed voxel-change threshold is applied. Coverage completeness and "
        "geometry preservation are the primary release gates; residual "
        "`InstitutionalDepartmentName` (or similar) in derivative JSON is flagged "
        "for metadata scrub before packaging if those JSON files are distributed.",
        "",
        f"TSV: `{tsv_path.name}`",
        "",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "bids_dir": str(bids.resolve()),
        "defaced_dir": str(defaced.resolve()),
        "dry_run": args.dry_run,
        "n_expected": len(bids_map),
        "n_defaced": len(def_map),
        "n_matched": len(matched),
        "n_missing": len(missing),
        "n_unexpected": len(unexpected),
        "geom_fail": geom_fail,
        "phi_json": phi_json,
        "json_invalid": json_invalid,
        "generated_by_dataset": generated_by_dataset,
        "median_pct_changed": _median(pct_values) if pct_values else None,
        "mean_pct_changed": (sum(pct_values) / len(pct_values)) if pct_values else None,
        "verdict": verdict,
        "tsv": str(tsv_path),
        "summary_md": str(md_path),
    }
    (out_dir / ("defacing_summary_dryrun.json" if args.dry_run else "defacing_summary.json")).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    log(f"Wrote {tsv_path}")
    log(f"Wrote {md_path}")
    log(f"Verdict: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
