# MRIQC cohort IQM summary

## Reproducibility

- Date (UTC): 2026-07-19T15:20:37.763914+00:00
- MRIQC version detected: 24.1.0.dev0+gd5b13cb5.d20240826
- Subjects: 1
- Scans analysed: 6 (T1w=2, bold=4)
- MRIQC directory: `/home/alexrees/scratch/derivatives/mriqc`
- BIDS directory: `/home/alexrees/scratch/bids`
- Participants table: `/home/alexrees/scratch/metadata/participants.tsv`
- Command: `python -m neuro_pipeline.qc.mriqc_summary --mriqc-dir /home/alexrees/scratch/derivatives/mriqc --bids-dir /home/alexrees/scratch/bids --output-dir /home/alexrees/scratch/reports/mriqc --participants /home/alexrees/scratch/metadata/participants.tsv`
- Software: Python 3.11.4, numpy 2.4.2, pandas 2.3.3, matplotlib 3.10.8

## Outputs

- `iqm_summary.csv` / `.tsv` / `.md` / `.tex`
- `iqm_statistics.csv` / `.md`
- `qc_outliers.tsv`
- `table_mriqc_quality.tex`
- `figures/figure1_iqm_distributions.pdf`
- `figures/figure2_qc_heatmap.pdf`
- `figures/figure3_outliers.pdf`
- `figures/figure4_age_quality.pdf` (if age available)
