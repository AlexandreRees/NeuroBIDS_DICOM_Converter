# FINAL SUB-043 MANUAL REVIEW REPORT

Generated: `2026-07-28T14:00:06.260776+00:00`

## Scope

Resolve remaining REVIEW Grating mappings for:

- `sub-043` / `ses-02` / **fMRI3**
- `sub-043` / `ses-02` / **fMRI4**

Read-only on `bids/` and `raw_original/`. Outputs only in `final_review/manual_resolution/`.

## Candidate BOLD examined

```
bids_run protocol_name  series_number  n_volumes duration_seconds acquisition_time  nifti_bytes  ImagingFrequency
      01      fMRI3_AP             15        226       211.762000                     336115949        123.257831
      02      fMRI3_AP             15        226       211.762000                     339542038        123.257877
      05      fMRI4_AP             19        226       211.762000                     336208795        123.257835
      06      fMRI4_AP             19        226       211.762000                     339784438        123.257881
      09      fMRI1_AP              3        226       211.762000                     339263351        123.257867
      11      fMRI2_AP              7        117       109.629000                     174019548        123.257825
      12      fMRI2_AP              7        226       211.762000                     339462159        123.257872
```


## MATLAB sources

```
 fmri_number                                                                                                                                                                                                                                             mat_file                                                           sha256  trigger_count duration_seconds matlab_timestamp  selected_run_is
           3 /lustre06/project/6001995/raw_original/Control/SUBC44_Session02_2025FEB19/SUBC44_Session02_2025FEB19_matlab/2-Grating/Results/February-19-2025_ 2-40-19_PM__scan_info_for_subject_SUBC44_Session02_2025FEB19__selected_run_is_2__fmri_number_is3.mat 2721b07525e7947c5acd7cafb16c3d67e910a8e9cf2a20c764b5b6f96fe026ef            226       210.833549                                 2
           4 /lustre06/project/6001995/raw_original/Control/SUBC44_Session02_2025FEB19/SUBC44_Session02_2025FEB19_matlab/2-Grating/Results/February-19-2025_ 2-44-31_PM__scan_info_for_subject_SUBC44_Session02_2025FEB19__selected_run_is_5__fmri_number_is4.mat d628382daa1ca4e28d8d96301622b904eeaa3c12133541db40feb34f3be417ab            226       210.832809                                 5
```


## Scores

```
 fmri_number candidate_run  score decision                                                                                             reason  series_number  n_volumes
           3            01      8 TIED_TOP +3_vol_226;+3_trig_226;+2_duration_lt5s;0_no_SeriesTime_in_JSON;0_series_number_tied_within_family             15        226
           3            02      8 TIED_TOP +3_vol_226;+3_trig_226;+2_duration_lt5s;0_no_SeriesTime_in_JSON;0_series_number_tied_within_family             15        226
           4            05      8 TIED_TOP +3_vol_226;+3_trig_226;+2_duration_lt5s;0_no_SeriesTime_in_JSON;0_series_number_tied_within_family             19        226
           4            06      8 TIED_TOP +3_vol_226;+3_trig_226;+2_duration_lt5s;0_no_SeriesTime_in_JSON;0_series_number_tied_within_family             19        226
```


## Decisions

### fMRI3 → **REVIEW** (no selected run)

- MATLAB: `February-19-2025_ 2-40-19_PM__scan_info_for_subject_SUBC44_Session02_2025FEB19__selected_run_is_2__fmri_number_is3.mat`
- Triggers: 226; duration ≈ 210.83 s; timestamp: ``
- Candidates: **run-01** and **run-02**
  - Both `ProtocolName=fMRI3_AP`, **SeriesNumber=15**, 226 volumes, TR=0.937, duration≈211.76 s
  - **No SeriesTime / AcquisitionTime / SeriesInstanceUID** in JSON
  - NIfTI content **differs** (byte size and volume hashes differ) → not trivial byte-duplicates
- Score: both **8**; Δ=0 → rule requires Δ≥3 for ACCEPT
- Why not auto-picked: fail-closed; choosing run-01 vs run-02 would be a guess

### fMRI4 → **REVIEW** (no selected run)

- MATLAB: `February-19-2025_ 2-44-31_PM__scan_info_for_subject_SUBC44_Session02_2025FEB19__selected_run_is_5__fmri_number_is4.mat`
- Triggers: 226; duration ≈ 210.83 s; timestamp: ``
- Candidates: **run-05** and **run-06**
  - Both `ProtocolName=fMRI4_AP`, **SeriesNumber=19**, 226 volumes, same TR/duration pattern
  - No SeriesTime/UID; distinct NIfTI content
- Score: both **8**; Δ=0 → REVIEW

## Why SeriesNumber / time gates did not break the tie

- `+2 SeriesTime` unavailable (empty in sidecars)
- `+2 SeriesNumber` cannot discriminate (identical within each twin pair)
- `selected_run_is` in MATLAB filename is the **paradigm/run-random index**, not the BIDS `run-XX` entity

## Confirmations

- No invented timing
- Events would still derive only from MATLAB `triggerTimes` once a BOLD target is curated
- **No BIDS files modified**
- **No events copied**

## Integration readiness

| | n |
|--|--:|
| ACCEPT | 0 |
| REVIEW | 2 |
| REJECT | 0 |

**Integration is NOT scientifically justified yet** for these two cases.

Curator options (outside this automated step):

1. Recover DICOM `SeriesTime` / `SeriesInstanceUID` from raw and break the tie
2. Inspect conversion provenance (why two magnitude BOLD share one SeriesNumber)
3. If confirmed duplicate reconstructions of one acquisition, pick one run by policy and document; attach events only to that run

`INTEGRATE_SUB043_EVENTS_READY.tsv` is intentionally **empty** (header only).
