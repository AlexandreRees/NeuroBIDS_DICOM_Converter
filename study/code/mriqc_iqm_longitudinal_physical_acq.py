#!/usr/bin/env python3
"""Longitudinal MixedLM on physical-acquisition T1w IQMs.

IQM ~ cohort * session + age + sex + (1|subject_id)
BH FDR across 56 IQMs for the cohort×session interaction.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, require_file, to_numeric_iqm  # noqa: E402
from mriqc_iqm_longitudinal import (  # noqa: E402
    FDR_ALPHA,
    audit_structure,
    fdr_column,
    fit_one,
    import_stats,
    plot_top_interactions,
)
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    assert_unmodified,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.longitudinal")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study-root", type=Path, default=None)
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.phys = root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    args.orig_loadings = qc / "pca_T1w_loadings.tsv"
    args.orig_long = qc / "longitudinal_results.tsv"
    args.session_long = qc / "longitudinal_session_level_results.tsv"
    args.out_dir = qc
    return args


def configure_logging():
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    LOGGER.addHandler(h)


def main(argv=None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    stats = import_stats()
    if not stats["ok"]:
        fail("scipy+statsmodels required: " + "; ".join(stats["missing"]))
    phys = pd.read_csv(args.phys, sep="\t")
    if len(phys) != EXPECTED_PHYSICAL_N:
        fail(f"Expected {EXPECTED_PHYSICAL_N} rows, found {len(phys)}.")
    iqms = pd.read_csv(args.orig_loadings, sep="\t")["iqm"].astype(str).tolist()
    missing = [c for c in iqms if c not in phys.columns]
    if missing:
        fail(f"Physical table missing IQMs: {missing}")
    t1 = phys.copy()
    t1["iqm_check"] = 0
    for col in iqms:
        t1[col] = to_numeric_iqm(t1[col])
    audit = audit_structure(t1)
    n_long = int(audit["n_both_sessions"])
    rows = []
    for iqm in iqms:
        LOGGER.info("Longitudinal MixedLM %s", iqm)
        rows.append(fit_one(t1, iqm, stats["smf"], n_long))
    results = pd.DataFrame(rows)
    results["cohort_q"] = fdr_column(results["cohort_p"], stats["multipletests"])
    results["session_q"] = fdr_column(results["session_p"], stats["multipletests"])
    results["interaction_q"] = fdr_column(results["interaction_p"], stats["multipletests"])
    results.to_csv(args.out_dir / "longitudinal_physical_acq_results.tsv", sep="\t", index=False, float_format="%.10g")
    both_ids = set(audit["status_by_subject"][audit["status_by_subject"] == "both_sessions"].index)
    plotted = plot_top_interactions(
        t1,
        results,
        both_ids,
        args.out_dir / "longitudinal_physical_acq_top_interactions.png",
        args.out_dir / "longitudinal_physical_acq_top_interactions.pdf",
    )
    sig_int = results.loc[results["interaction_q"] < FDR_ALPHA, "IQM"].tolist()
    orig_hits = []
    sess_hits = []
    if args.orig_long.is_file():
        orig = pd.read_csv(args.orig_long, sep="\t")
        col = "interaction_q" if "interaction_q" in orig.columns else None
        if col:
            orig_hits = orig.loc[orig[col] < FDR_ALPHA, "IQM"].astype(str).tolist()
    if args.session_long.is_file():
        sess = pd.read_csv(args.session_long, sep="\t")
        col = "interaction_q" if "interaction_q" in sess.columns else None
        if col:
            sess_hits = sess.loc[sess[col] < FDR_ALPHA, "IQM"].astype(str).tolist()

    lines = [
        "Physical-acquisition T1w IQM longitudinal analysis",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Model: IQM ~ C(cohort)*C(session) + age + C(sex) + (1|subject_id)",
        "Primary test: cohort × session interaction. BH FDR on 56 IQMs.",
        "Data_ON longitudinal n=1; Data_TON longitudinal n=1 — not population inference.",
        "PCs/IQMs are not quality scores.",
        "",
        f"n physical acquisitions: {len(t1)}",
        f"n subjects: {audit['n_subjects']}",
        f"n sessions: {audit['n_sessions']}",
        f"both sessions: {audit['n_both_sessions']}",
        f"subject×session cells with >1 physical acq: {audit['n_subject_session_with_multiple_t1w']}",
        "",
        f"Interaction FDR q<0.05: {len(sig_int)} / 56  {sig_int or 'none'}",
        f"Session FDR q<0.05: {int((results['session_q']<FDR_ALPHA).sum())} / 56",
        f"Cohort FDR q<0.05: {int((results['cohort_q']<FDR_ALPHA).sum())} / 56",
        "",
        "Comparison of interaction FDR hits:",
        f"  acquisition-level (264 rows): {orig_hits or 'none'}",
        f"  session-level FreeSurfer-selected: {sess_hits or 'none (file missing or no hits)'}",
        f"  physical-acquisition-level: {sig_int or 'none'}",
        "",
        f"plotted IQMs: {plotted}",
        "Original longitudinal_results.tsv was not modified.",
        "",
    ]
    (args.out_dir / "longitudinal_physical_acq_report.txt").write_text("\n".join(lines), encoding="utf-8")
    assert_unmodified(before)
    print("physical-acq longitudinal interaction FDR:", ", ".join(sig_int) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
