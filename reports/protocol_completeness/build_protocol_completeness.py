#!/usr/bin/env python3
"""Publication-ready MRI protocol completeness report.

Independent of demographic reporting.
Uses only metadata/session_mapping.csv (fallback: inventory). No DICOM re-scan.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path("/home/alexrees/scratch")
META = ROOT / "metadata"
OUT = ROOT / "reports" / "protocol_completeness"
OUT.mkdir(parents=True, exist_ok=True)

COHORT_ORDER = ["Control", "Data_ON", "Data_TON", "Glaucoma"]
ALIAS = {
    "DataON": "Data_ON",
    "DataTON": "Data_TON",
    "Data_on": "Data_ON",
    "Data_ton": "Data_TON",
}

ACQUISITIONS: list[tuple[str, str]] = [
    ("T1w_MPR", r"(?i)^t1w_mpr$|^t1w_mpr_nd$"),
    ("WMn_MPRAGE_sagittal", r"(?i)wmn_mprage"),
    ("Sag FLAIR 3D", r"(?i)sag\s*flair\s*3d"),
    ("REST1_AP", r"(?i)^rest1_ap$"),
    ("fMRI1_AP", r"(?i)^fmri1_ap$"),
    ("fMRI2_AP", r"(?i)^fmri2_ap$"),
    ("fMRI3_AP", r"(?i)^fmri3_ap$"),
    ("fMRI4_AP", r"(?i)^fmri4_ap$"),
    ("Control acquisitions", r"(?i)^control\d+_(?:ap|pa)$"),
    ("Movie1_AP", r"(?i)^movie1_ap$"),
    ("Movie2_AP", r"(?i)^movie2_ap$"),
    ("Movie3_AP", r"(?i)^movie3_ap$"),
    ("Movie4_AP", r"(?i)^movie4_ap$"),
    ("SpinEchoFieldMap_AP", r"(?i)^spinechofieldmap_ap$"),
    ("SpinEchoFieldMap_PA", r"(?i)^spinechofieldmap_pa$"),
    ("gsld_76dir_b2000_1mmiso_AP", r"(?i)gsld_76dir_b2000"),
    ("RESOLVE diffusion", r"(?i)^resolve_"),
]

MATRIX_CATEGORIES: list[tuple[str, list[str]]] = [
    ("T1", ["T1w_MPR", "WMn_MPRAGE_sagittal"]),
    ("FLAIR", ["Sag FLAIR 3D"]),
    ("fMRI", ["REST1_AP", "fMRI1_AP", "fMRI2_AP", "fMRI3_AP", "fMRI4_AP", "Control acquisitions"]),
    ("Movie", ["Movie1_AP", "Movie2_AP", "Movie3_AP", "Movie4_AP"]),
    ("DWI", ["gsld_76dir_b2000_1mmiso_AP", "RESOLVE diffusion"]),
    ("Fieldmaps", ["SpinEchoFieldMap_AP", "SpinEchoFieldMap_PA"]),
]


def _canon(c: object) -> str:
    s = str(c or "").strip()
    return ALIAS.get(s, s)


def _tex_escape(text: object) -> str:
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "✓": r"\checkmark",
        "✗": r"--",
    }
    return "".join(repl.get(ch, ch) for ch in str(text))


def load_session_mapping(path: Path | None = None) -> pd.DataFrame:
    sm_path = path or (META / "session_mapping.csv")
    if not sm_path.is_file():
        inv = META / "inventory_narval.csv"
        if not inv.is_file():
            raise FileNotFoundError("session_mapping.csv / inventory not found")
        sm_path = inv
    df = pd.read_csv(sm_path, dtype=str, low_memory=False).fillna("")
    if "participant_id" not in df.columns or "series_description" not in df.columns:
        raise ValueError(f"{sm_path} missing required columns")
    df["participant_id"] = df["participant_id"].astype(str).str.strip()
    df["cohort"] = df.get("cohort", pd.Series(dtype=str)).map(_canon)
    df["series_description"] = df["series_description"].astype(str)
    return df


def participant_presence(sm: pd.DataFrame) -> pd.DataFrame:
    participants = sm[["participant_id", "cohort"]].drop_duplicates("participant_id").copy()
    participants["cohort"] = participants["cohort"].map(_canon)
    for label, pattern in ACQUISITIONS:
        matched = set(
            sm.loc[
                sm["series_description"].str.contains(pattern, regex=True, na=False),
                "participant_id",
            ].astype(str)
        )
        participants[label] = participants["participant_id"].isin(matched)
    return participants.sort_values(["cohort", "participant_id"], kind="mergesort")


def cohort_availability(presence: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, _ in ACQUISITIONS:
        row: dict[str, object] = {"Acquisition": label}
        total_present = 0
        total_n = 0
        for cohort in COHORT_ORDER:
            sub = presence[presence["cohort"] == cohort]
            n = len(sub)
            if n == 0:
                row[cohort] = "—"
                continue
            pct = 100.0 * float(sub[label].sum()) / n
            row[cohort] = f"{pct:.0f}%"
            total_present += int(sub[label].sum())
            total_n += n
        row["Total"] = f"{100.0 * total_present / total_n:.0f}%" if total_n else "—"
        rows.append(row)
    return pd.DataFrame(rows)[["Acquisition", *COHORT_ORDER, "Total"]]


def participant_matrix(presence: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in presence.iterrows():
        out: dict[str, object] = {
            "participant_id": r["participant_id"],
            "cohort": r["cohort"],
        }
        for cat, sources in MATRIX_CATEGORIES:
            present = any(bool(r[src]) for src in sources if src in r.index)
            out[cat] = "✓" if present else "✗"
        rows.append(out)
    return pd.DataFrame(rows)


def missing_counts(matrix: pd.DataFrame) -> dict[str, int]:
    return {cat: int((matrix[cat] == "✗").sum()) for cat, _ in MATRIX_CATEGORIES}


def write_markdown(cohort_table: pd.DataFrame, matrix: pd.DataFrame) -> Path:
    path = OUT / "protocol_completeness_summary.md"
    lines = [
        "# MRI protocol completeness",
        "",
        "Acquisition presence from `metadata/session_mapping.csv` (no DICOM re-scan).",
        "",
        "## Table 1. MRI protocol completeness by acquisition",
        "",
        "| " + " | ".join(cohort_table.columns) + " |",
        "|" + "|".join(["---"] * len(cohort_table.columns)) + "|",
    ]
    for row in cohort_table.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    lines.extend(
        [
            "",
            "## Table 2. Participant-level MRI protocol completeness",
            "",
            "| " + " | ".join(matrix.columns) + " |",
            "|" + "|".join(["---"] * len(matrix.columns)) + "|",
        ]
    )
    for row in matrix.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_latex_pdf_png(
    cohort_table: pd.DataFrame, matrix: pd.DataFrame
) -> tuple[Path, Path, Path]:
    tex_path = OUT / "protocol_completeness_summary.tex"

    def body(df: pd.DataFrame, *, checks: bool = False) -> str:
        rows = []
        for i, row in enumerate(df.itertuples(index=False)):
            shade = r"\rowcolor{tablealt} " if i % 2 == 1 else ""
            cells = []
            for v in row:
                text = str(v)
                if checks:
                    if text == "✓":
                        cells.append(r"\checkmark")
                    elif text == "✗":
                        cells.append(r"--")
                    else:
                        cells.append(_tex_escape(text))
                else:
                    cells.append(_tex_escape(text.replace("%", r"\%")))
            rows.append(shade + " & ".join(cells) + r" \\")
        return "\n".join(rows)

    h1 = " & ".join(
        rf"\textcolor{{headergray}}{{\textbf{{{_tex_escape(c)}}}}}"
        for c in cohort_table.columns
    )
    h2 = " & ".join(
        rf"\textcolor{{headergray}}{{\textbf{{{_tex_escape(c)}}}}}"
        for c in matrix.columns
    )

    tex = rf"""% Independent protocol completeness report
