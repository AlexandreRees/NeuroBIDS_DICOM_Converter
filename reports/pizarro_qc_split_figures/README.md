# Pizarro figures split by run and modality

Generated from `pizarro_qc_revised/image_level_predictions.tsv` + BIDS `*_T1w.json`.

## Coverage

- Total T1w scored rows: **385**

### By run

- run-01: 132
- run-02: 131
- run-03: 119

### By modality

- `T1w_MPR`: 259
- `WMn_MPRAGE_sagittal`: 120
- `T1w_MPR_ND`: 6

## Outputs

- `by_run/run-01/` — n=132, mean artifact P=62.6, median=65
- `by_run/run-02/` — n=131, mean artifact P=47.6, median=40
- `by_run/run-03/` — n=119, mean artifact P=89.9, median=100

### By modality folders

- `by_modality/T1w_MPR/` — n=259, mean artifact P=54.3, median=50
- `by_modality/WMn_MPRAGE_sagittal/` — n=120, mean artifact P=90.8, median=100
- `by_modality/T1w_MPR_ND/` — n=6, mean artifact P=65.0, median=75

### By run × modality

- `by_run_and_modality/run-01/T1w_MPR/` — n=126
- `by_run_and_modality/run-01/T1w_MPR_ND/` — n=4
- `by_run_and_modality/run-02/T1w_MPR/` — n=128
- `by_run_and_modality/run-03/T1w_MPR/` — n=4
- `by_run_and_modality/run-03/WMn_MPRAGE_sagittal/` — n=115
