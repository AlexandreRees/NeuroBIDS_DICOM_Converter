"""Section computations for DWI technical validation."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd

from .common import (
    B0_THRESHOLD,
    ensure_scan_columns,
    fov_mm,
    load_bval,
    load_bvec,
    load_json,
    nifti_n_volumes,
    orientation_code,
    parse_entities,
    scan_id_from_nifti,
    sidecar_paths,
    unique_bval_string,
    voxel_volume_mm3,
)


def build_inventory(bids_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for nifti in sorted(bids_dir.rglob("*_dwi.nii.gz")):
        if "/derivatives/" in str(nifti):
            continue
        subject, session, run = parse_entities(nifti)
        bval, bvec, json_path = sidecar_paths(nifti)
        missing = []
        if not bval.is_file():
            missing.append("bval")
        if not bvec.is_file():
            missing.append("bvec")
        if not json_path.is_file():
            missing.append("json")
        status = "OK" if not missing else "MISSING_" + "_".join(m.upper() for m in missing)
        rows.append(
            {
                "scan_id": scan_id_from_nifti(nifti),
                "subject": subject,
                "session": session,
                "run": run,
                "nifti": str(nifti),
                "bval": str(bval),
                "bvec": str(bvec),
                "json": str(json_path),
                "nifti_present": nifti.is_file(),
                "bval_present": bval.is_file(),
                "bvec_present": bvec.is_file(),
                "json_present": json_path.is_file(),
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def enrich_inventory(inventory: pd.DataFrame) -> pd.DataFrame:
    """Add scan_id/run/presence columns to a legacy inventory TSV."""
    out = inventory.copy()
    if "scan_id" not in out.columns:
        out["scan_id"] = out["nifti"].map(lambda p: scan_id_from_nifti(p))
    if "run" not in out.columns:
        out["run"] = out["nifti"].map(lambda p: parse_entities(Path(p))[2])
    for col, key in [
        ("nifti_present", "nifti"),
        ("bval_present", "bval"),
        ("bvec_present", "bvec"),
        ("json_present", "json"),
    ]:
        if col not in out.columns:
            out[col] = out[key].map(lambda p: Path(p).is_file())
    return out


def check_gradient_consistency(row: pd.Series) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scan_id": row["scan_id"],
        "subject": row["subject"],
        "session": row["session"],
        "run": row.get("run", "n/a"),
        "nifti": row["nifti"],
        "n_volumes": np.nan,
        "n_bvals": np.nan,
        "n_bvec_columns": np.nan,
        "status": "FAIL",
    }
    try:
        if row["status"] != "OK":
            return result
        img = nib.load(row["nifti"])
        bvals = load_bval(Path(row["bval"]))
        bvecs = load_bvec(Path(row["bvec"]))
        n_vol = nifti_n_volumes(img)
        n_bvals = int(bvals.size)
        n_bvec = int(bvecs.shape[1])
        result.update(
            {
                "n_volumes": n_vol,
                "n_bvals": n_bvals,
                "n_bvec_columns": n_bvec,
                "status": "PASS" if n_vol == n_bvals == n_bvec else "FAIL",
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result


def integrity_summary(inventory: pd.DataFrame, consistency: pd.DataFrame) -> pd.DataFrame:
    cons = consistency.copy()
    if "scan_id" not in cons.columns and len(cons) == len(inventory):
        cons["scan_id"] = inventory["scan_id"].values
    cons_idx = cons.set_index("scan_id")
    dup_counts = Counter(inventory["nifti"].tolist())
    rows = []
    for _, r in inventory.iterrows():
        scan_id = r["scan_id"]
        n_vol = n_bval = n_bvec = np.nan
        cons_status = "N/A"
        if scan_id in cons_idx.index:
            c = cons_idx.loc[scan_id]
            if isinstance(c, pd.DataFrame):
                c = c.iloc[0]
            n_vol = c.get("n_volumes", np.nan)
            n_bval = c.get("n_bvals", np.nan)
            n_bvec = c.get("n_bvec_columns", np.nan)
            cons_status = c.get("status", "N/A")
        vol_match = cons_status == "PASS"
        rows.append(
            {
                "scan_id": scan_id,
                "subject": r["subject"],
                "session": r["session"],
                "run": r.get("run", "n/a"),
                "nifti_present": bool(r.get("nifti_present", True)),
                "bval_present": bool(r.get("bval_present", True)),
                "bvec_present": bool(r.get("bvec_present", True)),
                "json_present": bool(r.get("json_present", True)),
                "n_volumes": n_vol,
                "n_bvals": n_bval,
                "n_bvecs": n_bvec,
                "volumes_match": vol_match,
                "bvals_match": vol_match,
                "bvecs_match": vol_match,
                "duplicate_nifti": dup_counts[r["nifti"]] > 1,
                "inventory_status": r["status"],
                "consistency_status": cons_status,
                "integrity_status": (
                    "PASS"
                    if r["status"] == "OK"
                    and cons_status == "PASS"
                    and dup_counts[r["nifti"]] == 1
                    else "FAIL"
                ),
            }
        )
    return pd.DataFrame(rows)


def acquisition_row(row: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {
        "scan_id": row["scan_id"],
        "subject": row["subject"],
        "session": row["session"],
        "run": row.get("run", "n/a"),
        "nifti": row["nifti"],
        "voxel_size_x": np.nan,
        "voxel_size_y": np.nan,
        "voxel_size_z": np.nan,
        "voxel_size_str": "",
        "matrix_i": np.nan,
        "matrix_j": np.nan,
        "matrix_k": np.nan,
        "matrix_str": "",
        "fov_x_mm": np.nan,
        "fov_y_mm": np.nan,
        "fov_z_mm": np.nan,
        "slice_thickness_mm": np.nan,
        "TR_s": np.nan,
        "TE_s": np.nan,
        "PhaseEncodingDirection": "",
        "TotalReadoutTime": np.nan,
        "n_volumes": np.nan,
        "unique_bvals": "",
        "n_b0": np.nan,
        "n_diffusion_directions": np.nan,
        "max_bvalue": np.nan,
        "orientation": "",
        "protocol_id": "",
        "protocol_label": "",
    }
    try:
        img = nib.load(row["nifti"])
        zooms = tuple(float(z) for z in img.header.get_zooms()[:3])
        shape3 = tuple(int(s) for s in img.shape[:3])
        n_vol = nifti_n_volumes(img)
        meta: dict[str, Any] = {}
        if Path(row["json"]).is_file():
            meta = load_json(Path(row["json"]))
        bvals = load_bval(Path(row["bval"])) if Path(row["bval"]).is_file() else np.array([])
        ub = unique_bval_string(bvals) if bvals.size else ""
        is_b0 = bvals < B0_THRESHOLD if bvals.size else np.array([], dtype=bool)
        n_b0 = int(np.sum(is_b0)) if bvals.size else 0
        n_diff = int(np.sum(~is_b0)) if bvals.size else 0
        fov = fov_mm(shape3, zooms)
        st = meta.get("SliceThickness", zooms[2])
        out.update(
            {
                "voxel_size_x": zooms[0],
                "voxel_size_y": zooms[1],
                "voxel_size_z": zooms[2],
                "voxel_size_str": f"{zooms[0]:.3g}×{zooms[1]:.3g}×{zooms[2]:.3g}",
                "matrix_i": shape3[0],
                "matrix_j": shape3[1],
                "matrix_k": shape3[2],
                "matrix_str": f"{shape3[0]}×{shape3[1]}×{shape3[2]}",
                "fov_x_mm": round(fov[0], 2),
                "fov_y_mm": round(fov[1], 2),
                "fov_z_mm": round(fov[2], 2),
                "slice_thickness_mm": float(st) if st is not None else zooms[2],
                "TR_s": meta.get("RepetitionTime", np.nan),
                "TE_s": meta.get("EchoTime", np.nan),
                "PhaseEncodingDirection": str(meta.get("PhaseEncodingDirection", "")),
                "TotalReadoutTime": meta.get("TotalReadoutTime", np.nan),
                "n_volumes": n_vol,
                "unique_bvals": ub,
                "n_b0": n_b0,
                "n_diffusion_directions": n_diff,
                "max_bvalue": float(np.max(bvals)) if bvals.size else np.nan,
                "orientation": orientation_code(img.affine),
            }
        )
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def assign_protocols(acq: pd.DataFrame) -> pd.DataFrame:
    out = acq.copy()

    def key_row(r: pd.Series) -> str:
        # Round voxel size coarsely so floating-point header noise does not
        # explode the protocol count (e.g. 1.000 vs 1.001).
        if pd.notna(r["voxel_size_x"]):
            vox = (
                f"{round(float(r['voxel_size_x']), 1)}x"
                f"{round(float(r['voxel_size_y']), 1)}x"
                f"{round(float(r['voxel_size_z']), 1)}"
            )
        else:
            vox = "?"
        # Bin direction counts into the dominant scheme sizes
        nd_raw = int(r["n_diffusion_directions"]) if pd.notna(r["n_diffusion_directions"]) else -1
        if nd_raw < 0:
            nd = "?"
        elif nd_raw <= 16:
            nd = "11"
        elif nd_raw <= 200:
            nd = str(nd_raw)
        else:
            nd = "365"
        return f"{r['unique_bvals']}|{nd}|{vox}"

    out["_pkey"] = out.apply(key_row, axis=1)
    counts = out["_pkey"].value_counts()
    label_map = {}
    for i, key in enumerate(counts.index.tolist()):
        letter = chr(ord("A") + i) if i < 26 else f"P{i + 1}"
        label_map[key] = f"Protocol {letter}"
    out["protocol_id"] = out["_pkey"].map(label_map)
    out["protocol_label"] = out.apply(
        lambda r: (
            f"{r['protocol_id']}: b={r['unique_bvals']}; "
            f"{int(r['n_diffusion_directions']) if pd.notna(r['n_diffusion_directions']) else '?'} dir; "
            f"{r['voxel_size_str']} mm; n={counts[r['_pkey']]}"
        ),
        axis=1,
    )
    return out.drop(columns=["_pkey"])


def protocol_summary_table(acq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pid, g in acq.groupby("protocol_id", sort=False):
        rows.append(
            {
                "protocol_id": pid,
                "n_scans": len(g),
                "unique_bvals": g["unique_bvals"].mode().iloc[0] if len(g) else "",
                "n_diffusion_directions": int(g["n_diffusion_directions"].mode().iloc[0])
                if len(g) and pd.notna(g["n_diffusion_directions"].mode().iloc[0])
                else np.nan,
                "n_b0_typical": int(g["n_b0"].mode().iloc[0])
                if len(g) and pd.notna(g["n_b0"].mode().iloc[0])
                else np.nan,
                "voxel_size_str": g["voxel_size_str"].mode().iloc[0] if len(g) else "",
                "matrix_str": g["matrix_str"].mode().iloc[0] if len(g) else "",
                "TR_s_median": float(g["TR_s"].median()) if g["TR_s"].notna().any() else np.nan,
                "TE_s_median": float(g["TE_s"].median()) if g["TE_s"].notna().any() else np.nan,
                "PhaseEncodingDirection": (
                    g["PhaseEncodingDirection"].mode().iloc[0]
                    if g["PhaseEncodingDirection"].astype(str).str.len().gt(0).any()
                    else ""
                ),
                "TotalReadoutTime_median": float(g["TotalReadoutTime"].median())
                if g["TotalReadoutTime"].notna().any()
                else np.nan,
                "orientation": g["orientation"].mode().iloc[0] if len(g) else "",
            }
        )
    return pd.DataFrame(rows).sort_values("n_scans", ascending=False).reset_index(drop=True)


def geometry_qc_table(acq: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "scan_id",
        "subject",
        "session",
        "run",
        "protocol_id",
        "voxel_size_str",
        "matrix_str",
        "fov_x_mm",
        "fov_y_mm",
        "fov_z_mm",
        "slice_thickness_mm",
        "orientation",
    ]
    return acq[cols].copy()


_GRAD_ROW = re.compile(r"^\s*([0-9.+-eE]+)\s+(\S+)\s+(\([^)]*\))\s+(\S+)\s*$")


def parse_dwigradcheck_top(text: str) -> dict[str, str]:
    for line in str(text).splitlines():
        m = _GRAD_ROW.match(line)
        if not m:
            continue
        return {
            "mean_length": m.group(1),
            "axis_flipped": m.group(2),
            "axis_permutations": re.sub(r"\s+", "", m.group(3)),
            "axis_basis": m.group(4),
        }
    return {
        "mean_length": "",
        "axis_flipped": "",
        "axis_permutations": "",
        "axis_basis": "",
    }


def classify_review(status: str, text: str) -> str:
    if status == "PASS":
        return "none"
    if status == "FAIL":
        return "fail"
    top = parse_dwigradcheck_top(text)
    flip = top["axis_flipped"].lower()
    perm = top["axis_permutations"]
    identity_perm = perm in {"(0,1,2)", "(0, 1, 2)", ""}
    no_flip = flip in {"none", "0", "-", ""}
    if not no_flip and identity_perm:
        return "axis_flip"
    if no_flip and not identity_perm:
        return "axis_swap"
    if not no_flip and not identity_perm:
        return "axis_flip_and_swap"
    return "other"


def build_gradient_qc(
    inventory: pd.DataFrame,
    gradcheck: pd.DataFrame,
    acq: pd.DataFrame,
) -> pd.DataFrame:
    inv = ensure_scan_columns(inventory, inventory)
    gc = ensure_scan_columns(gradcheck, inventory)
    if "status" not in gc.columns:
        raise ValueError("dwigradcheck results missing status column")
    # Inventory also has a "status" column (OK/MISSING_…) — never merge that
    # name against dwigradcheck status (PASS/REVIEW/FAIL).
    gc_status = gc[["scan_id"]].copy()
    gc_status["grad_status"] = gc["status"].astype(str).values
    gc_status["grad_output"] = (
        gc["output"].astype(str).values if "output" in gc.columns else ""
    )
    if len(gc) == len(inv) and gc_status["scan_id"].isna().any():
        merged = inv.copy()
        merged["grad_status"] = gc["status"].astype(str).values
        merged["grad_output"] = (
            gc["output"].astype(str).values if "output" in gc.columns else ""
        )
    else:
        merged = inv.merge(gc_status, on="scan_id", how="left")

    proto = acq.set_index("scan_id")["protocol_id"] if len(acq) else pd.Series(dtype=str)
    rows = []
    for _, r in merged.iterrows():
        status = str(r.get("grad_status", "FAIL"))
        if status in {"", "nan", "None"}:
            status = "FAIL"
        output = str(r.get("grad_output", ""))
        top = parse_dwigradcheck_top(output)
        rows.append(
            {
                "scan_id": r["scan_id"],
                "subject": r["subject"],
                "session": r["session"],
                "run": r.get("run", "n/a"),
                "protocol_id": proto.loc[r["scan_id"]]
                if r["scan_id"] in proto.index
                else "",
                "status": status,
                "review_class": classify_review(status, output),
                "mean_length": top["mean_length"],
                "axis_flipped": top["axis_flipped"],
                "axis_permutations": top["axis_permutations"],
                "axis_basis": top["axis_basis"],
            }
        )
    return pd.DataFrame(rows)


def build_brainmask_qc(
    inventory: pd.DataFrame,
    mask_metrics: pd.DataFrame,
    acq: pd.DataFrame,
    tmp_dir: Path,
) -> pd.DataFrame:
    inv = ensure_scan_columns(inventory, inventory)
    mm = ensure_scan_columns(mask_metrics, inventory)
    if "scan_id" not in mm.columns and len(mm) == len(inv):
        mm = mm.copy()
        mm["scan_id"] = inv["scan_id"].values
    acq_idx = acq.set_index("scan_id")
    rows = []
    for _, r in inv.iterrows():
        sid = r["scan_id"]
        mask_path = tmp_dir / f"{sid}_mask.nii.gz"
        mrow = mm[mm["scan_id"] == sid] if "scan_id" in mm.columns else pd.DataFrame()
        mask_voxels = float(mrow["mask_voxels"].iloc[0]) if len(mrow) else np.nan
        brain_fraction = float(mrow["brain_fraction"].iloc[0]) if len(mrow) else np.nan
        vox_vol = np.nan
        brain_vol = np.nan
        protocol_id = ""
        if sid in acq_idx.index:
            a = acq_idx.loc[sid]
            if isinstance(a, pd.DataFrame):
                a = a.iloc[0]
            protocol_id = a.get("protocol_id", "")
            if pd.notna(a.get("voxel_size_x")):
                vox_vol = voxel_volume_mm3(
                    (
                        float(a["voxel_size_x"]),
                        float(a["voxel_size_y"]),
                        float(a["voxel_size_z"]),
                    )
                )
                if pd.notna(mask_voxels):
                    brain_vol = mask_voxels * vox_vol
        rows.append(
            {
                "scan_id": sid,
                "subject": r["subject"],
                "session": r["session"],
                "run": r.get("run", "n/a"),
                "protocol_id": protocol_id,
                "mask_file_present": mask_path.is_file(),
                "mask_voxels": mask_voxels,
                "voxel_volume_mm3": vox_vol,
                "brain_volume_mm3": brain_vol,
                "brain_fraction": brain_fraction,
            }
        )
    return pd.DataFrame(rows)


def _subsample(arr: np.ndarray, max_n: int = 500_000) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float64).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size <= max_n:
        return arr
    rng = np.random.default_rng(0)
    idx = rng.choice(arr.size, size=max_n, replace=False)
    return arr[idx]


def compute_signal_qc_one(row: pd.Series, mask_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "scan_id": row["scan_id"],
        "subject": row["subject"],
        "session": row["session"],
        "run": row.get("run", "n/a"),
        "protocol_id": row.get("protocol_id", ""),
        "median_b0_signal": np.nan,
        "median_diffusion_signal": np.nan,
        "p95_signal": np.nan,
        "p5_signal": np.nan,
        "cv_b0": np.nan,
        "background_signal": np.nan,
        "b0_SNR": np.nan,
        "CNR": np.nan,
        "status": "FAIL",
    }
    if not mask_path.is_file():
        out["status"] = "MISSING_MASK"
        return out
    try:
        img = nib.load(row["nifti"])
        mask = np.asanyarray(nib.load(str(mask_path)).dataobj) > 0
        bvals = load_bval(Path(row["bval"]))
        n_vol = nifti_n_volumes(img)
        if bvals.size != n_vol:
            out["status"] = "BVAL_MISMATCH"
            return out
        is_b0 = bvals < B0_THRESHOLD
        dataobj = img.dataobj
        b0_idx = np.where(is_b0)[0]
        diff_idx = np.where(~is_b0)[0]
        if b0_idx.size == 0:
            out["status"] = "NO_B0"
            return out

        b0_stack = [
            np.asanyarray(dataobj[..., int(i)], dtype=np.float32)
            for i in b0_idx[: min(8, b0_idx.size)]
        ]
        b0_mean = np.mean(np.stack(b0_stack, axis=-1), axis=-1)
        brain = b0_mean[mask]
        background = b0_mean[~mask]
        brain_s = _subsample(brain)
        bg_s = _subsample(background, max_n=200_000)
        med_b0 = float(np.median(brain_s)) if brain_s.size else np.nan
        bg_med = float(np.median(bg_s)) if bg_s.size else np.nan
        if bg_s.size:
            mad = float(np.median(np.abs(bg_s - np.median(bg_s))))
            noise = 1.4826 * mad if mad > 0 else float(np.std(bg_s))
        else:
            noise = np.nan
        snr = med_b0 / noise if noise and noise > 0 and np.isfinite(med_b0) else np.nan

        diff_vals = []
        if diff_idx.size:
            pick = np.unique(
                np.linspace(0, diff_idx.size - 1, num=min(6, diff_idx.size), dtype=int)
            )
            for pi in pick:
                vol = np.asanyarray(dataobj[..., int(diff_idx[int(pi)])], dtype=np.float32)
                diff_vals.append(vol[mask])
        if diff_vals:
            diff_cat = _subsample(np.concatenate([d.ravel() for d in diff_vals]))
            med_diff = float(np.median(diff_cat))
        else:
            med_diff = np.nan
            diff_cat = np.array([])

        all_for_pct = np.concatenate([brain_s, diff_cat]) if diff_cat.size else brain_s
        p5 = float(np.percentile(all_for_pct, 5)) if all_for_pct.size else np.nan
        p95 = float(np.percentile(all_for_pct, 95)) if all_for_pct.size else np.nan
        cv_b0 = (
            float(np.std(brain_s) / np.mean(brain_s))
            if brain_s.size and np.mean(brain_s) != 0
            else np.nan
        )
        cnr = (
            abs(med_b0 - med_diff) / noise
            if noise and noise > 0 and np.isfinite(med_b0) and np.isfinite(med_diff)
            else np.nan
        )
        out.update(
            {
                "median_b0_signal": med_b0,
                "median_diffusion_signal": med_diff,
                "p95_signal": p95,
                "p5_signal": p5,
                "cv_b0": cv_b0,
                "background_signal": bg_med,
                "b0_SNR": snr,
                "CNR": cnr,
                "status": "PASS",
            }
        )
    except Exception as exc:  # noqa: BLE001
        out["status"] = "FAIL"
        out["error"] = str(exc)
    return out


def inventory_pe_pairs(bids_dir: Path, inventory: pd.DataFrame) -> pd.DataFrame:
    sessions = inventory[["subject", "session"]].drop_duplicates()
    rows = []
    for _, r in sessions.iterrows():
        sub, ses = r["subject"], r["session"]
        fmap = bids_dir / sub / ses / "fmap"
        ap: list[str] = []
        pa: list[str] = []
        if fmap.is_dir():
            for p in sorted(fmap.glob("*dir-AP*epi.nii.gz")):
                if "part-phase" not in p.name:
                    ap.append(str(p))
            for p in sorted(fmap.glob("*dir-PA*epi.nii.gz")):
                if "part-phase" not in p.name:
                    pa.append(str(p))
        has_ap = len(ap) > 0
        has_pa = len(pa) > 0
        if has_ap and has_pa:
            status = "PAIR_OK"
        elif has_ap or has_pa:
            status = "PARTIAL"
        else:
            status = "MISSING"
        rows.append(
            {
                "subject": sub,
                "session": ses,
                "fmap_dir_present": fmap.is_dir(),
                "n_AP_epi": len(ap),
                "n_PA_epi": len(pa),
                "AP_files": ";".join(ap),
                "PA_files": ";".join(pa),
                "pair_status": status,
            }
        )
    return pd.DataFrame(rows)


def find_eddy_outputs(derivatives_dir: Path) -> list[Path]:
    if not derivatives_dir.is_dir():
        return []
    hits: list[Path] = []
    for pat in ("*eddy_movement*", "*eddy_outlier*", "*eddy_parameters", "*quad*"):
        hits.extend(derivatives_dir.rglob(pat))
    return sorted(set(hits))[:200]


def unique_directions_from_bvec(bvec_path: Path, bval_path: Path) -> np.ndarray:
    bvecs = load_bvec(bvec_path)
    bvals = load_bval(bval_path)
    mask = bvals >= B0_THRESHOLD
    dirs = bvecs[:, mask].T
    norms = np.linalg.norm(dirs, axis=1)
    keep = norms > 1e-6
    dirs = dirs[keep] / norms[keep, None]
    # Unique up to antipodal equivalence for sphere display: keep all signed
    return dirs
