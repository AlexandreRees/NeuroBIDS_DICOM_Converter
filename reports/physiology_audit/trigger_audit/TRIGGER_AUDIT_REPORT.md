# Trigger (Siemens EXT) complete audit

Generated: 2026-07-30  
Scope: all BIDS `recording-trigger` products + source PhysioLog EXT channels  
Action taken: **no new trigger files added** (none met healthy/usable gates)

---

## Executive verdict

**There are no healthy, exploitable volume-trigger trains to add.**

1. The Siemens PhysioLog **EXT** channel in this dataset is effectively a **flatline** (VALUE = 1 for the entire EXT table) in every source object inspected (EXT-only and multi-channel).
2. The **1223 existing** BIDS `*_recording-trigger_physio.tsv.gz` files are **not faithful EXT waveforms**. They are **parse artifacts** from `convert_physiolog_to_bids.py`, which digit-scrapes the EXT CSA region and contaminates samples with metadata (notably `SampleTime = 8` appearing as a spurious pulse value `8`).
3. Therefore expanding the dataset with EXT-only PhysioLogs would only add **flat / non-informative** channels, not usable sync triggers.

---

## What “trigger” means here

| Item | Fact |
|---|---|
| BIDS entity | `recording-trigger` |
| Siemens channel | `EXT` / `EXT2` (PhysioLog CSA) |
| Not eye-tracking | Eye-tracking is absent from BIDS; EXT ≠ gaze |
| Not ECG/pulse/resp | Those are `ECG` / `PULS` / `RESP` |

---

## Existing BIDS trigger QC (`TRIGGER_EXISTING_QC.tsv`)

| Metric | Result |
|---:|---|
| Trigger files in `bids/` | **1223** |
| Quality class | **1223 / 1223 = `MINIMAL_SYNC_MARK`** |
| Pulses detected | **exactly 1 pulse in every file** |
| Unique values | **{1, 8}** in all audited files |
| Duration | median **3.70 s** (range ~0.31–5.77 s) |
| Full TR-spaced volume train | **0** |

Interpretation: these files look like a short scrap of digits with a single artifactual `8`, not a scanner volume-trigger series.

Evidence that `8` is artifactual: proper parse of the EXT `ACQ_TIME_TICS / CHANNEL / VALUE` table in multi-channel PhysioLogs yields **n≈486 samples, all VALUE=1** (zero pulses), while the published trigger TSV has values `{1,8}`.

---

## Source EXT audit (PhysioLog DICOM)

### Coverage context

| Item | N |
|---:|
| Magnitude BOLD runs | 1625 |
| Existing triggers | 1223 |
| BOLD missing trigger | 402 |
| EXT-only PhysioLogs (status) | 222 |
| Unique-mapped EXT-only that could fill a missing BOLD stem | 209 |
| EXT-only with ambiguous BOLD mapping | 13 |

### Why EXT-only were previously excluded

Prior gate: StartTime required first **PULS/RESP** `ACQ_TIME_TICS`. EXT-only lack those channels → `EXT_ONLY_NO_STARTTIME` (n=206) or mapping ambiguous (n=11/13).

### New finding (StartTime *could* be recovered — but waveform is dead)

EXT sections do contain:

- `SampleTime = 8` → Fs = 125 Hz  
- `ACQ_TIME_TICS` for EXT  
- `vol0 ACQ_START_TICS`  

So StartTime ≈ `(EXT_tick − vol0_tick) × 0.0025` is computable (often ≈ −0.02 s).

**However**, the EXT VALUE table is **flatline (all 1s)** in:

- all EXT-only examples inspected (38/38 in the first batch; consistent across Control/fMRI/Movie/REST), and  
- multi-channel PhysioLogs’ EXT section (exemplar SUBC01 ses-02 fMRI1: 486× VALUE=1).

Gate for “healthy/usable”: ≥1 real pulse (VALUE>1) in the EXT table.  
**Pass count among inspected sources: 0.**

---

## Attempted recovery

Script: `code/recover_ext_only_triggers.py`  
Dry-run on first candidates failed initially on tick regex, then proper table parsing showed **flat EXT** → recovery correctly must **refuse** write.

**Files written to `bids/` / `release_dataset/`: none (by design).**

---

## Recommendation for publication

1. **Do not add** EXT-only triggers to the release.  
2. Treat existing `recording-trigger` as **low-value / likely artifactual**; prefer documenting:
   - either **withdraw** trigger products from the public release, or  
   - keep them but label clearly as *non-validated EXT scrape; not volume triggers*.  
3. Publish **pulse + respiratory (+ rare ECG)** without relying on triggers for RETROICOR/volume sync.  
4. Methods text should state that Siemens EXT PhysioLog does not provide a usable per-volume trigger train in this dataset.

---

## Output files (this audit)

| File | Content |
|---|---|
| `TRIGGER_EXISTING_QC.tsv` | Per-file QC of 1223 BIDS triggers |
| `TRIGGER_EXISTING_SUMMARY.tsv` | Class counts |
| `BOLD_MISSING_TRIGGER.tsv` | 402 BOLD stems without trigger |
| `EXT_ONLY_CANDIDATES.tsv` | 209 unique-map fill candidates |
| `EXT_ONLY_RECOVERY_DRYRUN.tsv` | Early dry-run failures |
| `TRIGGER_AUDIT_REPORT.md` | This report |

Source EXT stratified audit (`TRIGGER_SOURCE_EXT_AUDIT.tsv`): **160 / 160 = `UNUSABLE_FLATLINE`**
(80 EXT-only + 80 multi-channel with EXT). **0** files with VALUE>1.
Existing BIDS triggers: **1223 / 1223** artifact-like value sets `{1}`, `{8}`, or `{1,8}`
(`TRIGGER_EXISTING_ARTIFACT_FLAG.tsv`).

---

## Bottom line

**Audit: complete enough for a fail-closed decision.**  
**Add healthy triggers: 0.**  
**Do not complete the dataset with EXT-only flatlines or further parse artifacts.**
