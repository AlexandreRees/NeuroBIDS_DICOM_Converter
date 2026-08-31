# Audit Pizarro — exclusions listées vs transfer learning

**Date:** 2026-08-31  
**Question:** retirer les T1w listées améliore-t-il l’AUC du transfer learning (CNN Pizarro gelé → embeddings 128-D → régression logistique) ?  
**Réponse courte:** non pour la tâche publiée (NORM vs non-NORM). Les volumes vides / WMn run-03 ne sont **pas** dans le jeu de transfer (n = 264, run-01/02 seulement). Retirer les 8 MPRAGE bas CNR et/ou les 5 votes 50/50 **diminue** l’AUC OOF (0.964 → 0.940–0.952).

Tables machine-readable dans ce dossier : `listed_images_status.tsv`, `transfer_auc_with_without_exclusions.tsv`, `pizarro_screening_stats_exclusions.tsv`.

Embeddings : `pizarro_transfer_learning/output/with_embeddings/extraction_checkpoint.npz` (n = 264).  
Labels transfer : run-01 = non-NORM, run-02 = NORM (comme l’expérience publiée, AUC ≈ 0.964).  
Pizarro image-level : `reports/pizarro_qc_transfer_calibrated/image_level_predictions.tsv` (n = 387).  
IQM : `reports/mriqc_publication_audit/tables/mriqc_iqm_current.tsv`.

Le LR OOF est ré-entraîné sur le sous-ensemble (numpy, 5 folds stratifiés). Ce n’est pas une ré-extraction CNN.

---

## 1. Volumes vides / hors protocole (run-03)

| Stem | BIDS | Release | MRIQC | Pizarro P | Série | Dans transfer |
| --- | :---: | :---: | :---: | ---: | --- | :---: |
| `sub-039_ses-02_run-03_T1w` | oui | **oui** | non (W1.3) | 94 | WMn_MPRAGE_sagittal | non |
| `sub-058_ses-01_run-03_T1w` | oui | **oui** | non (W1.4) | 66 | WMn_MPRAGE_sagittal | non |
| `sub-066_ses-02_run-03_T1w` | oui | **non** | non | 100 | WMn_MPRAGE_sagittal | non |

MRIQC W1 : FOV ~192×224×224, intensité max ~390 / ~294 vs sibling ~4095. MRIQC échoue (`Input inhomogeneity-corrected data seem empty`). Ce sont des acquisitions incomplètes, pas des bugs MRIQC.

**Transfer :** 0/3 dans les 264 embeddings. Les retirer **ne change pas** l’AUC transfer.

**Screening Pizarro (387 T1w) :** mean P 69.67 → 69.54 après drop des 3 (négligeable). Pizarro les marque déjà « artefact » mais n’est pas l’outil pour les décider : l’absence d’IQM + FOV/intensité suffisent.

**Action données :** documenter (déjà W1). `sub-066_ses-02_run-03` est déjà hors `release_dataset`. Les deux autres y sont encore. Ne pas les utiliser en analyse anatomique. Retrait du dépôt public = décision PI, pas automatique ici.

---

## 2. MPRAGE run-01 — bas CNR / haut CJV

Tous sont `T1w_MPR`, **dans le transfer** (8/8), label non-NORM, transfer_proba_nonNORM 0.97–1.00.

| Stem | CNR | CJV | Pizarro P | Release | Flags MRIQC (z>3) |
| --- | ---: | ---: | ---: | :---: | --- |
| `sub-066_ses-01_run-01_T1w` | **0.53** | 0.94 | 100 | non | **qi_2, snr_csf, tpm_overlap_gm** (seul MPRAGE à 3 flags) |
| `sub-040_ses-01_run-01_T1w` | 0.61 | 0.97 | 100 | oui | — |
| `sub-013_ses-01_run-01_T1w` | 0.65 | 1.06 | 96 | oui | — |
| `sub-071_ses-01_run-01_T1w` | 0.65 | 0.91 | 100 | oui | — |
| `sub-040_ses-02_run-01_T1w` | 0.67 | 0.92 | 100 | oui | — |
| `sub-082_ses-01_run-01_T1w` | 0.71 | 0.85 | 100 | oui | — |
| `sub-076_ses-01_run-01_T1w` | 0.73 | 0.96 | 100 | non | — |
| `sub-078_ses-01_run-01_T1w` | 0.78 | **1.17** (pire CJV MPRAGE run-01) | 76 | oui | — |

CNR confirmé : ce sont 7 des 9 pires MPRAGE run-01 (n = 121). Manquent dans la liste PI : `sub-050_ses-01_run-01` (CNR 0.678, CJV 1.075) et `sub-052_ses-02_run-01` (CNR 0.722).

---

## 3. Pizarro incertain (votes ~50/50)

Tous **dans le transfer**. CNR MPRAGE normal (~0.93–1.79). Pizarro n’est pas d’accord avec le transfer :

| Stem | Run | Pizarro P | Transfer P(non-NORM) | CNR | Interprétation |
| --- | --- | ---: | ---: | ---: | --- |
| `sub-080_ses-01_run-01` | 01 | 50 | **0.997** | 0.93 | non-NORM clair pour le transfer ; Pizarro indécis |
| `sub-067_ses-01_run-02` | 02 | 50 | 0.002 | 1.57 | NORM clair pour le transfer |
| `sub-018_ses-01_run-02` | 02 | 50 | 0.007 | 1.64 | idem |
| `sub-017_ses-01_run-02` | 02 | 50 | 0.001 | 1.58 | idem |
| `sub-029_ses-01_run-02` | 02 | **52** | 0.008 | 1.79 | presque 50/50 ; transfer → NORM |

