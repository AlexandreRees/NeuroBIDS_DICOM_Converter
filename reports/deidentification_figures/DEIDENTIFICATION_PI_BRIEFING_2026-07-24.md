# Déidentification DICOM — briefing PI (24 juillet 2026)

**Verdict header (chemin recherche / conversion):** **PASS avec caveats**  
**Verdict framing publication:** **GO** si on documente un **sous-ensemble orienté PS3.15 Basic** (pas une conformité certifiée)

## Message 30 secondes

On déidentifie les **en-têtes DICOM sur des copies dérivées** seulement: l’archive `raw` **n’est jamais écrasée**. PHI effacé / pseudonymisé, UID remappés, dates décalées par participant, tags privés retirés; **pixels inchangés** à cette étape. Les paramètres scientifiques nécessaires (TR/TE, géométrie, SeriesDescription, etc.) sont **conservés** pour BIDS. Pour Scientific Data / OpenNeuro: accepter le framing Methods + table supplémentaire; **ne pas** revendiquer une conformité PS3.15 « certifiée ».

## Chiffres clés (politique documentée)

| Catégorie | Count |
| --- | ---: |
| Cleared (PHI / free-text / site) | **32** |
| Pseudonymized (PatientName / PatientID) | **2** |
| UID remapped | **8** |
| Date shifted | **8** |
| Preserved (science / times / sex) | **14** |
| Removed private tags (catégorie) | **1** |
| Pixel data unchanged (catégorie) | **1** |

Offsets dates: table privée `metadata/deidentify_date_shifts.csv` (**ne pas publier**).

## Ce que le PI doit retenir

1. **Immutabilité** — raw = vérité d’archive; déid = dérivé → conversion BIDS.
2. **Science intacte** — paramètres d’acquisition et pixels non altérés à ce stage.
3. **Longitudinalité** — décalage de dates par participant → intervalles relatifs préservés.
4. **Caveat honnête** — orientation PS3.15 Basic, sous-ensemble custom documenté.
5. **Defacing** — hors de ce stage (piste release / OpenNeuro séparée).

## Décision proposée pour le PI

1. **Accepter** le package figures + section Methods (FR briefing / EN manuscrit).
2. **Publier** la Supplementary Table des actions tag + Figs 1–4 (ou 1+3+4 en main text).
3. **Garder privé** offsets dates + maps identité raw↔canonique.
4. **Qualifer** toute phrase PS3.15: « oriented toward / documented subset », jamais « full certified compliance ».

## Artifacts

- Figures PI: `reports/deidentification_figures/figures/Fig01`–`Fig06`
- One-pager: `figures/Fig06_PI_onepager_deidentification.png`
- Manuscrit EN: `figure_*.png/.svg`, `deidentification_manuscript_section.md`
- Preuves: `reports/deidentification_report.md`, `reports/deidentification_ps315_openneuro_audit.md`
- Régénération: `python3 reports/deidentification_figures/generate_pi_figures.py`
