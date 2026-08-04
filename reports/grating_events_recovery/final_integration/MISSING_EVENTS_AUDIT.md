# Audit — cas non intégré + état des lieux missing events

Generated: 2026-07-28

## 1. Cas non intégré : `sub-046 ses-01 fMRI1`

### Verdict

L’intégration a **correctement bloqué** l’écriture sur `run-07`.  
Le mapping FINAL vers `run-07` est **scientifiquement incorrect** : c’est l’acquisition **incomplète**.  
La cible compatible avec MATLAB est **`run-09`** (226 volumes).

### Preuves

| Critère | run-07 (FINAL ACCEPT) | run-09 (jumeau) | MATLAB scan_info |
|---------|----------------------:|----------------:|-----------------:|
| ProtocolName | fMRI1_AP | fMRI1_AP | fMRI1 |
| SeriesNumber | **3** | **7** | — |
| Volumes BOLD | **219** | **226** | triggers **226** |
| Durée (~TR 0.937) | 205.2 s | 211.8 s | **210.83 s** |
| ImagingFrequency | 123.257846 | 123.257853 | — |
| events dans BIDS | non | non | — |

Écart triggers−volumes :

- run-07 : `|226−219|=7` → **hors tolérance (±2)** → `REVIEW`
- run-09 : `|226−226|=0` → compatible

Horodatage MATLAB fichier : `August-27-2024_11-42-15_AM`  
SHA16 enregistré : `8e2c62cca3be2202` (vérifié).

### Pourquoi FINAL avait choisi run-07

Chaîne de décision :

1. Recovery gate `AUTO_ACCEPT_FIRST_OF_DUPLICATE` → plus petit `SeriesNumber` parmi 2 BOLD `fMRI1_AP`
2. Final review a libellé ça `SERIESNUMBER_EXACT_MATCH` avec `volume_count=219` mais `matlab_trigger_count=226` et `duration_match=YES` (incohérent)
3. Intégration fail-closed a refusé l’écriture

### Recommandation curateur

| Action | Détail |
|--------|--------|
| **Corriger le mapping** | `sub-046 ses-01 fMRI1` → **ACCEPT `run-09`**, REJECT `run-07` (abort / incomplete) |
| Reason | Volume+duration match MATLAB ; SN3 = premier essai incomplet |
| Puis | Relancer `integrate_grating_events_to_bids.py --execute` sur ce seul cas |

`run-07` restera sans events (jumeau incomplet) — normal.

---

## 2. État des lieux — missing `task-fmri` events

| Metric | n |
|--------|--:|
| BOLD magnitude task-fmri | 553 |
| Avec events | 514 |
| **Missing** | **39** |
| Missing avant intégration | 57 |
| Réduction nette | −18 |

Inventaire détaillé :  
`reports/grating_events_recovery/final_integration/MISSING_EVENTS_INVENTORY.tsv`

### Par cause

| Cause | n | Interprétation |
|-------|--:|----------------|
| `NO_MATLAB_TRIGGERS` | **23** | Pas de `scan_info` / triggers pour ce protocole — **irrécupérable** sans nouvelle source |
| `TWIN_OF_MAPPED_RUN` | **11** | Jumeau du run déjà mappé (souvent abort SN plus bas) — **attendu**, ne pas remplir |
| `HAS_MATLAB_NOT_IN_FINAL_ACCEPT` | **2** | MATLAB présent mais pas dans ACCEPT final (`sub-011 ses-02`, `sub-024 ses-02` Rerun) — **candidats revue** |
| `INTEGRATION_HELD` (sub-046 run-07) | **1** | Mapping FINAL erroné — voir §1 |
| `AMBIGUOUS_PROTOCOL_TWINS_UNRESOLVED` (sub-046 run-09) | **1** | Bon candidat ; bloqué tant que FINAL pointe run-07 |
| `FINAL_REJECT` (sub-041 run-07) | **1** | Acquisition incomplète rejetée — OK |

### Par famille protocole

| Famille | missing |
|---------|--------:|
| fMRI1 | 15 |
| fMRI2 | 8 |
| fMRI3 | 8 |
| fMRI4 | 8 |

### Sessions entièrement sans events grating (4 runs)

Probablement **pas de MATLAB Grating** (ou chemin FOV / session non mappée) :

- `sub-047 ses-01`
- `sub-051 ses-01`
- `sub-057 ses-02`
- `sub-078 ses-01`
- `sub-081 ses-02` (souvent path FOV / MATLAB hors `2-Grating`)

### Twins volontairement sans events (après intégration OK)

Exemples : `sub-002 run-07`, `sub-023 run-07`, `sub-025 run-07`, `sub-043 run-01/05/11`, `sub-061 run-05`, `sub-083 run-07` — le run complet a reçu les events ; le jumeau reste vide.

---

## 3. Actionnable maintenant

1. **sub-046** : corriger ACCEPT → `run-09`, puis intégrer (1 events.tsv) → missing 39→38 (et run-07 restera twin vide).
2. **Revue ciblée** (2 cas MATLAB non-ACCEPT) : `sub-011 ses-02`, `sub-024 ses-02` (`fMRI2_AP_Rerun`).
3. **23 NO_MATLAB** : hors scope events reconstruction tant que les `.mat` ne sont pas retrouvés.

## Safety

Audit READ-ONLY sur BIDS / raw. Aucune écriture events dans cette étape.
