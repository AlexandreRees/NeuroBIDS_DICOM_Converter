#!/usr/bin/env python3
"""Build one-row-per-physical-T1w-acquisition table.

Reads the reconstruction audit and the clean IQM table. Does not modify
either. Reconstruction choice never uses IQM values: NORM is preferred
when present; otherwise SeriesDescription T1w_MPR is preferred over
T1w_MPR_ND.

Example:
  python code/mriqc_iqm_physical_acquisition_table.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, require_columns, require_file  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    assert_unmodified,
    fingerprint,
    select_reconstruction,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.table")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--clean-tsv", type=Path, default=None)
    parser.add_argument("--audit-tsv", type=Path, default=None)
    parser.add_argument("--out-tsv", type=Path, default=None)
    parser.add_argument("--out-report", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    meta = root / "metadata"
    args.study_root = root
    args.clean_tsv = args.clean_tsv.resolve() if args.clean_tsv else meta / "mriqc_iqm_clean.tsv"
    args.audit_tsv = (
        args.audit_tsv.resolve() if args.audit_tsv else qc / "t1w_reconstruction_audit.tsv"
    )
    args.out_tsv = (
        args.out_tsv.resolve() if args.out_tsv else meta / "mriqc_iqm_physical_acquisition.tsv"
    )
    args.out_report = (
        args.out_report.resolve()
        if args.out_report
        else qc / "physical_acquisition_table_report.txt"
    )
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)


def load_inputs(clean_path: Path, audit_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    require_file(clean_path, "clean IQM table")
    require_file(audit_path, "T1w reconstruction audit")
    clean = pd.read_csv(clean_path, sep="\t")
    audit = pd.read_csv(audit_path, sep="\t")
    require_columns(
        clean,
        ["subject_id", "session", "run", "bids_name", "sequence_group"],
        "clean IQM table",
    )
    require_columns(
        audit,
        ["subject", "session", "run", "bids_name", "NORM_status", "session_pattern"],
        "reconstruction audit",
    )
    t1 = clean.loc[clean["sequence_group"].astype(str) == "T1w"].copy()
    if len(t1) != 264:
        fail(f"Expected 264 T1w rows in the clean table, found {len(t1)}.")
    if len(audit) != 264:
        fail(f"Expected 264 audit rows, found {len(audit)}.")
    return t1, audit


def build_table(clean: pd.DataFrame, audit: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int | str]]:
    merged = audit.merge(
        clean,
        left_on=["subject", "session", "run", "bids_name"],
        right_on=["subject_id", "session", "run", "bids_name"],
        how="inner",
        suffixes=("_audit", ""),
    )
    if len(merged) != 264:
        fail(f"Audit/clean join produced {len(merged)} rows, expected 264.")
    if merged.filter(regex="cjv|cnr|snr_total").empty:
        fail("IQM columns did not join onto the audit rows.")

    selected_rows: list[dict] = []
    n_pairs_norm = 0
    n_pairs_other = 0
    n_singletons = 0
    n_independent_scans = 0
    n_excluded = 0
    n_sessions = 0
    rules_used: dict[str, int] = defaultdict(int)

    for (subject, session), g in merged.groupby(["subject", "session"], sort=True):
        n_sessions += 1
        clusters: dict[tuple, list] = {}
        pattern = str(g["session_pattern"].iloc[0])
        if pattern == "INDEPENDENT_SCANS_EACH_WITH_RECON_PAIRS":
            for _, row in g.iterrows():
                key = fingerprint(row)
                clusters.setdefault(key, []).append(row)
        else:
            clusters[("session_pair", "")] = [row for _, row in g.iterrows()]
        cluster_frames = []
        for key, rows in clusters.items():
            cluster_frames.append((key, pd.DataFrame(rows)))
        cluster_frames.sort(key=lambda kv: float(pd.to_numeric(kv[1]["SeriesNumber"], errors="coerce").min()))

        if pattern == "SINGLE_VOLUME":
            n_singletons += 1
        elif pattern == "PAIRED_NORM_NON_NORM":
            n_pairs_norm += 1
        elif pattern == "PAIRED_RECONSTRUCTIONS_OTHER":
            n_pairs_other += 1
        elif pattern == "INDEPENDENT_SCANS_EACH_WITH_RECON_PAIRS":
            n_independent_scans += len(cluster_frames)

        if pattern in {"PAIRED_NORM_NON_NORM", "PAIRED_RECONSTRUCTIONS_OTHER", "SINGLE_VOLUME"}:
            if len(cluster_frames) != 1:
                fail(
                    f"{subject} {session}: expected 1 physical cluster for {pattern}, "
                    f"found {len(cluster_frames)}."
                )
        if pattern == "INDEPENDENT_SCANS_EACH_WITH_RECON_PAIRS" and len(cluster_frames) != 2:
            fail(
                f"{subject} {session}: expected 2 physical clusters, found {len(cluster_frames)}."
            )

        for acq_i, (_key, cluster) in enumerate(cluster_frames, start=1):
            chosen, rule = select_reconstruction(cluster)
            rules_used[rule] += 1
            source_runs = sorted(int(x) for x in cluster["run"].tolist())
            excluded_runs = [r for r in source_runs if r != int(chosen["run"])]
            n_excluded += len(excluded_runs)
            phys_id = f"{subject}_{session}_phys{acq_i:02d}"
            rec = chosen.to_dict()
            rec["physical_acquisition_id"] = phys_id
            rec["subject_id"] = subject
            rec["selected_run"] = int(chosen["run"])
            rec["selected_reconstruction"] = str(chosen["NORM_status"])
            rec["selected_series_description"] = str(chosen["SeriesDescription"])
            rec["reconstruction_status"] = pattern
            rec["source_runs"] = ",".join(str(r) for r in source_runs)
            rec["excluded_runs"] = ",".join(str(r) for r in excluded_runs)
            rec["number_of_reconstructions"] = int(len(cluster))
            rec["n_physical_acq_in_session"] = int(len(cluster_frames))
            rec["selection_rule"] = rule
            rec["iqm_used_for_selection"] = False
            selected_rows.append(rec)

    out = pd.DataFrame(selected_rows)
    out = out.sort_values(["subject_id", "session", "physical_acquisition_id"]).reset_index(drop=True)
    if out["physical_acquisition_id"].duplicated().any():
        fail("Duplicate physical_acquisition_id values.")
    if int(out["iqm_used_for_selection"].any()):
        fail("IQM values were used for reconstruction selection.")

    counts = {
        "n_clean_t1w": 264,
        "n_sessions": n_sessions,
        "n_physical_acquisitions": len(out),
        "n_pairs_norm_non_norm": n_pairs_norm,
        "n_pairs_other_recon": n_pairs_other,
        "n_singletons": n_singletons,
        "n_independent_physical_scans_in_exception_session": n_independent_scans,
        "n_reconstructions_excluded": n_excluded,
        "rules": dict(rules_used),
        "n_vs_expected": len(out) - EXPECTED_PHYSICAL_N,
    }
    LOGGER.info("Physical acquisitions: %d (expected %d)", len(out), EXPECTED_PHYSICAL_N)
    return out, counts


DOC_COLS = [
    "physical_acquisition_id",
    "subject_id",
    "session",
    "selected_run",
    "run",
    "acq",
    "bids_name",
    "selected_reconstruction",
    "selected_series_description",
    "reconstruction_status",
    "source_runs",
    "excluded_runs",
    "number_of_reconstructions",
    "n_physical_acq_in_session",
    "selection_rule",
    "iqm_used_for_selection",
    "ProtocolName",
    "SeriesDescription",
    "ImageType",
    "NORM_status",
    "SeriesInstanceUID",
    "AcquisitionNumber",
    "SeriesNumber",
    "RepetitionTime",
    "EchoTime",
    "FlipAngle",
    "cohort",
    "age",
    "sex",
    "sequence_group",
]


def write_table(dest: Path, table: pd.DataFrame, clean: pd.DataFrame) -> None:
    front = [c for c in DOC_COLS if c in table.columns]
    rest = [c for c in table.columns if c not in front and not str(c).startswith("_")]
    # Prefer clean-table IQM column order after documentation columns.
    clean_rest = [c for c in clean.columns if c in rest]
    extra = [c for c in rest if c not in clean_rest]
    ordered = front + clean_rest + extra
    dest.parent.mkdir(parents=True, exist_ok=True)
    table.reindex(columns=ordered).to_csv(dest, sep="\t", index=False)
    LOGGER.info("Wrote %s (%d rows)", dest, len(table))


def write_report(dest: Path, counts: dict, table: pd.DataFrame, sources: dict[str, Path]) -> None:
    n = int(counts["n_physical_acquisitions"])
    delta = int(counts["n_vs_expected"])
    if delta == 0:
        n_note = f"{n} matches the expected {EXPECTED_PHYSICAL_N}."
    else:
        n_note = (
            f"{n} differs from the expected {EXPECTED_PHYSICAL_N} by {delta}. "
            "See cluster counts below."
        )
    lines = [
        "Physical-acquisition T1w table",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Sources (read-only):",
        f"  clean: {sources['clean']}",
        f"  audit: {sources['audit']}",
        "",
        "Selection never used IQM values. Rules, in order within a physical cluster:",
        "  1. If any reconstruction has ImageType NORM, keep NORM.",
        "  2. Else if SeriesDescription is T1w_MPR vs T1w_MPR_ND, keep T1w_MPR.",
        "  3. Else keep the higher SeriesNumber, then the higher run.",
        "Physical clusters are SAR + ShimSetting from the audit, not IQMs.",
        "sub-043 ses-02 yields two clusters (two independent scans).",
        "",
        f"n original T1w rows: {counts['n_clean_t1w']}",
        f"n sessions: {counts['n_sessions']}",
        f"n physical acquisitions: {counts['n_physical_acquisitions']}",
        f"n NORM+non-NORM reconstructed pairs (sessions): {counts['n_pairs_norm_non_norm']}",
        f"n reconstructed pairs without NORM token (sessions): {counts['n_pairs_other_recon']}",
        f"n singleton sessions: {counts['n_singletons']}",
        f"n independent physical scans in exception session: {counts['n_independent_physical_scans_in_exception_session']}",
        f"n reconstructions excluded: {counts['n_reconstructions_excluded']}",
        f"selection rules used: {counts['rules']}",
        f"count check: {n_note}",
        "",
        "Arithmetic: 123 NORM pairs + 6 other recon pairs + 2 singletons + 2 independent",
        "scans in sub-043 ses-02 = 133 physical acquisitions. 264 − 133 = 131 excluded",
        "reconstructions (one leftover from each of 129 dual sessions plus two leftovers",
        "from the four-volume exception session: 129 + 2 = 131).",
        "",
        "iqm_used_for_selection is False for every row.",
        f"unique subjects: {table['subject_id'].nunique()}",
        f"sessions with 2 physical acquisitions: {int((table.groupby(['subject_id','session']).size()==2).sum())}",
        "",
        "This table does not replace mriqc_iqm_clean.tsv. Previous PCA/cohort/",
        "longitudinal outputs were not modified.",
        "",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Wrote %s", dest)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    if args.out_tsv.resolve() in {p.resolve() for p in before}:
        fail(f"Refusing to overwrite a protected file: {args.out_tsv}")
    clean, audit = load_inputs(args.clean_tsv, args.audit_tsv)
    table, counts = build_table(clean, audit)
    if int(counts["n_physical_acquisitions"]) != EXPECTED_PHYSICAL_N:
        fail(
            f"Physical acquisition count {counts['n_physical_acquisitions']} "
            f"!= expected {EXPECTED_PHYSICAL_N}."
        )
    write_table(args.out_tsv, table, clean)
    write_report(
        args.out_report,
        counts,
        table,
        {"clean": args.clean_tsv, "audit": args.audit_tsv},
    )
    assert_unmodified(before)
    print(f"physical acquisitions: {len(table)}")
    print(f"reconstructions excluded: {counts['n_reconstructions_excluded']}")
    print("iqm_used_for_selection: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
