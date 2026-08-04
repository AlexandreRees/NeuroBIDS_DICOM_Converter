# Protocol fill — final status (2026-07-27T18:51:05.647231+00:00)

## Conversion
- Array 66496517: 84/84 tasks finished (73 COMPLETED on first pass; 11 FAILED then fixed via proto_fill_fix)
- Manifest failures across all 84 subjects: **NONE**
- merge-shards (canonical metadata): **done** 2026-07-27T14:33:52-04:00
- full-pack: interrupted after merge (Lustre I/O stall on pipeline_master.log); re-run if needed:
  `python -m neuro_pipeline.hpc merge-shards --code-root ~/scratch/neuro_pipeline --data-root ~/scratch --full-pack`

## Target sequences in BIDS (ProtocolName sidecars)
| Sequence | BIDS count | Inventory target |
|---|---|---|
| Localizer (anat `*_localizer*.nii.gz`) | 853 | ~303 series × ~3 planes |
| gsld_75TE_PA_3b0 | 264 | ~264 |
| resolve_*_PA | 132 | ~132 |

## Code fixes applied during monitoring
1. date-shift CSV lock / EmptyDataError
2. idempotent promote (localizer race)
3. synthetic zero bval/bvec for reverse-PE / short DWI
4. `*_dwi_ph` → `part-phase_dwi` rename + validation
5. strip Command Set (0000,*) before dcmwrite (SUBC048)
6. prefer largest / drop truncated Siemens duplicate DICOMs (SUBG02)
