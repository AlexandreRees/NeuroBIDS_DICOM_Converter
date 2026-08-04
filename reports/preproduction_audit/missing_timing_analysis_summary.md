# Missing task-fMRI timing analysis

Analyzed **158** production-selected grating runs with MISSING_TIMING.

## Classification counts

- `RECOVERABLE_MAPPING_FAILURE`: **158** (100.0%)
- `RECOVERABLE_SOURCE_SELECTION`: **0** (0.0%)
- `TRUE_MISSING_SOURCE`: **0** (0.0%)
- `INSUFFICIENT_METADATA`: **0** (0.0%)
- `NOT_A_VALID_TASK_RUN`: **0** (0.0%)

- Potentially recoverable (A+B): **158**
- Insufficient metadata (D): **0**
- Not recoverable (C+E): **0**

Dominant pattern: subject-ID zero-padding / cohort label mismatch between `session_mapping` canonical IDs (e.g. `SUBON02`, `SUBG05`) and MATLAB inventory labels (e.g. `SUBON002`, `SUBG005`).

Tables: `missing_timing_analysis.tsv`, `timing_recovery_estimate.tsv`
