# Audit des 51 runs task-fMRI irrécupérables

**Date:** 2026-07-23  
**Contexte:** Après Phase 2 (toutes cohortes), **456 / 507** runs ont des `events.tsv` (**89.94%**). Restent **51** runs sans events.  
**Politique:** aucun timing inventé, interpolé ou assigné par heuristique ambiguë.  
**Sources:** `phase2_remaining_missing.tsv`, sidecars BIDS, `session_mapping`, Results MATLAB sur `/project/def-amirs/raw_original`.

---

## Verdict en une phrase

Ces 51 runs ne sont **pas** bloqués par un bug de cohorte : pour chacun, soit les sources MATLAB manquent vraiment, soit elles existent mais **ne peuvent pas être reliées de façon unique** à un seul BOLD (ProtocolName dupliqué, `scan_info` dupliqué/absent, ou numéro fMRI MATLAB ≠ ProtocolName BIDS).

---

## Tableau synthétique

| Classe | N runs | Sessions | Peut-on reconstruire les onsets ? | Peut-on les attacher au bon BOLD ? |
|---|---:|---:|---|---|
| **B. ProtocolName dupliqué** | **32** | 13 | Oui (souvent) | **Non** — 2 BOLD pour le même `fMRI_N` |
| **A. Pas de Results grating** | **8** | 2 | **Non** | Non |
| **E. `scan_info` dupliqué** | **5** | 4 | Ambigu | Non sans arbitrage |
| **D. `scan_info` absent** | **4** | 2 | **Non** (pas de `triggerTimes`) | — |
| **C. Numéro fMRI MATLAB ≠ ProtocolName** | **2** | 1 | Oui (fMRI 5/6) | **Non** — BOLD labelés `fMRI3/4_AP` |
| **Total** | **51** | 21 | | |

| Cohorte | Remaining |
|---|---:|
| Control | 43 |
| Glaucoma | 6 |
| DataON | 2 |
| DataTON | 0 |

---

## Classe A — Pas de Results grating (8 runs)

**Définition:** le dossier de visite mappé à la session BIDS ne contient aucun `2-Grating/Results` (ni rescue daté unique). Sans `scan_info.triggerTimes` ni ordre de stimuli, la reconstruction est impossible.

### `sub-051` / `ses-01` (Control, SUBC052) — 4 runs

| Run | ProtocolName |
|---:|---|
| 01 | fMRI3_AP |
| 03 | fMRI4_AP |
| 05 | fMRI1_AP |
| 07 | fMRI2_AP |

**Pourquoi irrécupérable:**

- Visite mappée: `/project/def-amirs/raw_original/Control/SUBC52_SESSION01_2024NOV05` (date `20241105`).
- Contenu disque: DICOM + peripheral uniquement.
- **Aucun** dossier `2-Grating/Results`, aucun `scan_info`, aucun `fMRI_N.mat`.
- Rescue par date: aucun Results d’une autre visite du même sujet daté du `20241105`.

**Conclusion:** trou d’archive vrai (timing stimulus jamais sauvegardé / jamais déposé). Inventer des onsets violerait les standards Scientific Data.

### `sub-078` / `ses-01` (Glaucoma, SUBG13) — 4 runs

| Run | ProtocolName |
|---:|---|
| 01 | fMRI3_AP |
| 03 | fMRI4_AP |
| 05 | fMRI1_AP |
| 07 | fMRI2_AP |

**Pourquoi irrécupérable:**

- BIDS `ses-01` mappe vers `.../SUBG13-Session1-2024NOV25` (acquisition ~`20241125`).
- Cette visite: imaging + peripheral **sans** MATLAB grating.
- Des Results **existent** sous `.../SUBG13_SESSION02_2025MAY22/.../2-Grating/Results` (date ~`20250522`).
- Relier le MATLAB de mai 2025 au BOLD de novembre 2024 serait un **appariement inter-visites / inter-dates** — refusé (pas unique, pas justifié par `acquisition_date`).

**Conclusion:** pas un oubli de pipeline; c’est une incohérence visite BIDS ↔ MATLAB. Sans preuve d’identité de session (même date), on ne peut pas attacher.

