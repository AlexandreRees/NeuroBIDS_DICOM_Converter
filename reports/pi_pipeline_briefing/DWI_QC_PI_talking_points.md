# DWI QC — texte pour expliquer à ton PI

**Durée suggérée :** 2–3 minutes  
**Ordre des figures :** Fig01 → Fig02 → Fig03 → Fig05 (Fig04/06 si questions)

---

## En une phrase

> « Les DWI sont techniquement validés en lecture seule : intégrité 100 %, 0 échec `dwigradcheck`, paires AP/PA complètes. Les 111 REVIEW et les b0 négatifs sont des observations documentées — pas des exclusions, pas de correction de gradients appliquée. »

---

## Chiffres clés

| Item | Résultat |
|---|---|
| Scans / sujets / sessions | **361 / 82 / 120** |
| Intégrité NIfTI+bval+bvec+JSON | **361/361 PASS** |
| dwigradcheck | **250 PASS · 111 REVIEW · 0 FAIL** |
| Paires AP/PA | **120/120 sessions** |
| Protocoles | **6** (surtout A=232 et B=121) |
| Signal robuste (avec masque) | **216/361** |
| Exclusions auto basées DWI QC | **aucune** |

---

## Comment lire chaque figure

1. **Fig01 overview** — verdict global PASS + one-liner.
2. **Fig02 protocols** — multi-protocole clinique attendu (A haute résolution angulaire ; B 11 dir).
3. **Fig03 gradient** — REVIEW ≠ FAIL ; enrichi dans `run-02` (102/111) ; aucune correction appliquée.
4. **Fig04 signal** — SNR/CNR/brain fraction (descriptif ; médianes).
5. **Fig05 checklist** — tableau type Scientific Data.
6. **Fig06 warnings** — comment justifier REVIEW + b0 signés sans bloquer le dépôt.

---

## Pourquoi c’est pertinent pour le dataset

1. **Couche QC diffusion** complémentaire à MRIQC (anat/func) et Pizarro (T1).
2. **Transparence** : warnings expliqués et non “cachés”.
3. **Reproductibilité** : tables TSV + figures prêtes pour le Data Descriptor.
4. **Pas de modification des données** : BIDS / gradients inchangés → provenance claire.

---

## Conclusion PI

> « DWI QC = PASS pour la publication, avec documentation des REVIEW et des intensités signées. Ça ne bloque ni OpenNeuro ni Scientific Data. »

## Fichiers

`reports/pi_pipeline_briefing/figures/dwi/`
