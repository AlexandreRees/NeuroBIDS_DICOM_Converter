# De-identification figures and manuscript assets

Publication-oriented outputs derived from `reports/deidentification_report.md`.  
No pipeline source files were modified to produce this folder.

## PI presentation package (2026-07-24)

| Item | Path |
|---|---|
| Briefing PI (FR) | `DEIDENTIFICATION_PI_BRIEFING_2026-07-24.md` |
| Figure legends + slide order | `FIGURES_README.md` |
| Figures PI (PNG+PDF, FR) | `figures/Fig01`–`Fig06` |
| One-pager | `figures/Fig06_PI_onepager_deidentification.png` |
| Regenerator | `python3 reports/deidentification_figures/generate_pi_figures.py` |

Suggested projection order: Fig06 → Fig01 → Fig03 → Fig02/Fig05 → Fig04 (if asked).

## Generated files

### Scientific interpretation
| File | Description |
|---|---|
| `scientific_highlights.md` | Methodological strengths for manuscript framing |

### Figures (PNG + SVG) — manuscript EN
| File | Suggested figure number | Use |
|---|---|---|
| `figure_deidentification_workflow.png` / `.svg` | **Figure 1** | Main-text workflow |
| `figure_dicom_tag_actions.png` / `.svg` | **Figure 2** | Main-text or supplement quantitative summary |
| `figure_before_after_deidentification.png` / `.svg` | **Figure 3** | Main-text schematic (synthetic IDs only) |
| `figure_data_provenance.png` / `.svg` | **Figure 4** | Main-text provenance / integrity |

### Captions
| File | Companion figure |
|---|---|
| `figure_deidentification_workflow_caption.md` | Figure 1 |
| `figure_dicom_tag_actions_caption.md` | Figure 2 |
| `figure_before_after_caption.md` | Figure 3 |
| `figure_data_provenance_caption.md` | Figure 4 |

### Supplementary table
| File | Description |
|---|---|
| `Supplementary_Table_DICOM_Deidentification.xlsx` | Full tag action table |
| `Supplementary_Table_DICOM_Deidentification.csv` | Same table, CSV |
| `dicom_tag_action_counts.csv` | Counts underlying Figure 2 |

### Manuscript & review support
| File | Description |
|---|---|
| `deidentification_manuscript_section.md` | Full + short Methods prose with figure callouts |
| `reviewer_questions.md` | Anticipated reviewer Q&A |
| `generate_outputs.py` | Regenerates figures/tables (optional) |

## Recommended use in the manuscript

### Main text
- **Figure 1** — introduce the de-identification subsection.
- **Figure 3** — explain pseudonymization, date shifting, and UID remapping with a synthetic example.
- **Figure 4** — reinforce immutable raw data and derivative-only processing.
- Use the **short Scientific Data version** (~150–200 words) in the Data Descriptor Methods if space is tight; otherwise use the **full Methods version**.

### Main text or online Methods figure panel
- **Figure 2** — compact summary of transformation classes; suitable as a main-text panel if space allows, otherwise Supplementary Figure.

### Supplementary material
- **Supplementary Table** (`Supplementary_Table_DICOM_Deidentification.*`) — complete DICOM tag policy.
- Optionally relocate Figure 2 here if the main text is figure-limited.
- Keep date-shift offsets and raw↔canonical identity maps **out of** the public supplement (private provenance).

## Quantitative summary (Figure 2)

| Action category | Count in policy table |
|---|---:|
| Cleared | 32 |
| Pseudonymized | 2 |
| UID remapped | 8 |
| Date shifted | 8 |
| Preserved (explicit catalogue) | 14 |
| Removed private tags | 1 (policy category: all) |
| Pixel data unchanged | 1 (policy category) |

## Regenerating figures

**Preferred (PI + manuscript EN, PNG/PDF/SVG):**

```bash
python3 reports/deidentification_figures/generate_pi_figures.py
```

Legacy Graphviz renderer (optional):

```bash
python3 reports/deidentification_figures/render_figures.py
```

Supplementary tables / counts:

```bash
python3 reports/deidentification_figures/generate_outputs.py
```
