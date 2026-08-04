# Pizarro QC — texte pour expliquer à ton PI

**Durée suggérée :** 1–2 minutes  
**Figures à montrer :** `figures/pizarro/Figure_Pizarro_overview_PI.png`, puis histogramme / priorité de revue  
**Chiffres :** package régénéré **24 juillet 2026** (après ajout des ses-02)

---

## En une phrase

> « Pizarro est un outil de **dépistage automatique** des artefacts sur les T1. Il ne décide pas qui est inclus ou exclu : il nous dit **quels scans regarder en priorité**. MRIQC reste le QC quantitatif principal. »

---

## Qu’est-ce que c’est ?

- Modèle publié : **Pizarro et al., 2023** (*Medical Image Analysis*), modèle `Pizarro2023-FINAL`.
- Appliqué **uniquement** aux `*_T1w.nii.gz` (pas FLAIR, pas DWI, pas fMRI).
- Pour chaque T1 : **10 passes** Monte Carlo dropout → scores continus :
  - **artifact probability** (0–100) : fraction des votes “artefact”
  - **confidence** : accord majoritaire
  - **uncertainty** : ambiguïté des votes (max quand 50/50)

**Couverture :** **385/385** T1w, **83** sujets, **152** T1w en `ses-02`, **0** erreur d’inférence.

---

## Comment on l’a utilisé (important pour le PI)

1. On calcule les scores sur tout le dataset.
2. On trie les images à **haute probabilité d’artefact** et à **haute incertitude**.
3. Ces listes servent à **prioriser une inspection visuelle** (**246** images en file de revue prioritaire ; seuils P≥90 ou U≥0.9).
4. **Aucune exclusion automatique** basée sur Pizarro.
5. **MRIQC** reste le cadre QC quantitatif principal (IQMs).

Phrase clé :
> « Un score Pizarro élevé ≠ rejet. Cela signifie : à inspecter. »

---

## Pourquoi c’est quand même pertinent pour le dataset ?

Même si MRIQC existe déjà, Pizarro ajoute de la valeur pour *Scientific Data* / OpenNeuro :

1. **Due diligence** : second filet de QC structurel, indépendant, publié et citable.
2. **Efficacité** : avec 385 T1, on ne peut pas tout revoir au même niveau ; Pizarro oriente le temps de revue là où ça compte.
3. **Transparence** : scores continus + listes top-10 documentés dans le package (reproductible).
4. **Complémentarité** : MRIQC = métriques image quantitatives ; Pizarro = score global “artefact” entraîné sur des cas annotés.
5. **Narratif Data Descriptor** : montre une stratégie QC en couches (MRIQC + Pizarro + DWI QC), pas un seul outil.

---

## Comment lire les chiffres (sans sur-interpréter)

- Moyenne artifact P ≈ **65.8**, médiane ≈ **80** : **descriptif seulement**.
- Ce n’est **pas** un taux d’échec du dataset.
- Beaucoup de T1 “réels” (mouvement, bruit, contrastes cliniques) peuvent scorer haut sans être inutilisables.
- Les top-10 (probabilité / incertitude) = **files d’attente de revue**, pas des listes d’exclusion.

---

## Ce que tu peux proposer comme conclusion PI

> « Pizarro est intégré comme couche de screening T1. Couverture complète (385/385, y compris les nouvelles ses-02). Résultats documentés. Pas d’exclusion auto. Ça renforce la crédibilité QC du dataset pour Scientific Data, en complément de MRIQC et du DWI QC. »

---

## Fichiers utiles

| Fichier | Usage |
|---|---|
| `figures/pizarro/Figure_Pizarro_overview_PI.png` | Slide “c’est quoi / à quoi ça sert” |
| `figures/pizarro/Figure_Pizarro_probability_hist_PI.png` | Distribution des scores |
| `figures/pizarro/Figure_Pizarro_prob_vs_uncert_PI.png` | Espace de screening |
| `figures/pizarro/Figure_Pizarro_review_priority_PI.png` | Top-10 à inspecter |
| `figures/pizarro/Figure_Pizarro_uncertainty_PI.png` | Ambiguïté du modèle |
| `reports/pizarro_qc_revised/executive_summary.md` | Détail chiffres (package autoritatif) |
| `reports/pizarro_qc_scientific_data/PIZARRO_QC_REPORT.md` | Rapport Scientific Data |
| `code/reports/generate_pizarro_pi_figures.py` | Régénération des figures PI |
