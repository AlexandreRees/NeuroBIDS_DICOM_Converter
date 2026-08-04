# Protocol fill — status

Generated: 2026-07-27T15:45:53.231027+00:00

## Mapping verification (pre-job)

| Sequence | BIDS modality | suffix | planned n | Notes |
|---|---|---|---:|---|
| Localizer / Localizer_ND | `anat/` | `localizer` | 303 | 3-plane → `*_localizer_i0000N` |
| gsld_75TE_PA_3b0 | `dwi/` | `dwi` | 264 | reverse-PE b0; synthetic zero bval/bvec if missing |
| resolve_*_PA (primary) | `dwi/` | `dwi` | 132 | same; ADC/FA/TRACEW/TENSOR still skipped |

Still skipped (intentional): PhysioLog, PhoenixZIPReport, derived RESOLVE maps.

## Pilot SUBC001 (verified)

- `gsld_75TE_PA_3b0` → `run-03_dwi` + `run-04_dwi` (both sessions), ProtocolName OK, PE=`j` (PA)
- `resolve_*_PA` → `run-11_dwi` (both sessions), ProtocolName OK
- Localizers → `anat/*_localizer_i0000{1,2,3}.nii.gz`

## Slurm jobs

- Full cohort array: **66496517** (`--array=1-84%20`, resume=1)
- Logs: `logs/protocol_fill_%A_%a.{out,err}`
- After completion: `python -m neuro_pipeline.hpc merge-shards --code-root ~/scratch/neuro_pipeline --data-root ~/scratch --full-pack`

## Code changes

- Localizer planned under `anat/` (was `extra/` → skipped)
- Protocol reverse-PE b0 no longer technical-skipped; zero gradients synthesized
- dcm2niix `_i#####` multi-plane localizer outputs accepted
- Audit allows localizer square zero-padding (256×192 → 256×256)
