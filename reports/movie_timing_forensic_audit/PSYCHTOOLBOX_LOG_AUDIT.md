# Psychtoolbox logging audit (movie)

Generated: `2026-07-29T17:42:44Z`

## Unique movie-related `.m` scripts audited

- Unique content hashes: **8**
- Path examples: <RAW>/Glaucoma/SUBG08_Session01_2024FEB10/SUBG08_Session01_2024FEB10_MATLAB/3-Movie_Data/Show_movie.m, <RAW>/Glaucoma/SUBG08_Session01_2024FEB10/SUBG08_Session01_2024FEB10_MATLAB/3-Movie_Data/main.m, <RAW>/Glaucoma/SUBG13_SESSION02_2025MAY22/SUBG13_SESSION02_2025MAY22_MATLAB/1-Check_FOV_and_EyeTracking/3-Movie_Data/Show_movie.m, <RAW>/Glaucoma/SUBG13_SESSION02_2025MAY22/SUBG13_SESSION02_2025MAY22_MATLAB/1-Check_FOV_and_EyeTracking/3-Movie_Data/main.m, <RAW>/Glaucoma/SUBG02_SESSION2_2024MAR18/SUBG02-Matlab/3-Movie_Data/main.m, <RAW>/Control/SUBC10-Session1-2023JUL05/SUBC10_Session01_2023JUL05_Matlab/3-Movie_Data/Show_movie.m, <RAW>/Control/SUBC10-Session1-2023JUL05/SUBC10_Session01_2023JUL05_Matlab/3-Movie_Data/main.m, <RAW>/Data_TON/SUBTON02-session1-2025MAR07/TON02-Session1-2025March07-MATLAB/3-Movie_Data/main.m

## Runtime log / save behaviour

| Creates `.mat` via `save` | YES |
| Creates text/log via `fprintf`/`fopen`/`diary` | YES |
| Creates CSV via `writetable`/fprintf | NO |
| Saves timing variables (trigger/VBL/onset) | NO |

## Interpretation

Movie Results `.mat` files are written by `save(...)` in `main.m` BEFORE `Show_movie` runs; contents are identity-only (run_id / comment / change_eye).

`Show_movie.m` waits for one FORP `t` (`KbQueueWait`) and flips frames but **does not assign or save** Flip / VBL / GetSecs timestamps.

## Matched save/log call sites

- `<RAW>/Glaucoma/SUBG08_Session01_2024FEB10/SUBG08_Session01_2024FEB10_MATLAB/3-Movie_Data/main.m:11` — `outputFileID = fopen(outputFile, 'w');`
- `<RAW>/Glaucoma/SUBG08_Session01_2024FEB10/SUBG08_Session01_2024FEB10_MATLAB/3-Movie_Data/main.m:14` — `diary(outputFile);`
- `<RAW>/Glaucoma/SUBG08_Session01_2024FEB10/SUBG08_Session01_2024FEB10_MATLAB/3-Movie_Data/main.m:80` — `save([resultdir '/' (t) '_Subject_is_' comment '_selected_run_id_' num2str(run_id)])`
- `<RAW>/Glaucoma/SUBG13_SESSION02_2025MAY22/SUBG13_SESSION02_2025MAY22_MATLAB/1-Check_FOV_and_EyeTracking/3-Movie_Data/main.m:67` — `save([resultdir '/' (t) '_Subject_is_' comment '_selected_run_id_' num2str(run_id)])`
- `<RAW>/Glaucoma/SUBG02_SESSION2_2024MAR18/SUBG02-Matlab/3-Movie_Data/main.m:12` — `outputFileID = fopen(outputFile, 'w');`
- `<RAW>/Glaucoma/SUBG02_SESSION2_2024MAR18/SUBG02-Matlab/3-Movie_Data/main.m:15` — `diary(outputFile);`
- `<RAW>/Glaucoma/SUBG02_SESSION2_2024MAR18/SUBG02-Matlab/3-Movie_Data/main.m:81` — `save([resultdir '/' (t) '_Subject_is_' comment '_selected_run_id_' num2str(run_id)])`
- `<RAW>/Control/SUBC10-Session1-2023JUL05/SUBC10_Session01_2023JUL05_Matlab/3-Movie_Data/main.m:67` — `save([resultdir '/' (t) '_Subject_is_' comment '_selected_run_id_' num2str(run_id)])`
- `<RAW>/Data_TON/SUBTON02-session1-2025MAR07/TON02-Session1-2025March07-MATLAB/3-Movie_Data/main.m:11` — `outputFileID = fopen(outputFile, 'w');`
- `<RAW>/Data_TON/SUBTON02-session1-2025MAR07/TON02-Session1-2025March07-MATLAB/3-Movie_Data/main.m:14` — `diary(outputFile);`
- `<RAW>/Data_TON/SUBTON02-session1-2025MAR07/TON02-Session1-2025March07-MATLAB/3-Movie_Data/main.m:80` — `save([resultdir '/' (t) '_Subject_is_' comment '_selected_run_id_' num2str(run_id)])`

Total matched call sites: **11**
