# FINAL REPORT — Resting-state MATLAB protocol for sourcedata

Generated: `2026-07-27T22:19:57.305646+00:00`

## Scope

- Target: Psychtoolbox resting-state protocol script `main.m`
- Source scope: MATLAB folders matching resting-state (`4-resting state`), excluding FOV / Grating / Movie
- Destination (if PASS): `sourcedata/MATLAB_protocol/resting_state/main.m`
- Frozen (untouched): `raw_original/`, `bids/`, `derivatives/`, `release_dataset/`

## Audit artifacts

| File | Role |
|------|------|
| `matlab_source_inventory.tsv` | All resting `main.m` locations + hashes |
| `PHI_scan_report.tsv` | Pattern hits (file path + line + pattern; no quote of line text) |
| `resting_state_code_summary.md` | Scientific / technical description |
| `COPY_VALIDATION.tsv` | Copy identity check or no-copy record |

## Inventory summary

- Files found: **119**
- Unique content hashes: **18**
- Canonical hash (published candidate): `cbf1d5c8c657920e1b5bdef74da7008f11407abce4608a7e4120e7796f210ea8`
- Sessions matching canonical: **85**

## PHI scan summary (canonical exemplar)

Pattern hits by severity on the canonical file (content not reproduced):

- No pattern hits.

### Interpretation

- `LOW` hits on `Name` / `ID` are expected Psychtoolbox API usage (`KbName`, `psychtoolbox_forp_id`) and were treated as **non-blocking** after context review.
- Blocking severities for release: `CRITICAL`, `HIGH`, `MEDIUM`.

## Copy decision

- Decision: **PASS**
- Destination: `sourcedata/MATLAB_protocol/resting_state/main.m`
- Source SHA256 = destination SHA256: `cbf1d5c8c657920e1b5bdef74da7008f11407abce4608a7e4120e7796f210ea8`
- Byte-identical: **yes**

## Conclusion

**PASS — resting-state MATLAB protocol script contains no identifiable participant information and is suitable for sourcedata distribution.**

## Notes for OpenNeuro / Scientific Data

- This script does not log participant-level timing files.
- Resting-state BIDS `events.tsv` remain unnecessary for fixation-only rest.
- Other hash variants across sessions were inventoried but not published; they differ only by minor edits/whitespace in this cohort (see inventory).

## Internal note

`matlab_source_inventory.tsv` retains absolute source paths for curator traceability and should **not** be published with the open dataset.

