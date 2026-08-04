# FINAL MANUAL REVIEW REPORT — Grating events mapping

Generated: `2026-07-28T13:52:51.442678+00:00`

## Summary

| Metric | n |
|--------|--:|
| Total analysed | 21 |
| **ACCEPT** | 18 |
| **REVIEW** | 2 |
| **REJECT** | 1 |
| Run changed vs prior recommend | 9 |

## Decision table

| participant | session | fMRI# | run | decision | confidence | reason | vols | triggers | dup? |
|-------------|---------|------:|----:|----------|------------|--------|-----:|---------:|------|
| sub-002 | ses-01 | 1 | 09 | **ACCEPT** | HIGH | REDO_COMPLETE_ACQUISITION | 226 | 226 | True |
| sub-011 | ses-01 | 1 | 07 | **ACCEPT** | HIGH | UNIQUE_PROTOCOL_MATCH | 226 | 226 | False |
| sub-011 | ses-01 | 4 | 05 | **ACCEPT** | HIGH | REDO_COMPLETE_ACQUISITION | 226 | 226 | True |
| sub-012 | ses-01 | 4 | 03 | **ACCEPT** | HIGH | SERIESNUMBER_EXACT_MATCH | 226 | 226 | True |
| sub-016 | ses-02 | 1 | 09 | **ACCEPT** | HIGH | REDO_COMPLETE_ACQUISITION | 226 | 226 | True |
| sub-020 | ses-01 | 1 | 05 | **ACCEPT** | HIGH | UNIQUE_PROTOCOL_MATCH | 226 | 226 | False |
| sub-023 | ses-01 | 1 | 09 | **ACCEPT** | HIGH | DUPLICATE_RESOLVED_BY_VOLUME_COUNT | 226 | 226 | True |
| sub-024 | ses-02 | 1 | 07 | **ACCEPT** | HIGH | SERIESNUMBER_EXACT_MATCH | 226 | 226 | True |
| sub-024 | ses-02 | 2 | 11 | **ACCEPT** | HIGH | SERIESNUMBER_EXACT_MATCH | 226 | 226 | True |
| sub-025 | ses-01 | 1 | 09 | **ACCEPT** | HIGH | DUPLICATE_RESOLVED_BY_VOLUME_COUNT | 226 | 226 | True |
| sub-038 | ses-02 | 3 | 04 | **ACCEPT** | HIGH | REDO_COMPLETE_ACQUISITION | 226 | 226 | True |
| sub-040 | ses-01 | 1 | 07 | **ACCEPT** | HIGH | SERIESNUMBER_EXACT_MATCH | 226 | 226 | True |
| sub-040 | ses-01 | 1 | 09 | **ACCEPT** | HIGH | SERIESNUMBER_EXACT_MATCH | 226 | 226 | True |
| sub-041 | ses-01 | 1 | 07 | **REJECT** | HIGH | INCOMPLETE_ACQUISITION_ABORT | 27 | 28 | True |
| sub-041 | ses-01 | 1 | 09 | **ACCEPT** | HIGH | REDO_COMPLETE_ACQUISITION | 226 | 226 | True |
| sub-043 | ses-02 | 2 | 12 | **ACCEPT** | HIGH | SERIESNUMBER_EXACT_MATCH | 226 | 226 | True |
| sub-043 | ses-02 | 3 | 01 | **REVIEW** | LOW | AMBIGUOUS_DUPLICATE | 226 | 226 | True |
| sub-043 | ses-02 | 4 | 05 | **REVIEW** | LOW | AMBIGUOUS_DUPLICATE | 226 | 226 | True |
| sub-046 | ses-01 | 1 | 07 | **ACCEPT** | HIGH | SERIESNUMBER_EXACT_MATCH | 219 | 226 | True |
| sub-061 | ses-01 | 1 | 07 | **ACCEPT** | HIGH | DUPLICATE_RESOLVED_BY_VOLUME_COUNT | 226 | 226 | True |
| sub-083 | ses-01 | 1 | 09 | **ACCEPT** | HIGH | DUPLICATE_RESOLVED_BY_VOLUME_COUNT | 226 | 226 | True |

## Cases requiring manual inspection

### sub-043 / ses-02 / fmri_number=3
- Selected run: `01` — reason `AMBIGUOUS_DUPLICATE`
- Volumes: 226; triggers: 226; duplicate: True

### sub-043 / ses-02 / fmri_number=4
- Selected run: `05` — reason `AMBIGUOUS_DUPLICATE`
- Volumes: 226; triggers: 226; duplicate: True


## Validation methodology

- No synthetic timing — MATLAB `triggerTimes` only
- No BIDS files modified (read-only)
- Gates: subject/session, ProtocolName `fMRI{N}`, magnitude-only, ~226 volumes / ~210–211 s,
  triggers (≥200 = HIGH), duplicate hierarchy, REDO complete preference
- **Trigger↔volume pairing:** incomplete MATLAB (~28 trig) must not map to complete BOLD (226 vols)

## Integration readiness

`INTEGRATE_EVENTS_READY.tsv`: **18** ACCEPT rows.
Empty `events_tsv_source` ⇒ regenerate from MATLAB before copy.

## Control

- `bids/` unmodified
- No events written into BIDS
- No NIfTI/JSON modified

**READ ONLY AUDIT COMPLETE**
