# Lab movie clips ↔ HCP 7T clip correspondence (for manuscript citation)

**Date:** 2026-08-31  
**HCP protocol page:** https://www.humanconnectome.org/hcp-protocols-ya-7t-imaging  
**Clip catalogue used for names/years/durations:** Finn & Bandettini (2021), *NeuroImage*, Table 1  
**Clip file names / Vimeo URLs:** `HCP_7T_Movie_Info.csv` (HCP wiki)

Do **not** equate laboratory BIDS labels `Movie1`–`Movie4` with HCP concatenations `7T_MOVIE1_CC1`–`7T_MOVIE4_HO2`. Those HCP files are ~15 min montages (several clips + 20 s REST cards + a shared Vimeo validation clip). Each laboratory file is one ~172 s picture excerpt, recoded to 800×600 / 60 fps and padded with black to 196.821 s (210 × TR 0.937 s).

## Correspondence (cite at clip level)

| Lab file | MATLAB `run_id` | BIDS ProtocolName / `movie_label` | Eye (default) | Matching HCP **clip** (Finn Table 1) | HCP **run** that contains that clip | HCP class | Evidence (do not put stills in the paper) | Cite as |
|---|---:|---|---|---|---|---|---|---|
| `Movie1A.mp4` | 1 | Movie1 | left | **garden** — *Mrs. Meyer’s Clean Day* (2013), 203 s in HCP | `7T_MOVIE3_CC2` | CC (Vimeo) | Cabbage/raised-bed gardening; storefront **PETERSON GARDEN PROJECT**; **Muller Meats** sign with Chicago phone **773-561-7580** and Lula Café awning (Logan Square) | Mrs. Meyer’s Clean Day (2013); HCP clip “garden” |
| `Movie1B.mp4` | 3 | Movie3 | right | **garden** — same work, **second excerpt** | `7T_MOVIE3_CC2` | CC (Vimeo) | Archival caption **“Peterson Ave just west of Artesian looking west towards Campbell, 1942”**; community-garden / shop interviews | Same title; second laboratory excerpt |
| `Movie2A.mp4` | 2 | Movie2 | right | **inception** — *Inception* (2010), 228 s in HCP | `7T_MOVIE2_HO1` | HO (Cutting et al. 2012) | Cobb (DiCaprio) & Ariadne (Page) at Paris café; awning text **BUSSY** (Café Debussy); cobblestone / Haussmann streets | *Inception* (Nolan, 2010); HCP clip “inception” |
| `Movie2B.mp4` | 4 | Movie4 | left | **inception** (bulk of the file) **and** a short **home alone** head | Inception lives in `7T_MOVIE2_HO1`; Home Alone lives in `7T_MOVIE4_HO2` | HO | t≈10–35 s: Kevin breakfast / McCallister kitchen (*Home Alone*, 1990). From t≈40 s: Ariadne in Paris, folding-city shot (*Inception*). **No** 20 s REST card between them (lab hard cut, not an HCP montage) | Cite *Inception* as the main excerpt; mention a brief opening excerpt from *Home Alone* (1990) if the PI confirms the breakfast/kitchen |

Vimeo ID for the garden documentary (HCP CSV): `http://vimeo.com/63405160` (`Mrs_Meyers_Clean_Day`). Hollywood rows in the CSV have feature-film frame ranges only (no public URL).

## What does **not** match (do not cite these as your stimuli)

| HCP clip (Finn Table 1) | HCP run | Why it is not a lab file |
|---|---|---|
| Two Men; Welcome to Bridgeville; Pockets; Inside the Human Body | MOVIE1 CC1 | Not seen. Bridgeville is Bridgeville, PA (Chevrolet); lab garden footage is **Chicago** (Peterson / Muller Meats 773). |
| The Social Network; Ocean’s Eleven | MOVIE2 HO1 | Not identified in the four lab files. |
| Off The Shelf (“flower”); 1212 (“hotel”); Northwest Passage (“dreary”); Vimeo test–retest montage | MOVIE3 / all runs | No REST cards, no flower-escape animation, no 1.5 s validation montage. |
| Erin Brockovich; The Empire Strikes Back | MOVIE4 HO2 | Not identified. Do not cite *Star Wars* from ambiguous interiors. |

Laboratory `Movie1`/`Movie3` are **not** HCP `MOVIE1`/`MOVIE3` concatenations. Laboratory `Movie2`/`Movie4` are **not** HCP `MOVIE2`/`MOVIE4` concatenations.

## Duration note (why these are related works, not drop-in HCP mp4s)

| Item | Duration |
|---|---|
| HCP *Mrs. Meyer’s Clean Day* clip | 203 s (3:23) of picture |
| HCP *Inception* clip | 228 s (3:48) of picture |
| HCP *Home Alone* clip | 234 s (3:54) of picture |
| Each lab file | ~10 s black + **~172 s picture** + ~15 s black = 196.821 s |

Two lab excerpts of the garden film (1A+1B) exceed one copy of the 203 s HCP window, so the laboratory likely used a longer *Grow Inspired* / Mrs. Meyer’s source, or two overlapping windows — not a bit-exact copy of `7T_MOVIE3_CC2`. *Inception* in 2A+2B similarly exceeds the 228 s HCP window. Cite the **works** and the HCP **clip names**, not “we presented HCP MOVIE3”.

## Suggested manuscript wording (English, Data in Brief)

**Stimuli (methods):**

> During `task-movie` runs, participants viewed one of four laboratory-prepared audiovisual excerpts (`Movie1A.mp4`, `Movie2A.mp4`, `Movie1B.mp4`, `Movie2B.mp4`; 196.8 s including leading/trailing black frames), presented monocularly as documented in `code/task-movie/`. These excerpts were drawn from the same source works catalogued as individual clips in the Human Connectome Project Young Adult 7T movie-watching task (Glasser et al.; protocol overview: https://www.humanconnectome.org/hcp-protocols-ya-7t-imaging; clip list: Finn and Bandettini, 2021, Table 1). They are **not** the HCP concatenated ~15 min `.mp4` runs. `Movie1A` and `Movie1B` are two excerpts from the independent documentary *Mrs. Meyer’s Clean Day* (2013; HCP clip “garden” in `7T_MOVIE3_CC2`; Vimeo 63405160). `Movie2A` and `Movie2B` are excerpts from *Inception* (Nolan, 2010; HCP clip “inception” in `7T_MOVIE2_HO1`, Hollywood clips after Cutting et al., 2012). `Movie2B` additionally opens with a brief excerpt matching *Home Alone* (1990; HCP clip “home alone” in `7T_MOVIE4_HO2`) before the *Inception* segment, without the 20 s rest cards used in the HCP montages. Stimulus video files are not redistributed (third-party copyright).

**References to include:**

- HCP 7T protocol overview (URL above) — CC vs HO classification.  
- Finn ES, Bandettini PA (2021). Movie-watching outperforms rest for functional connectivity-based prediction of behavior. *NeuroImage*. **Table 1** (clip short names, full titles, years).  
- Cutting et al. (2012), as cited by HCP for Hollywood excerpt preparation.  
- Original works: *Mrs. Meyer’s Clean Day* (2013); *Inception* (Warner Bros./Legendary/Syncopy, 2010); *Home Alone* (20th Century Fox, 1990) if the opening of `Movie2B` is kept in the sentence.

## PI check before locking Movie2B

Confirm on the stimulus PC that `Movie2B.mp4` really switches from the McCallister kitchen to Paris at ~t=40 s. If the opening is *not* *Home Alone*, drop that clause and cite only *Inception* for Movie2A/Movie2B.
