# Pizarro QC revised package (Scientific Data)

**Regenerated:** 2026-07-24 (after ses-02 expansion)

T1-weighted structural MRI only. See `executive_summary.md` and `publication_methods.md`.

| Metric | Value |
| --- | ---: |
| T1w images scored | 385 |
| Subjects | 83 |
| ses-02 T1w | 152 |
| Inference errors | 0 |
| Mean / median artifact P | 65.8 / 80.0 |
| Priority review queue (P≥90 or U≥0.9) | 246 |

FLAIR and other non-T1w outputs are excluded. Legacy FLAIR rows are archived under `../neuro_pipeline/reports/pizarro_qc/archive_flair_deprecated/` (source tree) or the mirrored path under `neuro_pipeline/reports/`.

## Rebuild

```bash
source ~/scratch/venvs/pizarro_qc/bin/activate
export PYTHONPATH=~/scratch/neuro_pipeline PYTHONNOUSERSITE=1
python ~/scratch/neuro_pipeline/scripts/build_pizarro_scientific_data_report.py
python ~/scratch/code/reports/generate_pizarro_scientific_data_report.py
module load StdEnv/2023 python/3.11 scipy-stack
python3.11 ~/scratch/code/reports/generate_pizarro_pi_figures.py
```
