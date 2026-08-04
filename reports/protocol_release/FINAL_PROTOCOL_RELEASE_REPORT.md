# Final protocol release report

Generated: `2026-07-28T13:33:29Z`

## Structure (public)

```text
release_dataset/
  task-rest.json
  code/
    README.md
    task-fmri_condition_dictionary.*   # pre-existing
    presentStimParams.m                # pre-existing companion
    task-grating/   # 12 scripts + README + protocol md
    task-movie/     # scripts + README + run dictionary/assignments
    task-rest/      # main.m + README + protocol md
  docs/
    Protocols/
      Grating.md
      Movie.md
      Rest.md
```

## Counts

| Item | n |
| --- | ---: |
| Scripts published | 15 |
| Grating | 12 |
| Movie | 2 |
| Rest | 1 |
| FOV movie scripts excluded | 36 |
| Movie magnitude runs assigned | 536 |
| Movie magnitude runs unmapped | 0 |

## Hash policy

- One canonical exemplar per basename (modal SHA-256).
- Byte-identical copies retain source SHA-256.
- Sanitized movie scripts receive a new published SHA-256; source hash retained in `CODE_COPY_VALIDATION.tsv`.

## PHI audit

- Unique contents scanned: see `MATLAB_PHI_REPORT.tsv`
- HIGH findings on raw archive content: **15**
- Published tree re-scanned for `/home`, `/lustre`, `C:\Users` — see validation report

## FAIR

| Principle | Implementation |
| --- | --- |
| Findable | Task folders, dataset-level `task-rest.json`, docs/Protocols |
| Accessible | Open code + dictionaries in the BIDS deposit |
| Interoperable | BIDS task labels; TSV dictionaries; CogAtlas rest ID |
| Reusable | Clear event/no-event policy; no fabricated timing |

## Scientific Data / OpenNeuro expectations

| Expectation | Status |
| --- | --- |
| Paradigms documented for external readers | Yes (`docs/Protocols`) |
| Code that enables interpretation published | Yes (minimal necessary scripts) |
| No synthetic events | Yes |
| No stimulus MP4 without license package | Yes (not copied) |
| No PHI / internal paths in deposit | Targeted PASS — see validation |
| Validator-only minimalism avoided | Yes (documentation-first) |

## Recommendations

1. Keep grating `events.tsv` recovery separate from this protocol pack (mapping collisions).
2. If movie MP4 redistribution is desired later, obtain licenses and place under `stimuli/` with checksums.
3. Optionally add `task-movie.json` analogous to `task-rest.json`.
4. Do not publish `reports/protocol_release/` or inventory TSVs with source tokens.

## Decision log

See `CANONICAL_SELECTION.tsv` for per-file publish/exclude rationales.

## Post-build addition

- Added `task-movie.json` (TaskName / TaskDescription / Instructions; no CogAtlas ID without verified mapping).
