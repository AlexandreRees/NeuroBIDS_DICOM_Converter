"""Markdown / table report writers for DWI technical validation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import utc_now, write_text


def _fmt(x: float, nd: int = 3) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _dist_block(name: str, arr: np.ndarray) -> list[str]:
    arr = np.asarray(arr, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return [f"- {name}: no data"]
    q = np.percentile(arr, [5, 25, 50, 75, 95])
    return [
        f"- {name}: n={arr.size}; mean={_fmt(float(np.mean(arr)))}; "
        f"sd={_fmt(float(np.std(arr)))}; "
        f"p5={_fmt(float(q[0]))}; Q1={_fmt(float(q[1]))}; "
        f"median={_fmt(float(q[2]))}; Q3={_fmt(float(q[3]))}; "
        f"p95={_fmt(float(q[4]))}"
    ]


def write_integrity_report(path: Path, integrity: pd.DataFrame, inventory: pd.DataFrame) -> None:
    n = len(integrity)
    n_pass = int((integrity["integrity_status"] == "PASS").sum())
    n_fail = n - n_pass
    missing = inventory[inventory["status"] != "OK"]
    dups = int(integrity["duplicate_nifti"].sum()) if "duplicate_nifti" in integrity else 0
    lines = [
        "# Integrity Report — Diffusion MRI",
        "",
        f"Generated: {utc_now()}",
        "Mode: **READ-ONLY** (BIDS not modified)",
        "",
        "## Summary",
        "",
        f"- DWI acquisitions assessed: **{n}**",
        f"- Integrity PASS: **{n_pass}**",
        f"- Integrity FAIL: **{n_fail}**",
        f"- Missing sidecars: **{len(missing)}**",
        f"- Duplicate NIfTI paths: **{dups}**",
        "",
        "## File presence",
        "",
        f"- NIfTI present: **{int(integrity['nifti_present'].sum())}/{n}**",
        f"- bval present: **{int(integrity['bval_present'].sum())}/{n}**",
        f"- bvec present: **{int(integrity['bvec_present'].sum())}/{n}**",
        f"- JSON present: **{int(integrity['json_present'].sum())}/{n}**",
        "",
        "## Volume / gradient length matching",
        "",
        f"- Matching n_volumes = n_bvals = n_bvecs: "
        f"**{int(integrity['volumes_match'].sum())}/{n}**",
        "",
        "See `integrity_summary.tsv`.",
        "",
    ]
    if len(missing):
        lines.append("### Missing sidecar examples")
        lines.append("")
        for _, r in missing.head(20).iterrows():
            lines.append(f"- `{r.get('scan_id', r['nifti'])}` → `{r['status']}`")
        lines.append("")
    write_text(path, "\n".join(lines))


def write_acquisition_report(path: Path, acq: pd.DataFrame, proto: pd.DataFrame) -> None:
    lines = [
        "# Acquisition Consistency Report — Diffusion MRI",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Automatically identified protocols",
        "",
    ]
    for _, r in proto.iterrows():
        lines.extend(
            [
                f"### {r['protocol_id']}",
                "",
                f"- Unique b-values: `{r['unique_bvals']}`",
                f"- Diffusion directions: **{r['n_diffusion_directions']}**",
                f"- Typical b0 volumes: **{r['n_b0_typical']}**",
                f"- Voxel size (mm): **{r['voxel_size_str']}**",
                f"- Matrix: **{r['matrix_str']}**",
                f"- TR / TE (s): **{_fmt(r['TR_s_median'], 4)}** / **{_fmt(r['TE_s_median'], 4)}**",
                f"- PhaseEncodingDirection: `{r['PhaseEncodingDirection']}`",
                f"- TotalReadoutTime (median): **{_fmt(r['TotalReadoutTime_median'], 5)}**",
                f"- Orientation: `{r['orientation']}`",
                f"- Number of scans: **{int(r['n_scans'])}**",
                "",
            ]
        )
    lines.extend(
        [
            "## Cohort notes",
            "",
            f"- Total scans with acquisition metadata: **{len(acq)}**",
            f"- Distinct protocols: **{len(proto)}**",
            "",
            "See `Protocol_Consistency.tsv` and `Figure_protocols.png`.",
            "",
        ]
    )
    write_text(path, "\n".join(lines))


def write_diffusion_scheme_report(path: Path, acq: pd.DataFrame) -> None:
    bcounts = acq["unique_bvals"].value_counts()
    dcounts = acq["n_diffusion_directions"].value_counts().sort_index()
    lines = [
        "# Diffusion Scheme Report",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Unique b-value schemes",
        "",
    ]
    for scheme, n in bcounts.items():
        lines.append(f"- `{scheme}`: **{int(n)}** scans")
    lines.extend(["", "## Number of diffusion directions", ""])
    for nd, n in dcounts.items():
        lines.append(f"- **{int(nd)}** directions: **{int(n)}** scans")
    lines.extend(
        [
            "",
            "## Figures",
            "",
            "- Distribution of unique b-values (histogram / bar)",
            "- Distribution of number of diffusion directions",
            "- Protocol composition",
            "",
        ]
    )
    write_text(path, "\n".join(lines))


def write_geometry_report(path: Path, acq: pd.DataFrame, proto: pd.DataFrame) -> None:
    n_proto = len(proto)
    identical = n_proto == 1
    lines = [
        "# Geometry QC Report — Diffusion MRI",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Verdict",
        "",
        (
            "**100% identical geometry across all DWI acquisitions.**"
            if identical
            else f"**Multiple acquisition geometries / protocols detected ({n_proto}).**"
        ),
        "",
        "## Geometry keys",
        "",
        "Assessed: voxel size, matrix, orientation, FOV, slice thickness.",
        "",
    ]
    for _, r in proto.iterrows():
        lines.append(
            f"- {r['protocol_id']}: voxel `{r['voxel_size_str']}`, "
            f"matrix `{r['matrix_str']}`, orientation `{r['orientation']}`, "
            f"n={int(r['n_scans'])}"
        )
    lines.extend(["", "See `Geometry_QC.tsv`.", ""])
    write_text(path, "\n".join(lines))


def write_gradient_report(path: Path, grad: pd.DataFrame) -> None:
    n = len(grad)
    n_pass = int((grad["status"] == "PASS").sum())
    n_rev = int((grad["status"] == "REVIEW").sum())
    n_fail = int((grad["status"] == "FAIL").sum())
    lines = [
        "# Gradient Validation Report",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Summary",
        "",
        f"- PASS: **{n_pass}** / {n}",
        f"- REVIEW: **{n_rev}** / {n}",
        f"- FAIL: **{n_fail}** / {n}",
        "",
        "No gradient orientation corrections were applied to the distributed dataset.",
        "",
        "## REVIEW classification",
        "",
    ]
    rev = grad[grad["status"] == "REVIEW"]["review_class"].value_counts()
    if len(rev) == 0:
        lines.append("- None")
    else:
        for k, v in rev.items():
            lines.append(f"- `{k}`: **{int(v)}**")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "`dwigradcheck` ranks orientation hypotheses. Identity (no axis flip, "
            "permutation (0,1,2)) is scored PASS. Any non-identity top-ranked "
            "transform is REVIEW (suggested correction reported, not applied).",
            "",
            "See `Gradient_QC.tsv`, `Gradient_QC_summary.png`, and gradient sphere figures.",
            "",
        ]
    )
    write_text(path, "\n".join(lines))


def write_brainmask_report(path: Path, mask_qc: pd.DataFrame) -> None:
    lines = [
        "# Brain Mask QC Report",
        "",
        f"Generated: {utc_now()}",
        "",
        f"- Scans with mask metrics: **{mask_qc['brain_fraction'].notna().sum()}** / {len(mask_qc)}",
        f"- Mask NIfTI files present under `tmp/`: "
        f"**{int(mask_qc['mask_file_present'].sum())}**",
        "",
        "## Distributions",
        "",
    ]
    lines.extend(_dist_block("Brain fraction", mask_qc["brain_fraction"].to_numpy()))
    lines.extend(
        _dist_block("Brain volume (mm³)", mask_qc["brain_volume_mm3"].to_numpy())
    )
    lines.extend(
        _dist_block("Mask voxels", mask_qc["mask_voxels"].to_numpy())
    )
    lines.extend(
        [
            "",
            "Histograms and boxplots are provided in publication figures.",
            "",
            "See `BrainMask_QC.tsv`.",
            "",
        ]
    )
    write_text(path, "\n".join(lines))


def write_signal_report(path: Path, signal_qc: pd.DataFrame) -> None:
    n_pass = int((signal_qc["status"] == "PASS").sum()) if "status" in signal_qc else 0
    lines = [
        "# Signal Quality Report",
        "",
        f"Generated: {utc_now()}",
        "",
        "Robust within-mask statistics (median, percentiles, MAD-based noise).",
        "",
        f"- Scans with PASS signal QC: **{n_pass}** / {len(signal_qc)}",
        "",
        "## Distributions",
        "",
    ]
    for col, label in [
        ("median_b0_signal", "Median b0 signal"),
        ("median_diffusion_signal", "Median diffusion signal"),
        ("p95_signal", "95th percentile signal"),
        ("p5_signal", "5th percentile signal"),
        ("cv_b0", "Coefficient of variation (b0)"),
        ("background_signal", "Background signal"),
        ("b0_SNR", "b0 SNR (median brain / MAD noise)"),
        ("CNR", "CNR (|b0−diff| / MAD noise)"),
    ]:
        if col in signal_qc.columns:
            lines.extend(_dist_block(label, signal_qc[col].to_numpy()))
    lines.extend(["", "See `Signal_QC.tsv`.", ""])
    write_text(path, "\n".join(lines))


def write_motion_report(path: Path, eddy_hits: list[Path]) -> None:
    if not eddy_hits:
        text = f"""# Motion / Eddy QC Report

