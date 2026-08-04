# Defacing metadata precheck

Generated: 2026-07-22 20:04:27 UTC
Mode: **DRY-RUN** (no files modified)

- Defacing directory: `/lustre07/scratch/alexrees/derivatives/defacing`
- Sidecar JSON inspected (excluding dataset_description.json): **725**
- JSON containing `InstitutionalDepartmentName`: **718**

## Value counts

- `Department`: 676
- `Centre de Recherche`: 42

## Planned action on --apply

- Remove **only** `InstitutionalDepartmentName`
- Preserve all acquisition / scientific fields (including ProtocolName, SeriesDescription, TR/TE/TI/FlipAngle/…)
- Never modify NIfTI or any path under `bids/`
- Backup tree: `/home/alexrees/scratch/defacing_metadata_backup/<timestamp>/`

