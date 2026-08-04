# Background & Summary (Data Descriptor draft)

**Status:** descriptive draft for *Scientific Data*  
**Date:** 23 July 2026  
**Provenance:** study consent/protocol text (Protocol 2020-5879), BIDS inventory, participant summary tables, and existing Methods/Data Record drafts  
**Policy:** no subjective novelty/impact claims; unverified prior publications not invented

---

## Manuscript text (for submission)

### Background & Summary

Damage to the optic nerve—whether from trauma, inflammatory demyelination, or progressive neurodegenerative disease—interrupts visual input to the brain and can produce lasting changes in visual pathway structure and function. Clinical assessment of optic neuropathy remains incomplete with respect to the spatial distribution of injury, the downstream consequences for cortical visual processing, and the anatomical predictors of recovery or decline over time. Multimodal magnetic resonance imaging (MRI) provides complementary measures of brain and optic-pathway anatomy, white-matter microstructure, and haemodynamic responses at rest and during visual stimulation, and therefore offers a practical route to characterising how the visual system reorganises after loss of afferent input.

This Data Descriptor presents a Brain Imaging Data Structure (BIDS) MRI dataset assembled from a prospective observational study designed to examine brain responses to reduced visual input after optic nerve injury (McGill University Health Centre Research Ethics Board Protocol 2020-5879; sponsored by the U.S. Department of Defense Congressionally Directed Medical Research Programs Vision Program). The parent study recruits adults with traumatic optic neuropathy, optic neuritis, or glaucoma, together with participants with clinically normal vision, and acquires MRI at a baseline visit and at an approximately six-month follow-up. The scientific motivation of the acquisition protocol is to compare resting-state and visually evoked activity, and to assess structural integrity of connections between the eye and visual brain structures, across acute and chronic forms of optic injury and relative to healthy vision. Participants with spatially restricted visual-field loss further allow comparison of responses corresponding to seeing versus non-seeing portions of the visual field.

The present release comprises **84** participants organised into four cohorts recorded in `participants.tsv`: Control (*n* = 56), optic neuritis (BIDS label `DataON`; *n* = 7), traumatic optic neuropathy (BIDS label `DataTON`; *n* = 2), and Glaucoma (*n* = 19). The sample comprised 46 female and 38 male participants; individual ages are not released in the public `participants.tsv` (privacy-preserving choice for this clinical cohort). Imaging was planned as two sessions (`ses-01`, `ses-02`). Longitudinal coverage in the current BIDS tree is incomplete: 40 participants have both sessions, 43 have `ses-01` only, and 1 has `ses-02` only, reflecting incomplete follow-up rather than omitted placeholder folders.

Data were acquired at 3 T on a Siemens Prisma system and converted to BIDS (specification version 1.9.0) using a documented DICOM-to-BIDS workflow (`neuro_pipeline` 2.1.0; dcm2niix). The release includes structural MRI (T1-weighted, FLAIR, and B1-related anatomical series), diffusion-weighted MRI, spin-echo EPI field maps with opposing phase-encode directions, and functional BOLD acquisitions labelled as resting-state (`task-rest`), movie viewing (`task-movie`), visually driven task fMRI (`task-fmri`), and short control runs (`task-control`). Approximate modality counts in the converted tree include 356 T1-weighted, 125 FLAIR, 361 diffusion, 982 spin-echo field-map, and several thousand BOLD volumes with accompanying single-band references. De-identification followed a DICOM PS3.15-oriented custom workflow (identifier removal, UID remapping, date shifting), with anatomical defacing applied for public sharing of structural volumes. Quality-control procedures include BIDS validation, automated image-quality metrics, complementary deep-learning T1-weighted artifact screening, and diffusion acquisition checks; automated QC outputs are used to describe data quality and to prioritise inspection rather than as automatic exclusion criteria.

This dataset is intended to support secondary analyses that start from organised multimodal MRI inputs. Potential reuse includes studies of structure–function relationships in the human visual system after optic neuropathy, development and benchmarking of preprocessing and quality-control pipelines for clinical neuroimaging cohorts, and methodological work on BIDS conversion, de-identification, and longitudinal multimodal data management. The release describes the imaging resource and its technical preparation; it does not present new biological group-comparison results.

No peer-reviewed publications that analysed these data, in whole or in part, were identified in the materials available at the time of writing; any subsequent primary analyses should be cited here when published. Related open neuroimaging resources that organise large MRI collections for reuse include OpenNeuro and other BIDS-formatted public datasets, which provide complementary healthy and clinical imaging contexts for methods development and cross-cohort comparison.

---

## Author notes (not for submission)

1. **Prior publications.** Placeholder sentence assumes none yet. Replace with brief citations/summaries if primary papers exist (required by Scientific Data when applicable).
2. **Planned *n* = 130.** Consent text mentions a four-year plan to recruit 130 subjects. The release currently has 84. The draft deliberately does **not** claim recruitment is complete; optionally add one factual sentence if the team wants that context.
3. **TBI cohort.** Consent lists traumatic brain injury as a recruitment category; BIDS `participants.tsv` has no separate TBI label. Do not invent a TBI cohort count.
4. **Longitudinal counts.** Mapping metadata report 135 sessions / 51 participants with two visits; BIDS tree used in Methods has 124 subject–session folders / 40 with both `ses-01` and `ses-02`. Keep Background aligned with whichever source the Methods/Data Record use (currently BIDS tree).
5. **Related datasets cited.** The closing paragraph names OpenNeuro at a high level; add 1–2 specific Data Descriptors or clinical visual-pathway MRI papers if the authors prefer concrete comparisons (Scientific Data recommends citing some field-relevant resources without requiring exhaustive prior-art comparison).
6. **Tone check.** Avoid “unique”, “first”, “invaluable”, “critical gap”, or impact claims per journal guidance.
7. **Ethics / sharing.** Confirm consent language covers open sharing before finalising repository/DOI wording elsewhere in the manuscript.
8. **Age (privacy).** PI decision 2026-07-24: keep age **out** of public `participants.tsv`; **do not** report aggregate age (mean±SD) in the manuscript. Sex + cohort only in the public table. Internal age tables (`metadata/participant_age.tsv`, `reports/participant_summary/`) remain private / not for OpenNeuro.

---

## Suggested citations to wire in (from existing References draft)

- Gorgolewski et al., *Sci. Data* (2016) — BIDS  
- Markiewicz et al., *eLife* (2021) — OpenNeuro  
- Optional field background (authors to select): reviews or imaging studies of traumatic optic neuropathy, optic neuritis, or glaucoma (not invented here)

## Consistency anchors used

| Fact | Source |
| --- | --- |
| Protocol 2020-5879; DoD / CDMRP Vision; motivation text | User-supplied consent / study information |
| 84 participants; cohort *n*; age/sex | `Participant_Demographics.md`; Methods draft |
| Session coverage 40 / 43 / 1 | Methods draft / BIDS longitudinal coverage notes |
| Modalities and approximate counts | `bids/README.md`; `extracted_metrics.md` |
| Scanner Prisma 3 T; BIDS 1.9.0; neuro_pipeline 2.1.0 | Methods draft / dataset_description |
| No biological results in Data Descriptor | Scientific Data Data Descriptor format + project policy |
