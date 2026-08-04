# Functional event metadata validation

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
| Total task-fMRI runs (non-phase BOLD) | 507 |
| Validated `events.tsv` | 456 |
| Runs without `events.tsv` | 51 |
| **Coverage** | **89.9%** |

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

**51** acquisitions were intentionally released without `events.tsv`. Breakdown (see also `reports/stimulus_audit/IRRECOVERABLE_EVENTS_AUDIT.md`):

| Reason | N runs | Interpretation |
|---|---:|---|
| Duplicate ProtocolName | 32 | Timing often reconstructible, but ≥2 BOLD share the same `fMRI_N` label (often original + redo/rerun). |
| Missing Results / stimulus logs | 8 | No grating Results under the mapped visit (e.g. `sub-051`, `sub-078` ses-01). |
| Duplicate `scan_info` | 5 | Multiple trigger files for the same `fMRI_number`. |
| Missing `scan_info` | 4 | Stim-order present; measured triggers absent. |
| MATLAB numbering mismatch | 2 | MATLAB `fMRI_5/6` vs BOLD `fMRI3/4_AP` (`sub-032`); no unique ProtocolName match. |

**Total withheld:** 51 (= 32 + 8 + 5 + 4 + 2).

## Scientific rationale

Uncertain timing metadata can systematically bias task-fMRI analyses. For this Scientific Data release, **avoiding ambiguous event files was prioritized over maximizing the fraction of runs with events**. Imaging for all 507 acquisitions remains available; the absence of an `events.tsv` is an explicit, audited statement that a unique experimental↔BOLD timing link could not be established from the archive.

## Recommended manuscript wording

> Task-fMRI (grating) event files were reconstructed from original MATLAB experimental records, including scanner trigger times (`scan_info`) and stimulus-order permutations, and were attached to BOLD runs only when ProtocolName metadata identified a unique non-phase acquisition. Of 507 task-fMRI BOLD runs, 456 (89.9%) were released with validated `events.tsv` files. The remaining 51 runs were intentionally released without event metadata because of non-unique ProtocolName matches (n = 32), missing grating Results (n = 8), duplicate or missing `scan_info` trigger files (n = 5 and n = 4), or MATLAB versus ProtocolName numbering mismatch (n = 2). No timing was manually inferred and no synthetic events were generated.

## Figure

`Figure_Functional_Event_Metadata_Status.png` (also `.pdf`, `.svg`) summarizes coverage workflow, withholding reasons, and quality principles.

## Related audit sources

| File | Role |
|---|---|
| `reports/stimulus_audit/RECOVERED_EVENTS_PHASE2.md` | Phase-2 recovery across all cohorts |
| `reports/stimulus_audit/IRRECOVERABLE_EVENTS_AUDIT.md` | Per-class explanation of the 51 withheld runs |
| `reports/stimulus_audit/irrecoverable_events_audit.tsv` | Run-level classification |
