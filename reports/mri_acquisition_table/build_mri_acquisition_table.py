#!/usr/bin/env python3
"""Build a publication-quality MRI acquisition table from extracted metadata.

Sources of truth (no DICOM re-read):
  reports/protocol_sample/sequence_parameters.json
  reports/protocol_sample/sequence_summary.md
  reports/protocol_sample/methods_mri_acquisition.md
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path("/home/alexrees/scratch")
SRC = ROOT / "reports" / "protocol_sample" / "sequence_parameters.json"
OUT = ROOT / "reports" / "mri_acquisition_table"
OUT.mkdir(parents=True, exist_ok=True)


def _num(value) -> float | None:
    text = str(value).strip()
    if not text or text.lower() in {"not available", "nan", "none"}:
        return None
    text = re.sub(r"\s*ms$", "", text, flags=re.I)
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_num(value: float | None, digits: int = 2) -> str | None:
    if value is None:
        return None
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _pixel_spacing(value) -> tuple[float, float] | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "not available":
        return None
    try:
        if text.startswith("["):
            parsed = ast.literal_eval(text)
            return float(parsed[0]), float(parsed[1])
        v = float(text)
        return v, v
    except (ValueError, SyntaxError, TypeError, IndexError):
        return None


def _keep_series(desc: str) -> bool:
    if desc in {"PhoenixZIPReport", "Phoenix Document", "Localizer"}:
        return False
    if desc.endswith(("_PhysioLog", "_SBRef", "_ND", "_Pha")):
        return False
    if any(tok in desc for tok in ("_ADC", "_ColFA", "_FA", "_TENSOR", "_TRACEW")):
        return False
    return True


def _resolution_mm(px, thickness: float | None) -> str | None:
    if px is None or thickness is None:
        return None
    a, b = px
    vals = [_fmt_num(a, 2), _fmt_num(b, 2), _fmt_num(thickness, 2)]
    if vals[0] == vals[1] == vals[2]:
        return f"{vals[0]} mm isotropic"
    return f"{vals[0]}×{vals[1]}×{vals[2]} mm³"


@dataclass(frozen=True)
class Row:
    category: str
    sequence: str
    purpose: str
    parameters: str


def _epi_params(sample: dict, *, volumes: int | None, n_runs: int | None = None) -> str:
    tr = _fmt_num(_num(sample["tr"]), 0)
    te = _fmt_num(_num(sample["te"]), 0)
    fa = _fmt_num(_num(sample["flip_angle"]), 0)
    res = _resolution_mm(_pixel_spacing(sample["pixel_spacing"]), _num(sample["slice_thickness"]))
    parts = []
    if tr:
        parts.append(f"TR {tr} ms")
    if te:
        parts.append(f"TE {te} ms")
    if fa:
        parts.append(f"Flip angle {fa}°")
    if res:
        parts.append(res)
    if volumes:
        parts.append(f"{volumes} volumes")
    if n_runs and n_runs > 1:
        # runs already in sequence name; keep params clean
        pass
    # phase-encode from description suffix
    desc = sample["series_description"]
    if desc.endswith("_AP"):
        parts.append("PE AP")
    elif desc.endswith("_PA"):
        parts.append("PE PA")
    return "; ".join(parts)


def build_rows(sequences: list[dict]) -> list[Row]:
    kept = [s for s in sequences if _keep_series(s["series_description"])]

    # Deduplicate identical series_description by keeping the richest/first
    by_desc: dict[str, dict] = {}
    counts: dict[str, int] = defaultdict(int)
    for s in kept:
        desc = s["series_description"]
        counts[desc] += 1
        if desc not in by_desc:
            by_desc[desc] = s

    def uniq_run_names(pattern: str) -> list[str]:
        return sorted({d for d in by_desc if re.fullmatch(pattern, d)})

    rows: list[Row] = []

    # --- Anatomical ---
    if "T1w_MPR" in by_desc:
        s = by_desc["T1w_MPR"]
        res = _resolution_mm(_pixel_spacing(s["pixel_spacing"]), _num(s["slice_thickness"]))
        params = "; ".join(
            p
            for p in [
                f"TR {_fmt_num(_num(s['tr']), 0)} ms" if _num(s["tr"]) else None,
                f"TE {_fmt_num(_num(s['te']), 2)} ms" if _num(s["te"]) else None,
                f"Flip angle {_fmt_num(_num(s['flip_angle']), 0)}°" if _num(s["flip_angle"]) else None,
                res,
                "MPRAGE",
            ]
            if p
        )
        rows.append(Row("Anatomical", "T1-weighted MPRAGE", "Anatomical reference", params))

    if "WMn_MPRAGE_sagittal" in by_desc:
        s = by_desc["WMn_MPRAGE_sagittal"]
        res = _resolution_mm(_pixel_spacing(s["pixel_spacing"]), _num(s["slice_thickness"]))
        params = "; ".join(
            p
            for p in [
                f"TR {_fmt_num(_num(s['tr']), 0)} ms" if _num(s["tr"]) else None,
                f"TE {_fmt_num(_num(s['te']), 2)} ms" if _num(s["te"]) else None,
                f"Flip angle {_fmt_num(_num(s['flip_angle']), 0)}°" if _num(s["flip_angle"]) else None,
                res,
                "white-matter-nulled MPRAGE",
            ]
            if p
        )
        rows.append(
            Row("Anatomical", "White-matter-nulled MPRAGE", "White matter contrast", params)
        )

    if "Sag Flair 3D-0.8" in by_desc:
        s = by_desc["Sag Flair 3D-0.8"]
        res = _resolution_mm(_pixel_spacing(s["pixel_spacing"]), _num(s["slice_thickness"]))
        params = "; ".join(
            p
            for p in [
                f"TR {_fmt_num(_num(s['tr']), 0)} ms" if _num(s["tr"]) else None,
                f"TE {_fmt_num(_num(s['te']), 0)} ms" if _num(s["te"]) else None,
                f"Flip angle {_fmt_num(_num(s['flip_angle']), 0)}°" if _num(s["flip_angle"]) else None,
                res,
                "3D FLAIR",
            ]
            if p
        )
        rows.append(Row("Anatomical", "3D FLAIR", "Lesion-sensitive imaging", params))

    # --- Field map ---
    fmap_ap = by_desc.get("SpinEchoFieldMap_AP")
    fmap_pa = by_desc.get("SpinEchoFieldMap_PA")
    if fmap_ap or fmap_pa:
        s = fmap_ap or fmap_pa
        res = _resolution_mm(_pixel_spacing(s["pixel_spacing"]), _num(s["slice_thickness"]))
        params = "; ".join(
            p
            for p in [
                f"TR {_fmt_num(_num(s['tr']), 0)} ms" if _num(s["tr"]) else None,
                f"TE {_fmt_num(_num(s['te']), 0)} ms" if _num(s["te"]) else None,
                f"Flip angle {_fmt_num(_num(s['flip_angle']), 0)}°" if _num(s["flip_angle"]) else None,
                res,
                "spin-echo EPI; AP and PA phase-encode directions",
            ]
            if p
        )
        rows.append(
            Row(
                "Field map",
                "Spin-echo EPI field map (AP/PA)",
                "Susceptibility distortion correction",
                params,
            )
        )

    # --- Functional ---
    rest = by_desc.get("REST1_AP")
    if rest:
        # For EPI, number_of_slices commonly stores temporal frames in this extract
        vols = int(_num(rest["number_of_slices"]) or 0) or None
        rows.append(
            Row(
                "Functional",
                "Resting-state fMRI (1 run)",
                "Resting-state functional connectivity",
                _epi_params(rest, volumes=vols),
            )
        )

    movies = uniq_run_names(r"Movie\d+_AP")
    if movies:
        s = by_desc[movies[0]]
        vols = int(_num(s["number_of_slices"]) or 0) or None
        rows.append(
            Row(
                "Functional",
                f"Movie fMRI ({len(movies)} runs)",
                "Movie-based functional paradigm",
                _epi_params(s, volumes=vols),
            )
        )

    tasks = uniq_run_names(r"fMRI\d+_AP")
    if tasks:
        s = by_desc[tasks[0]]
        vols = int(_num(s["number_of_slices"]) or 0) or None
        rows.append(
            Row(
                "Functional",
                f"Task fMRI ({len(tasks)} runs)",
                "Task-based functional paradigm",
                _epi_params(s, volumes=vols),
            )
        )

    controls = sorted(
        d for d in by_desc if re.fullmatch(r"Control\d+_(AP|PA)", d)
    )
    if controls:
        s = by_desc[controls[0]]
        vols = int(_num(s["number_of_slices"]) or 0) or None
        pe_dirs = sorted({d.rsplit("_", 1)[-1] for d in controls})
        params = _epi_params(s, volumes=vols)
        # Replace single PE tag with actual set when mixed
        params = re.sub(r"; PE (AP|PA)$", "", params)
        if pe_dirs:
            params = f"{params}; PE {'/'.join(pe_dirs)}"
        rows.append(
            Row(
                "Functional",
                f"Control fMRI ({len(controls)} runs)",
                "Control functional acquisition",
                params,
            )
        )

    # --- Diffusion ---
    dwi_main = by_desc.get("gsld_76dir_b2000_1mmiso_AP")
    dwi_b0 = by_desc.get("gsld_75TE_PA_3b0")
    resolve_ap = by_desc.get("resolve_3scan_trace_tra_p3_160_1.4iso_AP")
    if dwi_main or dwi_b0 or resolve_ap:
        parts = []
        if dwi_main:
            s = dwi_main
            parts.append(
                "; ".join(
                    p
                    for p in [
                        f"TR {_fmt_num(_num(s['tr']), 0)} ms" if _num(s["tr"]) else None,
                        f"TE {_fmt_num(_num(s['te']), 0)} ms" if _num(s["te"]) else None,
                        "76 directions; b = 2000 s/mm²",
                        "1 mm isotropic (protocol)",
                        "PE AP",
                    ]
                    if p
                )
            )
        if dwi_b0:
            parts.append("reverse-PE b0 (PA; 3 volumes)")
        if resolve_ap and not dwi_main:
            s = resolve_ap
            res = _resolution_mm(
                _pixel_spacing(s["pixel_spacing"]), _num(s["slice_thickness"])
            )
            parts.append(
                "; ".join(
                    p
                    for p in [
                        f"TR {_fmt_num(_num(s['tr']), 0)} ms" if _num(s["tr"]) else None,
                        f"TE {_fmt_num(_num(s['te']), 0)} ms" if _num(s["te"]) else None,
                        res,
                        "RESOLVE",
                    ]
                    if p
                )
            )
        elif resolve_ap and dwi_main:
            parts.append("additional RESOLVE trace acquisition")
        rows.append(
            Row(
                "Diffusion",
                "Diffusion-weighted MRI",
                "Diffusion-weighted imaging",
                "; ".join(parts),
            )
        )

    # --- Calibration (optional but useful) ---
    if "tfl_b1map_1mmiso" in by_desc:
        s = by_desc["tfl_b1map_1mmiso"]
        params = "; ".join(
            p
            for p in [
                f"TR {_fmt_num(_num(s['tr']), 0)} ms" if _num(s["tr"]) else None,
                f"TE {_fmt_num(_num(s['te']), 2)} ms" if _num(s["te"]) else None,
                "turbo flash B1 mapping",
            ]
            if p
        )
        rows.append(Row("Calibration", "B1 map", "Transmit-field calibration", params))

    return rows


def write_markdown(rows: list[Row], scanners: list[dict], path: Path) -> None:
    scanner = next(
        (s for s in scanners if str(s.get("magnetic_field_strength")) == "3"),
        scanners[0] if scanners else {},
    )
    manufacturer = scanner.get("manufacturer", "SIEMENS")
    model = scanner.get("scanner_model", "Prisma")
    field = scanner.get("magnetic_field_strength", "3")
    soft = scanner.get("software_version", "syngo MR E11")

    lines = [
        "# MRI acquisition parameters",
        "",
        f"MRI data were acquired on a {manufacturer} {model} scanner at {field} T "
        f"(software {soft}). Parameters below summarize the session protocol; "
        "identical runs are grouped. Localizers, single-band references, physiological "
        "logs and derived diffusion maps are omitted.",
        "",
        "| Category | Sequence | Purpose | Acquisition parameters |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.category} | {row.sequence} | {row.purpose} | {row.parameters} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def tex_escape(text: str) -> str:
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "°": r"$^{\circ}$",
        "×": r"$\times$",
        "³": r"$^{3}$",
        "²": r"$^{2}$",
        "–": r"--",
        "—": r"---",
    }
    out = []
    for ch in text:
        out.append(repl.get(ch, ch))
    return "".join(out)


def write_latex(rows: list[Row], scanners: list[dict], path: Path) -> None:
    scanner = next(
        (s for s in scanners if str(s.get("magnetic_field_strength")) == "3"),
        scanners[0] if scanners else {},
    )
    manufacturer = scanner.get("manufacturer", "SIEMENS")
    model = scanner.get("scanner_model", "Prisma")
    field = scanner.get("magnetic_field_strength", "3")

    body_rows = []
    for i, row in enumerate(rows):
        prefix = r"\rowcolor{tablealt} " if i % 2 == 1 else ""
        body_rows.append(
            f"{prefix}{tex_escape(row.category)} & {tex_escape(row.sequence)} & "
            f"{tex_escape(row.purpose)} & {tex_escape(row.parameters)} \\\\"
        )

    tex = rf"""% Auto-generated MRI acquisition table for manuscript inclusion.
