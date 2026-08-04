# Audit — information manquante pour reconstruire `events.tsv` Movie fMRI

**Date:** 2026-07-28  
**Contexte opérateur:** *« avant que le film ne commence il y a une acquisition de quelques volumes, puis le movie commence »*  
**Scope:** MATLAB `3-Movie_Data` / `Movie_Data`, DICOM/BIDS `task-movie`, physio associées  
**Mode:** READ ONLY

---

## Verdict

**Reconstruction BIDS `events.tsv` scanner-locked : NON FAISABLE** avec les archives actuelles.

| Ce qu’on a | Ce qui manque pour un onset fiable |
|---|---|
| Identité du clip (`run_id` → Movie1A/2A/1B/2B) | Instant du **premier `t` accepté** relatif au volume 1 |
| Mapping œil (`change_eye`) | Nombre **N** de volumes « pre-movie » (dummy / wait) |
| BOLD 210 vol @ TR 0.937 s | `triggerTimes` / VBL / timestamps de frames **sauvegardés** |
| Physio `trigger` parfois présente (horloge volumes) | Lien IRM↔stimulus (onset movie ↔ SeriesTime / vol index) |

Sans **N** (ou un timestamp absolu du 1er trigger MATLAB), inventer `onset = N×TR` serait **synthétique** et non traçable — exclu pour publication.

---

## 1. Séquence réelle (code + pratique scanner)

### `main.m`

1. Dialogue `run_id` + initiales  
2. **`save(..._selected_run_id_*.mat)` AVANT** `Show_movie` → le `.mat` ne peut contenir aucun timing de run  
3. Appelle `Show_movie(moviename, eye)`

### `Show_movie.m` (ordre critique)

```
Flip écran « The experiment will start shortly »
OpenMovie → PlayMovie(movie, 1)     ← moteur démarré
KbQueueStart / KbQueueWait('t')     ← attend LE premier t
while GetMovieImage → Draw → Flip    ← affichage frames
```

Conséquences :

- MATLAB attend **un seul** `t` (pas une boucle « ignorer N triggers »).
- Les « quelques volumes » avant le film = volumes acquis **pendant** l’écran d’attente / avant le premier `t` vu par `KbQueueWait`.
- **N n’est pas fixe dans le code** : il dépend du moment où l’opérateur lance la séquence vs où MATLAB atteint `KbQueueWait`.
- Aucune valeur de retour de `Screen('Flip')` n’est capturée (`vbl` non assigné).
- Aucun `save` de timing en fin de run.

### Interprétation de votre observation

Oui : typiquement  
`volumes 1…N` = fixation / wait (pas encore de film affiché)  
`volume N+1…` ≈ début effectif du movie après le premier `t`.

Mais **N n’est nulle part dans les `.mat` ni dans les DICOM tags** comme métadonnée d’événement.

---

## 2. Contenu exact des `.mat` Movie (550 fichiers)

**Classification : 100 % `IDENTITY_ONLY`** (0 / 550 reconstructibles).

### Présent (identité)

| Variable | Rôle |
|---|---|
| `run_id` | 1–4 → clip / œil |
| `change_eye` | mapping œil |
| `comment` | initiales sujet |
| `answer` | checklist Yes/No |
| `t` | *datestr* wall-clock du **save pre-run**, pas un trigger |
| `resultdir`, `x`, `y`, … | UI / chemins |

### Absent (cherché dans les 550, trouvé 0 fois)

| Variable / donnée | Pourquoi indispensable |
|---|---|
| `triggerTimes` | horodatage des `t` scanner (comme Grating) |
| `vbl` / Flip timestamps | onset d’affichage relatif |
| `frameTimes` / `timestamps` / `onset` | table frame↔temps |
| Index volume du 1er frame affiché | ancrage BOLD |
| `N_dummy` / `n_volumes_before_movie` | vos « quelques volumes » |
| Durée / fps **mesurés** et sauvés | `movieduration`/`fps` PTB non persistés |

### Autres fichiers MATLAB Movie

| Source | N | Timing utilisable ? |
|---|---:|---|
| `output.txt` (diary) | 129 | Non — warnings PTB seulement, 0 ligne `triggerTimes` |
| `.mp4` | 104 | Media seulement |
| `main.m` / `Show_movie.m` | protocol | Décrivent le wait, **ne loggent pas** |

