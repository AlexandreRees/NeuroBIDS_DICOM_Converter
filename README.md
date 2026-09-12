# Shmuel Lab MRI Dataset Processing Pipeline

Methods, quality-control audits, and reproducibility code for the Shmuel Lab multimodal MRI dataset (Siemens Prisma), prepared for a Nature *Scientific Data* descriptor and open distribution.

## 1. Overview

This GitHub repository contains **software, documentation, manuscript materials, and audit reports** used to build and validate a BIDS-compliant MRI release.

**MRI imaging data, DICOM inventories, date-shift keys, and participant-level mapping tables are not stored in this repository.**  
Public imaging products will be distributed through the designated data platform (e.g., OpenNeuro / institutional release), separate from GitHub.

GitHub contains only:

- processing and audit **code**
- **documentation** and the Data in Brief manuscript (`paper/`)
- **audit / QC reports** (text tables and markdown; BIDS `sub-` identifiers only)

## 2. Scientific objective

Support transparent, fail-closed curation of a longitudinal 3T Prisma dataset spanning structural, diffusion, and task/resting functional MRI, with physiology where scientifically recoverable, under BIDS and de-identification constraints suitable for open science publication.

## 3. Repository structure

```
code/          # Python pipelines, BIDS builders, QC/audit scripts
paper/         # Data in Brief manuscript (LaTeX, protocol figures)
manuscript/    # Earlier Scientific Data drafting notes
reports/       # Scientific audits, QC summaries (no PHI tables)
tests/         # Unit / smoke tests
CITATION.cff   # Citation metadata
.gitignore     # Excludes imaging trees, PHI metadata, bulky dumps
```

Ignored by policy (not on GitHub): `bids/`, `sourcedata/`, `raw_original/`, `derivatives/`, `release_dataset/`, `metadata/` (participant mappings, ages, date shifts, DICOM inventories), containers/envs, NIfTI/DICOM binaries.

## 4. Reproducibility workflow

1. Obtain imaging data from the public/platform release (or institutional `raw_original` / BIDS trees on secure storage).
2. Clone this methods repository.
3. Install Python dependencies required by the target script (see script docstrings / environment notes).
4. Run audits or builders in **read-only / dry-run** mode against local data paths.
5. Write outputs only under designated `reports/` or release build directories — never modify protected source trees in production audits.

## 5. Data management

| Content | Location |
|---------|----------|
| DICOM / NIfTI volumes | Institutional storage + public data platform (not GitHub) |
| BIDS tree | Generated locally / released externally |
| Code, manuscript, audits | This repository |
| Participant mapping / date shifts | Institutional storage only (not GitHub) |

## 6. Quality control

Repository scripts and `reports/` document MRIQC / dmriqc-oriented QC, physiology recoverability audits, defacing / de-identification checks, and BIDS compliance reviews. Interpretation should follow the corresponding markdown reports rather than assuming automatic pass/fail for every modality.

## 7. BIDS compliance

Conversion and sidecar curation aim for BIDS-compliant structure suitable for OpenNeuro-style validation. Event and physiology products are only promoted when run-level mapping is scientifically non-ambiguous (fail-closed policy).

## 8. Publication status

Prepared in support of a *Scientific Data* manuscript describing the dataset and processing. Citation details will track the published article; until then use `CITATION.cff`.

## 9. Software requirements

- Python 3.10+ recommended
- Typical scientific stack: `numpy`, `nibabel`, `pydicom` (script-dependent)
- Optional HPC: Slurm on Compute Canada modules
- Container workflows (Apptainer) are documented in scripts but **image files are not shipped in Git**

## 10. Citation

If you use this repository, please cite the associated Scientific Data publication and this software via `CITATION.cff`.

```bibtex
@software{shmuel_mri_pipeline,
  title = {Shmuel Lab MRI Dataset Processing Pipeline},
  version = {1.0.1},
  url = {https://github.com/AlexandreRees/neuro_pipeline},
  year = {2026}
}
```

## License

Specify the project license in a future `LICENSE` file before public release if not already defined by the laboratory / publisher policy.
