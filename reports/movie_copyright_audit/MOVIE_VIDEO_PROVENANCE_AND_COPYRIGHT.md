# Movie stimulus provenance and copyright audit

**Date:** 2026-08-27  
**Requested path (Windows stimulus PC):** `D:\3-Movie_Data\3-Movie_Data`  
**Audited copy on Narval:** `/lustre07/scratch/alexrees/incoming/3-Movie_Data/3-Movie_Data/`  
**Mode:** read-only. MP4s were **not** copied into `release_dataset/` or `paper/`. Identification frames were written only under `/tmp` and are not part of this report.

The `D:\` tree is not mounted on the cluster. File names, sizes, and MATLAB scripts on the incoming copy match the earlier inventory in `reports/movie_events_audit/INCOMING_3_MOVIE_DATA_AUDIT.md`.

## Verdict

The four clips are **laboratory recodes** (Adobe Premiere Pro → Adobe Media Encoder 2022, Windows account `labuser`, 11–18 December 2022) of **third-party audiovisual works**, cut and padded to **196.821333 s** so that clip length matches 210 movie BOLD volumes × TR 0.937 s.

Container metadata contain **no title, artist, or copyright tag**. Identification is from (1) encode/XMP provenance, (2) luminance structure, and (3) distinctive on-screen text / iconic shots.

| File | Visual identification | Confidence | Likely rights holder |
|---|---|---|---|
| `Movie1A.mp4` | Chicago **Peterson Garden Project** short (Mrs. Meyer’s Clean Day / *Grow Inspired* garden documentary; same work HCP lists as `Mrs_Meyers_Clean_Day`, Vimeo `63405160`) | **High** (storefront lettering “PETERSON GARDEN PROJECT”; cabbage / harvest / raised-bed gardening throughout) | Mrs. Meyer’s Clean Day / The Caldrea Company (SC Johnson); commissioned branded film — **not** a lab original |
| `Movie1B.mp4` | Same **Chicago urban-garden / community** documentary family (lower-third “MULLER / Butcher, Muller Meats”; community garden; Lincoln Avenue landmarks including The Stars Motel / Tamara’s Donuts) | **High** that it is third-party documentary; **medium** that it is a second excerpt of the same Mrs. Meyer’s short vs another *Grow Inspired* episode | Same branded/documentary rights as Movie1A unless PI confirms a different CC Vimeo short |
| `Movie2A.mp4` | ***Inception* (2010)** — Cobb & Ariadne walking Paris; cobblestone / Haussmann streets | **High** | Warner Bros. Entertainment / Legendary Pictures / Syncopy |
| `Movie2B.mp4` | Iconic ***Inception*** Paris “folding city” from ~t=45 s; opening ~20 s of picture also matches ***Home Alone* (1990)** breakfast (Kevin, plaid pyjamas, red bowl) | **High** for Inception in the middle of the file; **medium** that the opening is a hard-cut *Home Alone* excerpt rather than a look-alike | Warner Bros. (Inception); if the opening is *Home Alone*, 20th Century Studios / Disney |

These titles overlap the **HCP 7T movie-watching** stimulus list (Finn & Bandettini 2021; `HCP_7T_Movie_Info.csv`), but the files are **not** unmodified HCP concatenations: each file is a single ~172 s picture segment with lab-added black leader/trailer, recoded to **800×600 @ 60 fps** for the stimulus display (`Show_movie.m` uses 800 px = 30° FOV).

**Public release policy is correct:** do not redistribute the MP4s. MATLAB protocol code and timing metadata may stay under `code/task-movie/`.

This is a technical provenance note, not legal advice.

## Folder contents (7 files)

```
incoming/3-Movie_Data/3-Movie_Data/
├── main.m
├── Show_movie.m
├── Movie1A.mp4
├── Movie1B.mp4
├── Movie2A.mp4
├── Movie2B.mp4
└── Results/
    └── July-05-2023_ 4-24-25_PM_Subject_is_t_selected_run_id_1.mat   # test only
