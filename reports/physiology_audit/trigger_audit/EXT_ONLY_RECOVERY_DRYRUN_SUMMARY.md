# EXT-only trigger recovery (dry-run)
Generated: `2026-07-30T15:30:50.983655+00:00`

Candidates attempted: **5**
Status counts: `{'FAIL': 5}`
Error counts: `{'missing_ticks:vol0=21378257:ext=None': 1, 'missing_ticks:vol0=24135119:ext=None': 1, 'missing_ticks:vol0=24110622:ext=None': 1, 'missing_ticks:vol0=21171488:ext=None': 1, 'missing_ticks:vol0=21275695:ext=None': 1}`

Method: StartTime from EXT ACQ_TIME_TICS vs vol0 ACQ_START_TICS (0.0025 s/tick).
Gates: unique BOLD map, SampleTime, n_samples>=10, >=1 pulse, no overwrite of existing trigger.
Results TSV: `/home/alexrees/scratch/reports/physiology_audit/trigger_audit/EXT_ONLY_RECOVERY_DRYRUN.tsv`
