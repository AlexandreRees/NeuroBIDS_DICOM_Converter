# Pipeline overview

> **Template:** Describe how neuro-bids-pipeline is used for **this** study.  
> For step-by-step commands, see the repository README. For technical design, see  
> [`docs/PIPELINE_ARCHITECTURE.md`](../../docs/PIPELINE_ARCHITECTURE.md).

---

## 1. Summary

| Pipeline | Command | When to run |
|----------|---------|-------------|
| Research | `neuro-pipeline` | DICOM → internal BIDS for analysis |
| Release | `neuro-release` | Internal BIDS → OpenNeuro-ready public dataset |

---

## 2. Research pipeline stages

Fill in study-specific notes for each stage:

| Step | CLI module | Primary inputs | Primary outputs | Study notes |
|------|------------|----------------|-----------------|-------------|
| inventory | `neuro-inventory` | `raw_original/` | `metadata/inventory.csv` | `{{NOTES}}` |
| generate_mapping | `neuro-mapping` | inventory | `metadata/participant_mapping.csv`, `session_mapping.csv` | `{{NOTES}}` |
| convert_to_bids | `neuro-convert` | DICOM + mapping | `raw_bids/`, conversion reports | `{{NOTES}}` |
| validate_dataset | `neuro-validate` | `raw_bids/` | BIDS validation, acquisition validation | `{{NOTES}}` |
| quality_control | `neuro-qc` | `raw_bids/` | QC CSV/HTML reports | `{{NOTES}}` |
| derivatives_build | `neuro-derivatives` | `raw_bids/` | Locked dataset, checksum manifest | `{{NOTES}}` |

Expected acquisitions per session (if using acquisition validation): `{{EXPECTED_ACQUISITIONS}}`

---

## 3. Release pipeline stages

| Step | CLI module | Primary inputs | Primary outputs | Study notes |
|------|------------|----------------|-----------------|-------------|
| anonymize | `neuro-release-anonymize` | `raw_bids/` | `Public_Dataset/`, `Private/` | `{{NOTES}}` |
| validate_public_dataset | `neuro-validate-public` | `Public_Dataset/` | Public validation report | `{{NOTES}}` |
| release_gate | `neuro-release-gate` | Release artifacts | Gate report, readiness flag | `{{NOTES}}` |

Defacing policy for this study: `{{DEFACING_POLICY}}`

---

## 4. Orchestration options

Document how operators invoke the pipeline in practice:

| Mode | Command | Use case |
|------|---------|----------|
| Full research run | `neuro-pipeline --project-root {{ROOT}}` | Default batch processing |
| Resume | `neuro-pipeline --resume` | After interrupted run |
| Stop early | `neuro-pipeline --stop-after convert_to_bids` | Partial rerun / debugging |
| Single step | `neuro-convert --project-root {{ROOT}}` | Manual stage execution |

Checkpoints: `metadata/research_checkpoints.json`, `metadata/release_checkpoints.json`

---

## 5. Reporting and provenance

Artifacts generated for documentation and reproducibility:

| Report | Command / source | Output path |
|--------|------------------|-------------|
| Pipeline manifest | automatic per step | `metadata/pipeline_manifest.json` |
| QC summary HTML | `neuro-qc-report` | `derivatives/neuro_pipeline/qc/pipeline_qc_summary.html` |
| Methods section | `neuro-generate-methods` | `docs/METHODS.md` |
| Execution provenance | `save_provenance()` | `{{PROVENANCE_DIR}}/execution_provenance.json` |

---

## 6. Quality gates

Define pass/fail criteria used before downstream analysis or publication:

| Gate | Criterion | Action on failure |
|------|-----------|-------------------|
| BIDS validation | bids-validator exit code 0 | `{{ACTION}}` |
| Acquisition validation | `acquisition_validation.json` passed | `{{ACTION}}` |
| QC | no `fail` status in `qc_detail.csv` | `{{ACTION}}` |
| Release gate | `metadata/release_ready.json` | `{{ACTION}}` |

---

## 7. Timeline

| Milestone | Target date | Responsible |
|-----------|-------------|-------------|
| Pilot conversion | `{{DATE}}` | `{{OWNER}}` |
| Full cohort processing | `{{DATE}}` | `{{OWNER}}` |
| Public release | `{{DATE}}` | `{{OWNER}}` |
