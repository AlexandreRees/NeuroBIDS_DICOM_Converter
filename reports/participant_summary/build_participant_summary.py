#!/usr/bin/env python3
"""Build publication-ready participant demographic and longitudinal tables.

Sources (no DICOM re-read):
  metadata/participant_mapping.csv
  metadata/sessions.tsv
  metadata/participants_preview.tsv (optional sex cross-check)

Presentation follows clinical baseline-characteristics style:
  variables as rows, cohorts as columns.

Regenerate whenever mapping/session tables change:
  python reports/participant_summary/build_participant_summary.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path("/home/alexrees/scratch")
META = ROOT / "metadata"
OUT = ROOT / "reports" / "participant_summary"
OUT.mkdir(parents=True, exist_ok=True)

# Internal cohort keys (pipeline labels) in manuscript column order
COHORT_KEYS = ["Control", "Data_ON", "Data_TON", "Glaucoma"]

# Display names for manuscript columns
COHORT_DISPLAY = {
    "Control": "Control",
    "Data_ON": "Optic neuritis (ON)",
    "Data_TON": "Traumatic optic neuropathy (TON)",
    "DataON": "Optic neuritis (ON)",  # legacy alias
    "DataTON": "Traumatic optic neuropathy (TON)",
    "Glaucoma": "Glaucoma",
    "Total": "Total",
}


def _tex_escape(text: str) -> str:
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
        "\u00b1": r"$\pm$",  # ±
        "\u2265": r"$\geq$",  # ≥
        "\u2013": r"--",  # en-dash
        "\u2014": r"---",  # em-dash
    }
    return "".join(repl.get(ch, ch) for ch in str(text))


def _tex_header(text: str) -> str:
    """Multi-line centered headers for long cohort names (fits equal-width X cols)."""
    t = str(text)
    if t.startswith("Traumatic optic neuropathy"):
        return (
            r"\shortstack[c]{"
            + _tex_escape("Traumatic optic")
            + r"\\"
            + _tex_escape("neuropathy")
            + r"\\"
            + _tex_escape("(TON)")
            + "}"
        )
    if t.startswith("Optic neuritis"):
        return (
            r"\shortstack[c]{"
            + _tex_escape("Optic neuritis")
            + r"\\"
            + _tex_escape("(ON)")
            + "}"
        )
    return _tex_escape(t)


def _tex_cell(text: str, *, first_col: bool) -> str:
    """Escape cell text; keep numeric cohort values on one line."""
    esc = _tex_escape(text)
    if first_col:
        return esc
    # Compact ± spacing in TeX so mean±SD fits equal-width columns
    esc = esc.replace(r" $\pm$ ", r"$\pm$")
    return rf"\mbox{{{esc}}}"


def _fmt_n_pct(n: int, denom: int) -> str:
    if denom <= 0:
        return f"{n}"
    return f"{n} ({100.0 * n / denom:.1f}%)"


def _fmt_mean_sd(mean: float, sd: float) -> str:
    return f"{mean:.2f} ± {sd:.2f}"


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    participants = pd.read_csv(META / "participant_mapping.csv", dtype=str).fillna("")
    sessions = pd.read_csv(META / "sessions.tsv", sep="\t", dtype=str).fillna("")
    alias = {"DataON": "Data_ON", "DataTON": "Data_TON"}
    if "cohort" in participants.columns:
        participants["cohort"] = participants["cohort"].replace(alias)
    if "cohort" in sessions.columns:
        sessions["cohort"] = sessions["cohort"].replace(alias)
    # Prefer preview sex if present and non-empty
    preview = META / "participants_preview.tsv"
    if preview.is_file():
        prev = pd.read_csv(preview, sep="\t", dtype=str).fillna("")
        if {"participant_id", "sex"}.issubset(prev.columns):
            sex_map = dict(zip(prev["participant_id"], prev["sex"]))
            participants = participants.copy()
            participants["patient_sex"] = participants.apply(
                lambda r: sex_map.get(r["participant_id"], r.get("patient_sex", ""))
                or r.get("patient_sex", ""),
                axis=1,
            )
        if "age" in prev.columns and "age" not in participants.columns:
            participants = participants.merge(
                prev[["participant_id", "age"]], on="participant_id", how="left"
            )
    # Dedicated age extraction table (preferred source when present)
    age_path = META / "participant_age.tsv"
    if age_path.is_file():
        ages = pd.read_csv(age_path, sep="\t", dtype=str).fillna("")
        if {"participant_id", "age"}.issubset(ages.columns):
            participants = participants.drop(columns=["age"], errors="ignore")
            participants = participants.merge(
                ages[["participant_id", "age"]], on="participant_id", how="left"
            )
    return participants, sessions


def _prepare_demo(
    participants: pd.DataFrame, sessions: pd.DataFrame
) -> tuple[pd.DataFrame, list[str], bool]:
    """Shared extraction: session counts, sex, cohort; age only if present."""
    sess_counts = (
        sessions.groupby("participant_id", sort=False)
        .size()
        .rename("n_sessions")
        .reset_index()
    )
    demo = participants.merge(sess_counts, on="participant_id", how="left")
    demo["n_sessions"] = pd.to_numeric(demo["n_sessions"], errors="coerce").fillna(0).astype(int)
    demo["sex"] = demo["patient_sex"].astype(str).str.strip().str.upper()
    demo["cohort"] = demo["cohort"].astype(str).str.strip()

    if "age" in demo.columns:
        demo["age_num"] = pd.to_numeric(demo["age"], errors="coerce")
        age_available = bool(demo["age_num"].notna().any())
    else:
        demo["age_num"] = pd.NA
        age_available = False

    cohorts = [c for c in COHORT_KEYS if c in set(demo["cohort"])] + sorted(
        set(demo["cohort"]) - set(COHORT_KEYS)
    )
    return demo, cohorts, age_available


def _age_cell(sub: pd.DataFrame, age_available: bool) -> str:
    n = len(sub)
    if not age_available:
        return "Not available"
    ages = pd.to_numeric(sub.get("age_num"), errors="coerce").dropna()
    if len(ages) == 0:
        age_cell = "Not available"
    elif len(ages) == 1:
        age_cell = f"{float(ages.iloc[0]):.1f}"
    else:
        age_cell = _fmt_mean_sd(float(ages.mean()), float(ages.std(ddof=1)))
    if len(ages) < n:
        age_cell = f"{age_cell} (n={len(ages)})"
    return age_cell


def _cohort_stats(sub: pd.DataFrame, age_available: bool) -> dict:
    """Per-cohort statistics (unchanged calculations)."""
    n = len(sub)
    female = int((sub["sex"] == "F").sum())
    male = int((sub["sex"] == "M").sum())
    sess_mean = float(sub["n_sessions"].mean()) if n else float("nan")
    sess_sd = float(sub["n_sessions"].std(ddof=1)) if n > 1 else 0.0
    n1 = int((sub["n_sessions"] == 1).sum())
    n2 = int((sub["n_sessions"] == 2).sum())
    n_ge3 = int((sub["n_sessions"] >= 3).sum())
    total_sessions = int(sub["n_sessions"].sum())
    return {
        "n": n,
        "female": female,
        "male": male,
        "sess_mean": sess_mean,
        "sess_sd": sess_sd,
        "n1": n1,
        "n2": n2,
        "n_ge3": n_ge3,
        "total_sessions": total_sessions,
        "age": _age_cell(sub, age_available),
    }


def _session_ids_by_label(sessions: pd.DataFrame) -> dict[str, set[str]]:
    """Map session_id label -> set of participant_ids present for that session."""
    out: dict[str, set[str]] = {}
    for sid in ("ses-01", "ses-02"):
        out[sid] = set(
            sessions.loc[sessions["session_id"] == sid, "participant_id"].astype(str)
        )
    return out


def _demo_for_session(
    demo: pd.DataFrame, session_pids: set[str], cohort: str | None
) -> pd.DataFrame:
    """Participants present for a given session, optionally restricted to one cohort."""
    sub = demo[demo["participant_id"].isin(session_pids)]
    if cohort is not None:
        sub = sub[sub["cohort"] == cohort]
    return sub


def _session_cohort_stats(
    demo: pd.DataFrame,
    sid_map: dict[str, set[str]],
    cohort_key: str | None,
    age_available: bool,
) -> dict[str, dict[str, str]]:
    """Per-session stats for one cohort (or Total when cohort_key is None)."""
    out: dict[str, dict[str, str]] = {}
    for sid in ("ses-01", "ses-02"):
        sub = _demo_for_session(demo, sid_map[sid], cohort_key)
        n = len(sub)
        female = int((sub["sex"] == "F").sum())
        male = int((sub["sex"] == "M").sum())
        out[sid] = {
            "n": str(n),
            "age": _age_cell(sub, age_available),
            "female": _fmt_n_pct(female, n) if n else "0",
            "male": _fmt_n_pct(male, n) if n else "0",
        }
    return out


def _drop_age_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove age characteristic rows (matched on Characteristic column)."""
    mask = ~df["Characteristic"].astype(str).str.startswith("Age")
    return df.loc[mask].reset_index(drop=True)


