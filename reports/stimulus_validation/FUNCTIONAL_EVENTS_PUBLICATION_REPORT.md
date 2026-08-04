# Functional events — publication report

**Generated:** 2026-07-23T20:23:11Z  
**Final verdict:** **PASS WITH DOCUMENTED LIMITATIONS**

## Executive summary

The dataset includes **452** `task-fmri` `*_events.tsv` files generated from original experimental records (scanner trigger recordings + MATLAB stimulus-order / protocol metadata). Automatic validation of these files yielded **PASS** (452 PASS, 0 WARNING, 0 FAIL). Coverage is **89.2%** of task-fMRI BOLD runs (452/507). Runs without an unambiguous protocol→BIDS correspondence intentionally lack events files.

## Validation statistics

| Item | Value |
|---|---:|
| Events files | 452 |
| PASS | 452 |
| WARNING | 0 |
| FAIL | 0 |
| Overall validation | PASS |

## Coverage

| Item | Value |
|---|---:|
| task-fMRI BOLD runs | 507 |
| With events | 452 |
| Without events | 55 |
| Coverage | 89.2% |

### Missing-reason totals

| Category | Count |
|---|---:|
| No unique ProtocolName mapping | 28 |
| No unique verified mapping | 18 |
| Incomplete MATLAB logs | 9 |

## Remaining limitations

1. Incomplete coverage: 55 task-fMRI runs have no events file (non-unique or incomplete experimental↔BIDS mapping).  
2. `stim-XX` labels are not accompanied by a machine-readable stimulus-parameter dictionary in the public release.  
3. `task-movie` / `task-control` lack scanner-locked event tables.  
4. Movie stimulus media are not redistributed (rights).

## Recommended manuscript wording

> Event timing files are available for 452 task-fMRI runs. These files were generated from the original experimental logs by combining scanner trigger recordings with stimulus-order metadata. Event files were created only when a unique correspondence between protocol records and BIDS acquisitions could be established. Runs without an unambiguous mapping intentionally remain without `events.tsv`.

Avoid: reconstructed / estimated / predicted / approximated / invented.  
Prefer: generated from original experimental records / derived from original acquisition logs / recovered from recorded triggers.

## Publication recommendation

Proceed with Scientific Data wording that:

- states coverage explicitly (452/507, 89.2%),  
- documents uniqueness gating,  
- reports validation outcome (**PASS**),  
- discloses paradigm-specific absence of movie/control events.

## Supporting files

| File | Role |
|---|---|
| `events_validation.tsv` | Per-file validation |
| `EVENTS_VALIDATION_REPORT.md` | Validation narrative |
| `EVENTS_PROVENANCE.md` | Provenance |
| `MISSING_EVENTS.md` / `missing_events.tsv` | Missingness |
| `FUNCTIONAL_EVENTS_SUMMARY.md` | Coverage table |
| `Figure_FunctionalEventsCoverage.*` | Publication figure |

## Final verdict

**PASS WITH DOCUMENTED LIMITATIONS**
