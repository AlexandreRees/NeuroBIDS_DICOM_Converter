#!/usr/bin/env python3
"""Compute raw-DWI motion / slice-outlier / SNR–CNR QC for GSLD (+ RESOLVE for comparison).

No FSL eddy required. Metrics are eddy-analogous summaries from raw volumes:
  - translation (mm) from brain COM on b=0 volumes
  - rotation (deg) from principal-axis orientation of brain mask
  - slice outliers via robust z-score of in-plane slice means
  - b0 SNR / CNR within an intensity-derived brain mask

Usage:
  python compute_dwi_motion_snr_qc.py           # all GSLD_AP + RESOLVE_AP
  python compute_dwi_motion_snr_qc.py --limit 8 # smoke
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import nibabel as nib
import numpy as np

ROOT = Path("/lustre07/scratch/alexrees")
INV = ROOT / "derivatives/dmriqc/audit/dmriqc_sequence_inventory.tsv"
OUT_DIR = ROOT / "derivatives/dmriqc/qc_metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FAMILIES = {"GSLD_AP_multishell", "RESOLVE_AP"}


def classify(desc: str) -> str:
    d = (desc or "").lower()
    if "tracew" in d:
        return "RESOLVE_TRACEW"
    if "resolve" in d and ("_pa" in d or d.endswith("pa")):
        return "RESOLVE_PA"
    if "resolve" in d:
        return "RESOLVE_AP"
    if "pa_3b0" in d or "75te_pa" in d:
        return "GSLD_PA_b0"
    if "gsld" in d or "76dir" in d or "b2000" in d:
        return "GSLD_AP_multishell"
    return "OTHER"


def load_targets(limit: int | None):
    rows = list(csv.DictReader(open(INV), delimiter="\t"))
    out = []
    for r in rows:
        fam = r.get("sequence_family") or classify(r.get("SeriesDescription") or "")
        if fam not in FAMILIES:
            continue
        nii = ROOT / "bids" / r["subject"] / r["session"] / "dwi" / f"{r['bids_basename']}.nii.gz"
        bval = nii.with_suffix("").with_suffix(".bval")
        if not nii.exists():
            continue
        out.append(
            {
                "scan_id": r["bids_basename"],
                "subject": r["subject"],
                "session": r["session"],
                "run": r["run"],
                "sequence_family": fam,
                "SeriesDescription": r.get("SeriesDescription", ""),
                "nii": str(nii),
                "bval": str(bval) if bval.exists() else "",
            }
        )
    out.sort(key=lambda x: x["scan_id"])
    if limit:
        out = out[:limit]
    return out


def robust_mask(vol: np.ndarray) -> np.ndarray:
    """Fast brain-ish mask from intensity (no BET)."""
    v = vol.astype(np.float32, copy=False)
    # ignore zeros / padding
    pos = v[v > 0]
    if pos.size < 1000:
        thr = np.percentile(v, 85)
    else:
        thr = np.percentile(pos, 60)
    m = v > thr
    # keep largest chunk roughly by requiring also above global soft thr
    return m


def com(mask: np.ndarray, zooms):
    idx = np.argwhere(mask)
    if idx.size == 0:
        return np.zeros(3)
    c = idx.mean(axis=0).astype(float)  # i,j,k
    return c * np.asarray(zooms, float)


def principal_axis_angle_deg(mask: np.ndarray, zooms) -> float:
    """Angle (deg) of primary in-plane axis vs x; used as orientation proxy."""
    idx = np.argwhere(mask)
    if len(idx) < 50:
        return np.nan
    # use i,j only (in-plane), weighted by physical mm
    pts = idx[:, :2].astype(float)
    pts[:, 0] *= zooms[0]
    pts[:, 1] *= zooms[1]
    pts -= pts.mean(axis=0)
    cov = pts.T @ pts / max(len(pts) - 1, 1)
    try:
        w, vec = np.linalg.eigh(cov)
    except np.linalg.LinAlgError:
        return np.nan
    v = vec[:, int(np.argmax(w))]
    return float(np.degrees(np.arctan2(v[1], v[0])))


def angle_diff_deg(a, b):
    if not np.isfinite(a) or not np.isfinite(b):
        return np.nan
    d = (a - b + 180) % 360 - 180
    return abs(d)


def slice_outlier_count(vol: np.ndarray, z=3.5) -> int:
    """Count slices whose mean intensity is a robust outlier within the volume."""
    # vol: X,Y,Z
    sm = vol.mean(axis=(0, 1))
    med = np.median(sm)
    mad = np.median(np.abs(sm - med)) + 1e-6
    zsc = 0.6745 * (sm - med) / mad
    return int(np.sum(np.abs(zsc) > z))


def snr_cnr(mean_b0: np.ndarray, mean_dw: np.ndarray, mask: np.ndarray):
    bg = ~mask
    # noise from background MAD (fallback: lower 20% intensities)
    if bg.sum() < 500:
        thr = np.percentile(mean_b0, 20)
        bg = mean_b0 <= thr
    noise = 1.4826 * np.median(np.abs(mean_b0[bg] - np.median(mean_b0[bg]))) + 1e-6
    sb0 = float(np.median(mean_b0[mask])) if mask.any() else np.nan
    sdw = float(np.median(mean_dw[mask])) if mask.any() else np.nan
    snr = sb0 / noise
    cnr = abs(sb0 - sdw) / noise
    return snr, cnr, sb0, sdw, noise


def process_scan(rec: dict) -> dict:
    try:
        img = nib.load(rec["nii"])
        zooms = img.header.get_zooms()[:3]
        # bvals
        if rec["bval"]:
            b = np.atleast_1d(np.loadtxt(rec["bval"])).astype(float).ravel()
        else:
            # assume all volumes
            b = np.zeros(img.shape[3] if img.ndim == 4 else 1)
        nvol = int(img.shape[3]) if img.ndim == 4 else 1
        if b.size != nvol:
            # length mismatch: truncate/pad
            if b.size > nvol:
                b = b[:nvol]
            else:
                b = np.pad(b, (0, nvol - b.size), constant_values=b[-1] if b.size else 0)

        b0_idx = np.where(b < 50)[0]
        dw_idx = np.where(b >= 50)[0]
        if b0_idx.size == 0:
            b0_idx = np.array([0], dtype=int)

        # subsample DW for slice-outlier pass (cap cost)
        if dw_idx.size > 40:
            dw_sample = dw_idx[:: max(1, len(dw_idx) // 40)]
        else:
            dw_sample = dw_idx
        check_idx = np.unique(np.concatenate([b0_idx, dw_sample]))

        data = img.dataobj  # memmap-friendly
        # reference = first b0
        ref = np.asanyarray(data[..., int(b0_idx[0])], dtype=np.float32)
        ref_mask = robust_mask(ref)
        ref_com = com(ref_mask, zooms)
        ref_ang = principal_axis_angle_deg(ref_mask, zooms)

        trans = []  # RMS mm relative to ref
        rots = []
        # motion on b0s only (stable contrast)
        for i in b0_idx:
            vol = np.asanyarray(data[..., int(i)], dtype=np.float32)
            m = robust_mask(vol)
            c = com(m, zooms)
            dxyz = c - ref_com
            trans.append(float(np.linalg.norm(dxyz)))
            ang = principal_axis_angle_deg(m, zooms)
            rots.append(angle_diff_deg(ang, ref_ang))

        # slice outliers across checked volumes
        slice_outs = []
        vols_with_out = 0
        for i in check_idx:
            vol = np.asanyarray(data[..., int(i)], dtype=np.float32)
            n_out = slice_outlier_count(vol)
            slice_outs.append(n_out)
            if n_out > 0:
                vols_with_out += 1

        # SNR/CNR on mean b0 / mean dw
        mean_b0 = np.mean([np.asanyarray(data[..., int(i)], dtype=np.float32) for i in b0_idx[: min(8, len(b0_idx))]], axis=0)
        if dw_idx.size:
            take = dw_idx[: min(12, len(dw_idx))]
            mean_dw = np.mean([np.asanyarray(data[..., int(i)], dtype=np.float32) for i in take], axis=0)
        else:
            mean_dw = mean_b0
        mask = robust_mask(mean_b0)
        snr, cnr, med_b0, med_dw, noise = snr_cnr(mean_b0, mean_dw, mask)

        trans_arr = np.asarray(trans, float)
        rot_arr = np.asarray(rots, float)
        so_arr = np.asarray(slice_outs, float)

        return {
            **{k: rec[k] for k in ("scan_id", "subject", "session", "run", "sequence_family", "SeriesDescription")},
            "n_volumes": nvol,
            "n_b0": int(b0_idx.size),
            "n_checked_volumes": int(check_idx.size),
            "trans_rms_mean_mm": float(np.nanmean(trans_arr)),
            "trans_rms_max_mm": float(np.nanmax(trans_arr)),
            "trans_rms_std_mm": float(np.nanstd(trans_arr)),
            "rot_mean_deg": float(np.nanmean(rot_arr)),
            "rot_max_deg": float(np.nanmax(rot_arr)),
            "slice_outliers_mean": float(np.nanmean(so_arr)),
            "slice_outliers_max": float(np.nanmax(so_arr)),
            "pct_volumes_with_slice_outlier": 100.0 * vols_with_out / max(len(check_idx), 1),
            "b0_SNR": snr,
            "CNR": cnr,
            "median_b0": med_b0,
            "median_diffusion": med_dw,
            "noise_mad": noise,
            "brain_voxels": int(mask.sum()),
            "status": "OK",
            "error": "",
        }
    except Exception as e:
        return {
            **{k: rec.get(k, "") for k in ("scan_id", "subject", "session", "run", "sequence_family", "SeriesDescription")},
            "status": "FAIL",
            "error": str(e),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    ap.add_argument("--out", type=str, default=str(OUT_DIR / "dwi_motion_snr_qc.tsv"))
    args = ap.parse_args()

    targets = load_targets(args.limit)
    print(f"targets={len(targets)} workers={args.workers}", flush=True)
    rows = []
    # process sequentially if workers==1 else pool
    if args.workers == 1:
        for i, t in enumerate(targets, 1):
            r = process_scan(t)
            rows.append(r)
            print(f"[{i}/{len(targets)}] {r.get('scan_id')} {r.get('status')} "
                  f"trans={r.get('trans_rms_mean_mm','')} slice={r.get('slice_outliers_mean','')}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(process_scan, t): t for t in targets}
            done = 0
            for fut in as_completed(futs):
                r = fut.result()
                rows.append(r)
                done += 1
                print(f"[{done}/{len(targets)}] {r.get('scan_id')} {r.get('status')}", flush=True)

    rows.sort(key=lambda r: r.get("scan_id", ""))
    # union of keys
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    out = Path(args.out)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    ok = sum(1 for r in rows if r.get("status") == "OK")
    print(f"Wrote {out} OK={ok}/{len(rows)}", flush=True)


if __name__ == "__main__":
    main()
