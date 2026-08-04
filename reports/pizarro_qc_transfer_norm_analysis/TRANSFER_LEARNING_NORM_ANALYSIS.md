# Transfer learning NORM confounding analysis

**Date:** 2026-08-04  
**Status:** READ-ONLY validation (no modification of `raw_original/`, `bids/`, `derivatives/`, or `reports/pizarro_qc_transfer_calibrated/`)  
**Embeddings:** reused from `pizarro_transfer_learning/output/with_embeddings/` (128-D `activation_22/Relu:0`)  
**QC label:** FAIL if original Pizarro score / artifact probability ≥ 50; PASS otherwise  

## 1. Why this analysis

The previously reported embedding logistic regression achieved ROC-AUC ≈ 0.964 when labels were defined as:

- run-01 → Siemens **non-NORM**
- run-02 → Siemens **NORM**

Because label ≡ reconstruction regime, that high AUC may reflect domain encoding of NORM rather than image quality. This report therefore re-targets learning to a **quality proxy independent of the label definition used in the original transfer experiment**, and tests within-run vs cross-run generalization.

## 2. Why NORM can bias transfer learning

If latent features primarily separate Siemens reconstruction kernels, a classifier trained on mixed runs with NORM-proxy labels will look excellent while failing as an artifact/quality detector under distribution shift. The critical test is whether quality prediction **trained in one reconstruction regime transfers to the other**.

## 3. Dataset

| Subset | N | FAIL | PASS |
| --- | ---: | ---: | ---: |
| All (run-01/02) | 264 | 171 | 93 |
| run-01 (non-NORM) | 132 | 104 | 28 |
| run-02 (NORM) | 132 | 67 | 65 |

## 4. Methods (common pipeline)

Pizarro CNN frozen → 128-D embedding → Logistic Regression (`StandardScaler` + balanced LR, C=1).  
Within-run/global metrics use stratified OOF CV. Cross experiments train on one run and test on the other. Uncertainty: bootstrap 95% CI (2000 resamples).

## 5. Results — discrimination

| Analysis | ROC-AUC | Accuracy | Balanced Acc. | F1 | MCC |
| --- | ---: | ---: | ---: | ---: | ---: |
| Global (mixed runs CV) | 0.948 | 0.875 | 0.857 | 0.905 | 0.723 |
| Run-01 only CV | 0.968 | 0.924 | 0.874 | 0.952 | 0.768 |
| Run-02 only CV | 0.938 | 0.841 | 0.841 | 0.847 | 0.682 |
| Cross run-01→run-02 | 0.908 | 0.871 | 0.871 | 0.878 | 0.744 |
| Cross run-02→run-01 | 0.984 | 0.947 | 0.914 | 0.967 | 0.839 |

Mean within-run AUC = **0.953**; mean cross-run AUC = **0.946**; drop = **0.007**.

See `AUC_COMPARISON.tsv` for CIs and pairwise tests.

## 6. Domain shift (embeddings)

- Mean intra-run distance: 13.940
- Mean inter-run distance: 14.873
- Silhouette (by run): 0.066
- Davies–Bouldin (by run): 3.870

**Domain shift detected: NO**  
No strong run-linked separation in embedding space.

## 7. Does run alone predict QC?

Logistic regression `QC_fail ~ run`: OR(run-02 vs run-01)=0.278 [95% CI 0.162–0.476], p=3.15e-06, McFadden pseudo-R²=0.068

AIC/BIC comparisons across `run`, `run+session`, and `run+subject` (when identifiable) are in `norm_effect_regression.tsv`. If run is highly predictive of FAIL/PASS, reconstruction regime is a confounder for any quality label correlated with acquisition settings.

## 8. Automatic conclusion (case 1)

The model generalizes across Siemens reconstruction regimes (cross-run AUC remains comparable to within-run AUC).

**Potential NORM confounding: LOW**

### Interpretation caveat

Using Pizarro score ≥ 50 as QC ground truth is itself model-derived. This analysis therefore tests whether the **embedding+LR stack recovers/generalizes that score across Siemens reconstruction domains**, which is exactly the right stress test for NORM confounding of the transfer pipeline. It does **not** replace expert visual QC labels.

## 9. Figures

- `publication_ROC.png/.pdf`
- `publication_embedding.png/.pdf` (PCA/UMAP)
- `publication_calibration.png/.pdf`
- `feature_importance_run01.png`, `feature_importance_run02.png`
- `embedding_PCA.png`, `embedding_TSNE.png`, `embedding_UMAP.png`

## 10. Reproducibility

```bash
/lustre07/scratch/alexrees/venvs/pizarro_qc/bin/python \
  /lustre07/scratch/alexrees/code/pizarro_transfer_norm_analysis.py
```
