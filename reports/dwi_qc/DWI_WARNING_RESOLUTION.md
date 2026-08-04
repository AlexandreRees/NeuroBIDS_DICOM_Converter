# DWI QC warning resolution

Generated: 2026-07-23 16:49:02 UTC

Audit only. bids/, raw_original/, derivatives/ were not modified.

## Warning 1: dwigradcheck REVIEW

**Current warning:** dwigradcheck REVIEW

**Evidence:** n=111; classes={'axis_swap': 25, 'axis_flip_and_swap': 70, 'axis_flip': 16}; runs={'run-02': 102, 'run-01': 3, 'run-04': 2, 'run-05': 3, 'run-03': 1}

**Conclusion:** QC ARTIFACT

**Needs correction?** NO

**Reason:** REVIEW enriched in run-02 (heterogeneous suggestions; no single corrective transform; 0 FAIL).

## Warning 2: Negative mean b0

**Current warning:** Negative mean b0

**Evidence:** n=26; classes={'signed_reconstruction_with_overinclusive_mask': 15, 'signed_reconstruction': 11}

**Conclusion:** QC ARTIFACT

**Needs correction?** NO

**Reason:** All negative mean-b0 scans classified as signed reconstruction ± overinclusive mask; not corrupt volumes.

## Warning 3: PASS flip='0' classifier

**Current warning:** PASS flip='0' classifier

**Evidence:** mislabelled PASS≈3

**Conclusion:** SOFTWARE ISSUE

**Needs correction?** NO

**Reason:** 3 PASS labels treat flip='0' as identity in interpret_dwigradcheck (reporting only).

## Warning 4: Brain-mask Dice vs BET

**Current warning:** Brain-mask Dice vs BET

**Evidence:** BET-checked=97 (priority subset enriched for negative-b0 and high brain-fraction masks; 145/361 scans lacked on-disk `tmp/` masks for re-validation); Dice<0.90=96; median Dice=0.793. This rate is **not** a cohort-wide prevalence estimate.

**Conclusion:** EXPECTED ACQUISITION VARIATION

**Needs correction?** NO

**Reason:** dwi2mask and FSL BET implement different brain-extraction objectives; disagreement is expected and was concentrated in a bias-enriched priority subset. Automated masks remain QC aids only. Do not exclude DWI series solely on Dice<0.90. Prefer robust median signal metrics over mask-fraction thresholds.
