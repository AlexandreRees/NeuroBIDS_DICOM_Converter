# Audit — `incoming/3-Movie_Data` (zip PC décompressé)

**Date:** 2026-07-29  
**Path:** `/home/alexrees/scratch/incoming/3-Movie_Data/3-Movie_Data/`  
**Mode:** READ ONLY

## Verdict

**Aucune information nouvelle pour reconstruire des `events.tsv` movie.**

Ce dépôt est un **paquet protocole** (scripts + clips + 1 `.mat` de test), **pas** une archive de résultats sujets. Le code est **identique** (SHA256) à celui déjà présent dans `raw_original` et déjà audité.

| Besoin pour `events.tsv` | Présent ici ? |
|---|---|
| Onset movie relatif au volume 1 (N ou timestamp) | **Non** |
| `triggerTimes` / VBL / Flip timestamps sauvegardés | **Non** |
| Logs run par sujet/session | **Non** (1 `.mat` test seulement) |
| Identité clip / œil (`run_id`, `change_eye`) | Oui (dans le code + `.mat` test) |
| Durée des clips MP4 | Oui (~196.82 s ≈ 210 × TR 0.937 s) |

## Contenu exact (tous les dossiers)

```
incoming/3-Movie_Data/
└── 3-Movie_Data/
    ├── main.m
    ├── Show_movie.m
    ├── Movie1A.mp4   (~196.82 s)
    ├── Movie1B.mp4   (~196.82 s)
    ├── Movie2A.mp4   (~196.82 s)
    ├── Movie2B.mp4   (~196.82 s)
    └── Results/
        └── July-05-2023_ 4-24-25_PM_Subject_is_t_selected_run_id_1.mat  (test, comment='t')
```

**7 fichiers au total.** Pas d’autres sous-dossiers, pas de CSV/TXT/log/physio/eyetracking.

## Code (comportement timing inchangé)

1. `main.m` fait `save(..._selected_run_id_*.mat)` **avant** `Show_movie` → le `.mat` ne peut contenir aucun timing de run.
2. `Show_movie.m` : écran d’attente → `PlayMovie` → `KbQueueWait` (un seul `t`) → boucle `GetMovieImage` / `Flip` **sans** capturer ni sauver les timestamps.
3. SHA256 `main.m` / `Show_movie.m` = copies `raw_original` (ex. SUBC01 session1).

## Unique `.mat` (test)

Variables : `answer`, `change_eye`, `comment`, `resultdir`, `run_id`, `t`, `x`, `y`  
→ **IDENTITY_ONLY**. Pas de `triggerTimes`, `vbl`, `onset`, etc.

## Implication durée MP4 ≈ longueur BOLD

Clips ≈ **196.82 s** ; BOLD movie typique **210 vol × 0.937 s ≈ 196.8 s**.  
Cela **ne donne pas** l’onset (où commence le film dans la série). Si des volumes « wait » existent au début de la même série, le film et l’acquisition se chevauchent partiellement — toujours sans N loggé.

## Conclusion

Même conclusion que `MOVIE_MISSING_INFO_FOR_EVENTS_AUDIT.md` : **events.tsv scanner-locked non faisables** à partir de cette archive. Rien à intégrer en BIDS events pour `task-movie`.
