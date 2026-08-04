#!/usr/bin/env python3
"""FINAL publication-grade DWI Technical Validation pipeline (READ-ONLY on BIDS).

Never modifies bids/, raw_original/, or derivatives/.
All outputs are written under reports/dwi_qc/.

Example:
  module load StdEnv/2023 python/3.11 scipy-stack
  python code/run_dwi_technical_validation.py \\
      --bids-dir /home/alexrees/scratch/bids \\
      --qc-dir /home/alexrees/scratch/reports/dwi_qc \\
      --reuse-existing
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

# Allow `python code/run_dwi_technical_validation.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dwi_tv.common import (  # noqa: E402
    DEFAULT_BIDS,
    DEFAULT_QC,
    apply_style,
    log,
    read_existing_tsv,
    utc_now,
    write_tsv,
)
from dwi_tv import figures as figmod  # noqa: E402
from dwi_tv import reports as repmod  # noqa: E402
from dwi_tv import sections as sec  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    p.add_argument("--qc-dir", type=Path, default=DEFAULT_QC)
    p.add_argument(
        "--derivatives-dir",
        type=Path,
        default=Path("/home/alexrees/scratch/derivatives"),
    )
    p.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Reuse existing inventory / consistency / gradcheck / mask TSVs when present.",
    )
    p.add_argument(
        "--skip-signal",
        action="store_true",
        help="Skip robust signal recomputation (use empty/partial Signal_QC).",
    )
    p.add_argument(
        "--skip-visual",
        action="store_true",
        help="Skip per-scan visual_examples generation.",
    )
    p.add_argument(
        "--max-visuals",
        type=int,
        default=12,
        help="Max representative visual examples (stratified by protocol).",
    )
    p.add_argument("--max-scans", type=int, default=None, help="Limit scans (testing).")
    p.add_argument("--workers", type=int, default=4)
    return p.parse_args()


def _signal_worker(payload: dict) -> dict:
    row = pd.Series(payload["row"])
    return sec.compute_signal_qc_one(row, Path(payload["mask"]))


def _acq_worker(row_dict: dict) -> dict:
    return sec.acquisition_row(pd.Series(row_dict))


def main() -> int:
    args = parse_args()
    bids_dir = args.bids_dir.resolve()
    qc_dir = args.qc_dir.resolve()
    if not bids_dir.is_dir():
        log(f"ERROR: BIDS not found: {bids_dir}")
        return 1

    qc_dir.mkdir(parents=True, exist_ok=True)
    pub = qc_dir / "publication"
    pub.mkdir(parents=True, exist_ok=True)
    visual_dir = qc_dir / "visual_examples"
    visual_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = qc_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    apply_style()

    t0 = time.time()
    log("=" * 70)
    log("DWI Technical Validation (READ-ONLY)")
    log(f"BIDS: {bids_dir}")
    log(f"Output: {qc_dir}")
    log(f"Started: {utc_now()}")
    log("=" * 70)

    # ------------------------------------------------------------------
    # Section 1 — Integrity
    # ------------------------------------------------------------------
    log("\n[1/13] Dataset integrity…")
    inv_path = qc_dir / "dwi_inventory.tsv"
    if args.reuse_existing and inv_path.is_file():
        inventory = sec.enrich_inventory(pd.read_csv(inv_path, sep="\t"))
        log(f"  Reused inventory: {len(inventory)} scans")
    else:
        inventory = sec.build_inventory(bids_dir)
        write_tsv(inventory, inv_path)
        log(f"  Built inventory: {len(inventory)} scans")

    if args.max_scans is not None:
        inventory = inventory.iloc[: args.max_scans].copy()

    cons_path = qc_dir / "dwi_gradient_consistency.tsv"
    cons_full = read_existing_tsv(cons_path)
    if (
        args.reuse_existing
        and cons_full is not None
        and len(cons_full) >= len(inventory)
    ):
        consistency = cons_full.copy()
        # Align legacy row-ordered table to current inventory slice
        if "scan_id" not in consistency.columns:
            # Assume same order as full on-disk inventory
            full_inv = sec.enrich_inventory(pd.read_csv(inv_path, sep="\t"))
            consistency = consistency.iloc[: len(full_inv)].copy()
            consistency["scan_id"] = full_inv["scan_id"].values
            consistency["nifti"] = full_inv["nifti"].values
        consistency = consistency[
            consistency["scan_id"].isin(set(inventory["scan_id"]))
        ].copy()
        log(f"  Reused gradient consistency table ({len(consistency)} rows)")
    else:
        log("  Checking volume/bval/bvec consistency…")
        consistency = pd.DataFrame(
            [sec.check_gradient_consistency(r) for _, r in inventory.iterrows()]
        )
        # Only overwrite the shared legacy TSV when processing the full cohort
        if args.max_scans is None:
            write_tsv(consistency, cons_path)

    integrity = sec.integrity_summary(inventory, consistency)
    write_tsv(integrity, qc_dir / "integrity_summary.tsv")
    repmod.write_integrity_report(
        qc_dir / "Integrity_Report.md", integrity, inventory
    )
    log(
        f"  Integrity PASS: {(integrity['integrity_status']=='PASS').sum()}/{len(integrity)}"
    )

    # ------------------------------------------------------------------
    # Section 2/4 — Acquisition + Geometry
    # ------------------------------------------------------------------
    log("\n[2/13] Acquisition consistency + geometry…")
    acq_cache = qc_dir / "Protocol_Consistency_per_scan.tsv"
    if args.reuse_existing and acq_cache.is_file():
        acq = pd.read_csv(acq_cache, sep="\t")
        # Ensure same scans
        if set(acq["scan_id"]) != set(inventory["scan_id"]):
            acq = None  # type: ignore[assignment]
        else:
            log(f"  Reused per-scan acquisition table ({len(acq)})")
    else:
        acq = None

    if acq is None:
        log(f"  Extracting acquisition metadata ({args.workers} workers)…")
        rows = [r.to_dict() for _, r in inventory.iterrows()]
        results = []
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futs = [ex.submit(_acq_worker, r) for r in rows]
            for i, fut in enumerate(as_completed(futs), 1):
                results.append(fut.result())
                if i % 50 == 0 or i == len(futs):
                    log(f"    {i}/{len(futs)}")
        acq = pd.DataFrame(results)
        acq = sec.assign_protocols(acq)
        write_tsv(acq, acq_cache)

    if "protocol_id" not in acq.columns or acq["protocol_id"].isna().all():
        acq = sec.assign_protocols(acq)

    proto = sec.protocol_summary_table(acq)
    write_tsv(proto, qc_dir / "Protocol_Consistency.tsv")
    geom = sec.geometry_qc_table(acq)
    write_tsv(geom, qc_dir / "Geometry_QC.tsv")
    repmod.write_acquisition_report(
        qc_dir / "Acquisition_Consistency_Report.md", acq, proto
    )
    repmod.write_geometry_report(qc_dir / "Geometry_QC_Report.md", acq, proto)
    figmod.figure_protocols(proto, qc_dir / "Figure_protocols")
    log(f"  Protocols: {len(proto)}")

    # ------------------------------------------------------------------
    # Section 3 — Diffusion scheme
    # ------------------------------------------------------------------
    log("\n[3/13] Diffusion scheme figures…")
    repmod.write_diffusion_scheme_report(qc_dir / "Diffusion_Scheme_Report.md", acq)
    figmod.figure_bvalue_distribution(acq, pub / "Figure2_bvalues")
    figmod.figure_directions(acq, pub / "Figure3_directions")
    figmod.figure_protocol_composition(acq, pub / "Figure1_protocols")
    # Also mirror Figure_protocols already written at qc root

    # ------------------------------------------------------------------
    # Section 5 — Gradient validation
    # ------------------------------------------------------------------
    log("\n[5/13] Gradient validation…")
    gc_path = qc_dir / "dwigradcheck_results.tsv"
    if not gc_path.is_file():
        log("  ERROR: dwigradcheck_results.tsv missing — run run_dwi_qc.py first")
        grad = pd.DataFrame(
            {
                "scan_id": inventory["scan_id"],
                "subject": inventory["subject"],
                "session": inventory["session"],
                "run": inventory["run"],
                "protocol_id": "",
                "status": "FAIL",
                "review_class": "fail",
                "mean_length": "",
                "axis_flipped": "",
                "axis_permutations": "",
                "axis_basis": "",
            }
        )
    else:
        gradcheck = pd.read_csv(gc_path, sep="\t")
        # Align by row if lengths match (legacy TSV without scan_id)
        if len(gradcheck) != len(inventory):
            log(
                f"  WARNING: gradcheck rows ({len(gradcheck)}) != inventory "
                f"({len(inventory)}); aligning by min length"
            )
            n = min(len(gradcheck), len(inventory))
            gradcheck = gradcheck.iloc[:n].copy()
            inv_align = inventory.iloc[:n].copy()
            grad = sec.build_gradient_qc(inv_align, gradcheck, acq)
        else:
            grad = sec.build_gradient_qc(inventory, gradcheck, acq)
    write_tsv(grad, qc_dir / "Gradient_QC.tsv")
    repmod.write_gradient_report(qc_dir / "Gradient_Report.md", grad)
    figmod.figure_gradient_qc_summary(grad, qc_dir / "Gradient_QC_summary")
    figmod.figure_gradient_qc_summary(grad, pub / "Figure_gradient_qc")
    sphere_paths = figmod.build_protocol_spheres(acq, qc_dir)
    # Copy primary spheres into publication as Figure4
    if sphere_paths:
        for i, sp in enumerate(sphere_paths[:2]):
            for ext in (".png", ".pdf", ".svg"):
                src = sp.with_suffix(ext)
                if src.is_file():
                    shutil.copy2(src, pub / f"Figure4_gradient_sphere_{i+1}{ext}")
    log(
        f"  PASS={int((grad['status']=='PASS').sum())} "
        f"REVIEW={int((grad['status']=='REVIEW').sum())} "
        f"FAIL={int((grad['status']=='FAIL').sum())}"
    )

    # ------------------------------------------------------------------
    # Section 6 — Brain mask QC
    # ------------------------------------------------------------------
    log("\n[6/13] Brain mask QC…")
    mm_path = qc_dir / "dwi_mask_metrics.tsv"
    if mm_path.is_file():
        mask_metrics = pd.read_csv(mm_path, sep="\t")
    else:
        mask_metrics = pd.DataFrame(
            columns=["subject", "session", "mask_voxels", "brain_fraction"]
        )
    mask_qc = sec.build_brainmask_qc(inventory, mask_metrics, acq, tmp_dir)
    write_tsv(mask_qc, qc_dir / "BrainMask_QC.tsv")
    repmod.write_brainmask_report(qc_dir / "BrainMask_Report.md", mask_qc)
    figmod.figure_brainmask(mask_qc, pub / "Figure5_brainmask")

    # ------------------------------------------------------------------
    # Section 7 — Signal QC
    # ------------------------------------------------------------------
    log("\n[7/13] Signal quality (robust)…")
    sig_path = qc_dir / "Signal_QC.tsv"
    if args.skip_signal and sig_path.is_file():
        signal_qc = pd.read_csv(sig_path, sep="\t")
        log("  Skipped recompute; reused Signal_QC.tsv")
    elif args.skip_signal:
        signal_qc = pd.DataFrame(
            {
                "scan_id": inventory["scan_id"],
                "subject": inventory["subject"],
                "session": inventory["session"],
                "status": "SKIPPED",
            }
        )
        write_tsv(signal_qc, sig_path)
    else:
        acq_idx = acq.set_index("scan_id")
        payloads = []
        for _, r in inventory.iterrows():
            rd = r.to_dict()
            if r["scan_id"] in acq_idx.index:
                rd["protocol_id"] = acq_idx.loc[r["scan_id"]].get("protocol_id", "")
            payloads.append(
                {
                    "row": rd,
                    "mask": str(tmp_dir / f"{r['scan_id']}_mask.nii.gz"),
                }
            )
        results = []
        log(f"  Computing robust signal metrics ({args.workers} workers)…")
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futs = {ex.submit(_signal_worker, p): i for i, p in enumerate(payloads)}
            done = 0
            for fut in as_completed(futs):
                results.append(fut.result())
                done += 1
                if done % 25 == 0 or done == len(payloads):
                    log(f"    {done}/{len(payloads)}")
        signal_qc = pd.DataFrame(results)
        write_tsv(signal_qc, sig_path)
    repmod.write_signal_report(qc_dir / "Signal_Report.md", signal_qc)
    if "median_b0_signal" in signal_qc.columns:
        figmod.figure_signal(signal_qc, pub / "Figure6_signal")

    # ------------------------------------------------------------------
    # Section 8 — Motion
    # ------------------------------------------------------------------
    log("\n[8/13] Motion / eddy QC…")
    eddy_hits = sec.find_eddy_outputs(args.derivatives_dir.resolve())
    repmod.write_motion_report(qc_dir / "Motion_QC.md", eddy_hits)
    log(f"  Eddy-related files found: {len(eddy_hits)}")

    # ------------------------------------------------------------------
    # Section 9 — PE pairs
    # ------------------------------------------------------------------
    log("\n[9/13] Susceptibility PE pairs…")
    pairs = sec.inventory_pe_pairs(bids_dir, inventory)
    write_tsv(pairs, qc_dir / "PE_pairs.tsv")
    repmod.write_pe_pairs_report(qc_dir / "PE_pairs_Report.md", pairs)
    log(
        f"  PAIR_OK={int((pairs['pair_status']=='PAIR_OK').sum())}/"
        f"{len(pairs)}"
    )

    # ------------------------------------------------------------------
    # Section 10 — Visual QC
    # ------------------------------------------------------------------
    log("\n[10/13] Visual QC examples…")
    example_paths: list[Path] = []
    if not args.skip_visual:
        # Stratified sample by protocol
        chosen: list[pd.Series] = []
        for pid, g in acq.groupby("protocol_id"):
            # Prefer scans with masks
            g2 = g.copy()
            g2["_has_mask"] = g2["scan_id"].map(
                lambda s: (tmp_dir / f"{s}_mask.nii.gz").is_file()
            )
            g2 = g2.sort_values("_has_mask", ascending=False)
            take = max(1, args.max_visuals // max(len(proto), 1))
            for _, r in g2.head(take).iterrows():
                chosen.append(r)
        chosen = chosen[: args.max_visuals]
        for r in chosen:
            out_png = visual_dir / f"{r['scan_id']}_visual_qc.png"
            if out_png.is_file():
                example_paths.append(out_png)
                continue
            nifti = Path(r["nifti"])
            bval = Path(str(nifti).replace(".nii.gz", ".bval"))
            mask = tmp_dir / f"{r['scan_id']}_mask.nii.gz"
            try:
                ok = figmod.make_visual_example(
                    nifti, bval, mask if mask.is_file() else None, out_png
                )
                if ok:
                    example_paths.append(out_png)
                    log(f"  Wrote {out_png.name}")
            except Exception as exc:  # noqa: BLE001
                log(f"  Visual failed for {r['scan_id']}: {exc}")
        if example_paths:
            figmod.figure_visual_montage(example_paths, qc_dir / "Visual_QC_Figure")
            for ext in (".png", ".pdf", ".svg"):
                src = (qc_dir / "Visual_QC_Figure").with_suffix(ext)
                if src.is_file():
                    shutil.copy2(src, pub / f"Figure7_visual_qc{ext}")
    else:
        log("  Skipped visuals")

    # ------------------------------------------------------------------
    # Section 11–13 — Publication summary table + final MD
    # ------------------------------------------------------------------
    log("\n[11-13/13] Final technical validation table + manuscript section…")
    table_rows, overall = repmod.build_status_table(
        integrity=integrity,
        grad=grad,
        mask_qc=mask_qc,
        signal_qc=signal_qc,
        pairs=pairs,
        eddy_available=bool(eddy_hits),
    )
    repmod.export_validation_table(table_rows, qc_dir)
    figmod.figure_summary_table_image(table_rows, pub / "Figure8_technical_validation_summary")
    # Also copy summary to qc root naming
    for ext in (".png", ".pdf", ".svg"):
        src = (pub / "Figure8_technical_validation_summary").with_suffix(ext)
        if src.is_file():
            shutil.copy2(src, qc_dir / f"TechnicalValidation_Summary{ext}")

    repmod.write_technical_validation_md(
        qc_dir / "Technical_Validation_DWI.md",
        inventory=inventory,
        integrity=integrity,
        proto=proto,
        grad=grad,
        mask_qc=mask_qc,
        signal_qc=signal_qc,
        pairs=pairs,
        table_rows=table_rows,
        overall=overall,
    )

    # Provenance
    provenance = {
        "generated_utc": utc_now(),
        "bids_dir": str(bids_dir),
        "qc_dir": str(qc_dir),
        "n_scans": len(inventory),
        "n_protocols": len(proto),
        "overall": overall,
        "read_only": True,
        "reuse_existing": args.reuse_existing,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (qc_dir / "technical_validation_provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )

    log("\n" + "=" * 70)
    log(f"DONE in {time.time() - t0:.1f}s — Overall: {overall}")
    log(f"Primary manuscript file: {qc_dir / 'Technical_Validation_DWI.md'}")
    log("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
