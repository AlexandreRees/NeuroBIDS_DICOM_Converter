#!/usr/bin/env python3
"""Publication documentation for functional event metadata validation.

Read-only w.r.t. BIDS: does not modify or write any bids/** files.
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path("/home/alexrees/scratch")
OUT = ROOT / "reports" / "stimulus_validation"
OUT.mkdir(parents=True, exist_ok=True)

TOTAL = 507
VALIDATED = 456
MISSING = 51
COVERAGE = 100.0 * VALIDATED / TOTAL

BREAKDOWN = [
    (
        "Duplicate ProtocolName",
        32,
        "Two or more non-phase BOLD acquisitions share the same ProtocolName fMRI_N; unique events↔BOLD mapping impossible.",
    ),
    (
        "Missing Results/stimulus logs",
        8,
        "Mapped visit folder contains no 2-Grating/Results (no scan_info / stim-order sources).",
    ),
    (
        "Duplicate scan_info",
        5,
        "Multiple scan_info files for the same fMRI_number; trigger source not unique.",
    ),
    (
        "Missing scan_info",
        4,
        "Stimulus-order present but no scan_info triggerTimes for the required fMRI_number.",
    ),
    (
        "MATLAB numbering mismatch",
        2,
        "MATLAB fMRI_number (e.g. 5/6) does not match any BOLD ProtocolName (e.g. fMRI3/4_AP).",
    ),
]

assert sum(n for _, n, _ in BREAKDOWN) == MISSING
assert VALIDATED + MISSING == TOTAL

# ---------------------------------------------------------------------------
# TASK 1 — FUNCTIONAL_EVENTS_SUMMARY.tsv
# ---------------------------------------------------------------------------
summary_rows = [
    {
        "Category": "Total task-fMRI acquisitions",
        "Count": TOTAL,
        "Percentage": f"{100.0:.1f}",
        "Description": "Non-phase BIDS task-fmri BOLD runs in the release tree.",
    },
    {
        "Category": "Validated events.tsv released",
        "Count": VALIDATED,
        "Percentage": f"{COVERAGE:.1f}",
        "Description": (
            "Events generated only when scan_info triggerTimes, stimulus order, "
            "and unique ProtocolName↔BOLD mapping were available."
        ),
    },
    {
        "Category": "Runs without events.tsv",
        "Count": MISSING,
        "Percentage": f"{100.0 * MISSING / TOTAL:.1f}",
        "Description": "Intentionally released without events.tsv; no invented timing.",
    },
]
for name, n, desc in BREAKDOWN:
    summary_rows.append(
        {
            "Category": name,
            "Count": n,
            "Percentage": f"{100.0 * n / TOTAL:.1f}",
            "Description": desc,
        }
    )

summary_path = OUT / "FUNCTIONAL_EVENTS_SUMMARY.tsv"
with summary_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=["Category", "Count", "Percentage", "Description"],
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(summary_rows)

# ---------------------------------------------------------------------------
# TASK 2 — Manuscript table
# ---------------------------------------------------------------------------
table_rows = [
    ("Validated event metadata", 456, "Released"),
    ("Ambiguous acquisition mapping", 32, "Withheld"),
    ("Missing stimulus source files", 8, "Withheld"),
    ("Ambiguous trigger source", 5, "Withheld"),
    ("Missing trigger information", 4, "Withheld"),
    ("Protocol mismatch", 2, "Withheld"),
]
assert sum(r[1] for r in table_rows if r[2] == "Withheld") == MISSING
assert table_rows[0][1] == VALIDATED

table_path = OUT / "Table_Functional_Event_Metadata_Status.tsv"
with table_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
    writer.writerow(["Status", "Number of runs", "Percentage", "Action"])
    for status, n, action in table_rows:
        writer.writerow([status, n, f"{100.0 * n / TOTAL:.1f}", action])

# ---------------------------------------------------------------------------
# TASK 3 — Markdown validation report
# ---------------------------------------------------------------------------
report = f"""# Functional event metadata validation

**Dataset component:** `task-fmri` (grating) BOLD acquisitions  
**Policy:** documentation only — BIDS imaging and existing events files were not modified by this report.  
**Provenance inputs:** `reports/stimulus_audit/RECOVERED_EVENTS_PHASE2.md`, `IRRECOVERABLE_EVENTS_AUDIT.md`, `irrecoverable_events_audit.tsv`, live BIDS inventory.

## Overview

Event metadata (`*_events.tsv`) for the grating `task-fmri` paradigm were derived from original experimental records, including:

