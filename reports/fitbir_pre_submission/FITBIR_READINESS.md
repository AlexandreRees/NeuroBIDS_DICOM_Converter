# FITBIR pre-submission readiness

Generated: `2026-07-30T14:52:06.516644+00:00`

**Scope:** READ-ONLY audit. No FITBIR submission artifacts were created.

## Overall readiness

**Score: 79 / 100**

| Domain | Score | Notes |
| --- | ---: | --- |
| Participants | 100 | participant_id=True, sex=True, age=True |
| Imaging | 100 | flags={'fieldmaps': True, 'physiology': True, 'DWI': True, 'T1': True, 'FLAIR': True, 'movie': True, 'rest': True, 'task_fMRI': True} |
| Physiology | 80 | BIDS physio sidecars detected |
| QC | 100 | 8/8 QC components present |
| Documentation | 100 | 15/15 topics with evidence |
| Provenance | 45 | Sidecars + reports present; absolute-path leakage in events provenance lowers score |
| Reproducibility | 65 | code/ + reports pipelines present; environment lockfiles NOT fully audited |

## Strengths

- BIDS dataset with **84** subjects detected
- Tasks present: control, fmri, movie, rest
- Derivatives trees: bids_priority_fixes, defacing, dmriqc, group_qc, mriqc, neuro_pipeline, physiology_characterization, physiology_qc, physiology_reproducibility
- Sampled variables inventoried: **3325**
- Likely CDE candidates: **37**

## Weaknesses

- Critical missing items: **1**
- Recommended missing items: **2**
- Many JSON sidecar keys lack explicit Description/Units in BIDS sidecars (typical; still needs FITBIR documentation).
- Age / rich phenotype CDEs may be absent or limited depending on participants.tsv content.

## Missing metadata (critical)

- **Absolute paths in BIDS events provenance**: events.json contain absolute filesystem paths and raw cohort labels (SUBC*/SUBG*) — must be redacted/normalized before FITBIR deposit

## Variables needing documentation

- See `VARIABLE_DOCUMENTATION_AUDIT.tsv` (filter `has_description == no`).

## Suggested Form Structures

- See `FORM_STRUCTURE_PROPOSAL.md`.

## Suggested Data Elements

- Likely CDEs: `LIKELY_COMMON_DATA_ELEMENTS.tsv`
- Likely UDEs: `POTENTIAL_UNIQUE_DATA_ELEMENTS.tsv`

## Risk assessment

| Risk | Level | Mitigation |
| --- | --- | --- |
| Incomplete phenotype CDEs (age/diagnosis) | HIGH if absent | Confirm source phenotype before FITBIR mapping |
| Undocumented derived QC variables | MEDIUM | Curate UDE definitions from pipeline docs |
| Event coverage gaps (grating) | MEDIUM | Use published exclusion tables; do not invent onsets |
| Physio trigger limitations | MEDIUM | Document in Form Structure notes |
| License/citation placeholders | HIGH for submission | Replace before FITBIR/OpenNeuro deposit |

## Next steps (NOT performed by this audit)

1. Manual review of Critical/Recommended gaps
2. Map confirmed variables to FITBIR CDEs
3. Draft UDE definitions for project-specific fields
4. Build Form Structures only after element definitions are approved
