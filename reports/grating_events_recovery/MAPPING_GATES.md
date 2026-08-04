# Mapping gates (fail-closed)

## G1 — Protocol family
BOLD `ProtocolName`/`SeriesDescription` must parse to the same integer `fmri_number`
as the MATLAB `scan_info` (`fmri_number_isN` / extracted field).

## G2 — Magnitude
Only magnitude BOLD (`part-phase` excluded). Phase shares events with magnitude sibling
but is never the integration target.

## G3 — File existence
NIfTI must exist on disk.

## G4 — Measured triggers
`n_triggers >= 2` from `triggerTimes`. Otherwise REJECT (no invented timing).

## G5 — Uniqueness / ordered 1:1
- 1 BOLD ↔ 1 MATLAB for that (sub, ses, N): AUTO_ACCEPT
- K BOLD ↔ K MATLAB, K>1: pair by ascending `SeriesNumber` ↔ MATLAB filename timestamp
  → AUTO_ACCEPT_ORDERED (acquisition-order hypothesis; spot-check required)
- K_bold ≠ K_matlab: REJECT (do not guess which redo to drop)

## G6 — Injectivity
Each BOLD run and each `scan_info` path assigned at most once.

## G5 extension — FIRST_OF_DUPLICATE (fail-closed)

When **K magnitude BOLD** share `fMRI{N}` but only **1** MATLAB `scan_info` exists:

- Pair MATLAB → **earliest `SeriesNumber`** only (`AUTO_ACCEPT_FIRST_OF_DUPLICATE`)
- Leave later series as `REJECT_UNSCORED_DUPLICATE` (no second trigger log → no events)
- This does **not** invent timing; it only chooses which existing BOLD receives the single measured log
