# Figures

Place manuscript figure files in this directory.

## Naming convention

```text
Figure_1.*
Figure_2.*
Figure_3.*
Figure_4.*
...
```

Preferred formats for Overleaf / Elsevier: **PDF** (vector) or **PNG** / **TIFF** (raster) as required by the journal.

Supplementary figures (if stored here) should use:

```text
SuppFigure_1.*
SuppFigure_2.*
...
```

## Anticipated main figures

| File | Role | Label in manuscript |
|------|------|---------------------|
| `Figure_1` | Dataset / experimental overview | `fig:dataset_overview` |
| `Figure_2` | Data processing workflow | `fig:processing_workflow` |
| `Figure_3` | Dataset organization or technical validation | `fig:dataset_organization` |
| `Figure_4` | Quality control / completeness | `fig:quality_control` |

## Usage in LaTeX

```latex
\begin{figure}
    \centering
    % \includegraphics[width=\linewidth]{figures/Figure_1.pdf}
    \caption{[TODO: Figure caption.]}
    \label{fig:dataset_overview}
\end{figure}
```

Do not invent scientific figures. Add real figure files when ready, then uncomment `\includegraphics`.
