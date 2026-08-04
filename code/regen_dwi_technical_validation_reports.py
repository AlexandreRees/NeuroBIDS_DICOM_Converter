#!/usr/bin/env python3
"""Regenerate DWI technical validation reports after bugfixes (read-only on BIDS)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from dwi_tv.common import apply_style, log, utc_now, write_tsv
from dwi_tv import figures as figmod
from dwi_tv import reports as repmod
from dwi_tv import sections as sec


def main() -> int:
    root = Path("/home/alexrees/scratch")
    qc = root / "reports" / "dwi_qc"
    pub = qc / "publication"
    pub.mkdir(parents=True, exist_ok=True)
    apply_style()

    inv = sec.enrich_inventory(pd.read_csv(qc / "dwi_inventory.tsv", sep="\t"))
    cons = pd.read_csv(qc / "dwi_gradient_consistency.tsv", sep="\t")
    if "scan_id" not in cons.columns:
        cons = cons.copy()
        cons["scan_id"] = inv["scan_id"].values
    integrity = sec.integrity_summary(inv, cons)
    write_tsv(integrity, qc / "integrity_summary.tsv")
    repmod.write_integrity_report(qc / "Integrity_Report.md", integrity, inv)
    n_pass = int((integrity["integrity_status"] == "PASS").sum())
    log(f"Integrity PASS={n_pass}/{len(integrity)}")

    acq = pd.read_csv(qc / "Protocol_Consistency_per_scan.tsv", sep="\t")
    acq = sec.assign_protocols(acq)
    write_tsv(acq, qc / "Protocol_Consistency_per_scan.tsv")
    proto = sec.protocol_summary_table(acq)
    write_tsv(proto, qc / "Protocol_Consistency.tsv")
    geom = sec.geometry_qc_table(acq)
    write_tsv(geom, qc / "Geometry_QC.tsv")
    repmod.write_acquisition_report(
        qc / "Acquisition_Consistency_Report.md", acq, proto
    )
    repmod.write_geometry_report(qc / "Geometry_QC_Report.md", acq, proto)
    repmod.write_diffusion_scheme_report(qc / "Diffusion_Scheme_Report.md", acq)
    figmod.figure_protocols(proto, qc / "Figure_protocols")
    figmod.figure_protocol_composition(acq, pub / "Figure1_protocols")
    figmod.figure_bvalue_distribution(acq, pub / "Figure2_bvalues")
    figmod.figure_directions(acq, pub / "Figure3_directions")
    log(f"Protocols now: {len(proto)}")
    print(proto.to_string())

    gc = pd.read_csv(qc / "dwigradcheck_results.tsv", sep="\t")
    grad = sec.build_gradient_qc(inv, gc, acq)
    write_tsv(grad, qc / "Gradient_QC.tsv")
    repmod.write_gradient_report(qc / "Gradient_Report.md", grad)
    figmod.figure_gradient_qc_summary(grad, qc / "Gradient_QC_summary")
    figmod.figure_gradient_qc_summary(grad, pub / "Figure_gradient_qc")
    spheres = figmod.build_protocol_spheres(acq, qc)
    for i, sp in enumerate(spheres[:2]):
        for ext in (".png", ".pdf", ".svg"):
            src = sp.with_suffix(ext)
            if src.is_file():
                shutil.copy2(src, pub / f"Figure4_gradient_sphere_{i + 1}{ext}")
    gpass = int((grad["status"] == "PASS").sum())
    grev = int((grad["status"] == "REVIEW").sum())
    gfail = int((grad["status"] == "FAIL").sum())
    log(f"Gradient PASS={gpass} REVIEW={grev} FAIL={gfail}")
    print(grad["review_class"].value_counts().to_string())

    mask_metrics = pd.read_csv(qc / "dwi_mask_metrics.tsv", sep="\t")
    mask_qc = sec.build_brainmask_qc(inv, mask_metrics, acq, qc / "tmp")
    write_tsv(mask_qc, qc / "BrainMask_QC.tsv")
    repmod.write_brainmask_report(qc / "BrainMask_Report.md", mask_qc)
    figmod.figure_brainmask(mask_qc, pub / "Figure5_brainmask")

    signal_qc = pd.read_csv(qc / "Signal_QC.tsv", sep="\t")
    pmap = acq.set_index("scan_id")["protocol_id"]
    signal_qc["protocol_id"] = signal_qc["scan_id"].map(pmap)
    write_tsv(signal_qc, qc / "Signal_QC.tsv")
    repmod.write_signal_report(qc / "Signal_Report.md", signal_qc)
    figmod.figure_signal(signal_qc, pub / "Figure6_signal")
    spass = int((signal_qc["status"] == "PASS").sum())
    smiss = int((signal_qc["status"] == "MISSING_MASK").sum())
    log(f"Signal PASS={spass} MISSING_MASK={smiss}")

    pairs = pd.read_csv(qc / "PE_pairs.tsv", sep="\t")
    eddy_hits = sec.find_eddy_outputs(root / "derivatives")
    repmod.write_motion_report(qc / "Motion_QC.md", eddy_hits)
    repmod.write_pe_pairs_report(qc / "PE_pairs_Report.md", pairs)

    examples = sorted((qc / "visual_examples").glob("*_visual_qc.png"))
    if examples:
        figmod.figure_visual_montage(examples, qc / "Visual_QC_Figure")
        for ext in (".png", ".pdf", ".svg"):
            src = (qc / "Visual_QC_Figure").with_suffix(ext)
            if src.is_file():
                shutil.copy2(src, pub / f"Figure7_visual_qc{ext}")

    table_rows, overall = repmod.build_status_table(
        integrity=integrity,
        grad=grad,
        mask_qc=mask_qc,
        signal_qc=signal_qc,
        pairs=pairs,
        eddy_available=bool(eddy_hits),
    )
    repmod.export_validation_table(table_rows, qc)
    figmod.figure_summary_table_image(
        table_rows, pub / "Figure8_technical_validation_summary"
    )
    for ext in (".png", ".pdf", ".svg"):
        src = (pub / "Figure8_technical_validation_summary").with_suffix(ext)
        if src.is_file():
            shutil.copy2(src, qc / f"TechnicalValidation_Summary{ext}")

    repmod.write_technical_validation_md(
        qc / "Technical_Validation_DWI.md",
        inventory=inv,
        integrity=integrity,
        proto=proto,
        grad=grad,
        mask_qc=mask_qc,
        signal_qc=signal_qc,
        pairs=pairs,
        table_rows=table_rows,
        overall=overall,
    )
    prov = {
        "generated_utc": utc_now(),
        "n_scans": len(inv),
        "n_protocols": len(proto),
        "overall": overall,
        "gradient": grad["status"].value_counts().to_dict(),
        "signal_pass": spass,
        "pe_pair_ok": int((pairs["pair_status"] == "PAIR_OK").sum()),
        "read_only": True,
    }
    (qc / "technical_validation_provenance.json").write_text(
        json.dumps(prov, indent=2), encoding="utf-8"
    )
    print("OVERALL", overall)
    for a, b in table_rows:
        print(f"  {a}: {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
