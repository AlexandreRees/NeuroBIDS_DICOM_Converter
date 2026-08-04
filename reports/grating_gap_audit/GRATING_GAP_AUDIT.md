# Grating gap audit — detailed linking & integration prospects

## Executive summary

| Gap | n | Linkable? | Integrable now? |
|-----|--:|-----------|-----------------|
| Missing `task-fmri` events | 57 | **partial (~30)** | After remapping duplicates / redos |
| Run-mapping collisions | 16 | **yes, with rules** | Yes if SeriesNumber / chrono policy accepted |
| Events without magnitude BOLD | 7 | Remap | Fix target run; never attach to phase-only |
| Protocol `.m` → sourcedata | 12 scripts | yes (modal) | Yes after PHI audit (like rest) |
| Results `.mat` → public sourcedata | ~1900 | risky | **Not recommended open** (PHI in filenames) |

Detail tables: `gap_57_missing_events_detail.tsv`, `gap_16_collisions_mapping_detail.tsv`, `gap_7_no_bold_detail.tsv`

---

## How Grating links MATLAB → BIDS today

```
MATLAB 2-Grating/Results/
  scan_info_…_fmri_number_is{N}.mat   →  triggerTimes
  fMRI_{N}.mat / sequence_of_stimuli… →  stim order
  runs_random.mat                       →  paradigm

Mapper: ProtocolName contains "fMRI{N}_" AND unique match → BIDS run-XX
Then write: sub-*_task-fmri_run-XX_events.tsv
```

**Failure mode #1 — duplicate ProtocolName:** two BOLDs both named `fMRI1_AP` (e.g. run-07 and run-09). Unique-match mapper cannot assign MATLAB `fmri_number=1` → collision / missing events.

**Failure mode #2 — redo labels:** `fMRI1_AP_REDO`, `fMRI2_AP_Rerun` parse as fMRI1/2 but collide with the original.

**Failure mode #3 — wrong BIDS run index:** MATLAB N mapped to a `run-0X` that is **phase-only** (no magnitude) → 7 `SKIP_no_bold`.

---

## A) 57 missing events — taxonomy

| gap_reason | n |
|------------|--:|
| MATLAB_EXISTS_BUT_NOT_MAPPED_TO_THIS_BIDS_RUN | 30 |
| NO_MATLAB_INVENTORY_FOR_SESSION | 16 |
| NONUNIQUE_OR_MISSING_MATLAB_SOURCES | 8 |
| NO_SCAN_INFO_FOR_PROTOCOL_fMRI_N | 2 |
| NO_USABLE_TRIGGERTIMES | 1 |

### Recoverability

1. **MATLAB_EXISTS_BUT_NOT_MAPPED (30) — best recovery candidates**
   - Pattern: almost always **two series with the same `fMRI1_AP`** (or fMRI3/fMRI4 duplicates / REDO).
   - Example `sub-002/ses-01`: run-07 and run-09 both `fMRI1_AP`; MATLAB has scan_info for fmri 1–4; validation only wrote events for runs 01/03/05 (fMRI2/3/4).
   - Linking strategy:
     - Sort BOLD by `SeriesNumber` (acquisition order).
     - Within each `fMRI{N}` family, assign in order to MATLAB files for that N (1st series ↔ first scan_info; 2nd ↔ redo only if a second MATLAB N exists, else document as unscored duplicate).
     - Cross-check `scan_info` filename timestamps when SeriesTime is available.
   - **Do not invent timing** — only attach existing measured trigger mats.

2. **NO_MATLAB_INVENTORY (16 = 4 subjects × 4 runs)**
   - `sub-051/ses-01`, `sub-078/ses-01`: `has_matlab=False` — **true archive gap**.
   - `sub-057/ses-02`: path exists but inventory empty for grating Results — verify folder contents manually.
   - `sub-081/ses-02`: mapped path appears to point at `1-Check_FOV_…` only — **bad MATLAB root mapping**, may be fixable by correcting session_mapping.

3. **NONUNIQUE_OR_MISSING_SOURCES (8)** — scan_info cardinality ≠ 1 → manual pick or exclude.

4. **NO_SCAN_INFO / NO_TRIGGERS (3)** — not recoverable without new source data.

---

## B) 16 collisions

Same root cause as A.1: timing **was generated** (`desc-matlabFMRI*` under `tmp_processing/events_validation/all_events/`) but **not placed** on a unique BIDS run.

| Status | Action |
|--------|--------|
| Timing exists | Keep |
| Need | Deterministic BOLD target (SeriesNumber policy) |
| Then | Promote to `run-XX_events.tsv` + provenance JSON |

---

## C) 7 events without magnitude BOLD

All 7 target a `run-XX` that has **only `part-phase_bold`**; magnitude lives on other run indices (odd/even PE pairing in BIDS).

| Meaning | Mapper assigned a phase-only run index — not a missing magnitude acquisition |
| Fix | Remap events onto the correct magnitude run (ProtocolName + SeriesNumber) |
| Never | Publish events beside phase-only as if it were the analysis BOLD |

---

## D) Protocol `.m` → sourcedata

~120 sessions share **12** stable basenames (`main.m`, `GratingStimulus1–5.m`, Checker*, `RandomGenerator.m`, …).

| Publish? | Yes — **protocol pack** (modal hash per basename), like resting `main.m` |
| Per-subject copies? | No |
| Blocker | PHI audit not run yet |
| Destination | `sourcedata/MATLAB_protocol/grating/` |

---

## E) Results `.mat` → sourcedata / bids

| Publish raw `.mat` on OpenNeuro? | **Discouraged** |
| Why | Filenames embed subject codes (`Subject_is_050`, …); mats may hold IDs |
| Better for open data | Derived `events.tsv` + sidecar provenance (**hashes**, not raw paths) |
| If needed | Restricted access sourcedata after PHI scrub / rename |

---

## Recommended integration order

1. PHI-audit + copy grating `.m` protocol pack → `sourcedata/MATLAB_protocol/grating/`
2. Remap duplicate `fMRI1_AP` / REDO via SeriesNumber → fill ~30 missing + resolve 16 collisions
3. Fix 7 phase-only mis-targets → remap to magnitude
4. Fix `sub-081` (and check `sub-057`) MATLAB path mapping; accept `sub-051`/`sub-078` as irrecoverable if no archive
5. Document remaining nonunique / no-trigger as irrecoverable
6. Do **not** bulk-publish Results `.mat` publicly without PHI scrub
