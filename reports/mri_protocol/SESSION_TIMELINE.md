# Session timeline — complete MRI acquisition workflow

**Provenance.** Chronological order reconstructed from DICOM `SeriesNumber` / `SeriesTime` in `metadata/session_mapping.csv`, cross-checked against BIDS JSON `ProtocolName`, `SequenceName`, and `PhaseEncodingDirection`. The **canonical** order below is the modal full protocol as realized on exemplar visit `SUBC01` session 2 (`sub-001` / `ses-02` source path) and confirmed present as a complete set in **108** mapped sessions. A minority of visits reorder late control runs, omit the second localizer, or swap Control2/Control3 phase-encode labels.

**Scanner context (supported).** Siemens Prisma, 3 T, software syngo MR E11, receive coil `HeadNeck_64` on imaging series (BIDS JSON); patient position HFS. DICOM `InstitutionName` is de-identified to a placeholder and is **not** retained in BIDS sidecars.

---

## From patient entry to final acquisition

### 1. Patient positioning and first localizer

After the participant is positioned head-first supine in the 64-channel head/neck coil, a three-plane GRE **Localizer** is acquired. This scout establishes the anatomical frame used to prescribe all subsequent slice packs. Without it, functional and structural geometries cannot be planned on the console.

**Why first:** Required for geometric planning. Supported by SeriesNumber 1 across sampled sessions.

### 2. Functional MRI block begins (task first)

The session then enters a continuous multiband gradient-echo EPI BOLD block (`SequenceName` `epfid2d1_104`; TR 937 ms; TE 37 ms; flip angle 52°; multiband factor 8; 2 mm isotropic; PE AP encoded as BIDS `j-`).

**fMRI1_AP** and **fMRI2_AP** (226 volumes each) are acquired first. These are the visually driven grating/checkerboard task runs (`task-fmri`).

**Why functional MRI is first (Likely, based on session structure + paradigm reports; not a written SOP in-repo):** Task and movie runs are long, attention-demanding, and stimulus-synchronized (Psychtoolbox / FORP trigger). Placing them early reduces the risk that accumulating fatigue, discomfort, or motion after lengthy structural/diffusion scanning will degrade the primary experimental BOLD data. This inference is consistent with the observed SeriesNumber order but is not documented in a scanner SOP file within the repository — mark as **Likely**.

### 3. Interleaved reverse-PE control

**Control1_PA** (20 volumes; PE PA / BIDS `j`) is acquired between task pairs. It uses the same EPI geometry as the AP BOLD runs but opposite phase encoding.

**Why here:** Provides an early reverse-PE EPI sample inside the task block for polarity-aware QC and complements later control runs. Stimulus content of control runs is **Unknown** in available MATLAB/operator documentation (flagged previously in paradigm reports).

### 4. Remaining task runs

**fMRI3_AP** and **fMRI4_AP** complete the four-run task set.

### 5. Movie viewing (first half), then mid-block field maps

**Movie1_AP** and **Movie2_AP** (210 volumes each) present naturalistic movie segments (`task-movie`).

Immediately afterward, **SpinEchoFieldMap_AP** and **SpinEchoFieldMap_PA** (`SequenceName` `epse2d1_104`; TR 9710 ms; TE 66 ms) are acquired as an opposed-PE spin-echo EPI pair.

**Why movie before anatomy (Likely):** Movie runs share the BOLD coil setup and stimulus pathway already active for task fMRI; keeping all visually driven BOLD contiguous avoids breaking the functional setup for long anatomical scans. **Supported:** movies precede T1/FLAIR/WMn in canonical SeriesNumber order.

**Why field maps between Movie2 and Movie3 (Supported by SeriesNumber in canonical sessions):** Places a blip-up/blip-down SE pair near the temporal center of the functional block so that susceptibility estimates remain representative of the BOLD shim state. BIDS `IntendedFor` on these field maps lists functional BOLD and SBRef series (task-fmri, movie, rest, control), not DWI.

### 6. Movie viewing (second half) then resting-state

**Movie3_AP** and **Movie4_AP** complete the movie set. **REST1_AP** (320 volumes) follows, with monocular fixation and no stimulus blocks (`task-rest`).

**Why resting-state after movie (Likely):** Rest is the longest continuous BOLD run (~5 min) and does not require active visual paradigm scripts beyond fixation; acquiring it after task/movie avoids inserting a long passive run between attention-demanding paradigms. Order is **Supported**; motivational wording is **Likely**.

### 7. Second localizer

A second **Localizer** appears in most sessions (112 sessions with two Localizer clusters; 14 with three; only 6 with one).

**Why another localizer (Likely):** After ~30+ minutes of functional scanning, subject motion or table/coil adjustments may shift anatomy relative to the first scout; a re-scout supports accurate prescription of structural and diffusion geometries. Presence of a second localizer is **Supported**; exact operator instruction is **Unknown**.

### 8. Structural MRI begins with standard T1w MPRAGE