def compute_tables(
    participants: pd.DataFrame, sessions: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute clinical-style tables (cohorts as columns).

    Returns:
      table1: demographics with ses-01/ses-02 n under Participants (no sessions mean±SD)
      table1_by_session: demographics with ses-01/ses-02 columns per cohort
      table2: longitudinal availability
      table3: per-participant session list
    """
    demo, cohorts, age_available = _prepare_demo(participants, sessions)
    sid_map = _session_ids_by_label(sessions)

    stats: dict[str, dict] = {}
    for cohort in cohorts:
        stats[cohort] = _cohort_stats(demo[demo["cohort"] == cohort], age_available)
    stats["Total"] = _cohort_stats(demo, age_available)

    # Session attendance counts per cohort (and total)
    sess_n: dict[str, dict[str, int]] = {sid: {} for sid in ("ses-01", "ses-02")}
    for cohort in cohorts:
        for sid, pids in sid_map.items():
            sess_n[sid][cohort] = int(
                len(_demo_for_session(demo, pids, cohort))
            )
    for sid, pids in sid_map.items():
        sess_n[sid]["Total"] = int(len(_demo_for_session(demo, pids, None)))

    col_keys = cohorts + ["Total"]
    col_names = [COHORT_DISPLAY.get(k, k) for k in col_keys]

    # ----- Table 1: Participant demographic characteristics -----
    # Sessions-per-participant mean±SD removed; ses-01/ses-02 n added under Participants.
    demo_rows = [
        "Participants, n",
        "ses-01 / ses-02, n",
        "Age, mean ± SD (years)",
        "Female, n (%)",
        "Male, n (%)",
    ]
    t1_data = {"Characteristic": demo_rows}
    for key, name in zip(col_keys, col_names):
        s = stats[key]
        n = s["n"]
        t1_data[name] = [
            str(n),
            f"{sess_n['ses-01'][key]} / {sess_n['ses-02'][key]}",
            s["age"],
            _fmt_n_pct(s["female"], n),
            _fmt_n_pct(s["male"], n),
        ]
    table1 = pd.DataFrame(t1_data)

    # ----- Table 1b: Demographics with ses-01 / ses-02 columns per cohort -----
    by_sess_rows = [
        "Participants, n",
        "Age, mean ± SD (years)",
        "Female, n (%)",
        "Male, n (%)",
    ]
    row_keys = ["n", "age", "female", "male"]
    t1b_data: dict[str, list] = {"Characteristic": by_sess_rows}
    for key, name in zip(col_keys, col_names):
        cohort_key = None if key == "Total" else key
        sess_stats = _session_cohort_stats(demo, sid_map, cohort_key, age_available)
        for sid in ("ses-01", "ses-02"):
            col = f"{name} {sid}"
            t1b_data[col] = [sess_stats[sid][rk] for rk in row_keys]
    table1_by_session = pd.DataFrame(t1b_data)

    # ----- Table 2: Longitudinal data availability -----
    long_rows = [
        "Participants with 1 session, n (%)",
        "Participants with 2 sessions, n (%)",
        "Participants with ≥3 sessions, n (%)",
        "Total number of imaging sessions",
        "Mean sessions per participant",
    ]
    t2_data = {"Characteristic": long_rows}
    for key, name in zip(col_keys, col_names):
        s = stats[key]
        n = s["n"]
        t2_data[name] = [
            _fmt_n_pct(s["n1"], n),
            _fmt_n_pct(s["n2"], n),
            _fmt_n_pct(s["n_ge3"], n),
            str(s["total_sessions"]),
            f"{s['sess_mean']:.2f}",
        ]
    table2 = pd.DataFrame(t2_data)

    # ----- Supplementary: per-participant list (unchanged layout) -----
    table3 = (
        demo[["participant_id", "cohort", "n_sessions"]]
        .rename(
            columns={
                "participant_id": "Participant ID",
                "cohort": "Cohort",
                "n_sessions": "Number of sessions",
            }
        )
        .sort_values(["Cohort", "Participant ID"], kind="mergesort")
        .reset_index(drop=True)
    )
    return table1, table1_by_session, table2, table3


def _write_xlsx(path: Path, df: pd.DataFrame, sheet_name: str = "Sheet1") -> None:
    """Write a minimal .xlsx using the standard library (no openpyxl required)."""
    import zipfile
    from xml.sax.saxutils import escape

    def col_name(idx: int) -> str:
        name = ""
        n = idx
        while True:
            n, rem = divmod(n, 26)
            name = chr(65 + rem) + name
            if n == 0:
                break
            n -= 1
        return name

    rows_xml = []
    header_cells = []
    for j, col in enumerate(df.columns):
        ref = f"{col_name(j)}1"
        header_cells.append(
            f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(col))}</t></is></c>'
        )
    rows_xml.append(f'<row r="1">{"".join(header_cells)}</row>')
    for i, row in enumerate(df.itertuples(index=False), start=2):
        cells = []
        for j, value in enumerate(row):
            ref = f"{col_name(j)}{i}"
            text = "" if value is None else str(value)
            if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
                cells.append(f'<c r="{ref}"><v>{text}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'
                )
        rows_xml.append(f'<row r="{i}">{"".join(cells)}</row>')

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        + "".join(rows_xml)
        + "</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)


def write_csv_xlsx_md(name: str, df: pd.DataFrame, title: str, note: str = "") -> None:
    csv_path = OUT / f"{name}.csv"
    xlsx_path = OUT / f"{name}.xlsx"
    md_path = OUT / f"{name}.md"
    df.to_csv(csv_path, index=False)
    _write_xlsx(xlsx_path, df, sheet_name=name[:31])
    lines = [f"# {title}", ""]
    if note:
        lines.extend([note, ""])
    headers = list(df.columns)
    lines.append("| " + " | ".join(str(h) for h in headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def write_latex_table(
    name: str,
    df: pd.DataFrame,
    *,
    caption: str,
    label: str,
    col_spec: str,
    wrap_headers: bool = True,
    clinical_layout: bool = False,
    session_pair_headers: bool = False,
) -> Path:
    tex_path = OUT / f"{name}.tex"
    body = []
    for i, row in enumerate(df.itertuples(index=False)):
        shade = r"\rowcolor{tablealt} " if i % 2 == 1 else ""
        cells_list = [
            _tex_cell(v, first_col=(j == 0)) if clinical_layout else _tex_escape(v)
            for j, v in enumerate(row)
        ]
        body.append(f"{shade}{' & '.join(cells_list)} \\\\")

    # Detect cohort+session paired columns: "<Cohort> ses-01", "<Cohort> ses-02", ...
    pair_groups: list[tuple[str, str, str]] = []
    if session_pair_headers:
        data_cols = list(df.columns[1:])
        if len(data_cols) % 2 != 0:
            raise ValueError("session_pair_headers requires an even number of data columns")
        for i in range(0, len(data_cols), 2):
            c1, c2 = data_cols[i], data_cols[i + 1]
            if not (str(c1).endswith(" ses-01") and str(c2).endswith(" ses-02")):
                raise ValueError(f"Expected ses-01/ses-02 column pair, got {c1!r}, {c2!r}")
            cohort = str(c1)[: -len(" ses-01")]
            pair_groups.append((cohort, str(c1), str(c2)))

    if session_pair_headers and pair_groups:
        top_bits = [
            rf"\textcolor{{headergray}}{{\textbf{{{_tex_escape(df.columns[0])}}}}}"
        ]
        for cohort, _, _ in pair_groups:
            top_bits.append(
                rf"\multicolumn{{2}}{{c}}{{\textcolor{{headergray}}{{\textbf{{{_tex_header(cohort)}}}}}}}"
            )
        top_header = " & ".join(top_bits) + r" \\"
        # cmidrules between cohort pairs (cols 2-3, 4-5, ...; 1-indexed in booktabs)
        cmid = " ".join(
            rf"\cmidrule(lr){{{2 + 2 * i}-{3 + 2 * i}}}" for i in range(len(pair_groups))
        )
        sub_bits = [""]  # empty under Characteristic
        for _ in pair_groups:
            sub_bits.append(
                rf"\textcolor{{headergray}}{{\textbf{{{_tex_escape('ses-01')}}}}}"
            )
            sub_bits.append(
                rf"\textcolor{{headergray}}{{\textbf{{{_tex_escape('ses-02')}}}}}"
            )
        sub_header = " & ".join(sub_bits) + r" \\"
        header_block = f"{top_header}\n{cmid}\n{sub_header}"
    else:
        header_bits = []
        for j, c in enumerate(df.columns):
            if j == 0:
                header_bits.append(
                    rf"\textcolor{{headergray}}{{\textbf{{{_tex_escape(c)}}}}}"
                )
            elif wrap_headers:
                header_bits.append(
                    rf"\textcolor{{headergray}}{{\textbf{{{_tex_header(str(c))}}}}}"
                )
            else:
                header_bits.append(
                    rf"\textcolor{{headergray}}{{\textbf{{{_tex_escape(c)}}}}}"
                )
        header_block = " & ".join(header_bits) + r" \\"

    # Equal-width centered X columns for cohort data; flexible X for row labels.
    # Coefficients sum to n_X so tabularx allocates width correctly.
    if clinical_layout:
        n_data = len(df.columns) - 1
        # Label column moderately wider; cohort columns share the rest equally.
        # Shares must sum to (n_data + 1) for tabularx.
        label_share = 1.35 if session_pair_headers else 1.20
        data_share = (n_data + 1 - label_share) / n_data
        col_defs = (
            rf"\newcolumntype{{Y}}{{>{{\raggedright\arraybackslash\hsize={label_share:.3f}\hsize}}X}}"
            "\n"
            rf"\newcolumntype{{C}}{{>{{\centering\arraybackslash\hsize={data_share:.3f}\hsize}}X}}"
        )
        col_spec = "Y" + ("C" * n_data)
        tabcolsep = "1.6pt" if session_pair_headers else "2.8pt"
        geometry = "margin=12mm" if session_pair_headers else "margin=18mm"
        table_font = r"\footnotesize" if session_pair_headers else r"\small"
        # Tiny clamp absorbs residual booktabs/xcolor padding (~few pt)
        use_resizebox = True
    else:
        col_defs = (
            r"\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}"
            "\n"
            r"\newcolumntype{Y}{>{\raggedright\arraybackslash}X}"
            "\n"
            r"\newcolumntype{C}[1]{>{\centering\arraybackslash}p{#1}}"
        )
        tabcolsep = "5pt"
        geometry = "margin=18mm"
        table_font = ""
        use_resizebox = False

    if use_resizebox:
        table_body = rf"""\noindent\resizebox{{\textwidth}}{{!}}{{%
\begin{{tabularx}}{{\textwidth}}{{{col_spec}}}
\toprule
{header_block}
\midrule
{chr(10).join(body)}
\bottomrule
\end{{tabularx}}%
}}"""
    else:
        table_body = rf"""\begin{{tabularx}}{{\textwidth}}{{{col_spec}}}
\toprule
{header_block}
\midrule
{chr(10).join(body)}
\bottomrule
\end{{tabularx}}"""

    tex = rf"""% Auto-generated participant summary table for manuscript inclusion.
% Standalone compile for PDF/PNG preview; table body is Overleaf-compatible.
\documentclass[11pt]{{article}}
\usepackage[{geometry}]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{tabularx}}
\usepackage{{array}}
\usepackage{{graphicx}}
\usepackage[table]{{xcolor}}
\usepackage{{caption}}
\usepackage{{microtype}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern}}