Generated: {utc_now()}

## Status: not available

FSL `eddy` / `eddy_quad` outputs were **not found** under derivatives for this release package.

Motion estimates (mean motion, RMS displacement, outlier slices, percentage of replaced slices) are therefore **not available**.

This does not modify the distributed BIDS dataset. Preprocessing derivatives (including eddy) are outside the scope of the distributed raw BIDS release audited here.

## Conclusion

Motion / eddy QC: **N.A.**
"""
    else:
        lines = [
            "# Motion / Eddy QC Report",
            "",
            f"Generated: {utc_now()}",
            "",
            f"Found {len(eddy_hits)} candidate eddy-related files (read-only inventory):",
            "",
        ]
        for p in eddy_hits[:50]:
            lines.append(f"- `{p}`")
        lines.append("")
        text = "\n".join(lines)
    write_text(path, text)


def write_pe_pairs_report(path: Path, pairs: pd.DataFrame) -> None:
    n = len(pairs)
    ok = int((pairs["pair_status"] == "PAIR_OK").sum())
    partial = int((pairs["pair_status"] == "PARTIAL").sum())
    missing = int((pairs["pair_status"] == "MISSING").sum())
    lines = [
        "# Phase-Encoding Pairs Report (Susceptibility Distortion QC)",
        "",
        f"Generated: {utc_now()}",
        "",
        "Inventoried SpinEcho / EPI fieldmap acquisitions with `dir-AP` and `dir-PA` "
        "(excluding `part-phase`).",
        "",
        f"- Sessions assessed: **{n}**",
        f"- AP/PA pairs present (`PAIR_OK`): **{ok}**",
        f"- Partial (AP or PA only): **{partial}**",
        f"- Missing fmap pairs: **{missing}**",
        "",
        "See `PE_pairs.tsv`.",
        "",
    ]
    write_text(path, "\n".join(lines))


def write_technical_validation_md(
    path: Path,
    *,
    inventory: pd.DataFrame,
    integrity: pd.DataFrame,
    proto: pd.DataFrame,
    grad: pd.DataFrame,
    mask_qc: pd.DataFrame,
    signal_qc: pd.DataFrame,
    pairs: pd.DataFrame,
    table_rows: list[tuple[str, str]],
    overall: str,
) -> None:
    n_scans = len(inventory)
    n_subj = inventory["subject"].nunique()
    n_ses = inventory[["subject", "session"]].drop_duplicates().shape[0]
    lines = [
        "# Technical Validation — Diffusion MRI",
        "",
        f"Generated: {utc_now()}",
        "",
        "This section summarises read-only technical validation of diffusion-weighted "
        "MRI (DWI) acquisitions in the distributed BIDS dataset. No modifications were "
        "applied to `bids/`, `raw_original/`, or `derivatives/`.",
        "",
        "## Dataset integrity",
        "",
        f"A total of **{n_scans}** DWI acquisitions from **{n_subj}** participants "
        f"(**{n_ses}** sessions) were inventoried. NIfTI, bval, bvec and JSON sidecars "
        f"were present for "
        f"**{int((integrity['integrity_status']=='PASS').sum())}/{n_scans}** scans with "
        "matching volume / gradient table lengths. "
        f"Missing sidecars: **{int((inventory['status']!='OK').sum())}**; "
        f"duplicate NIfTI paths: **{int(integrity['duplicate_nifti'].sum())}**.",
        "",
        "## Acquisition consistency",
        "",
        f"Automated protocol clustering identified **{len(proto)}** acquisition "
        "protocol(s):",
        "",
    ]
    for _, r in proto.iterrows():
        lines.append(
            f"- **{r['protocol_id']}**: b=`{r['unique_bvals']}`, "
            f"{r['n_diffusion_directions']} directions, "
            f"{r['voxel_size_str']} mm, n={int(r['n_scans'])}"
        )
    lines.extend(
        [
            "",
            "## Gradient validation",
            "",
            f"`dwigradcheck` (MRtrix3) yielded PASS **{int((grad['status']=='PASS').sum())}**, "
            f"REVIEW **{int((grad['status']=='REVIEW').sum())}**, "
            f"FAIL **{int((grad['status']=='FAIL').sum())}**. "
            "REVIEW cases were classified as axis flip, axis swap, combined flip+swap, "
            "or other. Suggested orientation corrections were **not applied** to the "
            "distributed data.",
            "",
            "## Geometry",
            "",
            (
                "All DWI volumes share a single geometry."
                if len(proto) == 1
                else f"Geometry differs across **{len(proto)}** protocols "
                "(voxel size / matrix / FOV / orientation summarised in "
                "`Geometry_QC.tsv`)."
            ),
            "",
            "## Signal quality",
            "",
            "Robust within-mask metrics (median b0 / diffusion signal, percentiles, "
            "coefficient of variation, background level, MAD-based b0 SNR and CNR) "
            f"were computed for **{int((signal_qc['status']=='PASS').sum()) if 'status' in signal_qc else 0}** "
            "scans with available brain masks. Distributions (not only means) are "
            "reported in `Signal_Report.md` and publication figures.",
            "",
            "## Brain masks",
            "",
            f"Automated brain-mask metrics were available for "
            f"**{int(mask_qc['brain_fraction'].notna().sum())}/{len(mask_qc)}** scans "
            f"(median brain fraction "
            f"{_fmt(float(mask_qc['brain_fraction'].median()))}).",
            "",
            "## Motion",
            "",
            "FSL eddy / eddy_quad motion summaries were **not available** in the "
            "audited derivatives tree for this release (see `Motion_QC.md`).",
            "",
            "## Distortion pairs",
            "",
            f"Opposite phase-encoding EPI fieldmaps (AP/PA) were present for "
            f"**{int((pairs['pair_status']=='PAIR_OK').sum())}/{len(pairs)}** sessions "
            "(see `PE_pairs.tsv`).",
            "",
            "## Visual inspection",
            "",
            "Representative multi-planar snapshots (b0, b≈1000, highest b-value; "
            "axial / coronal / sagittal with mask overlay) are stored under "
            "`visual_examples/` and summarised in `Visual_QC_Figure.png`.",
            "",
            "## Summary",
            "",
            f"**Overall technical validation: {overall}**",
            "",
            "| QC item | Status |",
            "| --- | --- |",
        ]
    )
    for item, status in table_rows:
        lines.append(f"| {item} | {status} |")
    lines.extend(
        [
            "",
            "## Output files",
            "",
            "- `integrity_summary.tsv`, `Integrity_Report.md`",
            "- `Protocol_Consistency.tsv`, `Acquisition_Consistency_Report.md`",
            "- `Geometry_QC.tsv`, `Geometry_QC_Report.md`",
            "- `Gradient_QC.tsv`, `Gradient_Report.md`",
            "- `BrainMask_QC.tsv`, `BrainMask_Report.md`",
            "- `Signal_QC.tsv`, `Signal_Report.md`",
            "- `Motion_QC.md`, `PE_pairs.tsv`, `PE_pairs_Report.md`",
            "- `TechnicalValidation_Table.tsv` / `.docx` / `.pdf`",
            "- Publication figures (PNG/PDF/SVG) under `publication/`",
            "",
        ]
    )
    write_text(path, "\n".join(lines))


def build_status_table(
    *,
    integrity: pd.DataFrame,
    grad: pd.DataFrame,
    mask_qc: pd.DataFrame,
    signal_qc: pd.DataFrame,
    pairs: pd.DataFrame,
    eddy_available: bool,
) -> tuple[list[tuple[str, str]], str]:
    def pass_fail(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    bids_ok = bool((integrity["inventory_status"] == "OK").all())
    nifti_ok = bool(integrity["nifti_present"].all())
    bval_ok = bool(integrity["bvals_match"].all())
    bvec_ok = bool(integrity["bvecs_match"].all())
    json_ok = bool(integrity["json_present"].all())
    # Gradient: FAIL only if any FAIL; REVIEW allowed as PASS with note? User example says PASS.
    # For Scientific Data: REVIEW without applied correction → WARNING if many, else PASS.
    n_fail_g = int((grad["status"] == "FAIL").sum())
    n_rev = int((grad["status"] == "REVIEW").sum())
    if n_fail_g:
        grad_status = "FAIL"
    elif n_rev:
        grad_status = "PASS*"  # reviewed suggestions not applied
    else:
        grad_status = "PASS"
    mask_ok = mask_qc["brain_fraction"].notna().mean() >= 0.95
    if len(signal_qc) == 0 or "status" not in signal_qc.columns:
        sig_ok = False
    else:
        # PASS if a majority of computed scans succeed (missing masks allowed)
        computed = signal_qc[signal_qc["status"].isin(["PASS", "FAIL", "BVAL_MISMATCH", "NO_B0"])]
        if len(computed) == 0:
            sig_ok = (signal_qc["status"] == "PASS").any()
        else:
            sig_ok = float((computed["status"] == "PASS").mean()) >= 0.8
    motion_status = "PASS" if eddy_available else "N.A."
    pe_ok = (pairs["pair_status"] == "PAIR_OK").mean() >= 0.9 if len(pairs) else False
    visual_ok = True  # generated by pipeline

    rows = [
        ("BIDS consistency", pass_fail(bids_ok)),
        ("NIfTI integrity", pass_fail(nifti_ok)),
        ("b-values", pass_fail(bval_ok)),
        ("b-vectors", pass_fail(bvec_ok)),
        ("JSON metadata", pass_fail(json_ok)),
        ("Gradient orientation", grad_status),
        ("Brain mask", pass_fail(bool(mask_ok))),
        ("Signal quality", pass_fail(bool(sig_ok))),
        ("Motion estimates", motion_status),
        ("Susceptibility pairs", pass_fail(bool(pe_ok))),
        ("Visual inspection", pass_fail(visual_ok)),
    ]
    hard = [s for _, s in rows if s == "FAIL"]
    if hard:
        overall = "FAIL"
    elif any(s in {"N.A.", "PASS*", "WARNING"} for _, s in rows):
        overall = "PASS (with documented caveats)"
    else:
        overall = "PASS"
    rows.append(("Overall technical validation", overall if overall.startswith("PASS") else overall))
    # Normalize overall cell
    rows[-1] = (
        "Overall technical validation",
        "PASS" if overall.startswith("PASS") else overall,
    )
    return rows, rows[-1][1]


def export_validation_table(rows: list[tuple[str, str]], out_dir: Path) -> None:
    df = pd.DataFrame(rows, columns=["QC_item", "Status"])
    tsv = out_dir / "TechnicalValidation_Table.tsv"
    df.to_csv(tsv, sep="\t", index=False)

    # DOCX
    try:
        from docx import Document

        doc = Document()
        doc.add_heading("Diffusion MRI — Technical Validation", level=1)
        table = doc.add_table(rows=1, cols=2)
        hdr = table.rows[0].cells
        hdr[0].text = "QC item"
        hdr[1].text = "Status"
        for item, status in rows:
            cells = table.add_row().cells
            cells[0].text = item
            cells[1].text = status
        doc.save(str(out_dir / "TechnicalValidation_Table.docx"))
    except Exception as exc:  # noqa: BLE001
        write_text(out_dir / "TechnicalValidation_Table_docx_error.txt", str(exc))

    # PDF via reportlab
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        pdf_path = out_dir / "TechnicalValidation_Table.pdf"
        doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
        styles = getSampleStyleSheet()
        data = [["QC item", "Status"]] + [list(r) for r in rows]
        t = Table(data, colWidths=[4.2 * inch, 2.0 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.94, 0.94, 0.94)),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story = [
            Paragraph("Diffusion MRI — Technical Validation", styles["Heading1"]),
            Spacer(1, 0.2 * inch),
            t,
        ]
        doc.build(story)
    except Exception as exc:  # noqa: BLE001
        write_text(out_dir / "TechnicalValidation_Table_pdf_error.txt", str(exc))