---

## Classe B — ProtocolName BIDS dupliqué (32 runs) — cause dominante

**Définition:** le timing MATLAB pour un `fMRI_number` est souvent **reconstructible**, mais **deux** (ou plus) sidecars BOLD non-phase dans la même session portent le même numéro de protocole (`fMRI1_AP`, `fMRI4_AP`, parfois `fMRI1_AP` + `fMRI1_AP_Rerun`). La règle stricte exige **exactement un** match → refus.

**Exemple type — `sub-002/ses-01`:**

| BIDS run | ProtocolName | Events |
|---:|---|---|
| 01 | fMRI2_AP | présent |
| 03 | fMRI3_AP | présent |
| 05 | fMRI4_AP | présent |
| **07** | **fMRI1_AP** | **absent** |
| **09** | **fMRI1_AP** | **absent** |

- Un seul `scan_info` `fmri_number_is1` existe et produit des events valides.
- Impossible de savoir **sans arbitrage manuel** s’il appartient à `run-07` ou `run-09` (souvent original vs redo/rerun).

**Même logique pour:**

| Session | Runs manquants | Protocole(s) en collision |
|---|---|---|
| `sub-002/ses-01` | 07, 09 | fMRI1_AP ×2 |
| `sub-011/ses-01` | 03, 05 | fMRI4_AP ×2 |
| `sub-012/ses-01` | 03, 05 | fMRI4_AP ×2 |
| `sub-016/ses-02` | 07, 09 | fMRI1_AP ×2 |
| `sub-023/ses-01` | 07, 09 | fMRI1_AP ×2 |
| `sub-024/ses-02` | 01, 03, 07, 11 | fMRI1 + fMRI1_Rerun; fMRI2 + fMRI2_Rerun |
| `sub-025/ses-01` | 07, 09 | fMRI1_AP ×2 |
| `sub-038/ses-02` | 02, 04 | fMRI3_AP ×2 |
| `sub-040/ses-01` | 07, 09 | fMRI1_AP ×2 |
| `sub-043/ses-02` | 01,02,05,06,11,12 | fMRI2/3/4 chacun ×2 |
| `sub-046/ses-01` | 07, 09 | fMRI1_AP ×2 |
| `sub-061/ses-01` (DataON) | 05, 07 | fMRI1_AP ×2 |
| `sub-083/ses-01` (Glaucoma) | 07, 09 | fMRI1_AP ×2 |

**Pourquoi on ne “choisit” pas le plus tôt / le Rerun:**  
choisir original vs redo sans journal opérateur unique = **devinette**. Ce n’est pas publication-grade.

**Ce qu’il faudrait pour récupérer (hors scope auto):**  
table manuelle `fmri_number → bids_run` (ou exclusion explicite d’un des deux BOLD), documentée dans le manuscrit.

---

## Classe C — Numéro MATLAB ≠ ProtocolName BIDS (2 runs)

### `sub-032/ses-01` (Control, SUBC033) — runs 01 & 03

| BIDS run | ProtocolName | Events |
|---:|---|---|
| 01 | fMRI3_AP | **absent** |
| 03 | fMRI4_AP | **absent** |
| 05 | fMRI1_AP | présent (MATLAB fMRI 1) |
| 07 | fMRI2_AP | présent (MATLAB fMRI 2) |

**Sources MATLAB présentes:** `fmri_number` **1, 2, 5, 6** (pas 3 ni 4).

| MATLAB fMRI# | Statut Phase 2 |
|---:|---|
| 1 | events déjà présents |
| 2 | events déjà présents |
| **5** | timing OK, **aucun** BOLD `ProtocolName` contenant 5 |
| **6** | timing OK, **aucun** BOLD `ProtocolName` contenant 6 |

**Pourquoi irrécupérable automatiquement:**  
Les BOLD manquants s’appellent `fMRI3_AP` / `fMRI4_AP`, alors que les seuls `scan_info` restants sont numérotés **5** et **6**. Les mapper 5→3 et 6→4 serait une hypothèse d’opérateur (renommage / compteur de runs), pas une preuve dans les métadonnées.

