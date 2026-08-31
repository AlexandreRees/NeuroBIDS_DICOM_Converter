# Data in Brief — Data Descriptor manuscript

Modular LaTeX skeleton for an Elsevier **Data in Brief** Data Descriptor. Upload the entire `paper/` directory to [Overleaf](https://www.overleaf.com/) and set `main.tex` as the root document.

This repository is an **architecture/template**. Scientific content must be added later. Do not treat TODO placeholders as finished manuscript text.

## Project

Purpose: write the manuscript section-by-section without restructuring paths, labels, or front matter later. `main.tex` is only the document controller; body text lives under `sections/`.

## Journal

**Data in Brief** (Elsevier). Document class: `elsarticle` (preprint, 12 pt). Bibliography: `elsarticle-num` (numeric citations `[1]`, `[2]`, …).

## Manuscript architecture

```text
paper/
├── build/           Local build artifacts only (see build/README.md)
├── figures/         Figure files (Figure_1.*, …)
├── sections/        One .tex file per major section / front-matter abstract
├── supplementary/   Supplementary tables and figures
├── tables/          Specifications table + main Tables 1–4
├── main.tex         Document controller
├── references.bib   BibTeX database (no fabricated entries)
└── README.md        This file
```

| Path | Role |
|------|------|
| `sections/01_abstract.tex` | Abstract (≤250 words); unnumbered front matter |
| `sections/02_…`–`16_…` | Numbered manuscript sections |
| `tables/specifications_table.tex` | Specifications Table after keywords |
| `tables/table1_…`–`table4_…` | Main editable tables |
| `supplementary/` | Extra tables/figures, not mixed into core narrative |
| `references.bib` | Citations via `\cite{key}` |

Front matter (Abstract, Keywords, Specifications Table) is **not** numbered as normal sections.

## Compilation

### Overleaf

1. Zip the `paper/` folder (or sync via Git).  
2. New Project → Upload Project.  
3. Menu → Main document → `main.tex`.  
4. Compiler: **pdfLaTeX** (default). BibTeX runs automatically with `elsarticle-num`.

### Local

```bash
cd paper
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

Or:

```bash
latexmk -pdf main.tex
# optional: latexmk -pdf -outdir=build main.tex
```

Requirements: TeX Live (or MiKTeX) with `booktabs`, `graphicx`, `hyperref`, etc. This project vendors `elsarticle.cls` and `elsarticle-num.bst` so compilation works even when the Elsevier class is not installed system-wide (Overleaf already provides them).

## Figures

See `figures/README.md`. Name files `Figure_1.pdf`, `Figure_2.pdf`, …. Uncomment `\includegraphics` in the relevant section files when assets exist. Captions and `\label{fig:...}` are already wired; cite with `\ref{fig:...}`.

## Tables

See `tables/README.md`. Main tables use `booktabs` (no vertical rules). Reference with `\ref{tab:...}`. The Specifications Table is imported from `main.tex` immediately after the front matter.

## References

Edit `references.bib` only with real entries. Style is Elsevier numeric (`\bibliographystyle{elsarticle-num}`). In text: `\cite{reference_key}` → `[n]`. TODO comments in the `.bib` file list expected citation categories (BIDS, dcm2niix, dataset DOI, etc.).

## Supplementary material

See `supplementary/README.md`. Kept separate from the main section sequence. Optional appendix `\input`s are commented out at the bottom of `main.tex` for internal review only.

## TODO policy

Placeholders use forms such as:

```latex
[TODO: INSERT CONTENT]
% TODO: Add participant demographics.
```

**All TODO markers must be removed or replaced before journal submission.**

Do not invent participant numbers, acquisition parameters, ethics IDs, DOIs, authors, affiliations, software versions, QC thresholds, or references.

## Submission checklist

- [ ] Title finalized
- [ ] Authors verified
- [ ] Affiliations verified
- [ ] Corresponding author verified
- [ ] Abstract ≤250 words
- [ ] 1–7 keywords
- [ ] Specifications Table completed
- [ ] All sections completed
- [ ] Tables completed
- [ ] Figures supplied separately
- [ ] Figure captions finalized
- [ ] Supplementary files finalized
- [ ] Ethics statement completed
- [ ] Data repository DOI added
- [ ] Dataset cited
- [ ] Software cited
- [ ] CRediT completed
- [ ] Acknowledgements completed
- [ ] Conflict of interest statement completed
- [ ] References checked
- [ ] All figures cited
- [ ] All tables cited
- [ ] All supplementary files cited
- [ ] Manuscript compiles without errors
- [ ] No TODO placeholders remain