- scanner trigger recordings stored in MATLAB `scan_info` files (`triggerTimes`);
- MATLAB stimulus-order files (`fMRI_N.mat` / dated `sequence_of_stimuli` containing `Stim_order_selected`);
- BIDS acquisition metadata (`ProtocolName` / `SeriesDescription`) used to bind a protocol number to exactly one non-phase BOLD run.

Events were written **only** when a unique correspondence between the experimental protocol (`fMRI_number`) and a BOLD acquisition could be established, and when measured scanner triggers were available to compute onsets and durations.

**No timing information was manually inferred. No synthetic events were generated.** Acquisitions that failed uniqueness or source-completeness checks were intentionally released **without** an `events.tsv` file rather than with uncertain timing.

## Coverage

| Item | N |
|---|---:|
| Total task-fMRI runs (non-phase BOLD) | {TOTAL} |
| Validated `events.tsv` | {VALIDATED} |
| Runs without `events.tsv` | {MISSING} |
| **Coverage** | **{COVERAGE:.1f}%** |

Machine-readable summary: `FUNCTIONAL_EVENTS_SUMMARY.tsv`.  
Manuscript-oriented table: `Table_Functional_Event_Metadata_Status.tsv`.

## Validation criteria

### 1. BOLD file correspondence

Each released `events.tsv` must correspond to **exactly one** non-phase `task-fmri` BOLD acquisition in the same subject/session. Binding used recorded protocol labels (e.g. `fMRI4_AP` → `fMRI_number` 4). If zero or more than one matching BOLD sidecar was found, events were withheld.

### 2. Timing validity

For every released events file, onsets and durations were computed from measured `triggerTimes` (relative to the first trigger) combined with either:

- the recorded paradigm matrix in a matching `runs_random` workspace, or
- the canonical block design from `presentStimParams.m` (first baseline 10 volumes; 12 cycles of 8 stimulus + 10 baseline volumes).

Released events satisfy:

- `onset >= 0`;
- `duration > 0`;
- chronological ordering of successive events.

No default TR, interpolated triggers, or operator-guessed sync was used.

### 3. Metadata provenance

Provenance for each recoverable conversion required:

- `scan_info` → actual scanner `triggerTimes`;
- stimulus-order file → 12-condition `Stim_order_selected` labels (`stim-01`…`stim-12`);
- unique `ProtocolName` / `SeriesDescription` match → BIDS run destination.

### 4. Ambiguity rejection

If multiple plausible mappings existed (duplicate ProtocolName, duplicate `scan_info`, missing triggers, or MATLAB↔protocol number mismatch), **events were withheld**. Maximizing coverage was not prioritized over mapping certainty.

## Runs without event metadata

**{MISSING}** acquisitions were intentionally released without `events.tsv`. Breakdown (see also `reports/stimulus_audit/IRRECOVERABLE_EVENTS_AUDIT.md`):

| Reason | N runs | Interpretation |
|---|---:|---|
| Duplicate ProtocolName | 32 | Timing often reconstructible, but ≥2 BOLD share the same `fMRI_N` label (often original + redo/rerun). |
| Missing Results / stimulus logs | 8 | No grating Results under the mapped visit (e.g. `sub-051`, `sub-078` ses-01). |
| Duplicate `scan_info` | 5 | Multiple trigger files for the same `fMRI_number`. |
| Missing `scan_info` | 4 | Stim-order present; measured triggers absent. |
| MATLAB numbering mismatch | 2 | MATLAB `fMRI_5/6` vs BOLD `fMRI3/4_AP` (`sub-032`); no unique ProtocolName match. |

**Total withheld:** {MISSING} (= 32 + 8 + 5 + 4 + 2).

## Scientific rationale

Uncertain timing metadata can systematically bias task-fMRI analyses. For this Scientific Data release, **avoiding ambiguous event files was prioritized over maximizing the fraction of runs with events**. Imaging for all {TOTAL} acquisitions remains available; the absence of an `events.tsv` is an explicit, audited statement that a unique experimental↔BOLD timing link could not be established from the archive.

## Recommended manuscript wording

> Task-fMRI (grating) event files were reconstructed from original MATLAB experimental records, including scanner trigger times (`scan_info`) and stimulus-order permutations, and were attached to BOLD runs only when ProtocolName metadata identified a unique non-phase acquisition. Of {TOTAL} task-fMRI BOLD runs, {VALIDATED} ({COVERAGE:.1f}%) were released with validated `events.tsv` files. The remaining {MISSING} runs were intentionally released without event metadata because of non-unique ProtocolName matches (n = 32), missing grating Results (n = 8), duplicate or missing `scan_info` trigger files (n = 5 and n = 4), or MATLAB versus ProtocolName numbering mismatch (n = 2). No timing was manually inferred and no synthetic events were generated.

