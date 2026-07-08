# Architecture

> **Template:** Document *your* project’s deployment of neuro-bids-pipeline.  
> For the upstream pipeline design, see the repository reference  
> [`docs/PIPELINE_ARCHITECTURE.md`](../../docs/PIPELINE_ARCHITECTURE.md).

---

## 1. Purpose

Describe the scientific goal of this dataset and how the pipeline fits into your workflow.

| Field | Value |
|-------|-------|
| Project name | `{{PROJECT_NAME}}` |
| Principal investigator | `{{PI_NAME}}` |
| Pipeline version | `{{PIPELINE_VERSION}}` |
| BIDS target version | `{{BIDS_VERSION}}` |

---

## 2. System context

Summarise how data enters and leaves this project:

```text
{{DATA_SOURCE}} → raw_original/ → neuro-pipeline → raw_bids/ → neuro-release → Public_Dataset/
```

Note any external systems (PACS export, LORIS, REDCap, analysis clusters) without repeating the README quick-start.

---

## 3. Repository packages used

Map pipeline packages to responsibilities in *this* deployment:

| Package | Role in this project |
|---------|----------------------|
| `acquisition/` | `{{ACQUISITION_NOTES}}` |
| `conversion/` | `{{CONVERSION_NOTES}}` |
| `validation/` | `{{VALIDATION_NOTES}}` |
| `qc/` | `{{QC_NOTES}}` |
| `publication/` | `{{PUBLICATION_NOTES}}` |
| `workflows/` | Orchestration via `neuro-pipeline` / `neuro-release` |

Refer to [`docs/ARCHITECTURE_MIGRATION.md`](../../docs/ARCHITECTURE_MIGRATION.md) for the canonical package tree.

---

## 4. Project directory layout

Document the on-disk layout for **this** study:

```text
{{PROJECT_ROOT}}/
├── raw_original/          # {{RAW_ORIGINAL_DESCRIPTION}}
├── raw_bids/              # Internal research BIDS (locked after derivatives_build)
├── metadata/              # Mappings, manifests, checkpoints (private)
├── derivatives/           # Pipeline reports and QC
└── anonymization_release/ # Public release outputs (when applicable)
```

---

## 5. Data-flow diagram

Replace with a study-specific diagram or link to an external figure:

```mermaid
flowchart LR
    A[{{INPUT}}] --> B[neuro-pipeline]
    B --> C[raw_bids]
    C --> D[neuro-release]
    D --> E[{{OUTPUT}}]
```

---

## 6. Security and access

| Asset | Location | Who may access |
|-------|----------|----------------|
| Source DICOM | `raw_original/` | `{{ACCESS_RAW}}` |
| Participant mapping | `metadata/participant_mapping.csv` | `{{ACCESS_MAPPING}}` |
| Research BIDS | `raw_bids/` | `{{ACCESS_RESEARCH}}` |
| Public BIDS | `anonymization_release/Public_Dataset/` | `{{ACCESS_PUBLIC}}` |

---

## 7. Extension points

List downstream tools (fMRIPrep, QSIPrep, custom analyses) and which pipeline artifacts they consume:

| Tool | Input artifact | Notes |
|------|----------------|-------|
| `{{TOOL_NAME}}` | `{{ARTIFACT_PATH}}` | `{{NOTES}}` |

See `metadata/pipeline_manifest.json` for machine-readable paths after each run.

---

## 8. Change log

| Date | Change | Author |
|------|--------|--------|
| `{{DATE}}` | Initial architecture document | `{{AUTHOR}}` |
