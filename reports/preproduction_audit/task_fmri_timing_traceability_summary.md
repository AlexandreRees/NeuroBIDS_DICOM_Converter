# Task-fMRI (grating) timing traceability

Production coverage counts **only** series with `selected_for_conversion=True`.

Excluded from production: duplicate DICOM series (same fMRI slot), phase (`_Pha`), rerun/redo labels, SBRef/physio, and failed/non-production labels.

## Counts

- Grating bold plan rows evaluated: **1106**
- Selected for conversion (production): **536**
- Excluded: **570**
- READY: **510**
- RESOLVED_SOURCE_CONFLICT: **20**
- MISSING_TIMING: **6**
- Production coverage (ready + resolved): **98.9%**

Table: `task_fmri_timing_traceability.tsv`
Updated summary: `functional_timing_summary.tsv`
