# MRIQC coverage audit (post-retry)

**Generated:** 2026-07-28T15:39:10Z
**Verdict:** **FAIL**
**BIDS:** `/home/alexrees/scratch/bids`
**Derivatives:** `/home/alexrees/scratch/derivatives/mriqc`

## Summary

| Level | Complete | Expected | Coverage |
| --- | ---: | ---: | ---: |
| Sessions (all expected T1w+BOLD IQMs) | 130 | 135 | 96.3% |
| T1w IQMs | 384 | 387 | 99.2% |
| BOLD IQMs (magnitude) | 1623 | 1625 | 99.9% |

### Status counts

| Status | N |
| --- | ---: |
| `BOLD_ONLY` | 3 |
| `COMPLETE_BOTH` | 127 |
| `PARTIAL` | 5 |

## Incomplete sessions

| subject | session | mriqc_t1w | expected_t1w | mriqc_bold | expected_bold | n_missing_t1w | n_missing_bold | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sub-002 | ses-01 | 3 | 3 | 12 | 13 | 0 | 1 | PARTIAL |
| sub-011 | ses-01 | 3 | 3 | 12 | 13 | 0 | 1 | PARTIAL |
| sub-039 | ses-02 | 2 | 3 | 12 | 12 | 1 | 0 | PARTIAL |
| sub-058 | ses-01 | 2 | 3 | 12 | 12 | 1 | 0 | PARTIAL |
| sub-066 | ses-02 | 2 | 3 | 12 | 12 | 1 | 0 | PARTIAL |

