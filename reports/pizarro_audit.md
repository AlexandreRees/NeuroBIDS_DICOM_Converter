# Audit d'implémentation — Pizarro et al. (2023)

**Date:** 2026-07-27 16:29 UTC  
**Pipeline:** `neuro_pipeline.qc.pizarro_qc`  
**Dépôt officiel vendored:** `neuro_pipeline/external/Pizarro-et-al-2023-DL-detects-MRI-artifacts`  
**GitHub:** https://github.com/AS-Lab/Pizarro-et-al-2023-DL-detects-MRI-artifacts  
**Prédictions analysées:** `/home/alexrees/scratch/reports/pizarro_qc_revised/image_level_predictions.tsv` (n=385)  
**Sorties expérimentales:** `reports/pizarro_audit/`  

> Ce rapport compare l'implémentation `neuro_pipeline` au code `production/` officiel.  
> Le script expérimental `code/pizarro_implementation_audit.py` **ne modifie pas** le pipeline principal.

==============================================================================
## 1. Audit du prétraitement
==============================================================================

### Verdict

**Le prétraitement est IDENTIQUE au dépôt officiel**, car `neuro_pipeline.qc.pizarro_qc` importe et appelle directement `production/utils.py::get_subj_data` (pas de re-implémentation locale).

| Étape | Officiel (`production/utils.py`) | Notre pipeline | Statut |
|---|---|---|---|
| Chargement NIfTI | `nib.load` dans `load_and_reorient` L35–41 | même fonction importée | **identique** |
| Orientation | `axcodes2ornt("SPL")` + `as_reoriented` L37–40 | idem | **identique** (SPL, **pas** RAS) |
| Transpose / swap | `swap_axes`: `swapaxes(0,2)` puis flips L15–20 | idem | **identique** |
| Flip | `img[::-1, ::-1, :]` L17 | idem | **identique** |
| Ordre des axes | après swap: axe le plus petit ramené en dernier L18–19 | idem | **identique** |
| Resize | `scipy.ndimage.zoom` si shape > (256,256,64) L29–32, L48–49 | idem | **identique** (ordre 3 spline par défaut) |
| Interpolation | défaut `zoom` = order=3 (spline) | idem | **identique** |
| Normalisation | z-score `(x-mean)/std` L8–12, **après** resize | idem | **identique** |
| Clipping | aucun | aucun | **identique** |
| Padding | zeros (256,256,64) L23–26 | idem | **identique** |
| Dimensions finales | reshape `(1,256,256,64,1)` L44–52 | idem | **identique** |
| Datatype | `astype(np.float32)` L53 | idem | **identique** |
| NaN | **non traités** explicitement | idem | **identique** (risque partagé) |
| Voxels négatifs | **conservés** (pas d'abs/clip) | idem | **identique** |

### Chaîne exacte (`get_subj_data`)

```text
NIfTI → reorient SPL → swap_axes (+ flips) → optional zoom → normalize → pad 256³×64 → float32 (1,256,256,64,1)
```

### Différences d'orchestration (hors prétraitement image)

| Point | Officiel `infer_onnx.py` | `pizarro_qc.py` | Statut |
|---|---|---|---|
| Appel prétraitement | `get_subj_data` | `get_subj_data` (import) | **identique** |
| Chargement parallèle | `multiprocessing.Queue` producteur | séquentiel | **légèrement différent** (orchestration seule) |
| Entrées | chemins libres | BIDS `*_T1w.nii.gz` sous `bids/` | **légèrement différent** (scope dataset) |

==============================================================================
## 2. Audit du modèle ONNX
==============================================================================

- Fichier utilisé: `/home/alexrees/scratch/neuro_pipeline/external/Pizarro-et-al-2023-DL-detects-MRI-artifacts/production/model.FINAL.onnx`
- SHA256: `cb84f2b90f7de452331ed9ba5152335b873aba95d0ca3766adfffecdafe5178a`
- Taille: 11958624 octets
- Symlink `production/weights/model.FINAL.onnx` → même fichier: **oui**
- ONNX Runtime: `1.23.2`
- Providers session audit: `['CPUExecutionProvider']`

| Contrôle | Officiel | Notre pipeline | Statut |
|---|---|---|---|
| `model.FINAL.onnx` | `weights/model.FINAL.onnx` (symlink) | `production/model.FINAL.onnx` (même inode via resolve) | **identique** |
| `disabled_optimizers=["EliminateDropout"]` | oui (`infer_onnx.py` L81–84) | oui (`pizarro_qc.py` L226–230) | **identique** |
| `onnxruntime.set_seed` | oui (défaut 1010) | oui (défaut 1010) | **identique** |
| Providers | non spécifié (défaut ORT; CUDA commenté) | `CPUExecutionProvider` forcé | **légèrement différent** |
| `SessionOptions` / threads | non | `intra_op_num_threads` depuis `OMP_NUM_THREADS` | **légèrement différent** |
| MC runs défaut | 10 | 10 | **identique** |

**Note:** forcer CPU est attendu sur Narval pour reproductibilité; cela ne change pas les poids, seulement le backend d'exécution.

==============================================================================
## 3. Audit des MC Dropout
==============================================================================

La session ONNX est créée **une fois** par sujet; les 10 passes `sess.run` réutilisent la même session (poids non rechargés). `EliminateDropout` est désactivé pour conserver le dropout stochastique.

Échantillon expérimental: **20** T1 (seed=1010).

- Images avec **exactement la même sortie** aux 10 passes: **0 / 20**
- → Le dropout MC est **actif** (variabilité observée).

Extrait (`tables/mc_dropout_audit_20.tsv`):

| filename | n_art/10 | soft σ | n_unique softmax | identical? |
|---|---:|---:|---:|---|
| `sub-073_ses-01_run-03_T1w.nii.gz` | 10/10 | 0.1049 | 10 | False |
| `sub-066_ses-02_run-01_T1w.nii.gz` | 10/10 | 0.0165 | 10 | False |
| `sub-025_ses-01_run-02_T1w.nii.gz` | 4/10 | 0.3018 | 10 | False |
| `sub-054_ses-02_run-03_T1w.nii.gz` | 4/10 | 0.3415 | 10 | False |
| `sub-008_ses-01_run-01_T1w.nii.gz` | 4/10 | 0.2530 | 10 | False |
| `sub-040_ses-02_run-03_T1w.nii.gz` | 10/10 | 0.0790 | 10 | False |
| `sub-043_ses-02_run-03_T1w.nii.gz` | 5/10 | 0.2899 | 10 | False |
| `sub-041_ses-01_run-01_T1w.nii.gz` | 5/10 | 0.3622 | 10 | False |
| `sub-016_ses-02_run-01_T1w.nii.gz` | 8/10 | 0.3396 | 10 | False |
| `sub-014_ses-01_run-01_T1w.nii.gz` | 10/10 | 0.1243 | 10 | False |
| `sub-043_ses-02_run-04_T1w.nii.gz` | 4/10 | 0.3195 | 10 | False |
| `sub-081_ses-02_run-01_T1w.nii.gz` | 10/10 | 0.0887 | 10 | False |

Table complète: `reports/pizarro_audit/tables/mc_dropout_audit_20.tsv`

==============================================================================
## 4. Analyse des probabilités
==============================================================================

Les scores publiés `artifact_probability` sont dérivés des TSVs sujets (classification + probability de majorité MC) via `build_pizarro_scientific_data_report.continuous_metrics_from_row`:

```text
artifact_probability = 100 × (# votes MC « artifact ») / 10
confidence           = 100 × max(p_art, 1−p_art)   # = probability officielle collate
uncertainty          = entropie binaire de p_art
```

**Sémantique importante:** `collate_inferences` du dépôt officiel retourne la probabilité d'accord avec la **classe majoritaire**, pas une soft-proba artifact unique. Notre package publication convertit correctement vers la fraction de votes artifact.

| Stat | Valeur (n=385) |
|---|---:|
| Moyenne | 65.84 |
| Médiane | 80.00 |
| = 0% | 22 |
| = 80% | 24 |
| = 90% | 32 |
| = 100% | 137 |
| ≥ 90% | 169 (43.9%) |
| ≥ 80% | 193 (50.1%) |

### Histogramme (déciles)

| Probabilité | n |
|---:|---:|
| 0 | 22 |
| 10 | 22 |
| 20 | 25 |
| 30 | 21 |
| 40 | 31 |
| 50 | 25 |
| 60 | 21 |
| 70 | 25 |
| 80 | 24 |
| 90 | 32 |
| 100 | 137 |

Figure: `reports/pizarro_audit/artifact_probability_hist.png`

### Comparaison au papier

Le papier (MedIA 2023) rapporte des performances de **détection** (accuracy / F1) sur une base ~34 800 scans (~98% clean), avec amélioration via data-ramping et **filtrage par incertitude épistémique** (accuracy test jusqu'à 99.5% après seuil d'incertitude). Il ne publie pas un histogramme de `artifact_probability` sur une cohorte BIDS externe comparable à la nôtre.

**Donc:** un taux élevé de scores ≥90% sur *notre* dataset n'est **pas** directement contredit par une figure du papier; cela signale surtout un **décalage de domaine** et/ou une sensibilité du classifieur hors distribution.

### Stratification par `SeriesDescription` (explication principale)

Table: `reports/pizarro_audit/tables/artifact_prob_by_seriesdescription.tsv`

| SeriesDescription | n | mean | % @100 | % ≥90 |
|---|---:|---:|---:|---:|
| `T1w_MPR` | 259 | 54.32 | 20.1 | 28.2 |
| `WMn_MPRAGE_sagittal` | 120 | 90.75 | 70.0 | 77.5 |
| `T1w_MPR_ND` | 6 | 65.0 | 16.7 | 50.0 |

**Lecture:** `WMn_MPRAGE` (n=120) a une moyenne **90.75%** et **77.5%** ≥90%, contre `T1w_MPR` (n=259) moyenne **54.32%** / **28.2%** ≥90%. Le skew global est donc largement porté par le contraste white-matter-nulled, hors distribution typique du corpus Pizarro.

==============================================================================
## 5. Comparaison 10 vs 100 MC runs
==============================================================================

Script expérimental: `code/pizarro_implementation_audit.py` (option `--mc-grid 10 25 50 100`). Le défaut production reste **MC=10** (`pizarro_qc.DEFAULT_MC_RUNS`).

Note: `pizarro_qc.py` expose déjà `--mc-runs` en CLI; cet audit utilise un script séparé pour ne pas toucher aux sorties publication.

n images = 30

| Métrique | Valeur |
|---|---:|
| mean p_art MC10 | 74.00 |
| mean p_art MC100 | 74.10 |
| mean |Δ| (10 vs 100) | 7.17 |
| max |Δ| (10 vs 100) | 28.00 |

Table: `reports/pizarro_audit/tables/mc_runs_comparison.tsv`

| filename | MC10 | MC25 | MC50 | MC100 |
|---|---:|---:|---:|---:|
| `sub-073_ses-01_run-03_T1w.nii.gz` | 100.0 | 100.0 | 100.0 | 100.0 |
| `sub-066_ses-02_run-01_T1w.nii.gz` | 100.0 | 100.0 | 100.0 | 100.0 |
| `sub-025_ses-01_run-02_T1w.nii.gz` | 60.0 | 52.0 | 36.0 | 32.0 |
| `sub-054_ses-02_run-03_T1w.nii.gz` | 60.0 | 56.0 | 52.0 | 47.0 |
| `sub-008_ses-01_run-01_T1w.nii.gz` | 70.0 | 56.0 | 58.0 | 58.0 |
| `sub-040_ses-02_run-03_T1w.nii.gz` | 100.0 | 100.0 | 100.0 | 99.0 |
| `sub-043_ses-02_run-03_T1w.nii.gz` | 60.0 | 60.0 | 76.0 | 77.0 |
| `sub-041_ses-01_run-01_T1w.nii.gz` | 60.0 | 48.0 | 40.0 | 36.0 |
| `sub-016_ses-02_run-01_T1w.nii.gz` | 100.0 | 84.0 | 80.0 | 82.0 |
| `sub-014_ses-01_run-01_T1w.nii.gz` | 90.0 | 88.0 | 82.0 | 88.0 |
| `sub-043_ses-02_run-04_T1w.nii.gz` | 30.0 | 36.0 | 40.0 | 43.0 |
| `sub-081_ses-02_run-01_T1w.nii.gz` | 90.0 | 84.0 | 88.0 | 89.0 |
| `sub-021_ses-01_run-01_T1w.nii.gz` | 30.0 | 40.0 | 48.0 | 46.0 |
| `sub-010_ses-01_run-01_T1w.nii.gz` | 100.0 | 100.0 | 100.0 | 100.0 |
| `sub-081_ses-02_run-02_T1w.nii.gz` | 100.0 | 100.0 | 100.0 | 100.0 |

==============================================================================
## 6. Audit des T1 classés 100%
==============================================================================

Total images à 100%: **137**. Ci-dessous les **20 premières** (ordre du TSV publication).

Table: `reports/pizarro_audit/tables/top20_artifact100_metadata.tsv`

| subject | session | file | orient | SeriesDescription | TR | TE | FA |
|---|---|---|---|---|---:|---:|---:|
| sub-001 | ses-01 | `sub-001_ses-01_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-001 | ses-02 | `sub-001_ses-02_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-002 | ses-01 | `sub-002_ses-01_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-002 | ses-02 | `sub-002_ses-02_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-003 | ses-01 | `sub-003_ses-01_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-003 | ses-02 | `sub-003_ses-02_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-004 | ses-01 | `sub-004_ses-01_run-01_T1w.nii.gz` | RAS | T1w_MPR | 2.5 | 0.00222 | 8 |
| sub-004 | ses-01 | `sub-004_ses-01_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-004 | ses-02 | `sub-004_ses-02_run-01_T1w.nii.gz` | RAS | T1w_MPR | 2.5 | 0.00222 | 8 |
| sub-004 | ses-02 | `sub-004_ses-02_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-005 | ses-01 | `sub-005_ses-01_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-006 | ses-02 | `sub-006_ses-02_run-01_T1w.nii.gz` | RAS | T1w_MPR | 2.5 | 0.00222 | 8 |
| sub-006 | ses-02 | `sub-006_ses-02_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-007 | ses-01 | `sub-007_ses-01_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-008 | ses-01 | `sub-008_ses-01_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-008 | ses-02 | `sub-008_ses-02_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-010 | ses-01 | `sub-010_ses-01_run-01_T1w.nii.gz` | RAS | T1w_MPR | 2.5 | 0.00222 | 8 |
| sub-010 | ses-01 | `sub-010_ses-01_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-011 | ses-01 | `sub-011_ses-01_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |
| sub-011 | ses-02 | `sub-011_ses-02_run-03_T1w.nii.gz` | RAS | WMn_MPRAGE_sagittal | 4 | 0.00382 | 7 |

### Points communs (tous les 100%)

| SeriesDescription | n @ 100% |
|---|---:|
| `WMn_MPRAGE_sagittal` | 84 |
| `T1w_MPR` | 52 |
| `T1w_MPR_ND` | 1 |

Hypothèses à retenir: présence majeure de contrastes **WMn_MPRAGE** et **T1w_MPR** Siemens Prisma 3T; FOV / contraste potentiellement hors distribution du corpus d'entraînement Pizarro (base clinique différente).

==============================================================================
## 7. Vérification des entrées réseau
==============================================================================

Pour 5 T1: tenseurs prétraités sauvés en `.npy` sous `reports/pizarro_audit/preprocessed/`, stats dans `tables/preprocessed_input_stats.tsv`.

| # | file | orig shape | orig min/max | pre shape | pre min/max | pre mean±std |
|---:|---|---|---|---|---|---|
| 1 | `sub-002_ses-01_run-02_T1w.nii.gz` | (208, 300, 320) | 0/4.1e+03 | (1, 256, 256, 64, 1) | -0.896/4.99 | 6.01e-08±1 |
| 2 | `sub-054_ses-01_run-02_T1w.nii.gz` | (208, 300, 320) | 0/4.1e+03 | (1, 256, 256, 64, 1) | -1.03/4.13 | -2.42e-08±1 |
| 3 | `sub-052_ses-02_run-03_T1w.nii.gz` | (192, 224, 224) | 0/398 | (1, 256, 256, 64, 1) | -2.51/13.9 | 9.31e-09±1 |
| 4 | `sub-058_ses-01_run-01_T1w.nii.gz` | (208, 300, 320) | 0/4.1e+03 | (1, 256, 256, 64, 1) | -1.1/4.63 | -2.58e-08±1 |
| 5 | `sub-083_ses-01_run-02_T1w.nii.gz` | (208, 300, 320) | 0/4.1e+03 | (1, 256, 256, 64, 1) | -1.12/3.96 | -5.15e-08±1 |

Attendu: `pre_shape=(1,256,256,64,1)`, dtype float32, moyenne proche de 0 et écart-type proche de 1 **avant padding** (le padding de zéros peut tirer mean/std après reshape).

==============================================================================
## 8. Conclusion
==============================================================================

### Fidélité au dépôt officiel

**Oui — très élevée.** Prétraitement et collation MC utilisent le code `production/utils.py` officiel; le modèle est `model.FINAL.onnx` avec `EliminateDropout` désactivé, seed 1010, MC=10. Différences limitées à l'orchestration (CPU forcé, threads, pas de multiprocessing).

### Pourquoi autant de scores ≥ 90% ?

Causes **probables** (par ordre de plausibilité scientifique):

1. **Décalage de domaine (principal):** stratification empirique — `WMn_MPRAGE_sagittal` concentre la majorité des 100%/≥90%, alors que `T1w_MPR` est nettement plus bas. Le modèle a été entraîné sur une base clinique imbalanced (~98% clean) sans ce contraste white-matter-nulled.
2. **Sémantique du score:** `artifact_probability` = fraction de votes MC, pas une calibration de soft-max. Beaucoup de 100% = 10/10 votes artifact (décision dure répétée), pas « 100% de confiance soft calibrée ».
3. **Pas un bug de dropout:** si l'audit MC montre des sorties non identiques entre passes, le stochastique fonctionne; le biais est donc côté données/domaine.
4. **Entrées avant defacing:** FOV tête/cou et visage présents peuvent différer des exemples d'entraînement (à tester expérimentalement vs défaced).
5. **Différences ORT mineures (CPU/threads)** peu susceptibles d'expliquer un excès massif de 100%.

### Améliorations scientifiquement justifiées

| Action | Justifiée ? | Commentaire |
|---|---|---|
| Documenter domaine + WMn vs MPR | **Oui** | Transparence Scientific Data |
| Stratifier scores par `SeriesDescription` | **Oui** | Explique les modes |
| Comparer face-intact vs défaced (expérience) | **Oui** | Test d'hypothèse FOV/visage |
| Utiliser uncertainty pour prioriser la revue | **Oui** | Aligné avec le papier |
| Augmenter MC à 100 en production | Optionnel | Stabilité; ne change pas le modèle |
| Recalibrer / changer seuils d'exclusion auto | **Non pour dépôt** | On n'exclut déjà pas auto |

### Ce qu'il ne faut PAS faire (comparabilité papier)

- **Ne pas** modifier `get_subj_data` (orientation SPL, swap, normalize, pad).
- **Ne pas** réactiver `EliminateDropout`.
- **Ne pas** remplacer `model.FINAL.onnx` par un autre checkpoint.
- **Ne pas** changer la définition des votes MC si on veut rester comparable.
- **Ne pas** « corriger » les scores élevés par post-hoc ad hoc sans expérience contrôlée.

### Recommandation opérationnelle

Conserver l'implémentation actuelle comme **screening** (déjà la politique publication). Interpréter les ≥90% comme **file de revue visuelle**, pas comme taux d'échec du dataset. Pour expliquer le skew au PI: montrer la stratification WMn/MPR + rappel domaine.

---

### Fichiers produits

| Fichier | Contenu |
|---|---|
| `reports/pizarro_audit.md` | Ce rapport |
| `reports/pizarro_audit/tables/mc_dropout_audit_20.tsv` | Variabilité MC |
| `reports/pizarro_audit/tables/mc_runs_comparison.tsv` | MC 10/25/50/100 |
| `reports/pizarro_audit/tables/top20_artifact100_metadata.tsv` | Métadonnées 100% |
| `reports/pizarro_audit/tables/artifact100_by_seriesdescription.tsv` | Comptage des 100% |
| `reports/pizarro_audit/tables/artifact_prob_by_seriesdescription.tsv` | Stratification complète |
| `reports/pizarro_audit/tables/preprocessed_input_stats.tsv` | Stats entrées |
| `reports/pizarro_audit/preprocessed/*.npy` | Tenseurs réseau |
| `reports/pizarro_audit/artifact_probability_hist.png` | Histogramme |