% Compile with pdflatex. Requires: booktabs, tabularx, xcolor, array, caption, geometry.
\documentclass[11pt]{{article}}
\usepackage[margin=18mm]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{tabularx}}
\usepackage{{array}}
\usepackage[table]{{xcolor}}
\usepackage{{caption}}
\usepackage{{microtype}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern}}

\definecolor{{tablealt}}{{RGB}}{{245,247,250}}
\definecolor{{headergray}}{{RGB}}{{55,65,81}}
\captionsetup{{font=small,labelfont=bf,skip=6pt}}

\newcolumntype{{L}}[1]{{>{{\raggedright\arraybackslash}}p{{#1}}}}
\newcolumntype{{Y}}{{>{{\raggedright\arraybackslash}}X}}

\begin{{document}}
\pagestyle{{empty}}
\setlength{{\tabcolsep}}{{5pt}}
\renewcommand{{\arraystretch}}{{1.22}}

\begin{{table}}[htbp]
\centering
\caption{{MRI acquisition parameters. Data were acquired on a {tex_escape(str(manufacturer))} {tex_escape(str(model))} scanner at {tex_escape(str(field))}\,T. Identical functional runs are grouped. Localizers, single-band reference images, physiological logs and derived diffusion maps are omitted.}}
\label{{tab:mri_acquisition}}
\begin{{tabularx}}{{\textwidth}}{{@{{}}L{{2.0cm}}L{{3.5cm}}L{{3.2cm}}Y@{{}}}}
\toprule
\textcolor{{headergray}}{{\textbf{{Category}}}} &
\textcolor{{headergray}}{{\textbf{{Sequence}}}} &
\textcolor{{headergray}}{{\textbf{{Purpose}}}} &
\textcolor{{headergray}}{{\textbf{{Acquisition parameters}}}} \\
\midrule
{chr(10).join(body_rows)}
\bottomrule
\end{{tabularx}}
\end{{table}}

\end{{document}}
"""
    path.write_text(tex, encoding="utf-8")


def write_docx_via_pandoc(md_path: Path, docx_path: Path) -> None:
    subprocess.run(
        ["pandoc", str(md_path), "-o", str(docx_path), "--from", "markdown", "--to", "docx"],
        check=True,
    )


def compile_pdf(tex_path: Path, pdf_path: Path) -> None:
    work = tex_path.parent
    for _ in range(2):
        proc = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex_path.name],
            cwd=work,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 and "Output written on" not in (proc.stdout + proc.stderr):
            raise RuntimeError(proc.stdout[-2000:] + "\n" + proc.stderr[-1000:])
    produced = work / (tex_path.stem + ".pdf")
    if not produced.exists():
        raise RuntimeError("pdflatex did not produce a PDF")
    if produced.resolve() != pdf_path.resolve():
        pdf_path.write_bytes(produced.read_bytes())
    for ext in (".aux", ".log", ".out"):
        aux = work / (tex_path.stem + ext)
        if aux.exists():
            aux.unlink()


def render_png(pdf_path: Path, png_path: Path) -> None:
    # Density must precede the PDF input for correct rasterization DPI.
    subprocess.run(
        [
            "magick",
            "-density",
            "300",
            str(pdf_path) + "[0]",
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
            "-quality",
            "100",
            str(png_path),
        ],
        check=True,
    )


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    rows = build_rows(data["sequences"])
    scanners = data.get("scanners", [])

    md = OUT / "MRI_Acquisition_Table.md"
    tex = OUT / "MRI_Acquisition_Table.tex"
    docx = OUT / "MRI_Acquisition_Table.docx"
    pdf = OUT / "MRI_Acquisition_Table.pdf"
    png = OUT / "MRI_Acquisition_Table.png"

    write_markdown(rows, scanners, md)
    write_latex(rows, scanners, tex)
    write_docx_via_pandoc(md, docx)
    compile_pdf(tex, pdf)
    render_png(pdf, png)

    print(f"Wrote {len(rows)} rows to {OUT}")
    for p in (md, tex, docx, pdf, png):
        print(f"  {p} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
