#!/usr/bin/env python3
"""Append + QC DWI scans for specific BIDS sessions (incremental).

Does not rewrite existing completed rows. Appends new inventory rows and runs
gradcheck / mask / signal / figures for those new scans only, then regenerates
the cohort report.

Modes:
  --list-new          Append inventory if needed, write index list, exit
  --task-id N         Process new_indices[N] only (array worker)
  (neither)           Process all new indices serially

Example:
  python code/run_dwi_qc_append_sessions.py \\
    --session-list neuro_pipeline/scripts/subjects_missing_ses02_retry11.tsv \\
    --list-new
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd


def load_mod():
    path = Path("/home/alexrees/scratch/code/run_dwi_qc.py")
    spec = importlib.util.spec_from_file_location("run_dwi_qc", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def load_targets(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as fh:
        data_lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    for row in csv.DictReader(data_lines, delimiter="\t"):
        pid = (row.get("participant_id") or "").strip()
        sid = (row.get("session_id") or "").strip()
        if not pid or not sid:
            continue
        out.append((pid, sid))
    return out


def nan_row(columns: list[str], subject: str, session: str) -> dict:
    row = {c: np.nan for c in columns}
    if "subject" in row:
        row["subject"] = subject
    if "session" in row:
        row["session"] = session
    return row


def session_match(row_session: str, target_session: str) -> bool:
    a = str(row_session)
    b = str(target_session)
    if a == b:
        return True
    # inventory may store ses-02 or 02
    if a.replace("ses-", "") == b.replace("ses-", ""):
        return True
    return False


def process_one(mod, idx: int, inv, cons, bvals, grads, masks, signals, tmp_dir, fig_dir) -> None:
    row = inv.loc[idx]
    label = f"{row['subject']} {row['session']} idx={idx}"
    print(f"\n=== {label} ===", flush=True)

    cons_row = mod.check_gradient_consistency(row)
    for k in ("subject", "session", "n_volumes", "n_bvals", "n_bvec_columns", "status"):
        if k in cons.columns:
            cons.loc[idx, k] = cons_row.get(k, np.nan)

    bsum = mod.bvalue_summary(row)
    for k, v in bsum.items():
        if k in bvals.columns:
            bvals.loc[idx, k] = v

    if row["status"] != "OK" or cons_row.get("status") != "PASS":
        print("  Skip mask/gradcheck (inventory/consistency fail)", flush=True)
        grads.loc[idx, "subject"] = row["subject"]
        grads.loc[idx, "session"] = row["session"]
        grads.loc[idx, "status"] = "SKIP"
        grads.loc[idx, "output"] = "inventory/consistency failed"
        return

    print("  dwigradcheck…", flush=True)
    g = mod.run_dwigradcheck(row)
    for k, v in g.items():
        if k in grads.columns:
            grads.loc[idx, k] = v

    try:
        print("  dwi2mask…", flush=True)
        mask_path = mod.run_dwi2mask(row, tmp_dir)
        mstats = mod.mask_metrics(row, mask_path)
        for k, v in mstats.items():
            if k in masks.columns:
                masks.loc[idx, k] = v
        print("  signal…", flush=True)
        sstats = mod.signal_metrics(row, mask_path)
        for k, v in sstats.items():
            if k in signals.columns:
                signals.loc[idx, k] = v
        print("  figure…", flush=True)
        mod.make_figure(row, fig_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"  WARNING: mask/signal/figure failed: {exc}", flush=True)
        traceback.print_exc()
        masks.loc[idx, "subject"] = row["subject"]
        masks.loc[idx, "session"] = row["session"]
        masks.loc[idx, "mask_voxels"] = np.nan
        masks.loc[idx, "brain_fraction"] = np.nan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bids-dir", type=Path, default=Path("/home/alexrees/scratch/bids"))
    ap.add_argument("--output-dir", type=Path, default=Path("/home/alexrees/scratch/reports/dwi_qc"))
    ap.add_argument("--session-list", type=Path, required=True)
    ap.add_argument("--task-id", type=int, default=None)
    ap.add_argument("--list-new", action="store_true")
    ap.add_argument("--new-index-file", type=Path, default=None)
    ap.add_argument("--rewrite-report", action="store_true")
    args = ap.parse_args()

    mod = load_mod()
    bids = args.bids_dir.resolve()
    out = args.output_dir.resolve()
    targets = load_targets(args.session_list)
    target_set = set(targets)

    inv_path = out / "dwi_inventory.tsv"
    if not inv_path.is_file():
        print(f"ERROR: missing {inv_path}", file=sys.stderr)
        return 1

    inv = pd.read_csv(inv_path, sep="\t")
    cons = pd.read_csv(out / "dwi_gradient_consistency.tsv", sep="\t")
    bvals = pd.read_csv(out / "dwi_bvalue_summary.tsv", sep="\t")
    grads = pd.read_csv(out / "dwigradcheck_results.tsv", sep="\t")
    masks = pd.read_csv(out / "dwi_mask_metrics.tsv", sep="\t")
    signals = pd.read_csv(out / "dwi_signal_metrics.tsv", sep="\t")

    known = set(inv["nifti"].astype(str))
    new_rows: list[dict] = []
    for pid, sid in targets:
        ses = bids / pid / sid / "dwi"
        if not ses.is_dir():
            continue
        for nifti in sorted(ses.glob("*_dwi.nii.gz")):
            if str(nifti) in known:
                continue
            subject, session = mod.parse_entities(nifti)
            bval, bvec, json_path = mod.sidecar_paths(nifti)
            new_rows.append(
                {
                    "subject": subject,
                    "session": session,
                    "nifti": str(nifti),
                    "bval": str(bval),
                    "bvec": str(bvec),
                    "json": str(json_path),
                    "status": mod.inventory_status(bval, bvec, json_path),
                }
            )

    if new_rows:
        start_idx = len(inv)
        inv = pd.concat([inv, pd.DataFrame(new_rows)], ignore_index=True)
        pad_cons = []
        pad_bvals = []
        pad_grads = []
        pad_masks = []
        pad_signals = []
        for nr in new_rows:
            pad_cons.append(nan_row(list(cons.columns), nr["subject"], nr["session"]))
            pad_bvals.append(nan_row(list(bvals.columns), nr["subject"], nr["session"]))
            pad_grads.append(nan_row(list(grads.columns), nr["subject"], nr["session"]))
            pad_masks.append(nan_row(list(masks.columns), nr["subject"], nr["session"]))
            pad_signals.append(nan_row(list(signals.columns), nr["subject"], nr["session"]))
        cons = pd.concat([cons, pd.DataFrame(pad_cons)], ignore_index=True)
        bvals = pd.concat([bvals, pd.DataFrame(pad_bvals)], ignore_index=True)
        grads = pd.concat([grads, pd.DataFrame(pad_grads)], ignore_index=True)
        masks = pd.concat([masks, pd.DataFrame(pad_masks)], ignore_index=True)
        signals = pd.concat([signals, pd.DataFrame(pad_signals)], ignore_index=True)
        mod.write_tsv(inv, inv_path)
        mod.write_tsv(cons, out / "dwi_gradient_consistency.tsv")
        mod.write_tsv(bvals, out / "dwi_bvalue_summary.tsv")
        mod.write_tsv(grads, out / "dwigradcheck_results.tsv")
        mod.write_tsv(masks, out / "dwi_mask_metrics.tsv")
        mod.write_tsv(signals, out / "dwi_signal_metrics.tsv")
        print(f"Appended {len(new_rows)} DWI scans starting at index {start_idx}", flush=True)

    # Indices for target sessions still needing QC
    new_indices: list[int] = []
    for idx, row in inv.iterrows():
        subj = str(row["subject"])
        sess = str(row["session"])
        matched = any(
            subj == pid and session_match(sess, sid) for pid, sid in target_set
        )
        if not matched:
            continue
        needs = False
        if idx >= len(masks) or pd.isna(masks.loc[idx, "brain_fraction"]):
            needs = True
        elif idx >= len(grads):
            needs = True
        else:
            st = str(grads.loc[idx].get("status", ""))
            if st in {"", "nan", "NaN"} or pd.isna(grads.loc[idx].get("status", np.nan)):
                needs = True
        if needs:
            new_indices.append(int(idx))

    index_file = args.new_index_file or (out / "ses02_retry11_dwi_indices.txt")
    index_file.write_text(
        "\n".join(str(i) for i in new_indices) + ("\n" if new_indices else ""),
        encoding="utf-8",
    )
    print(f"Wrote {len(new_indices)} indices → {index_file}", flush=True)

    if args.list_new:
        return 0

    if args.rewrite_report and args.task_id is None and not new_indices:
        mod.write_report(out, inv, cons, bvals, grads, masks, signals)
        print(f"Rewrote report under {out}", flush=True)
        return 0

    if not new_indices:
        print("Nothing to process", flush=True)
        return 0

    mod.ensure_tools()
    tmp_dir = out / "tmp"
    fig_dir = out / "figures"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    if args.task_id is not None:
        if args.task_id < 0 or args.task_id >= len(new_indices):
            print(f"Task {args.task_id} out of range (n={len(new_indices)}); skip", flush=True)
            return 0
        todo = [new_indices[args.task_id]]
    else:
        todo = new_indices

    for idx in todo:
        process_one(mod, idx, inv, cons, bvals, grads, masks, signals, tmp_dir, fig_dir)
        mod.write_tsv(cons, out / "dwi_gradient_consistency.tsv")
        mod.write_tsv(bvals, out / "dwi_bvalue_summary.tsv")
        mod.write_tsv(grads, out / "dwigradcheck_results.tsv")
        mod.write_tsv(masks, out / "dwi_mask_metrics.tsv")
        mod.write_tsv(signals, out / "dwi_signal_metrics.tsv")

    if args.task_id is None or args.rewrite_report:
        mod.write_report(out, inv, cons, bvals, grads, masks, signals)
        print(f"Updated report under {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