```

MATLAB comments name only `Movie1A.mp4` … `Movie2B.mp4`. They do **not** name commercial titles. Operators are allowed to change “the path and name of the movies”.

## Technical provenance (identical pattern on all four)

| Property | Value |
|---|---|
| Container | `mp42` / `mp42mp41` |
| Video | H.264 High, 800×600, yuv420p, **60 fps**, 11808 frames, ~196.80 s |
| Audio | AAC-LC, 48 kHz, stereo |
| Handler | Mainconcept (Adobe) Video / Sound Media Handler |
| `creation_time` | 2022-12-18 (UTC): 1A 13:35:09; 2A 13:44:21; 2B 13:44:35; 1B 13:51:23 |
| Encoder | **Adobe Media Encoder 2022.0 (Windows)** |
| Nested history | Premiere/AME jobs also on **2022-12-11** |
| Premiere projects | `C:\Users\labuser\Desktop\tqm-worker\output\cr_project_<uuid>.prproj` (unique UUID per encode; `tqm-worker` = AME/Team queue worker) |
| Title / copyright tags | **Absent** (`dc:title`, `xmpRights`, `copyright` not present) |

SHA256:

| File | SHA256 | Bytes |
|---|---|---:|
| Movie1A.mp4 | `3f3b8c6e6fb477a34fdb1d1a8c77d0c267bd60122b30b6b8493d0ba997d74d20` | 183368517 |
| Movie1B.mp4 | `2782a0661439c6116ef98de3ab3572b0490b384f9826c625a5c435696d2a30cf` | 181514135 |
| Movie2A.mp4 | `de37a4c26cc19de10429fa50c56fb2f28b2bdc5159c8f339b8880fd527b998c7` | 178229515 |
| Movie2B.mp4 | `b6b23fcce6cfde874b41e68380d861420eabdd832bd98da7209cef506019fa29` | 173312179 |

## Temporal structure (all four files)

Mean luminance at 1 fps:

- **t = 0–9 s:** black leader  
- **t ≈ 10–181 s:** picture (~**172 s** of stimulus)  
- **t = 182–196 s:** black trailer  

No mid-file rest/black gap (unlike HCP 7T runs, which insert ~20 s rest between concatenated clips). Duration **196.821333 s** matches the archived ffprobe value used in `task-movie` events (`210 × 0.937 s = 196.770 s`, Δ ≈ 51 ms).

Interpretation: the lab **trimmed** source excerpts and **padded with black** so that one movie file equals one movie BOLD run.

## How titles were identified

Filenames and ffprobe/XMP do not name the films. Identification used stills after the black leader (t ≈ 12, 30, 45, 60, 90, 120, 150, 175 s).

**Movie1A — Peterson Garden Project / Mrs. Meyer’s Clean Day**

- Continuous gardening footage (cabbage close-up, raised beds, harvest).  
- At t ≈ 60 s, window lettering **PETERSON / GARDEN / PROJECT** (Chicago nonprofit).  
- LaManda Joy (Peterson Garden Project founder) was featured in the **Mrs. Meyer’s Clean Day *Grow Inspired*** film series.  
- HCP 7T MOVIE3 lists `Mrs_Meyers_Clean_Day` (203 s / 03:23 in Finn & Bandettini 2021) with Vimeo `http://vimeo.com/63405160`. Lab content is shorter (172 s picture), consistent with a trim plus black pad, not with copying the full ~15 min HCP `7T_MOVIE3_CC2` concatenation.

**Movie1B — same documentary family**

- Lower-third **MULLER / Butcher, Muller Meats**.  
- Urban community garden; Chicago street furniture (The Stars Motel, Tamara’s Donuts on Lincoln Avenue).  
- Watering tomato plants (t ≈ 60 s).  
- No mid-clip black, so this is one documentary excerpt, not a Hollywood mashup.

**Movie2A — *Inception* (2010)**

- Multiple times: Leonardo DiCaprio (Cobb) and Elliot Page (Ariadne) walking Paris cobblestones / Haussmann streets (the dream-architecture tutorial). Matches HCP MOVIE2 clip description: “Two characters explore a dream world…”.

**Movie2B — *Inception* (fold) ± possible *Home Alone* head**

- t ≈ 45–60 s: the **folding Paris** shot (unambiguous *Inception*).  
- t ≈ 12–30 s: child in plaid pyjamas at a breakfast table with a red bowl and floral wallpaper, matching *Home Alone* (Kevin). There is **no black gap** between those sections, so either the lab hard-cut two Hollywood excerpts into one 172 s file, or the breakfast ID should be confirmed by the PI against the stimulus PC original.

HCP never concatenates *Home Alone* and *Inception* inside one 3-minute file (they live in MOVIE4 vs MOVIE2). If both IDs are correct, this is a **lab-specific edit**, not a copy of an HCP mp4.

## Copyright implications

