# MRIQC ACF patch fix (2026-07-23)

## Root cause

The previous `mriqc_acf` retry (job `66310069`) did **not** disable AFNI ACF.

`config/mriqc_crash_tolerant_entrypoint.py` imported:

```text
nipype.interfaces.afni.preprocess.FWHMx
```

In MRIQC 24.0.2 / nipype, `FWHMx` lives in `nipype.interfaces.afni.utils`. The import failed silently:

```text
WARNING: could not import AFNI FWHMx for ACF patch: cannot import name 'FWHMx' from '...preprocess'
```

Crash files still showed `acf = True`, AFNI ACF model fit failed (`largest ACF ... too big for model fit`), and nipype raised `FileNotFoundError` for `out_acf` / `3dFWHMx.1D` — dropping IQM JSON for those BOLD (and some T1w) runs.

## Fix

In `neuro_pipeline/config/mriqc_crash_tolerant_entrypoint.py`:

1. Resolve `FWHMx` from `afni.utils` (fallback: `afni`, then `preprocess`).
2. Force `FWHMx._acf = False` (nipype flag that gates `out_acf` in `_list_outputs`).
3. Set `inputs.acf = False` and prefer `-ShowMeClassicFWHM`.
4. Patch `_list_outputs` to keep `_acf = False`.

Verified in new job logs:

```text
INFO: AFNI FWHMx patched (nipype.interfaces.afni.utils.FWHMx): acf=False, _acf=False ...
```

## Resubmit

| Item | Value |
|---|---|
| Job | **66329461** (`mriqc_fix`) |
| Script | `neuro_pipeline/scripts/run_mriqc_array_retry_incomplete.slurm` |
| Tasks | 27 incomplete sessions (same map as before) |
| Map | `metadata/mriqc_retry_incomplete_map.tsv` |

Baseline before this job: sessions **97/124**, T1w **353/356**, BOLD **1367/1496**.

Re-audit HTML/IQM coverage after the array completes.