**T1w_MPR** (0.8 mm isotropic MPRAGE) is acquired next.

**Why structural MRI starts afterwards (Likely):** Separates motion-sensitive, long anatomical acquisitions from the stimulus-driven functional block; provides the anatomical reference after BOLD is secured. Order is **Supported**.

### 9. Late control EPI pair

In the modal protocol, **Control2_AP** and **Control3_PA** (20 volumes each) follow T1w. A minority of sessions use swapped labels (**Control2_PA** / **Control3_AP**); exemplar `sub-001` `ses-01` is such a variant and also places these controls after diffusion.

**Certainty:** Modal labels and post-T1w placement — **Supported** by frequency counts and canonical SeriesNumber. Exact scientific role of control runs — **Unknown** (no stimulus script documentation).

### 10. Second spin-echo field map pair

**SpinEchoFieldMap_AP** / **SpinEchoFieldMap_PA** are repeated.

**Why repeated (Likely):** Updates the field estimate after the anatomical pause and late control EPI; provides redundancy if the mid-block pair is degraded. Dual pairs are **Supported** in canonical sessions; rationale is **Likely**.

### 11. Diffusion MRI near the end

**gsld_76dir_b2000_1mmiso_AP** acquires the primary multi-shell DWI (exemplar: 385 volumes; b = 0 / 1000 / 2000 s/mm²). **gsld_75TE_PA_3b0** then acquires reverse-PE b0 volumes at the same TE (75 ms) for susceptibility correction (TOPUP / eddy).

**Why AP for primary DWI (Supported by ProtocolName + PhaseEncodingDirection):** Standard choice matching the AP BOLD PE polarity family.  
**Why PA reverse b0 (Supported):** Opposed PE enables blip-up/blip-down field estimation specific to the diffusion EPI train (matched TE), distinct from the functional SE field maps.  
**Why diffusion near the end (Likely):** Multi-shell DWI is long and vibration/gradient-intensive; placing it after functional and core T1w prioritizes BOLD and anatomical reference if the participant aborts early. Order is **Supported**.

### 12. B1 mapping before RESOLVE

**tfl_b1map_1mmiso** (turbo-flash B1 map; BIDS `TB1TFL`) is acquired immediately before RESOLVE in the canonical order.

**Why B1 precedes RESOLVE (Likely):** Provides transmit-field context adjacent to the RF-sensitive RESOLVE block and late quantitative/clinical DWI. Temporal adjacency is **Supported**; a written requirement that RESOLVE depends on this B1 map is **Unknown**.

### 13. RESOLVE DWI pair

**resolve_3scan_trace_tra_p3_160_1.4iso_AP** (readout-segmented EPI DWI) and **resolve_3scan_trace_tra_p3_160_1.4iso_PA** (reverse-PE companion) follow. Vendor-derived TRACEW/ADC/FA/ColFA/TENSOR series exist in DICOM under the AP protocol; BIDS retains primary DWI volumes.

### 14. FLAIR late, WMn last

**Sag Flair 3D-0.8** (0.8 mm 3D FLAIR) is acquired late, then **WMn_MPRAGE_sagittal** (white-matter-nulled MPRAGE) as the final series in canonical full sessions.

**Why FLAIR late (Likely):** Clinical-research T2-FLAIR is important but secondary to BOLD, T1w, and primary DWI for the experimental aims; late placement still captures CSF-suppressed anatomy if the session completes. Order **Supported**.  
**Why WMn last (Likely):** Specialized complementary T1 contrast for deep gray / thalamic conspicuity after standard MPRAGE and FLAIR; least critical for core BOLD pipelines. Order **Supported**.

---

## Session schematic (canonical)

```text
Enter scanner → Localizer
  → fMRI1_AP → fMRI2_AP → Control1_PA → fMRI3_AP → fMRI4_AP
  → Movie1_AP → Movie2_AP → SE-fmap AP/PA → Movie3_AP → Movie4_AP → REST1_AP
  → Localizer
  → T1w_MPR → Control2_AP → Control3_PA → SE-fmap AP/PA
  → GSLD DWI AP → GSLD b0 PA → B1 map → RESOLVE AP → RESOLVE PA
  → 3D FLAIR → WMn MPRAGE → end
```

## Documented deviations (do not invent a single rigid workflow)

| Deviation | Evidence | Certainty |
|---|---|---|
| No mid-movie field maps; SE-fmap only after REST; controls after DWI; no second localizer | `sub-001` `ses-01` / SUBC01 Session1 SeriesNumber | Supported |
| Control2_PA / Control3_AP instead of Control2_AP / Control3_PA | 7 sessions each in exact-label counts | Supported |
| Single Localizer only | 6 sessions | Supported |
| Redo/rerun series (`fMRI*_Rerun`, `Movie4_AP_redo_*`, etc.) | session_mapping ProtocolName | Supported |
| Early session abort missing anatomy and/or DWI | protocol completeness reports | Supported |
