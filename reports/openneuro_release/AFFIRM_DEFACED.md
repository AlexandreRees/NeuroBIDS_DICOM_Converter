# AFFIRM_DEFACED — certification locale

**Generated (UTC):** `2026-08-04T14:35:17Z`  
**Package:** `/lustre07/scratch/alexrees/release_dataset`  
**Defacing derivatives:** `/lustre07/scratch/alexrees/derivatives/defacing`  
**Face-intact reference:** `/lustre07/scratch/alexrees/bids` (must differ)

## Verdict

# **PASS — ready to use OpenNeuro `--affirmDefaced`**

This is a **local certification**, not an OpenNeuro upload. Every face-bearing
anatomical NIfTI under `release_dataset/**/anat/` matches `derivatives/defacing/`
and is **not** identical to the face-intact `bids/` copy.

## Scope checked

| Modality | N in release |
|---|---:|
| T1w | 385 |
| FLAIR | 136 |
| T2w | 0 |
| TB1TFL | 270 |
| **Total** | **791** |

| Metric | N |
|---|---:|
| OK | 791 |
| FAIL | 0 |
| Missing defaced derivative | 0 |
| Identical to face-intact bids | 0 |

Detail: `AFFIRM_DEFACED_ANAT_IDENTITY.tsv` (file size + 1 MiB MD5 prefix).

## Retry11 / post-freeze ses-02

| Subject | Anat files (ses-02) | Status |
|---|---:|---|
| sub-057 | 6 | PASS |
| sub-064 | 5 | PASS |
| sub-066 | 6 | PASS |
| sub-067 | 6 | PASS |
| sub-068 | 6 | PASS |
| sub-069 | 6 | PASS |
| sub-072 | 6 | PASS |
| sub-073 | 6 | PASS |
| sub-074 | 6 | PASS |
| sub-078 | 0 | PASS (no anat) |
| sub-081 | 9 | PASS |

Supporting apply report: `reports/ses02_retry11/RELEASE_SES02_R11_UPDATE.md` (11/11 PASS).

## Failures

None.


## Affirmation statement (for OpenNeuro upload)

> I affirm that all structural MRI scans (T1w, FLAIR, and TB1TFL anatomicals present
> in this public package) have been defaced. Public `release_dataset` anatomicals were
> verified (size + content hash prefix) against `derivatives/defacing` produced with
> pydeface via `neuro_pipeline.modules.defacing.run_defacing_session`, and differ from
> the face-intact research `bids/` tree. No `desc-defaced` filename entities are used;
> standard BIDS anatomical names are retained.

## Still required before actual `openneuro upload --affirmDefaced`

1. Replace placeholder Authors / Name in `dataset_description.json`
2. Confirm REB consent for CC0 redistribution (LICENSE file already present)
3. Re-run bids-validator on `release_dataset/`
4. Optional visual spot-check of a random defaced sample

## Note on prior audit table

`RELEASE_ANAT_IDENTITY_CHECK.tsv` (481 rows) reflected the pre-retry11 freeze and
omitted post-freeze `ses-02` anatomicals. **This certificate supersedes it** for
`--affirmDefaced` readiness.
