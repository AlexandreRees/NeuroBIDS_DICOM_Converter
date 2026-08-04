# Légendes figures déidentification (PI / publication)

Figures PI: `reports/deidentification_figures/figures/` (PNG 300 dpi + PDF).  
Figures manuscrit (EN): `figure_*.png` / `.svg` à la racine de ce dossier.  
Régénération: `python3 reports/deidentification_figures/generate_pi_figures.py`

---

### Figure 1 — Workflow
**Fichier:** `Fig01_deidentification_workflow`  
**Message:** Archive brute immuable → inventaire / mapping → déidentification sur copies → BIDS + QC.  
**Légende (FR):** Workflow de préparation: les DICOM d’origine restent en lecture seule; la déidentification (PHI, dates, UID, tags privés) s’applique uniquement aux copies dérivées avant conversion BIDS.

### Figure 2 — Actions sur les tags DICOM
**Fichier:** `Fig02_dicom_tag_actions`  
**Message:** 32 effacés · 2 pseudonymisés · 8 UID · 8 dates · 14 conservés.

### Figure 3 — Avant / après (synthétique)
**Fichier:** `Fig03_before_after_deidentification`  
**Message:** PatientName/ID → SUBC…; dates décalées; UIDs → `2.25.*`. Aucun vrai ID.

### Figure 4 — Provenance
**Fichier:** `Fig04_data_provenance`  
**Message:** Chaîne complète avec colonne « DICOM brut immutable » et snapshots d’intégrité.

### Figure 5 — Composition de la politique
**Fichier:** `Fig05_policy_composition`  
**Message:** 66 entrées de politique regroupées (PHI / lien / science / pixels-privés). Caveat PS3.15.

### Figure 6 — One-pager PI
**Fichier:** `Fig06_PI_onepager_deidentification`  
**Usage:** ouvrir la réunion PI avec cette seule slide.

---

## Ordre de projection suggéré (8–10 min)

1. Fig06 (1 min) — message et recommandation  
2. Fig01 (2 min) — workflow  
3. Fig03 (2 min) — exemple concret  
4. Fig02 + Fig05 (2–3 min) — politique quantitative  
5. Fig04 si questions sur l’intégrité / audit (1–2 min)

## Package manuscrit (Scientific Data)

Utiliser les `figure_*.png/.svg` EN + captions `figure_*_caption.md` +  
`deidentification_manuscript_section.md` + `Supplementary_Table_DICOM_Deidentification.*`.
