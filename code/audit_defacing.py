#!/usr/bin/env python3
"""Read-only defacing audit for Scientific Data publication readiness.

Never modifies BIDS inputs, derivatives, NIfTI images, or JSON metadata.
All outputs are written under reports/defacing_audit/ only.

Examples:
  # Dry audit (coverage + structure + small image sample)
  python code/audit_defacing.py \\
    --bids-dir /home/alexrees/scratch/bids \\
    --dry-run

  # Full audit
  python code/audit_defacing.py \\
    --bids-dir /home/alexrees/scratch/bids
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd

DEFAULT_BIDS = Path("/home/alexrees/scratch/bids")
DEFAULT_OUTPUT = Path("/home/alexrees/scratch/reports/defacing_audit")
CANDIDATE_DEFACING_DIRS = (
    Path("/home/alexrees/scratch/bids/derivatives/defacing"),
    Path("/home/alexrees/scratch/derivatives/defacing"),
)

PHI_KEYS = {
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientAge",
    "PatientSex",
    "PatientWeight",
    "OtherPatientIDs",
    "OtherPatientNames",
    "InstitutionName",
    "InstitutionalDepartmentName",
    "InstitutionAddress",
    "AccessionNumber",
    "StudyDate",
    "SeriesDate",
    "AcquisitionDate",
    "AcquisitionDateTime",
    "ContentDate",
    "StudyTime",
    "SeriesTime",
    "AcquisitionTime",
    "ContentTime",
}

PRESERVE_KEYS = (
    "RepetitionTime",
    "EchoTime",
    "FlipAngle",
    "MagneticFieldStrength",
    "Manufacturer",
    "ProtocolName",
)

ENTITY_RE = re.compile(
    r"(?P<subject>sub-[^_/]+)(?:_(?P<session>ses-[^_/]+))?(?:_.*)?_T1w\.nii\.gz$"
)


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Read-only BIDS defacing audit.")
    p.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    p.add_argument(
        "--defacing-dir",
        type=Path,
        default=None,
        help="Defaced derivatives root. Auto-detected if omitted.",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Report directory (default: {DEFAULT_OUTPUT}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Coverage + structure + metadata sample; limit image pairwise QC.",
    )
    p.add_argument(
        "--sample-n",
        type=int,
        default=8,
        help="Paired images for difference/visual QC in dry-run (default: 8).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for representative figure selection.",
    )
    return p.parse_args()


def resolve_defacing_dir(explicit: Path | None, bids_dir: Path) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    candidates.extend(
        [
            bids_dir / "derivatives" / "defacing",
            bids_dir.parent / "derivatives" / "defacing",
            *CANDIDATE_DEFACING_DIRS,
        ]
    )
    seen: set[Path] = set()
    for cand in candidates:
        cand = cand.resolve()
        if cand in seen:
            continue
        seen.add(cand)
        if cand.is_dir() and any(cand.rglob("*_T1w.nii.gz")):
            return cand
    # Fall back to preferred documented path even if empty (audit will FAIL)
    if explicit is not None:
        return explicit.resolve()
    return (bids_dir / "derivatives" / "defacing").resolve()


def parse_entities(nifti: Path) -> tuple[str, str, str]:
    """Return subject, session, relative key sub-*/ses-*/anat/filename."""
    match = ENTITY_RE.search(nifti.name)
    subject = match.group("subject") if match else "unknown"
    session = (match.group("session") if match else None) or "n/a"
    parts = nifti.parts
    try:
        i = next(i for i, x in enumerate(parts) if x.startswith("sub-"))
        rel = "/".join(parts[i:])
    except StopIteration:
        rel = nifti.name
    return subject, session, rel


def find_t1w(root: Path, *, source_bids: bool) -> list[Path]:
    """Find T1w NIfTIs under root.

    If source_bids is True, skip anything under a derivatives/ folder.
    If False, treat root as a derivative tree and keep anat T1w files.
    """
    files: list[Path] = []
    if not root.is_dir():
        return files
    for p in sorted(root.rglob("*_T1w.nii.gz")):
        if source_bids and "derivatives" in p.parts:
            continue
        if not source_bids and "anat" not in p.parts:
            continue
        files.append(p)
    return files


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        log(f"WARNING: failed to read JSON {path}: {exc}")
        return None


def geometry_record(path: Path) -> dict[str, Any]:
    img = nib.load(str(path))
    hdr = img.header
    aff = np.asarray(img.affine, dtype=float)
    zooms = tuple(float(z) for z in hdr.get_zooms()[:3])
    shape = tuple(int(s) for s in img.shape)
    ornt = nib.aff2axcodes(aff)
    return {
        "path": str(path),
        "shape": shape,
        "zooms": zooms,
        "orientation": "".join(ornt),
        "affine": aff,
        "datatype": str(hdr.get_data_dtype()),
        "ndim": int(img.ndim),
    }


def compare_geometry(orig: dict[str, Any], defaced: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if orig["shape"] != defaced["shape"]:
        flags.append("dimension_mismatch")
    if not np.allclose(orig["zooms"], defaced["zooms"], rtol=0, atol=1e-5):
        flags.append("resolution_mismatch")
    if orig["orientation"] != defaced["orientation"]:
        flags.append("orientation_mismatch")
    if not np.allclose(orig["affine"], defaced["affine"], rtol=0, atol=1e-4):
        flags.append("affine_mismatch")
    if orig["ndim"] != defaced["ndim"]:
        flags.append("ndim_mismatch")
    if flags and ("dimension_mismatch" in flags or "resolution_mismatch" in flags):
        flags.append("unexpected_resampling")
    return flags


def phi_findings(meta: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    for key in meta:
        if key in PHI_KEYS:
            hits.append(key)
    return sorted(set(hits))


def voxel_difference(orig_path: Path, def_path: Path) -> dict[str, float]:
    o = np.asanyarray(nib.load(str(orig_path)).dataobj)
    d = np.asanyarray(nib.load(str(def_path)).dataobj)
    if o.shape != d.shape:
        return {
            "changed_voxel_percentage": np.nan,
            "changed_voxel_count": np.nan,
            "mean_difference": np.nan,
            "max_difference": np.nan,
            "changed_voxel_volume_mm3": np.nan,
        }
    # Defaced outputs may be float-encoded; compare in float with a 0.5
    # intensity threshold so tiny float rounding is not counted as change.
    o_f = o.astype(np.float64, copy=False)
    d_f = d.astype(np.float64, copy=False)
    diff = np.abs(o_f - d_f)
    changed = diff > 0.5
    n_changed = int(changed.sum())
    n_total = int(diff.size)
    zooms = nib.load(str(orig_path)).header.get_zooms()[:3]
    vox_vol = float(np.prod(zooms))
    return {
        "changed_voxel_percentage": 100.0 * n_changed / n_total if n_total else np.nan,
        "changed_voxel_count": float(n_changed),
        "mean_difference": float(diff.mean()),
        "max_difference": float(diff.max()) if n_total else np.nan,
        "changed_voxel_volume_mm3": float(n_changed * vox_vol),
    }


def metadata_compare(
    orig: dict[str, Any] | None, der: dict[str, Any] | None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "phi_in_derivative": [],
        "preserved_ok": True,
        "missing_preserved_keys": [],
        "changed_preserved_keys": [],
    }
    if der is None:
        out["preserved_ok"] = False
        out["missing_preserved_keys"] = list(PRESERVE_KEYS)
        return out
    out["phi_in_derivative"] = phi_findings(der)
    if orig is None:
        out["preserved_ok"] = False
        return out
    missing = []
    changed = []
    for key in PRESERVE_KEYS:
        if key not in der:
            missing.append(key)
            continue
        if key in orig and orig[key] != der[key]:
            changed.append(key)
    out["missing_preserved_keys"] = missing
    out["changed_preserved_keys"] = changed
    out["preserved_ok"] = not missing and not changed
    return out


def check_dataset_description(defacing_dir: Path) -> dict[str, Any]:
    path = defacing_dir / "dataset_description.json"
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "has_Name": False,
        "has_BIDSVersion": False,
        "has_GeneratedBy": False,
        "GeneratedBy": None,
        "violations": [],
        "provenance_missing": True,
    }
    if not path.is_file():
        result["violations"].append("missing_dataset_description.json")
        return result
    data = load_json(path) or {}
    result["has_Name"] = "Name" in data
    result["has_BIDSVersion"] = "BIDSVersion" in data
    result["has_GeneratedBy"] = "GeneratedBy" in data
    if not result["has_Name"]:
        result["violations"].append("dataset_description.missing_Name")
    if not result["has_BIDSVersion"]:
        result["violations"].append("dataset_description.missing_BIDSVersion")
    if not result["has_GeneratedBy"]:
        result["violations"].append("dataset_description.missing_GeneratedBy")
    gb = data.get("GeneratedBy")
    result["GeneratedBy"] = gb
    if gb:
        result["provenance_missing"] = False
    return result


def structure_violations(defacing_dir: Path, defaced_files: list[Path]) -> list[str]:
    violations: list[str] = []
    for p in defaced_files:
        rel = p.relative_to(defacing_dir)
        parts = rel.parts
        if len(parts) < 4:
            violations.append(f"shallow_path:{rel}")
            continue
        if not parts[0].startswith("sub-"):
            violations.append(f"missing_sub_entity:{rel}")
        if not parts[1].startswith("ses-"):
            violations.append(f"missing_ses_entity:{rel}")
        if parts[2] != "anat":
            violations.append(f"missing_anat_folder:{rel}")
        if not p.name.endswith("_T1w.nii.gz"):
            violations.append(f"non_t1w_name:{rel}")
        # BIDS derivatives conventionally keep source entities; pydeface often
        # does not add desc- labels — note but do not hard-fail.
        if "desc-" not in p.name and "space-" not in p.name:
            # informational only via prefix
            pass
    return violations


def write_tsv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, sep="\t", index=False)


def coverage_audit(
    originals: list[Path], defaced: list[Path]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    orig_map: dict[str, list[Path]] = defaultdict(list)
    def_map: dict[str, list[Path]] = defaultdict(list)
    for p in originals:
        _, _, key = parse_entities(p)
        orig_map[key].append(p)
    for p in defaced:
        _, _, key = parse_entities(p)
        def_map[key].append(p)

    all_keys = sorted(set(orig_map) | set(def_map))
    rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []

    for key in all_keys:
        subject, session, _ = parse_entities(Path(key))
        # Prefer entities from path components
        parts = key.split("/")
        subject = next((x for x in parts if x.startswith("sub-")), subject)
        session = next((x for x in parts if x.startswith("ses-")), session)
        n_orig = len(orig_map.get(key, []))
        n_def = len(def_map.get(key, []))
        orig_exists = n_orig > 0
        def_exists = n_def > 0
        if orig_exists and def_exists and n_def == 1 and n_orig == 1:
            status = "PASS"
        elif orig_exists and not def_exists:
            status = "MISSING"
        elif not orig_exists and def_exists:
            status = "UNEXPECTED"
        elif n_def > 1 or n_orig > 1:
            status = "DUPLICATE"
        else:
            status = "UNEXPECTED"
        row = {
            "subject": subject,
            "session": session,
            "relative_key": key,
            "original_T1_exists": orig_exists,
            "defaced_T1_exists": def_exists,
            "n_original": n_orig,
            "n_defaced": n_def,
            "status": status,
            "original_path": str(orig_map[key][0]) if n_orig else "",
            "defaced_path": str(def_map[key][0]) if n_def else "",
        }
        rows.append(row)
        if status == "MISSING":
            missing_rows.append(row)

    inv = pd.DataFrame(rows)
    missing = pd.DataFrame(missing_rows)
    subjects_with_t1 = sorted({parse_entities(p)[0] for p in originals})
    sessions_with_t1 = sorted(
        {
            (parse_entities(p)[0], parse_entities(p)[1])
            for p in originals
        }
    )
    summary = {
        "total_subjects_with_T1w": len(subjects_with_t1),
        "total_sessions_with_T1w": len(sessions_with_t1),
        "total_T1w_expected": len(originals),
        "total_defaced_found": len(defaced),
        "missing_defacing_cases": int((inv["status"] == "MISSING").sum())
        if len(inv)
        else 0,
        "duplicated_defacing_outputs": int((inv["status"] == "DUPLICATE").sum())
        if len(inv)
        else 0,
        "unexpected_derivative_files": int((inv["status"] == "UNEXPECTED").sum())
        if len(inv)
        else 0,
        "pass_pairs": int((inv["status"] == "PASS").sum()) if len(inv) else 0,
    }
    return inv, missing, summary


def plot_coverage(inv: pd.DataFrame, out_path: Path) -> None:
    counts = inv["status"].value_counts() if len(inv) else pd.Series(dtype=int)
    labels = ["PASS", "MISSING", "DUPLICATE", "UNEXPECTED"]
    values = [int(counts.get(l, 0)) for l in labels]
    colors = ["#2a9d8f", "#e76f51", "#e9c46a", "#264653"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.bar(labels, values, color=colors)
    ax.set_ylabel("T1w cases")
    ax.set_title("Defacing coverage by status")
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.5, str(v), ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_voxel_summary(cmp_df: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    if len(cmp_df) and cmp_df["changed_voxel_percentage"].notna().any():
        axes[0].hist(
            cmp_df["changed_voxel_percentage"].dropna(),
            bins=20,
            color="#457b9d",
            edgecolor="white",
        )
        axes[0].set_xlabel("Changed voxels (%)")
        axes[0].set_ylabel("Count")
        axes[0].set_title("Facial voxel change fraction")
        axes[1].hist(
            cmp_df["max_difference"].dropna(),
            bins=20,
            color="#1d3557",
            edgecolor="white",
        )
        axes[1].set_xlabel("Max |Δ intensity|")
        axes[1].set_ylabel("Count")
        axes[1].set_title("Maximum intensity difference")
    else:
        for ax in axes:
            ax.text(0.5, 0.5, "No paired comparisons", ha="center", va="center")
            ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_before_after(
    pairs: list[tuple[Path, Path, str, str]], out_path: Path, n_examples: int = 3
) -> bool:
    if not pairs:
        return False
    n = min(n_examples, len(pairs))
    fig, axes = plt.subplots(n, 6, figsize=(14, 3.2 * n))
    if n == 1:
        axes = np.expand_dims(axes, 0)
    for i in range(n):
        orig_p, def_p, subject, session = pairs[i]
        o_img = nib.load(str(orig_p))
        d_img = nib.load(str(def_p))
        o = np.asanyarray(o_img.dataobj, dtype=np.float32)
        d = np.asanyarray(d_img.dataobj, dtype=np.float32)
        # Reorient both to RAS for consistent display
        o_ras = nib.as_closest_canonical(o_img)
        d_ras = nib.as_closest_canonical(d_img)
        o = np.asanyarray(o_ras.dataobj, dtype=np.float32)
        d = np.asanyarray(d_ras.dataobj, dtype=np.float32)
        if o.shape != d.shape:
            for j in range(6):
                axes[i, j].axis("off")
            axes[i, 0].set_title(f"{subject} {session}: shape mismatch", fontsize=9)
            continue
        # Shared intensity window from original brain-ish percentiles
        lo, hi = np.percentile(o, (1, 99))
        if hi <= lo:
            hi = lo + 1.0
        x, y, z = [s // 2 for s in o.shape[:3]]
        # axial (z), coronal (y), sagittal (x)
        views = [
            ("axial orig", o[:, :, z]),
            ("axial def", d[:, :, z]),
            ("coronal orig", o[:, y, :]),
            ("coronal def", d[:, y, :]),
            ("sagittal orig", o[x, :, :]),
            ("sagittal def", d[x, :, :]),
        ]
        for j, (title, sl) in enumerate(views):
            axes[i, j].imshow(np.rot90(sl), cmap="gray", vmin=lo, vmax=hi)
            axes[i, j].set_title(title if i == 0 else "", fontsize=8)
            axes[i, j].axis("off")
        axes[i, 0].set_ylabel(f"{subject}\n{session}", fontsize=8)
    fig.suptitle(
        "Defacing before/after (identical slice coords & intensity window; QC only)",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return True


def extract_provenance(ddesc: dict[str, Any], sample_jsons: list[Path]) -> dict[str, Any]:
    prov: dict[str, Any] = {
        "software_name": None,
        "version": None,
        "command": None,
        "date": None,
        "provenance_missing": True,
        "sources": [],
    }
    gb = ddesc.get("GeneratedBy")
    if isinstance(gb, list) and gb:
        first = gb[0] if isinstance(gb[0], dict) else {}
        prov["software_name"] = first.get("Name")
        prov["version"] = first.get("Version")
        prov["command"] = first.get("Code") or first.get("Command") or first.get("Description")
        prov["date"] = first.get("Date") or first.get("ContainerImage")
        prov["provenance_missing"] = not bool(prov["software_name"])
        prov["sources"].append("dataset_description.json:GeneratedBy")
    # Sidecar scan for pydeface / GeneratedBy
    for jp in sample_jsons[:50]:
        meta = load_json(jp) or {}
        if "GeneratedBy" in meta:
            prov["sources"].append(str(jp))
            if prov["provenance_missing"]:
                gb2 = meta["GeneratedBy"]
                if isinstance(gb2, list) and gb2 and isinstance(gb2[0], dict):
                    prov["software_name"] = gb2[0].get("Name")
                    prov["version"] = gb2[0].get("Version")
                    prov["command"] = gb2[0].get("Code") or gb2[0].get("Description")
                    prov["date"] = gb2[0].get("Date")
                    prov["provenance_missing"] = not bool(prov["software_name"])
            break
        for key in ("DefacedBy", "SkullStripped", "SourceSoftware", "pydeface"):
            if key in meta:
                prov["sources"].append(f"{jp}:{key}")
    return prov


def verdict_from_findings(
    cov: dict[str, Any],
    geom_flags: Counter,
    phi_count: int,
    provenance_missing: bool,
    structure_n: int,
    corrupt_n: int,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    fail = False
    warn = False

    if cov["missing_defacing_cases"] > 0:
        fail = True
        reasons.append(f"missing defaced images ({cov['missing_defacing_cases']})")
    if corrupt_n > 0:
        fail = True
        reasons.append(f"corrupted/unreadable files ({corrupt_n})")
    hard_geom = (
        geom_flags.get("dimension_mismatch", 0)
        + geom_flags.get("affine_mismatch", 0)
        + geom_flags.get("orientation_mismatch", 0)
        + geom_flags.get("unexpected_resampling", 0)
    )
    if hard_geom > 0:
        fail = True
        reasons.append(f"geometry mismatch flags ({hard_geom})")
    if phi_count > 0:
        warn = True
        reasons.append(f"PHI-like keys in derivative JSON ({phi_count})")
    if provenance_missing:
        warn = True
        reasons.append("missing/incomplete provenance")
    if structure_n > 0:
        warn = True
        reasons.append(f"structure violations ({structure_n})")
    if cov["duplicated_defacing_outputs"] > 0:
        warn = True
        reasons.append(f"duplicate outputs ({cov['duplicated_defacing_outputs']})")
    if cov["unexpected_derivative_files"] > 0:
        warn = True
        reasons.append(f"unexpected derivatives ({cov['unexpected_derivative_files']})")

    if fail:
        return "FAIL", reasons
    if warn:
        return "WARNING", reasons
    return "PASS", ["coverage complete", "metadata clean", "spatial integrity preserved"]


def write_summary(
    path: Path,
    *,
    mode: str,
    bids_dir: Path,
    defacing_dir: Path,
    cov: dict[str, Any],
    ddesc: dict[str, Any],
    structure_viols: list[str],
    geom_flags: Counter,
    cmp_df: pd.DataFrame,
    qc_df: pd.DataFrame,
    prov: dict[str, Any],
    verdict: str,
    reasons: list[str],
    n_image_qc: int,
    n_pairs_total: int,
) -> None:
    can_release = verdict in {"PASS", "WARNING"}
    release_answer = (
        "YES, with documented caveats"
        if verdict == "WARNING"
        else ("YES" if verdict == "PASS" else "NO — remediate blockers before public release")
    )
    lines = [
        "# Defacing audit summary",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Mode: **{mode}**",
        "",
        "## Paths (read-only)",
        "",
        f"- BIDS root: `{bids_dir}`",
        f"- Defacing derivatives: `{defacing_dir}`",
        f"- Report output: `{path.parent}`",
        "",
        "## Executive verdict",
        "",
        f"**{verdict}**",
        "",
    ]
    for r in reasons:
        lines.append(f"- {r}")
    lines.extend(
        [
            "",
            "### Can the defaced anatomical derivatives be included in a "
            "Scientific Data public release?",
            "",
            f"**{release_answer}**",
            "",
            "Verdict rules:",
            "",
            "- **PASS**: coverage complete, metadata clean, spatial integrity preserved",
            "- **WARNING**: missing provenance, missing subjects, or metadata differences",
            "- **FAIL**: missing defaced images, corrupted files, or geometry mismatch",
            "",
            "## 1. Coverage",
            "",
            f"- Subjects with T1w: **{cov['total_subjects_with_T1w']}**",
            f"- Sessions with T1w: **{cov['total_sessions_with_T1w']}**",
            f"- T1w images expected: **{cov['total_T1w_expected']}**",
            f"- Defaced T1w found: **{cov['total_defaced_found']}**",
            f"- PASS pairs: **{cov['pass_pairs']}**",
            f"- Missing: **{cov['missing_defacing_cases']}**",
            f"- Duplicates: **{cov['duplicated_defacing_outputs']}**",
            f"- Unexpected: **{cov['unexpected_derivative_files']}**",
            "",
            "## 2. Derivatives structure",
            "",
            f"- `dataset_description.json` exists: **{ddesc['exists']}**",
            f"- Has Name / BIDSVersion / GeneratedBy: "
            f"**{ddesc['has_Name']}** / **{ddesc['has_BIDSVersion']}** / "
            f"**{ddesc['has_GeneratedBy']}**",
            f"- Structure violations: **{len(structure_viols)}**",
            "",
        ]
    )
    if structure_viols:
        lines.append("Examples:")
        for v in structure_viols[:20]:
            lines.append(f"- `{v}`")
        lines.append("")

    lines.extend(
        [
            "## 3. Spatial integrity",
            "",
            f"- Paired images QC'd: **{n_image_qc}** / **{n_pairs_total}**",
            f"- Flag counts: `{dict(geom_flags)}`",
            "",
            "## 4. Image difference (quantitative only)",
            "",
        ]
    )
    if len(cmp_df) and cmp_df["changed_voxel_percentage"].notna().any():
        lines.extend(
            [
                f"- Median changed voxel %: "
                f"**{cmp_df['changed_voxel_percentage'].median():.3f}**",
                f"- Mean changed voxel %: "
                f"**{cmp_df['changed_voxel_percentage'].mean():.3f}**",
                f"- Median max |Δ|: **{cmp_df['max_difference'].median():.2f}**",
                "",
            ]
        )
    else:
        lines.append("- No paired difference metrics available.")
        lines.append("")

    phi_n = int(qc_df["n_phi_keys"].sum()) if len(qc_df) and "n_phi_keys" in qc_df else 0
    lines.extend(
        [
            "## 5. Derivative metadata",
            "",
            f"- Derivative JSONs checked: **{len(qc_df)}**",
            f"- Total PHI-like key detections: **{phi_n}**",
            f"- Acquisition-parameter preservation failures: "
            f"**{int((~qc_df['preserved_ok']).sum()) if len(qc_df) else 0}**",
            "",
            "## 6. Provenance",
            "",
            f"- Software: `{prov.get('software_name')}`",
            f"- Version: `{prov.get('version')}`",
            f"- Command/description: `{prov.get('command')}`",
            f"- Date: `{prov.get('date')}`",
            f"- provenance_missing: **{prov.get('provenance_missing')}**",
            "",
            "## Safety",
            "",
            "- This audit is **read-only**.",
            "- No BIDS or derivative files were modified, overwritten, or deleted.",
            "- No new images were written inside BIDS.",
            "- Outputs written only under `reports/defacing_audit/`.",
            "",
            "## Output files",
            "",
            "- `defacing_subject_inventory.tsv`",
            "- `defacing_missing_subjects.tsv`",
            "- `defacing_image_comparison.tsv`",
            "- `defacing_qc_metrics.tsv`",
            "- `figures/defacing_coverage.png`",
            "- `figures/before_after_examples.png` (if pairs available)",
            "- `figures/voxel_difference_summary.png`",
            "",
        ]
    )
    if mode == "DRY_RUN":
        lines.extend(
            [
                "## Dry-run note",
                "",
                "Image pairwise QC and visual examples used a limited sample. "
                "Re-run without `--dry-run` for full-cohort integrity and difference metrics.",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    bids_dir = args.bids_dir.resolve()
    output_dir = args.output_dir.resolve()
    fig_dir = output_dir / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    if not bids_dir.is_dir():
        log(f"ERROR: BIDS directory not found: {bids_dir}")
        return 1

    defacing_dir = resolve_defacing_dir(args.defacing_dir, bids_dir)
    mode = "DRY_RUN" if args.dry_run else "FULL"
    log(f"Mode: {mode}")
    log(f"BIDS root (read-only): {bids_dir}")
    log(f"Defacing dir (read-only): {defacing_dir}")
    log(f"Output dir: {output_dir}")

    # --- 1. Coverage ---
    log("1/8 Coverage audit…")
    originals = find_t1w(bids_dir, source_bids=True)
    defaced = find_t1w(defacing_dir, source_bids=False)
    inv, missing_df, cov = coverage_audit(originals, defaced)
    write_tsv(
        inv[
            [
                "subject",
                "session",
                "original_T1_exists",
                "defaced_T1_exists",
                "status",
            ]
        ],
        output_dir / "defacing_subject_inventory.tsv",
    )
    # Keep a richer missing table for remediation
    if len(missing_df):
        write_tsv(
            missing_df[
                [
                    "subject",
                    "session",
                    "relative_key",
                    "original_path",
                    "status",
                ]
            ],
            output_dir / "defacing_missing_subjects.tsv",
        )
    else:
        write_tsv(
            pd.DataFrame(
                columns=["subject", "session", "relative_key", "original_path", "status"]
            ),
            output_dir / "defacing_missing_subjects.tsv",
        )
    log(
        f"   expected={cov['total_T1w_expected']} defaced={cov['total_defaced_found']} "
        f"missing={cov['missing_defacing_cases']}"
    )

    # --- 2. Structure ---
    log("2/8 Derivatives structure check…")
    ddesc = check_dataset_description(defacing_dir)
    structure_viols = structure_violations(defacing_dir, defaced)
    # Unexpected non-T1w NIfTIs in derivatives (informational for coverage)
    other_niis = [
        p
        for p in defacing_dir.rglob("*.nii.gz")
        if p.is_file() and not p.name.endswith("_T1w.nii.gz")
    ]
    log(
        f"   dataset_description={ddesc['exists']} structure_violations={len(structure_viols)} "
        f"other_nii={len(other_niis)}"
    )

    # Paired PASS rows for image QC
    pass_rows = inv[inv["status"] == "PASS"].copy() if len(inv) else inv
    n_pairs_total = len(pass_rows)
    if args.dry_run:
        rng = np.random.default_rng(args.seed)
        if n_pairs_total > args.sample_n:
            idx = rng.choice(pass_rows.index.to_numpy(), size=args.sample_n, replace=False)
            qc_rows = pass_rows.loc[sorted(idx)]
        else:
            qc_rows = pass_rows
    else:
        qc_rows = pass_rows
    log(f"3–5/8 Image QC on {len(qc_rows)} / {n_pairs_total} pairs…")

    cmp_records: list[dict[str, Any]] = []
    qc_records: list[dict[str, Any]] = []
    geom_flags: Counter = Counter()
    corrupt_n = 0
    figure_pairs: list[tuple[Path, Path, str, str]] = []

    for i, row in enumerate(qc_rows.itertuples(index=False), start=1):
        orig_p = Path(row.original_path)
        def_p = Path(row.defaced_path)
        subject, session = row.subject, row.session
        log(f"   [{i}/{len(qc_rows)}] {subject} {session}")
        rec_qc: dict[str, Any] = {
            "subject": subject,
            "session": session,
            "relative_key": row.relative_key,
            "geometry_flags": "",
            "n_phi_keys": 0,
            "phi_keys": "",
            "preserved_ok": False,
            "missing_preserved_keys": "",
            "changed_preserved_keys": "",
            "readable": True,
        }
        try:
            g0 = geometry_record(orig_p)
            g1 = geometry_record(def_p)
            flags = compare_geometry(g0, g1)
            for f in flags:
                geom_flags[f] += 1
            rec_qc["geometry_flags"] = ",".join(flags) if flags else "OK"
            rec_qc["orig_shape"] = str(g0["shape"])
            rec_qc["def_shape"] = str(g1["shape"])
            rec_qc["orig_zooms"] = str(g0["zooms"])
            rec_qc["def_zooms"] = str(g1["zooms"])
            rec_qc["orig_orientation"] = g0["orientation"]
            rec_qc["def_orientation"] = g1["orientation"]
            rec_qc["orig_datatype"] = g0["datatype"]
            rec_qc["def_datatype"] = g1["datatype"]

            diff = voxel_difference(orig_p, def_p)
            cmp_records.append(
                {
                    "subject": subject,
                    "session": session,
                    "changed_voxel_percentage": diff["changed_voxel_percentage"],
                    "changed_voxel_count": diff["changed_voxel_count"],
                    "mean_difference": diff["mean_difference"],
                    "max_difference": diff["max_difference"],
                }
            )
            # Keep volume in qc metrics (extra quantitative detail)
            rec_qc["changed_voxel_volume_mm3"] = diff["changed_voxel_volume_mm3"]

            oj = Path(str(orig_p).replace(".nii.gz", ".json"))
            dj = Path(str(def_p).replace(".nii.gz", ".json"))
            orig_meta = load_json(oj)
            def_meta = load_json(dj)
            meta_cmp = metadata_compare(orig_meta, def_meta)
            rec_qc["n_phi_keys"] = len(meta_cmp["phi_in_derivative"])
            rec_qc["phi_keys"] = ",".join(meta_cmp["phi_in_derivative"])
            rec_qc["preserved_ok"] = meta_cmp["preserved_ok"]
            rec_qc["missing_preserved_keys"] = ",".join(meta_cmp["missing_preserved_keys"])
            rec_qc["changed_preserved_keys"] = ",".join(meta_cmp["changed_preserved_keys"])

            figure_pairs.append((orig_p, def_p, subject, session))
        except Exception as exc:  # noqa: BLE001
            corrupt_n += 1
            rec_qc["readable"] = False
            rec_qc["geometry_flags"] = f"corrupt_or_unreadable:{exc}"
            log(f"   WARNING: {exc}")
            cmp_records.append(
                {
                    "subject": subject,
                    "session": session,
                    "changed_voxel_percentage": np.nan,
                    "changed_voxel_count": np.nan,
                    "mean_difference": np.nan,
                    "max_difference": np.nan,
                }
            )
        qc_records.append(rec_qc)

    cmp_df = pd.DataFrame(
        cmp_records,
        columns=[
            "subject",
            "session",
            "changed_voxel_percentage",
            "changed_voxel_count",
            "mean_difference",
            "max_difference",
        ],
    )
    qc_df = pd.DataFrame(qc_records)
    write_tsv(cmp_df, output_dir / "defacing_image_comparison.tsv")
    write_tsv(qc_df, output_dir / "defacing_qc_metrics.tsv")

    # --- 6–7 provenance + metadata already in loop; finish provenance ---
    log("6–7/8 Metadata & provenance…")
    sample_jsons = [
        Path(str(p).replace(".nii.gz", ".json"))
        for p in defaced[:20]
        if Path(str(p).replace(".nii.gz", ".json")).is_file()
    ]
    prov = extract_provenance(ddesc, sample_jsons)
    # Also count PHI across dry/full qc set already done; for dry-run note limited scope

    # --- 5 figures ---
    log("5/8 Figures…")
    plot_coverage(inv, fig_dir / "defacing_coverage.png")
    plot_voxel_summary(cmp_df, fig_dir / "voxel_difference_summary.png")
    # Prefer diverse subjects for before/after
    rng = np.random.default_rng(args.seed)
    by_sub: dict[str, list[tuple[Path, Path, str, str]]] = defaultdict(list)
    for trip in figure_pairs:
        by_sub[trip[2]].append(trip)
    subjects = list(by_sub.keys())
    rng.shuffle(subjects)
    selected: list[tuple[Path, Path, str, str]] = []
    for s in subjects:
        selected.append(by_sub[s][0])
        if len(selected) >= 3:
            break
    made = plot_before_after(selected, fig_dir / "before_after_examples.png", n_examples=3)
    if not made:
        log("   before_after_examples.png skipped (no safe pairs)")

    # Full-cohort metadata PHI scan in FULL mode for all defaced JSONs not already checked
    if not args.dry_run:
        log("   Full metadata sweep on remaining defaced JSONs…")
        checked = set(qc_df["relative_key"]) if len(qc_df) and "relative_key" in qc_df else set()
        extra_phi = 0
        for p in defaced:
            _, _, key = parse_entities(p)
            if key in checked:
                continue
            dj = Path(str(p).replace(".nii.gz", ".json"))
            meta = load_json(dj) or {}
            hits = phi_findings(meta)
            if hits:
                extra_phi += len(hits)
                qc_records.append(
                    {
                        "subject": parse_entities(p)[0],
                        "session": parse_entities(p)[1],
                        "relative_key": key,
                        "geometry_flags": "NOT_COMPUTED_META_ONLY",
                        "n_phi_keys": len(hits),
                        "phi_keys": ",".join(hits),
                        "preserved_ok": True,
                        "missing_preserved_keys": "",
                        "changed_preserved_keys": "",
                        "readable": True,
                    }
                )
        if extra_phi:
            log(f"   Extra PHI-like detections outside image-QC set: {extra_phi}")
            qc_df = pd.DataFrame(qc_records)
            write_tsv(qc_df, output_dir / "defacing_qc_metrics.tsv")

    phi_count = int(qc_df["n_phi_keys"].sum()) if len(qc_df) else 0
    verdict, reasons = verdict_from_findings(
        cov,
        geom_flags,
        phi_count,
        bool(prov.get("provenance_missing")),
        len(structure_viols) + len(ddesc.get("violations", [])),
        corrupt_n,
    )

    log("8/8 Writing summary…")
    write_summary(
        output_dir / "defacing_audit_summary.md",
        mode=mode,
        bids_dir=bids_dir,
        defacing_dir=defacing_dir,
        cov=cov,
        ddesc=ddesc,
        structure_viols=structure_viols + ddesc.get("violations", []),
        geom_flags=geom_flags,
        cmp_df=cmp_df,
        qc_df=qc_df,
        prov=prov,
        verdict=verdict,
        reasons=reasons,
        n_image_qc=len(qc_rows),
        n_pairs_total=n_pairs_total,
    )

    meta = {
        "mode": mode,
        "bids_dir": str(bids_dir),
        "defacing_dir": str(defacing_dir),
        "output_dir": str(output_dir),
        "coverage": cov,
        "verdict": verdict,
        "reasons": reasons,
        "provenance": prov,
        "other_derivative_niis": len(other_niis),
        "read_only": True,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8"
    )

    log("")
    log("========== DEFACING AUDIT ==========")
    log(f"Verdict: {verdict}")
    for r in reasons:
        log(f"  - {r}")
    log(f"Summary: {output_dir / 'defacing_audit_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