---

## Classe D — `scan_info` / `triggerTimes` absents (4 runs)

Sans `triggerTimes` mesurés, on refuse tout fallback TR.

### `sub-047/ses-01` (Control, SUBC048) — runs 01, 05, 07

- Results existent: `fMRI_1.mat` … `fMRI_4.mat` + `runs_random.mat`.
- **Aucun** fichier `*scan_info*` dans Results.
- Donc: ordre de stimuli oui, **onsets scanner non**.

### `sub-013/ses-01` run-07 (`fMRI2_AP`)

- Deux copies imbriquées de Results (dossier MATLAB dupliqué).
- `scan_info` présents pour fMRI **1, 3, 4** seulement — **pas de `scan_info` pour fMRI 2**.
- `fMRI_2.mat` (stim order) existe, mais sans triggers → irrécupérable pour ce run.
- (Les autres runs de cette session ont déjà des events d’une passe antérieure / autre chemin.)

---

## Classe E — `scan_info` dupliqué pour le même `fMRI_number` (5 runs)

**Définition:** plusieurs fichiers `scan_info` portent le même `fmri_number_isN` (souvent tentative + redo). Même après filtre `acquisition_date`, la cardinalité reste `scan>1` → pas de triplet unique.

| Session | Run(s) | Détail |
|---|---|---|
| `sub-011/ses-01` | 07 | `fMRI1_AP`; `scan=2, stim=1` |
| `sub-011/ses-02` | 06 | `fMRI1_AP`; `scan=2, stim=1` |
| `sub-020/ses-01` | 05 | `fMRI1_AP`; `scan=2, stim=1` |
| `sub-041/ses-01` | 07, 09 | `fMRI1_AP` + `fMRI1_AP_REDO`; `scan=2` — collision BOLD **et** scan_info |

**Pourquoi irrécupérable:** deux jeux de `triggerTimes` candidats; en choisir un sans journal = inventer l’appariement.

---

## Ce qui n’est **pas** la cause

- Pas un oubli DataON / Glaucoma / DataTON en général (ces cohortes sont largement couvertes: DataTON 100%, DataON 23/25, Glaucoma 71/77).
- Pas l’absence totale de design de paradigme (le design canonique `presentStimParams.m` est connu).
- Pas un refus arbitraire quand le mapping est unique (Phase 2 a écrit **106** nouveaux events dès que unique).

---

## Hiérarchie de “récupérabilité humaine” (si arbitrage manuel futur)

| Priorité | Classe | N | Condition pour débloquer |
|---|---|---:|---|
| 1 | B — ProtocolName dupliqué | 32 | Table manuelle run↔fMRI_number ou exclusion d’un BOLD redo |
| 2 | E — scan_info dupliqué | 5 | Identifier quel `scan_info` est le run valide |
| 3 | C — numérotation 5/6 vs 3/4 | 2 | Preuve opérateur que fMRI5/6 = séries fMRI3/4 |
| 4 | D — pas de triggers | 4 | **Impossible** sans nouvelles données |
| 5 | A — pas de Results | 8 | **Impossible** sans retrouver les `.mat` |

Les classes **A** et **D** (12 runs) sont des **impossibilités physiques** dans l’archive actuelle.  
Les classes **B**, **C**, **E** (39 runs) sont des **impossibilités d’appariement unique** — le timing existe souvent, mais l’attache BIDS n’est pas déterministe.

---

## `sub-051` n’est pas le seul cas impossible

| | Runs |
|---|---:|
| `sub-051` seul | 4 |
| Autres gaps archive (A+D hors 051) | 8 |
| Appariements non uniques (B+C+E) | 39 |
| **Total remaining** | **51** |

---

## Livrables

| Fichier | Rôle |
|---|---|
| `reports/stimulus_audit/IRRECOVERABLE_EVENTS_AUDIT.md` | Ce rapport |
| `reports/stimulus_audit/irrecoverable_events_audit.tsv` | Une ligne par run + classe |
| `reports/stimulus_audit/phase2_remaining_missing.tsv` | Raisons pipeline brutes |