\documentclass[11pt]{{article}}
\usepackage[margin=14mm,landscape,a4paper]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{tabularx}}
\usepackage{{array}}
\usepackage{{graphicx}}
\usepackage[table]{{xcolor}}
\usepackage{{caption}}
\usepackage{{microtype}}
\usepackage{{amssymb}}
\usepackage{{longtable}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern}}

\definecolor{{tablealt}}{{RGB}}{{245,247,250}}
\definecolor{{headergray}}{{RGB}}{{55,65,81}}
\captionsetup{{font=small,labelfont=bf,skip=6pt}}
\newcolumntype{{Y}}{{>{{\raggedright\arraybackslash}}X}}
\newcolumntype{{C}}{{>{{\centering\arraybackslash}}X}}

\begin{{document}}
\pagestyle{{empty}}
\setlength{{\tabcolsep}}{{3.5pt}}
\renewcommand{{\arraystretch}}{{1.2}}

\begin{{table}}[htbp]
\centering
\caption{{MRI protocol completeness by acquisition. Values are the percentage of participants with at least one matching series.}}
\label{{tab:protocol_completeness_by_acquisition}}
\small
\begin{{tabularx}}{{\textwidth}}{{@{{}}YCCCCC@{{}}}}
\toprule
{h1} \\
\midrule
{body(cohort_table)}
\bottomrule
\end{{tabularx}}
\end{{table}}

