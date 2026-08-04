# Methods — Functional MRI acquisition (draft)

**Status:** draft text for *Scientific Data* Data Descriptor Methods  
**Date:** 23 July 2026  
**Provenance:** `reports/functional_mri_paradigm_report.md`, MRI acquisition table, Methods/Data Record drafts  
**Note:** Sequence parameters are intended to live in the MRI acquisition table (Table X); this subsection focuses on paradigm content.

---

## Manuscript text (for submission)

**Functional MRI.**

BOLD data were acquired with a shared multiband EPI prescription (sequence family `epfid2d1_104`; multiband acceleration factor 8 in sampled sidecars). Representative TR, TE, flip angle, voxel size, and volume counts are summarised in Table X; matching single-band reference (SBRef) series were acquired with the BOLD runs. Visual stimuli were presented with Psychtoolbox scripts synchronised to the scanner trigger (FORP key `t`). Functional runs used monocular stimulation: the stimulated eye received the visual display and fixation, and the non-stimulated eye was blanked.

Within a typical session, four visually driven task runs (`task-fmri`; 226 volumes each), four movie-viewing runs (`task-movie`; 210 volumes each), one resting-state run (`task-rest`; 320 volumes), and short control EPI runs (`task-control`; 20 volumes) were acquired. Spin-echo EPI field maps in opposing phase-encode directions (AP/PA) were collected for susceptibility distortion correction (Table X).

For `task-fmri`, participants viewed a TR-locked block design comprising an initial baseline period (10 TRs) followed by 12 cycles of stimulus (8 TRs) and baseline (10 TRs). Stimulus materials included twelve grating/checkerboard conditions spanning magno- and parvo-biased variants (`stim-01`–`stim-12` in released event tables). Run order and stimulated eye were assigned according to the visit stimulus configuration. Verified `*_events.tsv` files are released only for a subset of `task-fmri` runs with a uniquely verified protocol-to-BOLD mapping; remaining task runs lack event tables in the present release.

For `task-movie`, each of the four runs presented one of four movie segments (`Movie1A`, `Movie2A`, `Movie1B`, `Movie2B`) with a fixation overlay, with left- or right-eye stimulation assigned by run. For `task-rest`, participants maintained monocular fixation on a gray background without stimulus blocks. Short `task-control` EPI runs were acquired with the same EPI geometry; stimulus content for these control runs is not documented in the available stimulus scripts. Event onset tables for movie and control runs are not distributed.

---

## Author notes (not for submission)

1. Replace `Table X` with the final MRI acquisition table number.
2. Keep `stim-01`–`stim-12` mapping cautious until a verified data dictionary is added (see Data Record draft).
3. Align event-file counts with Data Record / Technical Validation before submission.