---

## 3. Ce que donnent DICOM / BIDS Movie

| Élément | Disponible | Suffit pour events ? |
|---|---|---|
| Séries `Movie1/2/3/4_AP` | Oui | Non |
| Volumes typiques | **210** | Non (≠ table d’événements) |
| TR | **0.937 s** | Non seul |
| `SeriesTime` / `AcquisitionTime` | Parfois | Début **série**, pas onset movie |
| `SeriesNumber`, `ProtocolName` | Oui | Identité run seulement |
| ImageType mag/phase | Oui | Exclusion phase ok ; pas d’onset |

**BOLD Movie magnitude dans BIDS :** 536 runs, **0** `events.tsv`.

DICOM donne l’horloge d’acquisition des volumes, **pas** l’instant où Psychtoolbox a passé `KbQueueWait` ni le premier `Flip` du film.

---

## 4. Physio / triggers scanner

Audit physio Movie (`MOVIE_PHYSIO_TRIGGER_AUDIT.tsv`) :

| Interprétation | n |
|---|---:|
| Physio only (cardiac/resp) | 853 |
| Canal `trigger` possible (horloge volumes) | 432 |

Même avec canal EXT/`trigger` :

- on peut recaler les **volumes** ;
- on **ne peut pas** savoir à quel pulse le movie a démarré sans le log MATLAB du 1er `t` accepté ou un N constant documenté et vérifié.

Verdict physio : *« scanner trigger source possible but stimulus onset unavailable »*.

---

## 5. Checklist — ce qu’il faudrait archiver pour reconstruire

Pour un futur protocole (ou une récupération exceptionnelle), **minimum** :

1. **`triggerTimes`** (tous les `t`, ou au moins le premier accepté) avec horloge PTB  
2. **`movie_onset_vbl`** = timestamp du premier `Screen('Flip')` post-trigger  
3. **`n_triggers_ignored`** ou **`first_movie_volume_index`** (= N+1)  
4. Optionnel mais utile : `fps`, `movieduration`, `frame_index_at_start`  
5. Sauver le `.mat` **après** le run (pas seulement avant `Show_movie`)

Équivalent events.tsv minimal alors possible :

| onset | duration | trial_type |
|---|---|---|
| `N * TR` (si N connu et constant) **ou** `(movie_onset − series_start)` | durée clip | `movie` / nom du clip |
| 0 … `N*TR` | … | `wait` / `dummy` (optionnel) |

Aujourd’hui : **aucun des champs 1–3 n’existe sur disque**.

---

## 6. Ce qui est déjà récupérable (sans events timing)

Déjà dans `code/task-movie/` :

| `run_id` | Stimulus | Label BIDS-ish | Œil |
|---:|---|---|---|
| 1 | Movie1A.mp4 | Movie1 | left |
| 2 | Movie2A.mp4 | Movie2 | right |
| 3 | Movie1B.mp4 | Movie3 | right |
| 4 | Movie2B.mp4 | Movie4 | left |

→ mapping **identité** run↔clip↔œil OK pour README / sourcedata.  
→ **pas** d’`events.tsv` onset.

---

## 7. Recommandation publication

1. Publier BOLD Movie **sans** `events.tsv`.  
2. Fournir protocol `.m` + dictionnaire clip/œil.  
3. Documenter explicitement : *pre-movie volumes exist but N not logged; no scanner-locked onsets archived*.  
4. **Ne pas** synthétiser `onset = k×TR` sans preuve de k.

---

## Fichiers d’appui (audits existants)

- `reports/movie_events_audit/code_timing_audit/MOVIE_EVENTS_FEASIBILITY_FINAL_REPORT.md`
- `reports/movie_events_audit/code_timing_audit/SHOW_MOVIE_TIMING_ANALYSIS.md`
- `reports/movie_events_audit/code_timing_audit/MOVIE_MAT_VARIABLE_TIMING_INVENTORY.tsv`
- `reports/movie_events_audit/code_timing_audit/MOVIE_PHYSIO_TRIGGER_AUDIT.tsv`
- `code/task-movie/task-movie_run_dictionary.tsv`
