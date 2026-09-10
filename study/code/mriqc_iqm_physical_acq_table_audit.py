#!/usr/bin/env python3
"""Audit and freeze the physical-acquisition MRIQC T1w analytical table.

Loads study/metadata/mriqc_iqm_physical_acquisition.tsv (133 rows).
Does not modify that file. Does not drop rows or IQMs. Does not rerun
MRIQC, PCA, MixedLM, or Elastic Net. Does not join FreeSurfer.

The working copy is a documented snapshot of the same 133 observations
with one additive derived column (software_platform). Zero-variance
IQMs stay in the table and are listed in the QC report.

Example:
  python code/mriqc_iqm_physical_acq_table_audit.py
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import (  # noqa: E402
    EXPECTED_COHORTS,
    NEAR_ZERO_REL_SD,
    fail,
    iqm_family,
    require_columns,
    require_file,
    to_numeric_iqm,
)
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    EXPECTED_PHYSICAL_N,
    N_T1W_USABLE,
    assert_unmodified,
    file_sha256,
    snapshot_protected,
    software_platform_from_scanner,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.table_audit")

REQUIRED_ID_COLS = (
    "physical_acquisition_id",
    "subject_id",
    "session",
    "run",
    "bids_name",
    "cohort",
    "age",
    "sex",
    "scanner",
    "sequence_group",
    "filename",
    "selection_rule",
    "iqm_used_for_selection",
    "n_physical_acq_in_session",
)
EXPECTED_N_SESSIONS = 132
EXPECTED_N_SUBJECTS = 83
EXPECTED_N_RETAINED_IQMS = 58
EXPECTED_MULTI_ACQ_CELLS = {("sub-043", "ses-02")}
SUBJECT_RE = re.compile(r"^sub-\d{3}$")
SESSION_RE = re.compile(r"^ses-0[12]$")
PHYS_ID_RE = re.compile(r"^sub-\d{3}_ses-0[12]_phys\d{2}$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--source-tsv", type=Path, default=None)
    parser.add_argument("--roles-tsv", type=Path, default=None)
    parser.add_argument("--out-tsv", type=Path, default=None)
    parser.add_argument("--out-iqm-tsv", type=Path, default=None)
    parser.add_argument("--out-report", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    meta = root / "metadata"
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.source_tsv = (
        args.source_tsv.resolve()
        if args.source_tsv
        else meta / "mriqc_iqm_physical_acquisition.tsv"
    )
    args.roles_tsv = (
        args.roles_tsv.resolve() if args.roles_tsv else meta / "mriqc_iqm_column_roles.tsv"
    )
    args.out_tsv = (
        args.out_tsv.resolve()
        if args.out_tsv
        else meta / "mriqc_iqm_physical_acquisition_analytic.tsv"
    )
    args.out_iqm_tsv = (
        args.out_iqm_tsv.resolve()
        if args.out_iqm_tsv
        else qc / "physical_acquisition_table_audit_iqms.tsv"
    )
    args.out_report = (
        args.out_report.resolve()
        if args.out_report
        else qc / "physical_acquisition_table_audit_report.txt"
    )
    if args.out_tsv.resolve() == args.source_tsv.resolve():
        fail("Working-copy path must not overwrite the canonical physical-acquisition table.")
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)


def load_retained_iqms(roles_path: Path, table: pd.DataFrame) -> list[str]:
    require_file(roles_path, "column-role table")
    roles = pd.read_csv(roles_path, sep="\t")
    require_columns(roles, ["column", "retained_for_statistics", "role"], "column-role table")
    retained = roles.loc[roles["retained_for_statistics"].astype(bool), "column"].astype(str).tolist()
    if len(retained) != EXPECTED_N_RETAINED_IQMS:
        fail(
            f"Expected {EXPECTED_N_RETAINED_IQMS} retained IQMs in {roles_path}, "
            f"found {len(retained)}."
        )
    leaked = [
        c
        for c in retained
        if str(roles.loc[roles["column"] == c, "role"].iloc[0]) != "iqm"
    ]
    if leaked:
        fail(f"Non-IQM columns marked retained_for_statistics: {leaked}")
    missing = [c for c in retained if c not in table.columns]
    if missing:
        fail(f"Canonical table is missing retained IQMs: {missing}")
    return retained


def is_blank(value: Any) -> bool:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none", "<na>"}


def duplicate_keys(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    present = [c for c in cols if c in df.columns]
    if len(present) != len(cols):
        return pd.DataFrame()
    mask = df.duplicated(present, keep=False)
    if not mask.any():
        return pd.DataFrame()
    return df.loc[mask, present].sort_values(present).reset_index(drop=True)


def fmt_pairs(counts: pd.Series) -> str:
    return ", ".join(f"{idx}={int(n)}" for idx, n in counts.items())


def constant_columns(df: pd.DataFrame, exclude: set[str]) -> list[str]:
    names: list[str] = []
    for col in df.columns:
        if col in exclude:
            continue
        nunique = int(df[col].nunique(dropna=False))
        if nunique <= 1:
            names.append(col)
    return names


def iqm_catalog(df: pd.DataFrame, iqms: list[str], rel_sd: float) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n = len(df)
    for name in iqms:
        series = to_numeric_iqm(df[name])
        n_missing = int(series.isna().sum())
        n_valid = int(series.notna().sum())
        valid = series.dropna()
        nunique = int(valid.nunique()) if n_valid else 0
        variance = float(valid.var(ddof=0)) if n_valid else float("nan")
        sd = float(valid.std(ddof=0)) if n_valid else float("nan")
        mean = float(valid.mean()) if n_valid else float("nan")
        zero = bool(n_valid == 0 or nunique <= 1 or (np.isfinite(sd) and sd == 0.0))
        rel = abs(sd) / (abs(mean) + 1e-12) if np.isfinite(sd) and np.isfinite(mean) else float("nan")
        near = bool((not zero) and np.isfinite(rel) and rel < rel_sd)
        rows.append(
            {
                "iqm": name,
                "family": iqm_family(name),
                "n_rows": n,
                "n_valid": n_valid,
                "n_missing": n_missing,
                "missing_pct": 100.0 * n_missing / n if n else float("nan"),
                "nunique": nunique,
                "mean": mean,
                "sd": sd,
                "variance": variance,
                "zero_variance": zero,
                "near_zero_variance": near,
            }
        )
    return pd.DataFrame(rows)


def build_working_copy(source: pd.DataFrame) -> pd.DataFrame:
    out = source.copy()
    if "software_platform" not in out.columns:
        platform = software_platform_from_scanner(out["scanner"])
        cols = list(out.columns)
        insert_at = cols.index("scanner") + 1 if "scanner" in cols else len(cols)
        out.insert(insert_at, "software_platform", platform)
    else:
        derived = software_platform_from_scanner(out["scanner"])
        mismatch = out["software_platform"].astype(str) != derived.astype(str)
        if mismatch.any():
            fail("Existing software_platform disagrees with scanner mapping.")
    if len(out) != len(source):
        fail("Working copy changed the number of rows.")
    dropped = [c for c in source.columns if c not in out.columns]
    if dropped:
        fail(f"Working copy dropped source columns: {dropped}")
    return out


def audit(source: pd.DataFrame, iqms: list[str]) -> dict[str, Any]:
    n = len(source)
    if n != EXPECTED_PHYSICAL_N:
        fail(f"Expected {EXPECTED_PHYSICAL_N} physical-acquisition rows, found {n}.")

    require_columns(source, REQUIRED_ID_COLS, "physical-acquisition table")

    id_missing = {
        col: int(source[col].map(is_blank).sum())
        for col in ("physical_acquisition_id", "subject_id", "session", "cohort", "bids_name")
    }
    if any(id_missing.values()):
        fail(f"Missing identifiers: {id_missing}")

    bad_subject = source.loc[~source["subject_id"].astype(str).str.match(SUBJECT_RE), "subject_id"]
    if len(bad_subject):
        fail(f"Unexpected subject_id values: {sorted(set(bad_subject.astype(str)))}")
    bad_session = source.loc[~source["session"].astype(str).str.match(SESSION_RE), "session"]
    if len(bad_session):
        fail(f"Unexpected session values: {sorted(set(bad_session.astype(str)))}")
    bad_phys = source.loc[
        ~source["physical_acquisition_id"].astype(str).str.match(PHYS_ID_RE),
        "physical_acquisition_id",
    ]
    if len(bad_phys):
        fail(f"Unexpected physical_acquisition_id values: {sorted(set(bad_phys.astype(str)))}")

    extra_cohorts = sorted(set(source["cohort"].astype(str)) - set(EXPECTED_COHORTS))
    if extra_cohorts:
        fail(f"Unexpected cohorts: {extra_cohorts}")

    if source["physical_acquisition_id"].duplicated().any():
        dups = source.loc[
            source["physical_acquisition_id"].duplicated(keep=False),
            "physical_acquisition_id",
        ]
        fail(f"Duplicate physical_acquisition_id values: {sorted(set(dups.astype(str)))}")

    dup_tables = {
        "physical_acquisition_id": duplicate_keys(source, ["physical_acquisition_id"]),
        "bids_name": duplicate_keys(source, ["bids_name"]),
        "filename": duplicate_keys(source, ["filename"]),
        "subject_session_run": duplicate_keys(source, ["subject_id", "session", "run"]),
        "full_row": source.loc[source.duplicated(keep=False)].copy(),
    }
    hard_dups = {k: v for k, v in dup_tables.items() if len(v)}
    if hard_dups:
        detail = ", ".join(f"{k}={len(v)}" for k, v in hard_dups.items())
        fail(f"Duplicate analytical keys found ({detail}). No rows were dropped.")

    cell_n = source.groupby(["subject_id", "session"], sort=True).size()
    multi_cells = set(cell_n[cell_n > 1].index.tolist())
    if multi_cells != EXPECTED_MULTI_ACQ_CELLS:
        fail(
            "subject×session cells with more than one physical acquisition "
            f"were {sorted(multi_cells)}, expected {sorted(EXPECTED_MULTI_ACQ_CELLS)}. "
            "No rows were dropped."
        )
    if int((cell_n > 2).sum()):
        fail("A subject×session cell has more than two physical acquisitions.")

    counted = source.groupby(["subject_id", "session"])["n_physical_acq_in_session"].transform("size")
    disagree = counted != pd.to_numeric(source["n_physical_acq_in_session"], errors="coerce")
    if disagree.any():
        fail("n_physical_acq_in_session disagrees with the row counts.")

    if "iqm_used_for_selection" in source.columns and bool(
        pd.Series(source["iqm_used_for_selection"]).astype(str).str.lower().isin(["true", "1"]).any()
    ):
        fail("iqm_used_for_selection is True; reconstruction choice must be IQM-independent.")

    seq = source["sequence_group"].astype(str).unique().tolist()
    if seq != ["T1w"]:
        fail(f"Analytical table must be T1w only, found sequence_group={seq}")

    catalog = iqm_catalog(source, iqms, NEAR_ZERO_REL_SD)
    zero_iqms = catalog.loc[catalog["zero_variance"], "iqm"].tolist()
    near_iqms = catalog.loc[catalog["near_zero_variance"], "iqm"].tolist()
    missing_iqms = catalog.loc[catalog["n_missing"] > 0, "iqm"].tolist()
    n_usable = int((~catalog["zero_variance"]).sum())
    if n_usable != N_T1W_USABLE:
        LOGGER.warning(
            "Non-constant retained IQMs=%d (historical analysis set was %d). "
            "Zero-variance IQMs were kept in the working copy.",
            n_usable,
            N_T1W_USABLE,
        )

    n_subjects = int(source["subject_id"].nunique())
    n_sessions = int(source.groupby(["subject_id", "session"]).ngroups)
    if n_subjects != EXPECTED_N_SUBJECTS:
        fail(f"Expected {EXPECTED_N_SUBJECTS} subjects, found {n_subjects}.")
    if n_sessions != EXPECTED_N_SESSIONS:
        fail(f"Expected {EXPECTED_N_SESSIONS} sessions, found {n_sessions}.")

    constant_other = constant_columns(source, exclude=set(iqms))
    age_missing = int(pd.to_numeric(source["age"], errors="coerce").isna().sum())
    sex_missing = int(source["sex"].map(is_blank).sum())
    if age_missing or sex_missing:
        fail(f"Missing covariates: age={age_missing} sex={sex_missing}")

    return {
        "n_rows": n,
        "n_subjects": n_subjects,
        "n_sessions": n_sessions,
        "n_acquisitions": n,
        "n_cohorts": int(source["cohort"].nunique()),
        "n_by_cohort": source["cohort"].astype(str).value_counts().reindex(EXPECTED_COHORTS).fillna(0).astype(int),
        "n_subjects_by_cohort": source.groupby("cohort")["subject_id"].nunique().reindex(EXPECTED_COHORTS).fillna(0).astype(int),
        "n_by_session": source["session"].astype(str).value_counts().sort_index(),
        "n_subjects_both_sessions": int(
            (source.groupby("subject_id")["session"].nunique() == 2).sum()
        ),
        "multi_acq_cells": sorted(multi_cells),
        "catalog": catalog,
        "zero_variance_iqms": zero_iqms,
        "near_zero_variance_iqms": near_iqms,
        "iqms_with_missing": missing_iqms,
        "n_retained_iqms": len(iqms),
        "n_nonconstant_iqms": n_usable,
        "constant_non_iqm_columns": constant_other,
        "id_missing": id_missing,
        "duplicates": {k: int(len(v)) for k, v in dup_tables.items()},
    }


def write_report(
    dest: Path,
    audit_info: dict[str, Any],
    source_path: Path,
    source_sha: str,
    out_tsv: Path,
    out_iqm: Path,
) -> None:
    catalog: pd.DataFrame = audit_info["catalog"]
    if audit_info["iqms_with_missing"]:
        missing_block = [
            f"    {row['iqm']}: missing={int(row['n_missing'])} "
            f"({row['missing_pct']:.4g}%)"
            for _, row in catalog.loc[catalog["n_missing"] > 0].iterrows()
        ]
    else:
        missing_block = ["  none"]
    const_other = audit_info["constant_non_iqm_columns"]
    const_preview = const_other if len(const_other) <= 40 else const_other[:40] + ["..."]
    lines = [
        "Physical-acquisition MRIQC T1w table — QC audit",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "SCOPE",
        "  Unit of observation: one physical T1w acquisition (not a Siemens reconstruction pair).",
        "  Canonical source is read-only. IQMs were not recalculated. MRIQC was not rerun.",
        "  PCA, MixedLM, Elastic Net and FreeSurfer were not run. No rows were dropped.",
        "  The 264-row reconstruction-level table is not the analytical reference.",
        "",
        "SOURCE (unchanged)",
        f"  path: {source_path}",
        f"  sha256: {source_sha}",
        "",
        "COUNTS",
        f"  n_rows: {audit_info['n_rows']}",
        f"  n_subjects: {audit_info['n_subjects']}",
        f"  n_sessions: {audit_info['n_sessions']}",
        f"  n_acquisitions: {audit_info['n_acquisitions']}",
        f"  n_cohorts: {audit_info['n_cohorts']}",
        f"  n_by_cohort: {{{fmt_pairs(audit_info['n_by_cohort'])}}}",
        f"  n_subjects_by_cohort: {{{fmt_pairs(audit_info['n_subjects_by_cohort'])}}}",
        f"  n_by_session: {{{fmt_pairs(audit_info['n_by_session'])}}}",
        f"  subjects with ses-01 and ses-02: {audit_info['n_subjects_both_sessions']}",
        f"  subject×session cells with 2 physical acquisitions: {audit_info['multi_acq_cells']}",
        "",
        "ONE PHYSICAL ACQUISITION = ONE ANALYTICAL ROW",
        "  unique physical_acquisition_id: yes",
        "  unique bids_name / filename: yes",
        "  unique subject_id + session + run: yes",
        "  Expected exception kept: sub-043 ses-02 contributes two independent scans.",
        "  Duplicate keys: none",
        f"  missing identifiers: {audit_info['id_missing']}",
        "",
        "IQMs",
        f"  retained IQMs in column-role catalog: {audit_info['n_retained_iqms']}",
        f"  non-constant IQMs: {audit_info['n_nonconstant_iqms']}",
        f"  zero variance: {audit_info['zero_variance_iqms'] or 'none'}",
        f"  near-zero variance: {audit_info['near_zero_variance_iqms'] or 'none'}",
        "  missing values by IQM:",
        *missing_block,
        "  Zero-variance IQMs were documented, not deleted.",
        "",
        "NON-IQM CONSTANT COLUMNS (documented, not dropped)",
        f"  n: {len(const_other)}",
        f"  names: {const_preview}",
        "",
        "WORKING COPY",
        f"  path: {out_tsv}",
        "  rows: same 133 physical acquisitions as the canonical table",
        "  columns: all source columns plus software_platform (E11/XA30 from scanner)",
        "  silent deletions: none",
        f"  IQM missingness/variance table: {out_iqm}",
        "",
        "NOT DONE",
        "  PCA, MixedLM, Elastic Net, FreeSurfer join, MRIQC rerun.",
        "",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Wrote %s", dest)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    source_path = require_file(args.source_tsv, "physical-acquisition table")
    source_sha_before = file_sha256(source_path)
    before[source_path] = source_sha_before

    source = pd.read_csv(source_path, sep="\t")
    iqms = load_retained_iqms(args.roles_tsv, source)
    info = audit(source, iqms)
    working = build_working_copy(source)

    args.out_iqm_tsv.parent.mkdir(parents=True, exist_ok=True)
    info["catalog"].to_csv(args.out_iqm_tsv, sep="\t", index=False)
    LOGGER.info("Wrote %s", args.out_iqm_tsv)

    args.out_tsv.parent.mkdir(parents=True, exist_ok=True)
    working.to_csv(args.out_tsv, sep="\t", index=False)
    LOGGER.info("Wrote %s (%d rows, %d columns)", args.out_tsv, len(working), working.shape[1])

    write_report(
        args.out_report,
        info,
        source_path,
        source_sha_before,
        args.out_tsv,
        args.out_iqm_tsv,
    )
    assert_unmodified(before)
    if file_sha256(source_path) != source_sha_before:
        fail(f"Canonical table changed during the run: {source_path}")

    print(
        "Physical-acquisition table audit OK: "
        f"n_rows={info['n_rows']} n_subjects={info['n_subjects']} "
        f"n_sessions={info['n_sessions']} n_acquisitions={info['n_acquisitions']} "
        f"n_cohorts={info['n_cohorts']}"
    )
    print(f"Working copy: {args.out_tsv}")
    print(f"QC report: {args.out_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
