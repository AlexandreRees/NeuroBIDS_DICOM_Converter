# Provenance of task-fMRI event timing files

**Generated:** 2026-07-23T20:22:57Z  
**Policy:** documentation only; no BIDS events were regenerated in this step.

## Summary

Event timing files (`*_events.tsv`) for `task-fmri` were **generated from the original experimental records**. Timing information was obtained by combining:

1. **Scanner trigger recordings** stored in MATLAB `scan_info` results (`scan.runs.triggerTimes` from the FORP / `t` trigger stream)  
2. **MATLAB stimulus-order logs** (`fMRI_N.mat` / `Stim_order_selected`)  
3. **Protocol metadata** defining the block design (`presentStimParams.m`: initial baseline 10 TR; 12 cycles of 8 TR stimulus + 10 TR baseline)  
4. **BIDS acquisition metadata** (`ProtocolName` / `SeriesDescription`) to attach each timing table to exactly one BOLD run

## Uniqueness requirement

A file was generated **only when a unique correspondence** between experimental logs and one BIDS acquisition could be established (unique non-phase BOLD sidecar matching `fMRI{N}`).

If uniqueness could not be demonstrated, **no** `events.tsv` was generated for that run.

## What was not done

The following were **not** performed:

- no event timing was manually invented  
- no temporal interpolation was performed  
- no synthetic events were introduced  
- no default TR was substituted for missing trigger streams  

When the session `runs_random` workspace belonged to a different fMRI index than the run being processed, the **canonical block design from the original presentation script** was applied to the **same measured trigger times** and per-run stimulus order. That step uses original protocol definitions; it does not invent onsets.

## Output schema

| Column | Description |
|---|---|
| `onset` | Seconds relative to the first recorded scanner trigger of the run |
| `duration` | Seconds |
| `trial_type` | `baseline` or `stim-01` … `stim-12` |

## Counts in the current tree

- Validated event files: **452**  
- task-fMRI BOLD runs without events: **55**  
- Generation provenance log: `reports/stimulus_audit/recoverable_events_generation.tsv`