1. **No licence travels with the files.** AME/XMP history documents *how* they were transcoded, not *who* owns the pictures.  
2. **Hollywood (*Inception*, and *Home Alone* if confirmed)** remains with the studios. Research viewing during a consented scan does not create a right to put the MP4s on OpenNeuro / in the Data in Brief package. HCP itself distributes 7T movie mp4s only via ConnectomeDB under HCP terms and still treats Hollywood clips as third-party content (Cutting et al. excerpts).  
3. **Mrs. Meyer’s / Peterson Garden Project** is a **brand-commissioned** short. HCP grouped the Vimeo file with “Creative Commons” MOVIE3 clips; that classification should **not** be copied blindly:
   - CC, if still attached on Vimeo, is a licence of the **uploader’s** file, not of this 800×600 60 fps derivative;
   - brand and talent rights can survive a CC badge;
   - current Vimeo page/licence was not re-verified here (Vimeo served a bot check).  
4. **Paper wording** in `paper/sections/10_usage_notes.tex` (“Movie stimulus video files are not redistributed (third-party copyright)”) is appropriate for **all four** files. Do not split the public package into “CC MP4s + withheld Hollywood” without a written licence check.  
5. If the manuscript **names** the films, confirm titles with the PI (especially Movie2B). Naming a film for scientific description is not the same as redistributing the clip.

## What was not found

- Original commercial filenames, ISRC, studio copyright strings, or chapter titles in the MP4s.  
- A licence PDF, README, or purchase record in `3-Movie_Data`.  
- Evidence that these files are lab-original cinematography.  
- The Windows `D:\` disk itself (only the previously ingested zip copy).

## What the HCP 7T protocol page actually licenses

Source: [HCP 7T Imaging Protocol Overview](https://www.humanconnectome.org/hcp-protocols-ya-7t-imaging) (retrieved 2026-08-31).

That page **classifies** the 7T movie stimuli; it does **not** publish a redistribution licence for the compiled `.mp4` files.

Quoted policy on the page:

- Clips are “short (ranging from 1 to 4.3 minutes) independent film and Hollywood movie excerpts concatenated into .mp4 files of 11.9–13.7 minutes”, plus a shared Vimeo repeat-validation clip.
- **CC** (`7T_MOVIE1_CC1`, `7T_MOVIE3_CC2`): “movies composed of clips of freely available independent films under Creative Commons licensing”.
- **HO** (`7T_MOVIE2_HO1`, `7T_MOVIE4_HO2`): “clips from Hollywood movies as prepared and published by Cutting et al. 2012”.
- Stimulus files are named like the scans. Two encode versions exist (pre/post 2014-08-21).

What the page does **not** say:

- No studio names, no CC deed (CC BY, CC0, …), no permission to deposit the mp4s on OpenNeuro or in a journal supplement.
- The promised subsection “Movie watching stimuli and experimental details below” is **not present** on the current page (broken/missing).
- Clip-level URLs live elsewhere (`HCP_7T_Movie_Info.csv`): Vimeo links for CC shorts only; Hollywood rows have frame ranges in the feature, **no public URL**.

How HCP actually distributes the videos (mailing list / ConnectomeDB, not this protocol page): registered users can download `movie_stimulus.zip` from the S1200 project. That is access under HCP procedures, not a transfer of Hollywood copyright.

The WU-Minn [Open Access Data Use Terms](https://www.humanconnectome.org/storage/app/media/data_use_terms/DataUseTerms-HCP-Open-Access-26Apr2013.pdf) govern **participant imaging/behavioural data** (no re-identification; redistribution of *those* data under the same terms; required acknowledgement). They are not a licence to republish *Inception* or other studio excerpts.

Finn & Bandettini (2021) restate the same split: MOVIE1/3 = independent films “freely available under a Creative Commons license on Vimeo”; MOVIE2/4 = Hollywood.

Implication for this laboratory package: even if Movie1* overlap the HCP CC list and Movie2* overlap the HCP HO list, the HCP protocol page does **not** authorize putting the lab’s recoded 800×600 files in the public BIDS release.

## References used for identification

- Finn ES, Bandettini PA (2021). Movie-watching outperforms rest for functional connectivity-based prediction of behavior. *NeuroImage*. HCP clip table (Mrs. Meyer’s Clean Day; Inception; Home Alone; Ocean’s Eleven; Empire Strikes Back).  
- HCP `HCP_7T_Movie_Info.csv` (wiki copy): `Mrs_Meyers_Clean_Day` → `http://vimeo.com/63405160`; Hollywood clips listed without public URLs (`Inception_1`, `Home_Alone_1`, …).  
- HCP 7T protocol overview: CC vs HO (Cutting et al.) concatenations of 11.9–13.7 min — **not** the duration of these four files.  
- Peterson Garden Project / LaManda Joy featured in Mrs. Meyer’s *Grow Inspired* series (author bio; Chicago garden storefront on the clip).
