# Tables

Editable LaTeX tables for the Data in Brief manuscript.

| File | Purpose | Label |
|------|---------|-------|
| `specifications_table.tex` | Data in Brief Specifications Table (front matter) | `tab:specifications` |
| `table1_demographics.tex` | Participant demographics | `tab:demographics` |
| `table2_mri_acquisition.tex` | MRI acquisition parameters | `tab:mri_acquisition` |
| `table3_dataset_composition.tex` | Dataset composition | `tab:dataset_composition` |
| `table4_protocol_completeness.tex` | Protocol completeness | `tab:protocol_completeness` |

## Conventions

- Use `booktabs` (`\toprule`, `\midrule`, `\bottomrule`); avoid vertical rules.
- Always set `\caption{}` and `\label{tab:...}` before referencing with `\ref{}`.
- Do not invent numeric values; keep `[TODO]` until verified from source records.
- Prefer importing tables from section files (or `main.tex` for the specifications table) rather than duplicating table code.
