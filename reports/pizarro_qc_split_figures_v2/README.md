# Pizarro figures split by run and modality — **v2 (MC=50)**

Same layout as `pizarro_qc_split_figures/` (MC=10), but scored with **50 Monte Carlo dropout passes** (`n_mc_runs=50`).

Source: `pizarro_qc_revised_mc50/image_level_predictions.tsv` + BIDS `*_T1w.json`.

## Coverage

- Total T1w scored rows: **387**

### By run

- run-01: 132
- run-02: 132
- run-03: 120

### By modality

- `T1w_MPR`: 260
- `WMn_MPRAGE_sagittal`: 121
- `T1w_MPR_ND`: 6

## Outputs

- `by_run/run-01/` — n=132, mean artifact P=71.6, median=81
- `by_run/run-02/` — n=132, mean artifact P=49.7, median=50
- `by_run/run-03/` — n=120, mean artifact P=89.8, median=100

### By modality folders

- `by_modality/T1w_MPR/` — n=260, mean artifact P=60.1, median=64
- `by_modality/WMn_MPRAGE_sagittal/` — n=121, mean artifact P=90.5, median=100
- `by_modality/T1w_MPR_ND/` — n=6, mean artifact P=65.0, median=76

### By run × modality

- `by_run_and_modality/run-01/T1w_MPR/` — n=126
- `by_run_and_modality/run-01/T1w_MPR_ND/` — n=4
- `by_run_and_modality/run-02/T1w_MPR/` — n=129
- `by_run_and_modality/run-03/T1w_MPR/` — n=4
- `by_run_and_modality/run-03/WMn_MPRAGE_sagittal/` — n=116
