# Captions — Functional MRI paradigm assets

**Provenance:** Methods draft section *Functional MRI paradigms*; `reports/functional_mri_paradigm_report.md`; MRI acquisition table.

## Table 1. Functional paradigm summary

`Table1_Functional_paradigm_summary.png` (also `.pdf`, `.tex`, `.md`, `.docx`)

**Caption.** Functional MRI paradigm summary. All BOLD runs share TR 937 ms, TE 37 ms, flip angle 52°, 2 mm isotropic voxels, and multiband acceleration factor 8. Durations are approximate (volumes × TR). Stimulation was monocular; the non-stimulated eye was occluded.

## Table 2. Movie run eye assignment

`Table2_Movie_run_eye_assignment.png` (also `.pdf`, `.tex`, `.md`, `.docx`)

**Caption.** Monocular movie-run assignment for `task-movie`. Each run presented one movie segment with a fixation overlay. Left- or right-eye stimulation was assigned by run; the contralateral eye was occluded. Stimulus timing files are not included in the public release.

## Figure 1. Block-design timeline (`task-fmri`)

`Figure1_task_fmri_block_design.png` (also `.svg`, `.pdf`)

**Caption.** Block-design structure of one `task-fmri` run. After an initial 10-TR baseline, 12 cycles of 8-TR stimulus presentation and 10-TR baseline were acquired (226 volumes; TR = 937 ms). Twelve stimulus conditions (`stim-01`–`stim-12`) encompassed magnocellular and parvocellular grating and checkerboard variants; stimulus order was randomised across subjects.

## Figure 2. Paradigm overview (publication redesign)

`Figure2_functional_paradigm_overview.png` (also `.svg`, `.pdf`; 600 dpi PNG)

**Generator.** `code/generate_publication_figure2.py` (Scientific Data illustration style; independent of the older auto-diagram builder).

**Caption.** Functional MRI protocol overview. (**A**) Complete session timeline from Session 1 through Session 2 (6-month follow-up), with proportional acquisition blocks, volumes, and approximate durations. (**B**) Resting-state paradigm (`task-rest`): monocular fixation on a grey field without visual stimulation (320 volumes; ≈5.0 min). (**C**) Naturalistic movie paradigm (`task-movie`): four runs (Movie 1A/2A/1B/2B; 210 volumes each) with left/right eye assignment. (**D**) Block-design visual stimulation (`task-fmri`): 10-TR baseline followed by 12 cycles of 8-TR stimulus / 10-TR baseline (226 volumes; stimulus conditions `stim-01`–`stim-12`; order randomised). Shared BOLD EPI: TR 937 ms, TE 37 ms, FA 52°, 2 mm isotropic, MB 8.

## Suggested placement in Methods

Place **Table 1** immediately after the introductory paragraph of *Functional MRI paradigms*.  
Place **Figure 1** (and optionally **Table 2**) with the `task-fmri` / `task-movie` subsections.  
Place **Figure 2** as the primary overview figure for the Functional MRI paradigms section.
