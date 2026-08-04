# Pizarro transfer learning — NORM confounding validation

Read-only scientific analysis. Embeddings were **not** recomputed.

## Key outputs

- `TRANSFER_LEARNING_NORM_ANALYSIS.md` — full report
- `run01_metrics.json`, `run02_metrics.json`
- `cross_run01_to_run02_metrics.json`, `cross_run02_to_run01_metrics.json`
- `AUC_COMPARISON.tsv`
- Embedding plots: `embedding_PCA/TSNE/UMAP.png`
- Publication figures: `publication_ROC.png/.pdf`, `publication_embedding.png/.pdf`

## QC label

FAIL if `pizarro_score` / artifact probability ≥ 50.

## Reproduce

```bash
/lustre07/scratch/alexrees/venvs/pizarro_qc/bin/python \
  /lustre07/scratch/alexrees/code/pizarro_transfer_norm_analysis.py
```
