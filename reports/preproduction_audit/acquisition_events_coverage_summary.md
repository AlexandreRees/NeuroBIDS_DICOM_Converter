# Acquisition ↔ events coverage summary

Read-only audit of functional bold acquisitions vs MATLAB timing sources.

Source priority: (1) scan_info triggerTimes/vbl → (2) fMRI_N Stim_order_selected → (3) runs_random validation → (4) dated_sequence_of_stimuli fallback.

## Paradigm-separated readiness

Events timing is **required** only for task-fMRI / grating. Movie events are optional (stimulus availability reported separately). Resting-state events are not applicable.

- `task_fmri_grating`: total=1908; events_required=true; ready=1018; missing=846; resolved=44; coverage=55.7%
- `movie`: total=1070; events_required=false; ready=0; missing=0; resolved=0; coverage=97.8% (coverage = stimulus availability)
- `resting_state`: total=270; events_required=false; ready=0; missing=0; resolved=0; coverage=not_applicable (events not applicable)

## By BIDS task label

- `control`: n=802; READY=505; RESOLVED=22; MISSING=275; UNRESOLVED=0; N/A=0
- `fmri`: n=1106; READY=513; RESOLVED=22; MISSING=571; UNRESOLVED=0; N/A=0
- `movie`: n=1070; READY=0; RESOLVED=0; MISSING=0; UNRESOLVED=0; N/A=1070
- `rest`: n=270; READY=0; RESOLVED=0; MISSING=0; UNRESOLVED=0; N/A=270

Functional timing summary: `functional_timing_summary.tsv`
Detailed table: `acquisition_events_coverage.tsv`
Selected sources: `selected_timing_source.tsv`

Total functional bold runs audited: **3248**
