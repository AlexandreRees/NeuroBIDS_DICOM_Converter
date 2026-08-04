# MRIQC incomplete-session retries

1. **66277341** (`mriqc_inc`) — completed 27/27 around 2026-07-23 15:37 — coverage still FAIL (AFNI 3dFWHMx ACF / `out_acf`)
2. **66310069** (`mriqc_acf`) — requeued with FWHMx `acf=False` patch in `mriqc_crash_tolerant_entrypoint.py`
3. **66502493** (`mriqc_fix2`, 2026-07-27) — **sub-024/ses-01** (recover healthy missing IQMs) + **sub-074/ses-02** (segfault rerun). Pathological T1s documented in `MRIQC_PATHOLOGICAL_ACQUISITIONS.md` (incl. sub-066 `run-03_T1w`).

Script: `neuro_pipeline/scripts/run_mriqc_retry_partial_and_074.slurm`  
Task list: `metadata/mriqc_retry_partial_and_074.tsv`  
Logs: `logs/mriqc_retry2/`  
Audit: `reports/mriqc_coverage_audit/MRIQC_COVERAGE_AUDIT.md`
