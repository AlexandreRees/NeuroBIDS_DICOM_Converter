# Protocol gap-fill — pre-conversion audit

**Date:** 2026-07-27  
**Goal:** Ensure all protocol sequences appear in BIDS, specifically the three previously incomplete families.

## Mapping verification

| Sequence | Inventory | BIDS plan | Sessions missing in BIDS | Plan rows to convert | Mapping issues |
|---|---:|---:|---:|---:|---:|
| Localizer | 303 series / 135 sess | `anat` / `localizer` | 100 | 229 | **0** |
| gsld_75TE_PA_3b0 | 264 series / 130 sess | `dwi` | 101 | 204 | **0** |
| resolve_*_PA (primary) | 132 series / 130 sess | `dwi` | 104 | 106 | **0** |

All 539 missing plan rows resolve to a `session_mapping` series with non-empty `representative_dicom` / `series_instance_uid`.

## Already present (partial)

Some Control sessions already contain these series (e.g. `sub-001`):

- Localizer → `anat/*_localizer_i0000N.nii.gz` (dcm2niix multi-volume)
- gsld_75TE_PA_3b0 → `dwi/*_run-03/04_dwi` (PE=`j`)
- resolve_*_PA → `dwi/*_run-11_dwi` (PE=`j`)

## Conversion approach

- Task list: `metadata/protocol_gap_fill_tasks.tsv` (**109** subject×session)
- Series list: `reports/protocol_gap_fill_series.tsv` (**539** series)
- Slurm: `neuro_pipeline/scripts/run_protocol_gap_fill_array.slurm`
- Command: `python -m neuro_pipeline.hpc run-subject --subject <CANONICAL> --session <ses> --resume`
- Resume skips existing valid outputs; does not wipe the session
- Reverse-PE b0: converter synthesizes zero `.bval`/`.bvec` when Siemens omits gradients (`is_protocol_reverse_pe_b0`)

## Notes

- `Localizer` uses non-standard BIDS suffix `localizer` under `anat/` (documented in `bids/plan.py`) — required for full-protocol deposit per PI request.
- Derived RESOLVE maps (ADC/FA/ColFA/TRACEW) remain excluded by design; only primary `resolve_*_PA` is targeted.