## Figure

`Figure_Functional_Event_Metadata_Status.png` (also `.pdf`, `.svg`) summarizes coverage workflow, withholding reasons, and quality principles.

## Related audit sources

| File | Role |
|---|---|
| `reports/stimulus_audit/RECOVERED_EVENTS_PHASE2.md` | Phase-2 recovery across all cohorts |
| `reports/stimulus_audit/IRRECOVERABLE_EVENTS_AUDIT.md` | Per-class explanation of the 51 withheld runs |
| `reports/stimulus_audit/irrecoverable_events_audit.tsv` | Run-level classification |
"""

(OUT / "FUNCTIONAL_EVENT_METADATA_VALIDATION.md").write_text(report, encoding="utf-8")

# ---------------------------------------------------------------------------
# TASK 4 — Figure
# ---------------------------------------------------------------------------
plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "font.size": 9,
        "axes.linewidth": 0.8,
        "axes.edgecolor": "#333333",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

fig = plt.figure(figsize=(11.0, 7.2), dpi=200)
gs = fig.add_gridspec(
    2, 2, height_ratios=[1.05, 1.0], width_ratios=[1.15, 1.0], hspace=0.38, wspace=0.32
)

# Panel A — workflow
ax_a = fig.add_subplot(gs[0, :])
ax_a.set_xlim(0, 10)
ax_a.set_ylim(0, 3.2)
ax_a.axis("off")
ax_a.set_title("A. Event metadata workflow", loc="left", fontsize=11, fontweight="bold", pad=8)

boxes = [
    (0.4, 1.1, 2.6, 1.2, f"{TOTAL}\ntask-fMRI runs", "#EEF2F6"),
    (3.7, 1.1, 2.8, 1.2, f"{VALIDATED}\nvalidated events.tsv", "#D9EAD3"),
    (7.0, 1.1, 2.6, 1.2, f"{MISSING}\nwithheld\n(ambiguity / missing sources)", "#FCE8E6"),
]
for x, y, w, h, text, color in boxes:
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.04,rounding_size=0.08",
        linewidth=1.0,
        edgecolor="#333333",
        facecolor=color,
    )
    ax_a.add_patch(patch)
    ax_a.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=10)

for x0, x1 in ((3.0, 3.7), (6.5, 7.0)):
    ax_a.annotate(
        "",
        xy=(x1, 1.7),
        xytext=(x0, 1.7),
        arrowprops=dict(arrowstyle="-|>", color="#333333", lw=1.2),
    )

ax_a.text(
    5.0,
    0.35,
    f"Coverage = {VALIDATED}/{TOTAL} = {COVERAGE:.1f}%   ·   No invented timing   ·   Unique mapping required",
    ha="center",
    va="center",
    fontsize=9,
    color="#333333",
)

# Panel B — bar plot
ax_b = fig.add_subplot(gs[1, 0])
labels = [
    "ProtocolName\nduplication",
    "Missing\nResults",
    "Duplicate\nscan_info",
    "Missing\nscan_info",
    "MATLAB\nmismatch",
]
counts = [32, 8, 5, 4, 2]
colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3"]
bars = ax_b.bar(
    range(len(counts)),
    counts,
    color=colors,
    edgecolor="#333333",
    linewidth=0.6,
    width=0.72,
)
ax_b.set_xticks(range(len(labels)))
ax_b.set_xticklabels(labels, fontsize=8)
ax_b.set_ylabel("Number of runs")
ax_b.set_ylim(0, max(counts) * 1.18)
ax_b.set_title(
    "B. Reasons for withheld events (n = 51)", loc="left", fontsize=11, fontweight="bold"
)
ax_b.spines["top"].set_visible(False)
ax_b.spines["right"].set_visible(False)
for bar, n in zip(bars, counts):
    ax_b.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.6,
        str(n),
        ha="center",
        va="bottom",
        fontsize=9,
    )

# Panel C — principles
ax_c = fig.add_subplot(gs[1, 1])
ax_c.axis("off")
ax_c.set_title("C. Quality principles", loc="left", fontsize=11, fontweight="bold", pad=8)
ax_c.add_patch(
    FancyBboxPatch(
        (0.02, 0.08),
        0.96,
        0.84,
        transform=ax_c.transAxes,
        boxstyle="round,pad=0.02,rounding_size=0.02",
        linewidth=1.0,
        edgecolor="#CCCCCC",
        facecolor="#FAFAFA",
        zorder=0,
    )
)
principles = [
    "Original experimental sources only",
    "Unique BOLD ↔ protocol mapping required",
    "No invented or interpolated timing",
    "BIDS-compatible events.tsv when released",
]
y = 0.82
for text in principles:
    ax_c.text(
        0.06,
        y,
        "✓",
        transform=ax_c.transAxes,
        fontsize=14,
        color="#2E7D32",
        fontweight="bold",
        va="center",
        zorder=1,
    )
    ax_c.text(
        0.14,
        y,
        text,
        transform=ax_c.transAxes,
        fontsize=10,
        va="center",
        color="#222222",
        zorder=1,
    )
    y -= 0.18

fig.suptitle(
    "Functional event metadata status (task-fMRI)",
    fontsize=13,
    fontweight="bold",
    y=0.98,
)

for ext in ("png", "pdf", "svg"):
    fig.savefig(
        OUT / f"Figure_Functional_Event_Metadata_Status.{ext}",
        dpi=300 if ext == "png" else None,
    )
plt.close(fig)

# ---------------------------------------------------------------------------
# TASK 5 — README snippet
# ---------------------------------------------------------------------------
readme = """# Event metadata availability

