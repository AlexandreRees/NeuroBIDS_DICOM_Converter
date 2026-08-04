# Gradient Validation Report

Generated: 2026-07-23 14:40:37 UTC

## Summary

- PASS: **250** / 361
- REVIEW: **111** / 361
- FAIL: **0** / 361

No gradient orientation corrections were applied to the distributed dataset.

## REVIEW classification

- `axis_swap`: **51**
- `axis_flip_and_swap`: **44**
- `axis_flip`: **16**

## Interpretation

`dwigradcheck` ranks orientation hypotheses. Identity (no axis flip, permutation (0,1,2)) is scored PASS. Any non-identity top-ranked transform is REVIEW (suggested correction reported, not applied).

See `Gradient_QC.tsv`, `Gradient_QC_summary.png`, and gradient sphere figures.
