# Questions for the PhD (physio / peripheral) — publication blockers

**Context:** Siemens **PhysioLog DICOM** (per-run CSA) is largely already converted into BIDS (`~3575` `*_physio.tsv.gz`). What still blocks a complete / clean **peripheral + remaining physio** release is mostly **session-wide PMU files**, **ambiguous run mapping**, **timing confidence**, and **missing channels / eyetracking**.

Use this as a checklist in your meeting.

---

## A. Peripheral PMU (`.puls` / `.resp` / `.ecg` / `.ext` / `.pmu`) — currently EXCLUDED

These live under `peripheral/` / `*_Peripheral*` folders. Audit: **642 files, 0 with run mapping possible**.

| # | Question | Why it blocks |
|---|----------|---------------|
| 1 | Were peripheral PMU files meant to be **one continuous recording for the whole visit**, or should there be **one file per BOLD run**? | Today each file spans the entire session → cannot assign to a BIDS run fail-closed. |
| 2 | Is there a lab SOP / notebook that records **when PMU logging was started/stopped** relative to the first/last scan? | Without start anchors, we cannot cut session-wide traces into runs. |
| 3 | Do you trust Siemens header fields like `LogStartMDHTime` / MPCU ticks as absolute clocks? Any validated conversion you used before? | Our policy rejected unvalidated MDH→BIDS `StartTime` transforms. |
| 4 | Should `.ext` / `.ext2` be published as BIDS `recording-trigger`, or kept as internal QC only? | Many EXT-only PhysioLogs were also excluded (no PULS/RESP; StartTime often missing). |
| 5 | For sessions with **many EXT transitions** but unknown run boundaries: did anyone ever segment them manually? | ~107 files show many transitions but still no recoverable boundaries. |
| 6 | Consent / ethics: are peripheral waveforms (esp. **ECG**) allowed in the OpenNeuro/Scientific Data release, or de-identified aggregate only? | ECG is sparse in converted PhysioLog (n=12) but present in peripheral exports. |

**If PhD says “no per-run segmentation was ever done” → peripheral PMU stays out of Level-1 BIDS; document as source-only.**

---

## B. PhysioLog already in BIDS — residual science / methods questions

| # | Question | Why it matters |
|---|----------|----------------|
| 7 | Is **`StartTime = (physio_first_tick − vol0_ACQ_START_TICS) × 2.5 ms`** the convention you endorse? | We labeled confidence **MEDIUM**; methods text needs PhD sign-off. |
| 8 | Confirm **`SamplingFrequency = 1000 / SampleTime_ms`** (and that Siemens `Freq Per` must *not* be used). | Matches our gate; confirm for paper. |
| 9 | For **twin ProtocolName** BOLD (redo / orphan / duplicate `fMRI1_AP` etc.): which physio belongs to which run when mapping was fail-closed? | **48** PhysioLogs excluded as `MAPPING_AMBIGUOUS` — same twin problem as events. |
| 10 | EXT-only PhysioLogs (**206** excluded): publish trigger channel alone, or drop? | No cardiac/resp; often no StartTime. |
| 11 | **ECG**: only **12** BIDS `recording-ecg` products vs 1000+ pulse/resp. Was ECG rarely enabled, or did conversion drop it? | Affects what we claim in the data descriptor. |
| 12 | Any known bad sessions (belt slipped, empty PULS, wrong subject folder) that should be **explicitly listed as excluded** beyond automated gates? | Improves transparency; avoids reviewer surprises. |

---

## C. Eyetracking / FOV / other peripheral behavior

| # | Question | Why it blocks |
|---|----------|---------------|
| 13 | Where are raw eyetracking files (EyeLink `.edf`, Tobii, etc.), and were they acquired for which tasks/sessions? | **0** eyetrack files in current BIDS tree. |
| 14 | Is eyetracking in scope for this Scientific Data paper, or deferred? | If in scope, need format, sync method, and PHI review. |
| 15 | FOV / eye-dominance notes from `1-Check_FOV_and_EyeTracking`: are those only for MATLAB `change_eye`, or is there timed gaze data? | Affects movie laterality metadata vs true eyetrack timeseries. |

---

## D. Movie / task sync (related, if they own stimulus+physio)

| # | Question | Why it matters |
|---|----------|----------------|
| 16 | For movie: is the **first FORP `t`** after scan start the intended movie onset, and were any **dummy volumes** prescribed (fixed N)? | Code waits for **1× `t`** only; N not logged — blocks movie `events.tsv`. |
| 17 | Should physio `recording-trigger` be treated as a substitute for missing MATLAB `triggerTimes` for movie? | Scientifically weak without knowing which pulse = movie start. |

---

## E. Release policy decisions you need from them (yes/no)

Ask for explicit decisions:

1. **Include** converted PhysioLog (pulse/resp/trigger) in public BIDS? *(technically largely done)*  
2. **Exclude** session-wide peripheral PMU from public BIDS, keep in private `sourcedata` only?  
3. Sign-off on **StartTime / SamplingFrequency** methods paragraph.  
4. How to describe the **~305 excluded** PhysioLogs in the paper (table of reasons OK?).  
5. Eyetracking: **in / out** of this release.  
6. Any additional **PHI** in physio filenames or headers we must scrub beyond current allowlist.

---

## One-slide status (for the meeting)

| Stream | Status | Blocker |
|--------|--------|---------|
| PhysioLog DICOM → BIDS | **Mostly done** (~1256 BOLD stems, 3575 files) | Methods sign-off; ~305 exclusions |
| Peripheral PMU folders | **Excluded** | Session-wide; no run cut; no validated StartTime |
| Eyetracking | **Absent from BIDS** | Location/scope unknown |
| Movie events | **Not feasible** | No saved trigger/onset; N unknown |

---

## Pointers

- `reports/physiology_audit/final_bids_physio_readiness/FINAL_PHYSIO_READINESS_REPORT.md`
- `reports/physiology_audit/final_bids_physio_readiness/EXCLUDED_physio_reasons.tsv`
- `reports/physiology_audit/final_bids_physio_readiness/conversion_run/CONVERSION_SUMMARY.md`
- `reports/movie_timing_recovery_audit/PERIPHERAL_EXT_AUDIT.tsv`
- `reports/movie_events_audit/MOVIE_MISSING_INFO_FOR_EVENTS_AUDIT.md`