Validated task-fMRI event files are provided for 456 acquisitions.
Files were generated only when a unique correspondence between
experimental logs and BOLD acquisitions could be established.
Acquisitions lacking an unambiguous mapping were intentionally
released without event files.

Of 507 non-phase `task-fmri` BOLD runs, 456 (89.9%) include a validated
`*_events.tsv`. The remaining 51 runs were withheld from event release
because of duplicate ProtocolName matches (n = 32), missing grating
Results (n = 8), duplicate or missing `scan_info` trigger files
(n = 5 and n = 4), or MATLAB versus ProtocolName numbering mismatch
(n = 2). No timing was manually inferred and no synthetic events were
generated.

See `FUNCTIONAL_EVENT_METADATA_VALIDATION.md` for full validation criteria
and `Figure_Functional_Event_Metadata_Status.png` for a summary figure.
"""
(OUT / "README_EVENTS_SECTION.md").write_text(readme, encoding="utf-8")

# ---------------------------------------------------------------------------
# TASK 6 — INDEX
# ---------------------------------------------------------------------------
index = """# Functional event metadata validation — index

Publication documentation package (read-only w.r.t. BIDS).  
Directory: `reports/stimulus_validation/`

## Generated files

| File | Description |
|---|---|
| `FUNCTIONAL_EVENTS_SUMMARY.tsv` | Coverage counts and withholding breakdown |
| `Table_Functional_Event_Metadata_Status.tsv` | Manuscript table (status / N / % / action) |
| `FUNCTIONAL_EVENT_METADATA_VALIDATION.md` | Scientific Data–style validation report |
| `Figure_Functional_Event_Metadata_Status.png` | Publication figure (PNG) |
| `Figure_Functional_Event_Metadata_Status.pdf` | Publication figure (PDF) |
| `Figure_Functional_Event_Metadata_Status.svg` | Publication figure (SVG) |
| `README_EVENTS_SECTION.md` | Dataset README snippet |
| `INDEX.md` | This file |

## Source audits (not modified)

| File | Role |
|---|---|
| `reports/stimulus_audit/RECOVERED_EVENTS_PHASE2.md` | Phase-2 recovery summary |
| `reports/stimulus_audit/IRRECOVERABLE_EVENTS_AUDIT.md` | Why 51 runs remain without events |
| `reports/stimulus_audit/irrecoverable_events_audit.tsv` | Run-level classification |

## Headline numbers

- Total task-fMRI runs: **507**
- Validated events.tsv: **456**
- Missing events: **51**
- Coverage: **89.9%**
"""
(OUT / "INDEX.md").write_text(index, encoding="utf-8")

print("FUNCTIONAL EVENT METADATA VALIDATION COMPLETE")
print()
print("Total runs:", TOTAL)
print("Validated events:", VALIDATED)
print("Missing events:", MISSING)
print(f"Coverage: {COVERAGE:.1f}%")
print()
print("No BIDS files modified.")
print()
print("Outputs written to:", OUT)
for path in sorted(OUT.iterdir()):
    print(f"  {path.name}  ({path.stat().st_size} bytes)")
