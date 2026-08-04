# Final Movie timing audit

**Generated:** `2026-07-28T14:40:01.815223+00:00`

## Conclusion

Possible events reconstruction: **NO**

## Evidence found

- MATLAB protocol scripts (`main.m`, `Show_movie.m`) documenting FORP key `t` wait and movie playback.
- `Results/*.mat` with **identity** fields (`run_id`, `change_eye`, wall-clock save stamp).
- `output.txt` diaries with Psychtoolbox **diagnostics** (refresh / Flip warnings).
- Optional physiology recordings that may include scanner EXT pulses (volume clock), **not** stimulus event onsets.

## Evidence missing

- no `triggerTimes` (saved)
- no VBL timestamps (saved)
- no frame timestamps (saved)
- no scanner-locked stimulus onset
- no conserved IRM↔clip temporal table

## Publication recommendation

Release Movie BOLD data without `events.tsv`.  
Provide protocol code and stimulus mapping only.  
No synthetic onset generation.
