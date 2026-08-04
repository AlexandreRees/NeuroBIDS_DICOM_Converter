# Resolution — `NO_SAMPLETIME_AND_NO_STARTTIME` (N=38)

**Resolved:** `2026-07-29`  
**Class:** `NO_SAMPLETIME_AND_NO_STARTTIME`  
**Decision:** **DEFINITIVE EXCLUSION** from BIDS run-wise `*_physio` (Level-1 / OpenNeuro).  
**Table:** `DEFINITIVE_LOSS_NO_SAMPLETIME.tsv` (38 PhysioLog UIDs).

---

## Scope

| Subject | Session | N UIDs | BIDS physio today |
|---------|---------|-------:|-------------------|
| sub-007 | ses-01 | 13 | **0** |
| sub-008 | ses-01 | 11 | **0** |
| sub-009 | ses-01 | 12 | **0** |
| sub-042 | ses-01 | 2 (`control_run-03`, `control_run-05`) | 40 files on other runs (SF=125 Hz from CSA) |

Cause (forensic): PhysioLog DICOM CSA lacks recoverable channel `SampleTime` **and** first-channel tick → cannot derive `SamplingFrequency` or `StartTime` without inventing Hz / clock.

---

## Recovery checklist (executed)

### 1. Alternate PhysioLog / PMU dump in `raw_original`

| Subject | ses-01 folder | PhysioLog DICOM series | Peripheral / PMU folder |
|---------|---------------|------------------------|-------------------------|
| sub-007 | `Control/SUBC07-Session1-2023MAY31` | Yes (`*_PHYSIOLOG_*` under `*_NII`) — degraded CSA | **Absent** (Matlab + NII + eyetracking.zip only) |
| sub-008 | `Control/SUBC08-Session1-2023Jun02` | Yes — degraded CSA | **Absent** |
| sub-009 | `Control/SUBC09-Session1-2023JUN08` | Yes — degraded CSA | **Absent** |
| sub-042 | `Control/SUBC42_Session01_2024MAY06` | Yes; most runs convertible; Control2/3 EXT-only / failed gates | **Present** (see §2) |

No second, richer PhysioLog export was found for these sessions. ses-02 peripheral dumps exist for 007/008/009 but **do not** cover ses-01.

`physiolog_dicom_deep.tsv` for SUBC07/08/09 Session1: `sampletime_by_type=NA`, `log_datatypes=NA`, first PULS/RESP ticks missing (39/52 session rows).

### 2. Peripheral `.puls` / `.resp` (session-wide path)

| Subject | ses-01 `.puls`/`.resp` | Explicit ADC SF in header | Site-confirmed ADC rate | Run-locked? |
|---------|------------------------|---------------------------|-------------------------|-------------|
| sub-007 | **No** | — | — | — |
| sub-008 | **No** | — | — | — |
| sub-009 | **No** | — | — | — |
| sub-042 | **Yes** — `.../SUBC42_Session01_2024MAY06_Peripheral/` (`.puls`, `.resp`, `.ecg`, `.ext`, `.ext2`, `.pmu`) | **No** (`Freq Per` = 0; no SampleTime label; sync audit = NONE) | **No** (open in `QUESTIONS_FOR_PHD_PHYSIO_PERIPHERAL.md`) | **No** — continuous ~2 h MDH window (`LogStartMDHTime`→`LogStopMDHTime`) |

Policy (unchanged): session-wide peripheral PMU may enter BIDS **only** with documented ADC `SamplingFrequency` **and** a validated run-cut / session-level product design. Neither is available → **no session-wide conversion** performed.

Heuristic sample-count ≈ 400 Hz for sub-042 `.puls` vs MDH duration is **not** accepted as SF (would invent Hz; contradicts fail-closed gate).

### 3. BIDS run-wise recoverability

**Not recoverable cleanly.**

- Inventing Siemens-default Hz for degraded PhysioLogs is forbidden.
- Cutting sub-042 peripheral into `control_run-03/05` without validated triggers/clock is forbidden.
- Optional future path (out of Level-1 scope): if the site confirms peripheral ADC rates in writing, publish **session-level** sourcedata products for sub-042 only — still not a substitute for the 38 run-wise PhysioLog UIDs.

---

## Release wording (methods / Data Record)

> For sub-007, sub-008, and sub-009 session 1, Siemens PhysioLog DICOM objects are present but lack CSA `SampleTime` and first-channel acquisition ticks; no peripheral PMU (`.puls`/`.resp`) export exists for these visits. For sub-042 session 1, two control PhysioLogs fail the same gates; a session-wide peripheral PMU dump exists but has no explicit ADC sampling frequency and no validated run linkage. These **38** series are excluded from BIDS run-wise physiology (`NO_SAMPLETIME_AND_NO_STARTTIME`). No `SamplingFrequency` was invented from Siemens model defaults.

---

## Actions taken

1. Raw inventory under `/lustre06/project/6001995/raw_original/Control/` for the four sessions (above).
2. Confirmed absence of ses-01 peripheral for 007/008/009; presence for 042 without documented SF.
3. Closed as **DEFINITIVE_LOSS** — no BIDS conversion; document exclusion only.
4. Canonical list remains `DEFINITIVE_LOSS_NO_SAMPLETIME.tsv`; this file is the resolution note.

## Non-actions (intentional)

- No `*_physio.tsv.gz` written for these 38 UIDs.
- No peripheral→BIDS conversion for sub-042 ses-01.
- No change to successfully converted sub-042 ses-01 physio on other runs.
