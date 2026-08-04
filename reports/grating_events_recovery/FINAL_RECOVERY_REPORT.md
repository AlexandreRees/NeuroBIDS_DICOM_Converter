# Grating events recovery — FINAL REPORT

Generated: `2026-07-28T13:41:37.212072+00:00`

## Mode

- **FAIL-CLOSED** — no guessing when BOLD/MATLAB cardinality disagrees
- **READ-ONLY** on `bids/`, `raw_original/`, `derivatives/`, `release_dataset/`
- **No BIDS integration** — recommendations only
- **No invented timing**

## Multi-gate mapping

| Gate | Rule |
|------|------|
| G1 | ProtocolName → same `fmri_number` as MATLAB |
| G2 | Magnitude only (reject `part-phase`) |
| G3 | NIfTI exists |
| G4 | `n_triggers >= 2` |
| G5 | Unique **or** equal K:K order **or** K:1 → first `SeriesNumber` only |
| G6 | Each BOLD run / each `scan_info` used at most once |

**Prompt note:** the user message was truncated at « Le mapping doit être ». Gates are documented in `MAPPING_GATES.md` (fail-closed + `FIRST_OF_DUPLICATE`).

**`AUTO_ACCEPT_FIRST_OF_DUPLICATE`:** when 2+ mag BOLD share `fMRI{N}` but only 1 MATLAB log exists, pair to the earliest `SeriesNumber`; later series stay unscored (no invented second events).

## Counts

| Artifact | n |
|----------|--:|
| MATLAB_TRIGGER_DATABASE | 484 |
| BOLD_DATABASE | 1106 |
| Candidates | 474 |
| Rejected rows | 89 |
| AUTO_ACCEPT | 455 |
| AUTO_ACCEPT_ORDERED | 4 |
| AUTO_ACCEPT_FIRST_OF_DUPLICATE | 15 |
| Recommend INTEGRATE | 21 |
| … with precomputed events TSV | 7 |
| Already in BIDS | 453 |
| Prior-57 now matched | 21 |
| Prior-57 still missing | 36 |

## Recommendations

1. Curator review `candidates/RECOMMEND_INTEGRATE.tsv` (prefer rows with `precomputed_events_tsv`).
2. Spot-check all `AUTO_ACCEPT_ORDERED` pairs before release.
3. Do not integrate `rejected/` without manual decision.
4. A separate integration step (not run here) may copy approved TSVs into BIDS.

## Reject reasons

- `G1_FAIL_NO_MATCHING_MATLAB`: 63
- `G5_DUPLICATE_BOLD_NO_SECOND_MATLAB_LEFT_UNSCORED`: 15
- `G4_FAIL_TRIGGERS_LT_2`: 5
- `G5_FAIL_CARDINALITY_BOLD=1_MATLAB=2`: 3
- `G1_FAIL_NO_MATCHING_MAG_BOLD`: 3