Le transfer sépare déjà ces images selon le régime (run), pas selon un défaut visuel. Un vote 50/50 Pizarro n’est **pas** une preuve de mauvaise qualité MRIQC.

---

## 4. WMn — juger avec MRIQC, pas Pizarro

Aucun des 5 n’est dans le transfer. Pizarro P = **100** pour les 5 (et mean P run-03 = 89.9 vs 49.7 run-02) : le CNN Pizarro, entraîné sur MPRAGE T1w, traite le contraste inversé WMn comme artefact. **Ne pas exclure un WMn parce que Pizarro = 100.**

Les 5 listés sont exactement les **5 pires CNR** parmi 109 WMn (médiane CNR WMn = 1.72) :

| Stem | CNR | CJV | MRIQC notable | Release |
| --- | ---: | ---: | --- | :---: |
| `sub-084_ses-01_run-03_T1w` | **1.12** (min WMn) | 0.83 | — | non |
| `sub-030_ses-01_run-03_T1w` | 1.13 | **0.87** (max CJV WMn) | tpm_overlap_gm (z) | oui |
| `sub-066_ses-01_run-03_T1w` | 1.14 | 0.78 | snr_csf, tpm_overlap_gm/wm (z) | non |
| `sub-012_ses-01_run-03_T1w` | 1.27 | 0.75 | — | oui |
| `sub-012_ses-02_run-03_T1w` | 1.33 | 0.75 | — | oui |

Un flag Tukey/z n’est pas une exclusion automatique (principe MRIQC du dépôt). `sub-066` run-03 est le plus préoccupant (overlap tissus).

---

## 5. Transfer learning : avec vs sans

Tâche A = labels publiés (run-01 non-NORM vs run-02 NORM).  
Tâche B = FAIL si score Pizarro embedding ≥ 50 (proxy QC, circulaire).

| Exclusion | n kept | n drop | AUC A (NORM) | Δ A | AUC B (QC≥50) | Δ B |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aucune | 264 | 0 | **0.964** | — | 0.962 | — |
| 8 bas CNR run-01 | 256 | 8 | 0.952 | **−0.013** | 0.969 | +0.007 |
| 5 incertains 50/50 | 259 | 5 | 0.944 | **−0.020** | 0.977 | +0.015 |
| 8 + 5 | 251 | 13 | 0.940 | **−0.024** | 0.973 | +0.011 |
| empty + WMn run-03 | 264 | **0** | 0.964 | 0 | 0.962 | 0 |

### Pourquoi A baisse

Les 8 bas CNR sont tous run-01 (classe non-NORM) et des **exemples faciles** (gros défaut de contraste). Les retirer réduit la classe positive et enlève le signal que le LR utilise. Les 50/50 sont surtout du run-02 ; les retirer déséquilibre et enlève des NORM « difficiles » pour Pizarro mais clairs pour l’embedding.

### Pourquoi B monte un peu

On retire surtout des labels QC ambigus (P ≈ 50). L’AUC QC s’améliore parce que le problème devient plus facile, pas parce que le modèle généralise mieux. Ce n’est **pas** un argument pour exclure.

Les scores transfer **déjà fit** sur les 264 (`transfer_proba_nonNORM`) ont une AUC vs label NORM = 1.0 (surapprentissage in-sample). Ne pas les utiliser pour juger une exclusion ; l’OOF ci-dessus est l’expérience honnête.

---

## 6. Screening Pizarro (387 T1w), hors transfer

| Sous-ensemble | n | mean P | % P≥90 | % P≥50 |
| --- | ---: | ---: | ---: | ---: |
| tous | 387 | 69.67 | 42.9 | 73.6 |
| drop 3 vides | 384 | 69.54 | 42.7 | 73.4 |
| drop 5 WMn listés | 382 | 69.28 | 42.1 | 73.3 |
| drop toutes les listées | 366 | 68.80 | 41.5 | 72.1 |
| run-03 seul | 120 | **89.85** | 76.7 | 94.2 |
| run-03 sans listées | 112 | 89.48 | 75.9 | 93.8 |

Retirer empty/WMn ne « nettoie » pas Pizarro : le run-03 WMn reste massivement P≈100 par construction du CNN.

---

## 7. Recommandations

1. **Ne pas retrancher ces images pour « améliorer » le transfer.** L’AUC NORM empirique **baisse**.
2. **Volumes vides (039 / 058 / 066 ses-02 run-03) :** hors analyses anatomiques ; documenter (W1). Décision PI pour les deux encore dans `release_dataset`.
3. **WMn :** MRIQC (CNR/CJV/flags) uniquement. Ignorer Pizarro. Les 5 listés sont bien la queue CNR ; exclusion analyse-spécifique, pas dépôt-wide.
4. **MPRAGE bas CNR :** garder dans le transfer ; ce sont du signal. `sub-066_ses-01_run-01` est déjà hors release et reste le seul MPRAGE à 3 flags.
5. **50/50 Pizarro :** revue visuelle optionnelle ; le transfer les classe déjà selon le run. Ne pas en faire un critère d’exclusion.
6. **Ne pas utiliser Pizarro comme critère d’exclusion sujet** (déjà la ligne du dépôt).

Phrase methods (EN) possible :

> Pizarro CNN scores were not used as subject-level exclusion criteria. White-matter-nulled MPRAGE (run-03) is outside the Pizarro training contrast; quality of those series was assessed with MRIQC IQMs. Three run-03 volumes lacked IQMs because of empty/out-of-protocol FOV and were omitted from anatomical IQM summaries. Retraining the published embedding classifier after dropping low-CNR MPRAGE and Pizarro-uncertain cases reduced, rather than improved, NORM vs non-NORM OOF ROC-AUC (0.964 → 0.940).
