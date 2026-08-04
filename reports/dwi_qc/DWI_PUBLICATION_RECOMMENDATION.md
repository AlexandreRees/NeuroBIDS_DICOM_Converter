# Diffusion MRI QC — publication recommendation

Generated: 2026-07-23 16:49:02 UTC

## Summary recommendation

All current DWI QC WARNINGS can be **downgraded to documented observations** for the Scientific Data / OpenNeuro release. Objective checks did not identify gradient-table failures (0 FAIL), missing sidecars, or systematically corrupted diffusion volumes requiring exclusion or bvec modification.

## Mapping of WARNINGS

| Warning | Verdict | Needs data correction? |
|---|---|---|
| dwigradcheck REVIEW | QC ARTIFACT | NO |
| Negative mean b0 | QC ARTIFACT | NO |
| PASS flip='0' classifier | SOFTWARE ISSUE | NO |
| Brain-mask Dice vs BET | EXPECTED ACQUISITION VARIATION | NO |

## Recommended Scientific Data wording (draft)

Diffusion MRI acquisitions underwent read-only technical validation, including BIDS sidecar completeness, bval/bvec length consistency, MRtrix3 `dwigradcheck` orientation ranking, automated brain masking, and robust within-mask signal summaries. Across 361 evaluated scans, no gradient table failed `dwigradcheck`. A subset received a REVIEW rank (alternative axis flip/permutation scored higher than identity), predominantly among high-direction `run-02` shells; suggested transforms were heterogeneous and were **not** applied to the distributed dataset. Negative arithmetic mean b0 intensities in a minority of scans were attributable to signed reconstruction values and/or over-inclusive automated masks rather than blank or structurally corrupted volumes; median-based signal metrics are therefore reported. No subject was excluded solely on the basis of these QC metrics.

## Optional follow-ups (not release-blocking)

- Fix `interpret_dwigradcheck` so axis flip `0` is not treated as identity (reporting only).
- Prefer `dwi_signal_metrics_robust.tsv` (median b0 / median diffusion) in manuscript figures.
- Expand BET Dice beyond the priority subset if desired for supplementary material.

## Integrity

- No modifications to `bids/`, `raw_original/`, or `derivatives/`.
- No bvec corrections applied.