\clearpage

\begin{{longtable}}{{@{{}}l l c c c c c c@{{}}}}
\caption{{Participant-level MRI protocol completeness. Checkmark = present; en-dash = absent.}}
\label{{tab:protocol_completeness_participants}} \\
\toprule
{h2} \\
\midrule
\endfirsthead
\toprule
{h2} \\
\midrule
\endhead
\bottomrule
\endfoot
{body(matrix, checks=True)}
\end{{longtable}}
\end{{document}}
"""
    tex_path.write_text(tex, encoding="utf-8")

    for _ in range(2):
        proc = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex_path.name],
            cwd=OUT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0 and "Output written on" not in (proc.stdout + proc.stderr):
            raise RuntimeError(proc.stdout[-2000:] + "\n" + proc.stderr[-1000:])

    pdf = OUT / "protocol_completeness_summary.pdf"
    png = OUT / "protocol_completeness_summary.png"
    # PNG from first page (availability table)
    subprocess.run(
        [
            "magick",
            "-density",
            "300",
            str(pdf) + "[0]",
            "-background",
            "white",
            "-alpha",
            "remove",
            "-alpha",
            "off",
            "-colorspace",
            "sRGB",
            "-depth",
            "8",
            "-trim",
            "+repage",
            "-bordercolor",
            "white",
            "-border",
            "72x72",
            "-quality",
            "100",
            str(png),
        ],
        check=True,
    )
    for ext in (".aux", ".log", ".out"):
        p = OUT / f"protocol_completeness_summary{ext}"
        if p.exists():
            p.unlink()
    return tex_path, pdf, png


def print_summary(matrix: pd.DataFrame, missing: dict[str, int]) -> None:
    print()
    print("PROTOCOL COMPLETENESS SUMMARY:")
    print()
    print(f"Participants evaluated: {len(matrix)}")
    print()
    print("Missing acquisitions:")
    print()
    for cat, _ in MATRIX_CATEGORIES:
        print(f"{cat}: {missing[cat]}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument(
        "--session-mapping",
        type=Path,
        default=None,
    )
    args = parser.parse_args(argv)

    global META, OUT
    META = args.data_root / "metadata"
    OUT = args.data_root / "reports" / "protocol_completeness"
    OUT.mkdir(parents=True, exist_ok=True)

    sm = load_session_mapping(args.session_mapping or (META / "session_mapping.csv"))
    presence = participant_presence(sm)
    cohort_table = cohort_availability(presence)
    matrix = participant_matrix(presence)
    missing = missing_counts(matrix)

    md = write_markdown(cohort_table, matrix)
    tex, pdf, png = write_latex_pdf_png(cohort_table, matrix)
    print(f"Wrote {md}")
    print(f"Wrote {tex}")
    print(f"Wrote {pdf}")
    print(f"Wrote {png}")
    print_summary(matrix, missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