\definecolor{{tablealt}}{{RGB}}{{245,247,250}}
\definecolor{{headergray}}{{RGB}}{{55,65,81}}
\captionsetup{{font=small,labelfont=bf,skip=8pt,width=\textwidth}}
{col_defs}

\begin{{document}}
\pagestyle{{empty}}
\setlength{{\tabcolsep}}{{{tabcolsep}}}
\renewcommand{{\arraystretch}}{{1.28}}
\setlength{{\extrarowheight}}{{1pt}}

\begin{{table}}[htbp]
\centering
\caption{{{_tex_escape(caption)}}}
\label{{{label}}}
{table_font}
{table_body}
\end{{table}}
\end{{document}}
"""
    tex_path.write_text(tex, encoding="utf-8")
    return tex_path


def compile_pdf_png(tex_path: Path) -> None:
    work = tex_path.parent
    for _ in range(2):
        proc = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex_path.name],
            cwd=work,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0 and "Output written on" not in (proc.stdout + proc.stderr):
            raise RuntimeError(proc.stdout[-2000:] + "\n" + proc.stderr[-1000:])
    pdf = work / f"{tex_path.stem}.pdf"
    png = work / f"{tex_path.stem}.png"
    # 300 dpi; trim whitespace then add margins so edges are not cropped
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
        aux = work / f"{tex_path.stem}{ext}"
        if aux.exists():
            aux.unlink()


def main() -> None:
    participants, sessions = load_inputs()
    table1, table1_by_session, table2, table3 = compute_tables(participants, sessions)
    table1_no_age = _drop_age_rows(table1)
    table1_by_session_no_age = _drop_age_rows(table1_by_session)

    note = (
        "Age is mean ± SD from `metadata/participant_age.tsv` (first-session T1 DICOM). "
        "When age coverage is incomplete within a cohort, n is shown. "
        "Sex and session counts are computed from `participant_mapping.csv` and `sessions.tsv`. "
        "ses-01 / ses-02, n = number of participants with imaging at each session. "
        "Cohort columns use manuscript labels: Data_ON → Optic neuritis (ON); "
        "Data_TON → Traumatic optic neuropathy (TON)."
    )
    note_by_session = (
        "Each cohort has paired ses-01 and ses-02 columns. "
        "Age is the first-session T1-derived age for each participant present at that session. "
        "Sex and session counts are computed from `participant_mapping.csv` and `sessions.tsv`. "
        "Cohort columns use manuscript labels: Data_ON → Optic neuritis (ON); "
        "Data_TON → Traumatic optic neuropathy (TON)."
    )
    note_no_age = (
        "Age row omitted. Sex and session counts from `participant_mapping.csv` and "
        "`sessions.tsv`. Cohort labels: Data_ON → Optic neuritis (ON); "
        "Data_TON → Traumatic optic neuropathy (TON)."
    )
    note_by_session_no_age = (
        "Age row omitted. Each cohort has paired ses-01 and ses-02 columns. "
        "Sex and session counts from `participant_mapping.csv` and `sessions.tsv`."
    )

    outputs = [
        (
            "Participant_Demographics",
            table1,
            "Participant demographic characteristics",
            note,
        ),
        (
            "Participant_Demographics_no_age",
            table1_no_age,
            "Participant demographic characteristics (no age)",
            note_no_age,
        ),
        (
            "Participant_Demographics_by_Session",
            table1_by_session,
            "Participant demographic characteristics by session",
            note_by_session,
        ),
        (
            "Participant_Demographics_by_Session_no_age",
            table1_by_session_no_age,
            "Participant demographic characteristics by session (no age)",
            note_by_session_no_age,
        ),
        ("Longitudinal_Summary", table2, "Longitudinal data availability", ""),
        ("Participant_Session_List", table3, "Participant session list", ""),
    ]
    for name, df, title, ntxt in outputs:
        write_csv_xlsx_md(name, df, title, note=ntxt)

    # Clinical baseline: tabularx equal-width cohort columns (built in write_latex_table)
    clinical_spec = ""  # overridden when clinical_layout=True

    specs = [
        (
            "Participant_Demographics",
            table1,
            "Participant demographic characteristics by cohort. Age is derived from the first-session T1-weighted anatomical DICOM (PatientAge, else BirthDate+StudyDate). ses-01 / ses-02, n reports the number of participants imaged at each session. Values are n, n (%), or mean ± SD as indicated.",
            "tab:participant_demographics",
            clinical_spec,
            True,
            True,
            False,
        ),
        (
            "Participant_Demographics_no_age",
            table1_no_age,
            "Participant demographic characteristics by cohort (age omitted). ses-01 / ses-02, n reports the number of participants imaged at each session. Values are n or n (%) as indicated.",
            "tab:participant_demographics_no_age",
            clinical_spec,
            True,
            True,
            False,
        ),
        (
            "Participant_Demographics_by_Session",
            table1_by_session,
            "Participant demographic characteristics by cohort and imaging session. Each cohort has ses-01 and ses-02 columns. Age is the first-session T1-derived age for each participant present at that session. Values are n, n (%), or mean ± SD as indicated.",
            "tab:participant_demographics_by_session",
            clinical_spec,
            True,
            True,
            True,
        ),
        (
            "Participant_Demographics_by_Session_no_age",
            table1_by_session_no_age,
            "Participant demographic characteristics by cohort and imaging session (age omitted). Each cohort has ses-01 and ses-02 columns. Values are n or n (%) as indicated.",
            "tab:participant_demographics_by_session_no_age",
            clinical_spec,
            True,
            True,
            True,
        ),
        (
            "Longitudinal_Summary",
            table2,
            "Longitudinal data availability by cohort. Percentages are within-cohort proportions of participants. No participant currently has three or more imaging sessions.",
            "tab:longitudinal_summary",
            clinical_spec,
            True,
            True,
            False,
        ),
        (
            "Participant_Session_List",
            table3,
            "Per-participant cohort membership and number of imaging sessions.",
            "tab:participant_session_list",
            r"@{}L{3.2cm}L{3.0cm}Y@{}",
            False,
            False,
            False,
        ),
    ]

    for name, df, caption, label, col_spec, wrap_headers, clinical, sess_hdrs in specs:
        tex = write_latex_table(
            name,
            df,
            caption=caption,
            label=label,
            col_spec=col_spec,
            wrap_headers=wrap_headers,
            clinical_layout=clinical,
            session_pair_headers=sess_hdrs,
        )
        compile_pdf_png(tex)
        print(f"Wrote {name} ({len(df)} rows × {len(df.columns)} cols)")

    summary = OUT / "README.md"
    summary.write_text(
        "\n".join(
            [
                "# Participant summary tables",
                "",
                "Auto-generated from pipeline metadata (no DICOM re-read).",
                "Clinical baseline-characteristics layout: variables as rows, cohorts as columns.",
                "",
                "## Sources",
                "",
                "- `metadata/participant_mapping.csv`",
                "- `metadata/sessions.tsv`",
                "- `metadata/participants_preview.tsv` (sex cross-check when present)",
                "",
                "## Tables",
                "",
                "1. **Participant_Demographics** — Demographics with ses-01/ses-02 attendance n",
                "2. **Participant_Demographics_no_age** — Same as (1) without the age row",
                "3. **Participant_Demographics_by_Session** — Demographics with ses-01/ses-02 columns per cohort",
                "4. **Participant_Demographics_by_Session_no_age** — Same as (3) without the age row",
                "5. **Longitudinal_Summary** — Longitudinal data availability",
                "6. **Participant_Session_List** — Per-participant session counts (supplementary)",
                "",
                "## Cohort column labels",
                "",
                "| Pipeline label | Manuscript column |",
                "|---|---|",
                "| Control | Control |",
                "| Data_ON | Optic neuritis (ON) |",
                "| Data_TON | Traumatic optic neuropathy (TON) |",
                "| Glaucoma | Glaucoma |",
                "",
                "## Regenerate",
                "",
                "```bash",
                "python ~/scratch/reports/participant_summary/build_participant_summary.py",
                "```",
                "",
                "## Notes",
                "",
                "- Age is loaded from `metadata/participant_age.tsv` when present; cells are not fabricated.",
                "- One Control participant (sub-043) has ses-02 only (no ses-01), so Total ses-01 n = 83.",
                f"- Participants: **{len(participants)}**; sessions: **{len(sessions)}**.",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
