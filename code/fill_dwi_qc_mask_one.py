#!/usr/bin/env python3
"""Fill one missing DWI mask (Slurm array worker) or merge all parts."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import importlib.util
import numpy as np
import pandas as pd


def load_mod():
    path = Path("/home/alexrees/scratch/code/run_dwi_qc.py")
    spec = importlib.util.spec_from_file_location("run_dwi_qc", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, default=Path("/home/alexrees/scratch/reports/dwi_qc"))
    p.add_argument("--parts-dir", type=Path, default=None)
    p.add_argument("--missing-index-file", type=Path, default=None)
    p.add_argument("--task-id", type=int, default=None, help="0-based index into missing list")
    p.add_argument("--write-missing-list", action="store_true")
    p.add_argument("--merge", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out = args.output_dir.resolve()
    parts = (args.parts_dir or (out / "fill_parts")).resolve()
    parts.mkdir(parents=True, exist_ok=True)
    missing_file = (args.missing_index_file or (out / "missing_mask_indices.txt")).resolve()

    inv = pd.read_csv(out / "dwi_inventory.tsv", sep="\t")
    masks = pd.read_csv(out / "dwi_mask_metrics.tsv", sep="\t")
    cons = pd.read_csv(out / "dwi_gradient_consistency.tsv", sep="\t")

    if args.write_missing_list:
        idxs = masks.index[masks["brain_fraction"].isna()].tolist()
        missing_file.write_text("\n".join(str(i) for i in idxs) + ("\n" if idxs else ""), encoding="utf-8")
        print(f"Wrote {len(idxs)} indices to {missing_file}", flush=True)
        return 0

    if args.merge:
        mod = load_mod()
        signals = pd.read_csv(out / "dwi_signal_metrics.tsv", sep="\t")
        bvals = pd.read_csv(out / "dwi_bvalue_summary.tsv", sep="\t")
        grads = pd.read_csv(out / "dwigradcheck_results.tsv", sep="\t")
        n_merged = 0
        for path in sorted(parts.glob("idx_*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status") != "OK":
                continue
            idx = int(data["index"])
            masks.loc[idx, "mask_voxels"] = data["mask_voxels"]
            masks.loc[idx, "brain_fraction"] = data["brain_fraction"]
            for key in (
                "mean_signal",
                "median_signal",
                "std_signal",
                "mean_b0_signal",
                "mean_diffusion_signal",
            ):
                signals.loc[idx, key] = data[key]
            n_merged += 1
        mod.write_tsv(masks, out / "dwi_mask_metrics.tsv")
        mod.write_tsv(signals, out / "dwi_signal_metrics.tsv")
        mod.write_report(out, inv, cons, bvals, grads, masks, signals)
        still = int(masks["brain_fraction"].isna().sum())
        print(f"Merged {n_merged} parts; still NaN masks: {still}", flush=True)
        return 0 if still == 0 else 2

    if args.task_id is None:
        print("ERROR: --task-id required unless --write-missing-list/--merge", file=sys.stderr)
        return 1

    idxs = [int(x) for x in missing_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.task_id < 0 or args.task_id >= len(idxs):
        print(f"Task {args.task_id} out of range (n={len(idxs)}); nothing to do", flush=True)
        return 0

    idx = idxs[args.task_id]
    part_path = parts / f"idx_{idx:04d}.json"
    if part_path.is_file():
        prev = json.loads(part_path.read_text(encoding="utf-8"))
        if prev.get("status") == "OK":
            print(f"Already done idx={idx}", flush=True)
            return 0

    row = inv.loc[idx]
    cons_row = cons.loc[idx]
    print(f"Task {args.task_id}: idx={idx} {row['subject']} {row['session']} {Path(row['nifti']).name}", flush=True)

    result = {
        "index": idx,
        "subject": row["subject"],
        "session": row["session"],
        "nifti": row["nifti"],
        "status": "FAIL",
    }
    if row["status"] != "OK" or cons_row["status"] != "PASS":
        result["error"] = f"inventory={row['status']} consistency={cons_row['status']}"
        part_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0

    mod = load_mod()
    tmp = out / "tmp"
    fig = out / "figures"
    tmp.mkdir(parents=True, exist_ok=True)
    fig.mkdir(parents=True, exist_ok=True)
    try:
        mask_path = mod.run_dwi2mask(row, tmp)
        mstats = mod.mask_metrics(row, mask_path)
        sstats = mod.signal_metrics(row, mask_path)
        mod.make_figure(row, fig)
        result.update(
            {
                "status": "OK",
                "mask_voxels": mstats["mask_voxels"],
                "brain_fraction": mstats["brain_fraction"],
                "mean_signal": sstats["mean_signal"],
                "median_signal": sstats["median_signal"],
                "std_signal": sstats["std_signal"],
                "mean_b0_signal": sstats["mean_b0_signal"],
                "mean_diffusion_signal": sstats["mean_diffusion_signal"],
            }
        )
        part_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"OK idx={idx} brain_fraction={mstats['brain_fraction']:.4f}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        result["error"] = str(exc)
        part_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
