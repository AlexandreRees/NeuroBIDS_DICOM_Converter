# BIDS metadata cleaning — final check (AVANT vs APRÈS)

**Generated (UTC):** 2026-07-22T18:31:52.773500+00:00
**BIDS dir:** `/home/alexrees/scratch/bids`
**Backup (AVANT):** `/home/alexrees/scratch/bids_metadata_backup_before_cleaning`

## Verdict

- JSON validation after cleaning: **OK**
- Remaining REMOVE fields: **0** JSON file(s)
- Fields removed (occurrence delta): **7956**
- Scientific field presence rates: **unchanged** (Δ n = 0 for all monitored fields)
- Overall: **PASS**

## Counts — AVANT vs APRÈS

| Metric | AVANT (backup) | APRÈS (BIDS) | Δ |
| --- | ---: | ---: | ---: |
| JSON sidecars | 7956 | 7958 | +2 |
| Invalid JSON | 0 | 0 | 0 |
| JSON with ≥1 REMOVE field | 7956 | 0 | -7956 |
| Occurrences `InstitutionalDepartmentName` | 7956 | 0 | -7956 |

Note: the backup stores only the **7956** JSON files that were modified. BIDS still has **7958** JSON files total (includes root-level files such as `dataset_description.json` that never contained REMOVE fields and were not copied into the backup).

## Champs scientifiques conservés (présence parmi `sub-*/**/*.json`)

Sidecars scorés — AVANT: **7956** · APRÈS: **7956**

| Field | AVANT n | AVANT % | APRÈS n | APRÈS % | Δ n |
| --- | ---: | ---: | ---: | ---: | ---: |
| `RepetitionTime` | 7956 | 100.0% | 7956 | 100.0% | 0 |
| `EchoTime` | 7956 | 100.0% | 7956 | 100.0% | 0 |
| `FlipAngle` | 7956 | 100.0% | 7956 | 100.0% | 0 |
| `MagneticFieldStrength` | 7956 | 100.0% | 7956 | 100.0% | 0 |
| `Manufacturer` | 7956 | 100.0% | 7956 | 100.0% | 0 |
| `ManufacturersModelName` | 7956 | 100.0% | 7956 | 100.0% | 0 |
| `SliceTiming` | 7408 | 93.1% | 7408 | 93.1% | 0 |
| `PhaseEncodingDirection` | 7455 | 93.7% | 7455 | 93.7% | 0 |
| `TotalReadoutTime` | 7112 | 89.4% | 7112 | 89.4% | 0 |
| `EffectiveEchoSpacing` | 7112 | 89.4% | 7112 | 89.4% | 0 |

## Notes

- Cleaning removed only `InstitutionalDepartmentName` (**7956** occurrences).
- No NIfTI / TSV files were modified (`clean_bids_metadata.py`).
- Full backup of touched JSON: `~/scratch/bids_metadata_backup_before_cleaning/` (~289M, 7956 JSON).
- Also see: `reports/BIDS_METADATA_CLEANING_SUMMARY.md`, `bids_metadata_cleaning_before.tsv`, `bids_metadata_cleaning_after.tsv`, `reports/BIDS_METADATA_CLEANING_PRECHECK.md`.

