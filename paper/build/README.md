# Build artifacts

This directory is reserved for **generated** LaTeX build outputs when compiling locally, for example:

```text
.aux
.log
.out
.bbl
.blg
.synctex.gz
.toc
.fls
.fdb_latexmk
```

Do **not** store manuscript source files (`.tex`, `.bib`, figures) here.

## Overleaf

Overleaf manages build products in its own environment and does **not** require this folder. Do not attempt to force Overleaf into a non-standard output directory. Keep `build/` for local workflows only (e.g. `latexmk -outdir=build`).

## Local example

```bash
latexmk -pdf -outdir=build main.tex
```
