#!/usr/bin/env python3
"""MRIQC coverage audit: BIDS expected T1w + magnitude BOLD vs derivatives IQMs."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BIDS = Path("/home/alexrees/scratch/bids")
MRIQC = Path("/home/alexrees/scratch/derivatives/mriqc")
OUT = Path("/home/alexrees/scratch/reports/mriqc_coverage_audit")
TASKS = Path("/home/alexrees/scratch/metadata/mriqc_array_tasks.tsv")


def pair_from(p: Path):
    parts = p.parts
    sub = next((x for x in parts if x.startswith("sub-")), None)
    ses = next((x for x in parts if x.startswith("ses-")), None)
    name = p.name
    if sub is None:
        for tok in name.split("_"):
            if tok.startswith("sub-"):
                sub = tok
    if ses is None:
        for tok in name.split("_"):
            if tok.startswith("ses-"):
                ses = tok
    return sub, ses


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = pd.read_csv(TASKS, sep="\t", dtype=str)
    tasks["session"] = tasks["session_id"].apply(lambda x: f"ses-{int(x):02d}")
    tasks["array_task_id"] = range(1, len(tasks) + 1)

    exp_t1: dict[tuple[str, str], list[str]] = defaultdict(list)
    exp_bold: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in BIDS.rglob("*_T1w.nii.gz"):
        if "derivatives" in p.parts:
            continue
        key = pair_from(p)
        exp_t1[key].append(p.name.replace(".nii.gz", ""))
    for p in BIDS.rglob("*_bold.nii.gz"):
        if "derivatives" in p.parts:
            continue
        if "_part-phase" in p.name:
            continue
        key = pair_from(p)
        exp_bold[key].append(p.name.replace(".nii.gz", ""))

    got_t1: dict[tuple[str, str], set[str]] = defaultdict(set)
    got_bold: dict[tuple[str, str], set[str]] = defaultdict(set)
    for p in MRIQC.rglob("*_T1w.json"):
        if "group" in p.parts:
            continue
        key = pair_from(p)
        got_t1[key].add(p.name.replace(".json", ""))
    for p in MRIQC.rglob("*_bold.json"):
        if "group" in p.parts:
            continue
        key = pair_from(p)
        got_bold[key].add(p.name.replace(".json", ""))

    sessions = sorted(set(exp_t1) | set(exp_bold) | set(got_t1) | set(got_bold))
    rows = []
    missing_run_rows = []
    for sub, ses in sessions:
        et = exp_t1.get((sub, ses), [])
        eb = exp_bold.get((sub, ses), [])
        gt = got_t1.get((sub, ses), set())
        gb = got_bold.get((sub, ses), set())

        def missing(expected, got):
            miss = []
            for s in expected:
                if s in got:
                    continue
                if any(s == x or s in x or x in s for x in got):
                    continue
                miss.append(s)
            return miss

        miss_t1 = missing(et, gt)
        miss_bold = missing(eb, gb)
        t1_ok = len(miss_t1) == 0 and len(gt) >= len(et)
        # Prefer stem match completeness
        t1_complete = len(miss_t1) == 0
        bold_complete = len(miss_bold) == 0
        session_complete = t1_complete and bold_complete

        if len(gt) == 0 and len(gb) == 0:
            status = "MISSING"
        elif len(gt) == 0 and len(et) == 0:
            status = "BOLD_ONLY"
        elif len(gt) == 0:
            status = "BOLD_ONLY"
        elif len(gb) == 0:
            status = "T1W_ONLY"
        else:
            status = "COMPLETE_BOTH" if session_complete else "PARTIAL"

        rows.append(
            {
                "subject": sub,
                "session": ses,
                "expected_t1w": len(et),
                "mriqc_t1w": len(gt),
                "t1w_complete": t1_complete,
                "expected_bold": len(eb),
                "mriqc_bold": len(gb),
                "bold_complete": bold_complete,
                "session_complete": session_complete,
                "status": status,
                "n_missing_t1w": len(miss_t1),
                "n_missing_bold": len(miss_bold),
            }
        )
        if miss_t1 or miss_bold:
            missing_run_rows.append(
                {
                    "subject": sub,
                    "session": ses,
                    "missing_t1w": ";".join(miss_t1),
                    "missing_bold": ";".join(miss_bold[:12])
                    + ("..." if len(miss_bold) > 12 else ""),
                    "n_missing_t1w": len(miss_t1),
                    "n_missing_bold": len(miss_bold),
                }
            )

    df = pd.DataFrame(rows).sort_values(["subject", "session"])
    miss_df = pd.DataFrame(missing_run_rows).sort_values(
        ["n_missing_bold", "n_missing_t1w", "subject"], ascending=[False, False, True]
    )

    df.to_csv(OUT / "mriqc_iqm_completeness.tsv", sep="\t", index=False)
    miss_df.to_csv(OUT / "mriqc_missing_runs.tsv", sep="\t", index=False)
    df[
        [
            "subject",
            "session",
            "expected_t1w",
            "mriqc_t1w",
            "expected_bold",
            "mriqc_bold",
            "status",
            "session_complete",
        ]
    ].to_csv(OUT / "mriqc_session_coverage.tsv", sep="\t", index=False)

    n_sess = len(df)
    n_complete = int(df.session_complete.sum())
    n_t1 = int(df.expected_t1w.sum())
    g_t1 = int(df.mriqc_t1w.sum())
    n_bold = int(df.expected_bold.sum())
    g_bold = int(df.mriqc_bold.sum())
    status_counts = df.status.value_counts().to_dict()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    verdict = "PASS" if n_complete == n_sess and g_t1 >= n_t1 and g_bold >= n_bold else "FAIL"

    md = []
    md.append("# MRIQC coverage audit (post-retry)")
    md.append("")
    md.append(f"**Generated:** {now}")
    md.append(f"**Verdict:** **{verdict}**")
    md.append(f"**BIDS:** `{BIDS}`")
    md.append(f"**Derivatives:** `{MRIQC}`")
    md.append("")
    md.append("## Summary")
    md.append("")
    md.append("| Level | Complete | Expected | Coverage |")
    md.append("| --- | ---: | ---: | ---: |")
    md.append(
        f"| Sessions (all expected T1w+BOLD IQMs) | {n_complete} | {n_sess} | {100*n_complete/n_sess:.1f}% |"
    )
    md.append(f"| T1w IQMs | {g_t1} | {n_t1} | {100*g_t1/n_t1:.1f}% |")
    md.append(f"| BOLD IQMs (magnitude) | {g_bold} | {n_bold} | {100*g_bold/n_bold:.1f}% |")
    md.append("")
    md.append("### Status counts")
    md.append("")
    md.append("| Status | N |")
    md.append("| --- | ---: |")
    for k, v in sorted(status_counts.items()):
        md.append(f"| `{k}` | {v} |")
    md.append("")
    incomplete = df[~df.session_complete]
    md.append("## Incomplete sessions")
    md.append("")
    if len(incomplete):
        cols = [
            "subject",
            "session",
            "mriqc_t1w",
            "expected_t1w",
            "mriqc_bold",
            "expected_bold",
            "n_missing_t1w",
            "n_missing_bold",
            "status",
        ]
        md.append("| " + " | ".join(cols) + " |")
        md.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for _, r in incomplete.iterrows():
            md.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
        md.append("")
    else:
        md.append("None — full IQM coverage.")
        md.append("")

    report = OUT / "MRIQC_COVERAGE_AUDIT.md"
    report.write_text("\n".join(md) + "\n")
    print(f"VERDICT={verdict}")
    print(f"sessions_complete={n_complete}/{n_sess}")
    print(f"t1w={g_t1}/{n_t1}")
    print(f"bold={g_bold}/{n_bold}")
    print(f"report={report}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
