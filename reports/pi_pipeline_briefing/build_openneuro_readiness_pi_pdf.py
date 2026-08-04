#!/usr/bin/env python3
"""Build English PI PDF: OpenNeuro publication readiness briefing with figures."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path("/home/alexrees/scratch/reports")
OUT = ROOT / "pi_pipeline_briefing" / "OpenNeuro_Publication_Readiness_PI_Briefing.pdf"

FIGS = {
    "pipeline": ROOT / "pi_pipeline_briefing/figures/Figure_pipeline_complete_PI.png",
    "qc3": ROOT / "pi_pipeline_briefing/figures/Figure_QC_three_layers_quality.png",
    "mapping": ROOT / "pi_pipeline_briefing/figures/Figure_mapping_PI.png",
    "bids": ROOT / "pi_pipeline_briefing/figures/Figure_bids_conversion_PI.png",
    "deid": ROOT / "deidentification_figures/figures/Fig06_PI_onepager_deidentification.png",
    "mriqc_cov": ROOT / "mriqc_publication_audit/figures/Fig01_MRIQC_coverage_summary.png",
    "mriqc_prog": ROOT / "pi_pipeline_briefing/figures/mriqc_before_after.png",
    "mriqc_gaps": ROOT / "mriqc_publication_audit/figures/Fig08_four_missing_acquisitions.png",
    "mriqc_one": ROOT / "mriqc_publication_audit/figures/Fig09_PI_onepager_quality_summary.png",
    "pizarro": ROOT / "pi_pipeline_briefing/figures/pizarro/Figure_Pizarro_overview_PI.png",
    "dwi": ROOT / "pi_pipeline_briefing/figures/dwi/Fig01_DWI_overview_PI.png",
    "func": ROOT / "functional_mri_paradigm_figures/Figure2_functional_paradigm_overview.png",
}

INK = colors.HexColor("#1C2430")
MUTED = colors.HexColor("#5A6570")
OK = colors.HexColor("#0E6B5C")
WARN = colors.HexColor("#A65D1A")
FAIL = colors.HexColor("#B42318")
SOFT = colors.HexColor("#F3F1EC")
RULE = colors.HexColor("#D4D0C8")


def styles():
    base = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=18, textColor=INK, spaceAfter=4, leading=22, alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=11, textColor=MUTED, spaceAfter=10, leading=14, alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=13, textColor=INK, spaceBefore=12, spaceAfter=6, leading=16,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11, textColor=INK, spaceBefore=8, spaceAfter=4, leading=14,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, textColor=INK, leading=13, alignment=TA_JUSTIFY, spaceAfter=4,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, textColor=INK, leading=12.5, leftIndent=2,
        ),
        "callout": ParagraphStyle(
            "callout", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, textColor=INK, leading=13, alignment=TA_JUSTIFY,
        ),
        "caption": ParagraphStyle(
            "caption", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=8.5, textColor=MUTED, leading=11, spaceBefore=2, spaceAfter=8,
            alignment=TA_CENTER,
        ),
        "quote": ParagraphStyle(
            "quote", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=9.5, textColor=INK, leading=13, leftIndent=8, rightIndent=8,
            spaceBefore=6, spaceAfter=6,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.5, textColor=MUTED, leading=10,
        ),
        "th": ParagraphStyle(
            "th", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.5, textColor=INK, leading=11,
        ),
        "td": ParagraphStyle(
            "td", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.2, textColor=INK, leading=10.5,
        ),
    }
    return s


def fig(path: Path, max_w=170 * mm, max_h=95 * mm):
    if not path.is_file():
        return Paragraph(f"[Missing figure: {path.name}]", styles()["caption"])
    # Keep aspect ratio
    from reportlab.lib.utils import ImageReader
    ir = ImageReader(str(path))
    iw, ih = ir.getSize()
    scale = min(max_w / iw, max_h / ih)
    return Image(str(path), width=iw * scale, height=ih * scale)


def callout(text: str, s):
    data = [[Paragraph(text, s["callout"])]]
    t = Table(data, colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def table(headers, rows, col_widths, s):
    data = [[Paragraph(h, s["th"]) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(c), s["td"]) for c in row])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), SOFT),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    t.setStyle(TableStyle(style))
    return t


def bullets(items, s):
    return ListFlowable(
        [ListItem(Paragraph(i, s["bullet"]), leftIndent=8, bulletColor=OK) for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=12,
        spaceBefore=2,
        spaceAfter=4,
    )


def build():
    s = styles()
    story = []

    story.append(Paragraph(
        "Pipeline completion &amp; OpenNeuro publication readiness", s["title"]))
    story.append(Paragraph(
        "Technical briefing for the Principal Investigator<br/>"
        "Multimodal MRI dataset · BIDS 1.9.0 · 24 July 2026", s["subtitle"]))

    story.append(callout(
        "<b>30-second message.</b> We have a BIDS-organised multimodal MRI dataset "
        "(84 participants, 124 sessions) with DICOM de-identification, anatomical defacing, "
        "validated functional event metadata where mapping is unique, and three complementary "
        "QC layers (Pizarro, MRIQC, DWI). A public release tree (<font face='Courier'>release_dataset/</font>) "
        "has been built with defaced anatomicals under standard BIDS names. "
        "<b>OpenNeuro upload is blocked only by:</b> real author list + licence (CC0/CC-BY) in "
        "<font face='Courier'>dataset_description.json</font>, and PI confirmation of consent language. "
        "Imaging + QC content is deposit-ready.",
        s,
    ))
    story.append(Spacer(1, 6 * mm))

    # Section 1
    story.append(Paragraph("1. Executive verdict", s["h1"]))
    story.append(table(
        ["Question", "Verdict", "Detail"],
        [
            ["Is the research pipeline complete enough to present?",
             "<font color='#0E6B5C'><b>YES</b></font>",
             "Inventory → de-ID → BIDS → deface → QC → release package"],
            ["Is the imaging package scientifically documented?",
             "<font color='#0E6B5C'><b>YES</b></font>",
             "Methods / Data Record drafts; QC reports; event validation"],
            ["Can we upload to OpenNeuro today?",
             "<font color='#A65D1A'><b>NOT YET</b></font>",
             "Authors + Licence placeholders; optional: finish 11 pending ses-02"],
            ["Should incomplete QC / missing events block deposit?",
             "<font color='#0E6B5C'><b>NO</b></font>",
             "Document transparently (4 MRIQC gaps; 51 events withheld; DWI REVIEW)"],
        ],
        [55 * mm, 28 * mm, 87 * mm],
        s,
    ))

    story.append(Paragraph("2. Dataset snapshot", s["h1"]))
    story.append(table(
        ["Item", "N", "Note"],
        [
            ["Participants", "84", "Control 56; Glaucoma 19; DataON 7; DataTON 2"],
            ["BIDS sessions", "124", "ses-01: 83; ses-02: 41 (longitudinal incomplete by design)"],
            ["Mapped DICOM sessions (AUTO_CONFIRMED)", "135", "11 ses-02 not yet in BIDS (retry submitted)"],
            ["NIfTI in BIDS (approx.)", "7,956", "+ JSON sidecars"],
            ["T1w / FLAIR", "385 / 125", "Defaced T1w 385/385; FLAIR in release replacements"],
            ["BOLD / sbref / fmap / DWI", "2992 / 2892 / 982 / 361", "Multimodal"],
            ["task-fmri events.tsv", "456 / 507", "89.9% of eligible magnitude runs"],
            ["MRIQC IQMs (T1w+BOLD)", "1848 / 1852", "<b>99.8%</b> (24 Jul 2026 audit)"],
            ["Release package", "84 subjects", "17,101 files; ~1 TB public tree"],
        ],
        [62 * mm, 38 * mm, 70 * mm],
        s,
    ))

    story.append(Spacer(1, 3 * mm))
    story.append(fig(FIGS["pipeline"], max_h=78 * mm))
    story.append(Paragraph(
        "Figure 1. End-to-end pipeline overview (inventory → BIDS → defacing → QC → release).",
        s["caption"]))

    story.append(Paragraph("3. What was built (technical walkthrough)", s["h1"]))

    story.append(Paragraph("3.1 Inventory, mapping, and session confirmation", s["h2"]))
    story.append(bullets([
        "Source archive inventoried under <font face='Courier'>/project/def-amirs/raw_original/</font> (Control, Glaucoma, Data_ON, Data_TON).",
        "Series-level mapping frozen in <font face='Courier'>metadata/session_mapping.csv</font> (~10,026 MRI series) and session-level <font face='Courier'>mapping.csv</font>.",
        "Session confirmation: <b>135 AUTO_CONFIRMED</b> DICOM sessions + 6 auxiliary-only NO_DICOM_FOUND.",
        "Manual overrides documented (e.g. SUBC044 patient_id conflict) without disabling validation rules.",
    ], s))
    story.append(fig(FIGS["mapping"], max_h=70 * mm))
    story.append(Paragraph("Figure 2. Mapping / session confirmation summary.", s["caption"]))

    story.append(callout(
        "<b>Documented gap (transparent):</b> BIDS currently contains <b>124/135</b> AUTO_CONFIRMED sessions. "
        "The missing 11 are all non-Control <font face='Courier'>ses-02</font> visits (1 DataON, 1 DataTON, 9 Glaucoma). "
        "Root cause: conversion arrays originally hard-coded <font face='Courier'>--session ses-01</font>; "
        "Control ses-02 were later converted; the remaining 11 failed when scratch lacked those cohort raw trees. "
        "Retry array <font face='Courier'>ses02_r11</font> (job 66365527) points at project raw (verified present). "
        "Completing these sessions is recommended before final OpenNeuro freeze but is not a QC failure of the existing package.",
        s,
    ))

    story.append(Paragraph("3.2 DICOM de-identification (derived copies only)", s["h2"]))
    story.append(bullets([
        "Applied on <b>derived</b> DICOM copies used for conversion — the raw archive is never overwritten.",
        "Policy oriented to DICOM PS3.15 Basic Application Level Confidentiality Profile (Annex E): documented custom subset (not a certified PS3.15 product claim).",
        "Actions: clear PHI / free-text / site tags; pseudonymise PatientName/ID; remap UIDs; shift dates by participant-specific offsets (<font face='Courier'>deidentify_date_shifts.csv</font> — <b>do not publish</b>); remove private tags except documented Siemens CSA needed for BIDS physics (SliceTiming, PE, bvals).",
        "<b>Pixels unchanged</b> at this stage; acquisition parameters retained for science.",
    ], s))
    story.append(fig(FIGS["deid"], max_h=100 * mm))
    story.append(Paragraph(
        "Figure 3. De-identification one-pager. Methods framing: “oriented toward PS3.15 Basic; documented subset”.",
        s["caption"]))

    story.append(PageBreak())
    story.append(Paragraph("3.3 BIDS conversion", s["h2"]))
    story.append(bullets([
        "Tooling: <font face='Courier'>neuro_pipeline</font> 2.1.0 + dcm2niix; BIDSVersion <b>1.9.0</b>; DatasetType raw.",
        "Layout: <font face='Courier'>sub-*/ses-*/{anat,func,dwi,fmap}</font> with JSON sidecars; DWI includes .bval/.bvec.",
        "Post-conversion metadata hygiene: administrative / identifying JSON fields scrubbed without altering scientific acquisition keys (TR/TE, ProtocolName, PhaseEncodingDirection, …).",
        "XA30 SliceTiming recovery documented where Enhanced DICOM permitted measured timing (no invented SliceTiming from TR heuristics).",
    ], s))
    story.append(fig(FIGS["bids"], max_h=72 * mm))
    story.append(Paragraph("Figure 4. BIDS conversion outcome summary.", s["caption"]))

    story.append(Paragraph("3.4 Anatomical defacing", s["h2"]))
    story.append(bullets([
        "Tool: pydeface on structural images under <font face='Courier'>derivatives/defacing/</font>.",
        "Coverage: <b>T1w 385/385</b>; public package structural replacements = <b>481</b> (T1w + FLAIR; rebuild release after ses-02 if needed).",
        "Public release uses <b>standard BIDS filenames</b> (no desc-defaced entity); original identifiable anatomicals excluded from the release tree.",
    ], s))

    story.append(Paragraph("3.5 Functional paradigms and event metadata", s["h2"]))
    story.append(Paragraph(
        "Functional tasks: rest, fmri (grating), movie, control. Validated events.tsv files apply to the "
        "grating <font face='Courier'>task-fmri</font> paradigm only.",
        s["body"]))
    story.append(bullets([
        "Eligible non-phase magnitude task-fmri BOLD runs: <b>507</b>.",
        "Released with validated events: <b>456 (89.9%)</b>.",
        "Intentionally without events: <b>51</b> — duplicate ProtocolName (n=32), missing Results (n=8), duplicate/missing scan_info (n=5/4), MATLAB vs protocol number mismatch (n=2).",
        "<b>Policy:</b> no invented onsets; no synthetic events; imaging retained for all 507.",
    ], s))
    story.append(fig(FIGS["func"], max_h=78 * mm))
    story.append(Paragraph("Figure 5. Functional paradigm overview.", s["caption"]))

    story.append(Paragraph("4. Quality control — three complementary layers", s["h1"]))
    story.append(Paragraph(
        "The QC strategy is deliberately multi-layer: screening (Pizarro), quantitative IQMs (MRIQC), "
        "and diffusion technical validation (DWI QC). <b>None of these layers auto-excludes subjects "
        "from the deposit.</b>",
        s["body"]))
    story.append(fig(FIGS["qc3"], max_h=85 * mm))
    story.append(Paragraph(
        "Figure 6. Single-figure QC summary: Pizarro / MRIQC / DWI — quality evidenced without automatic exclusions.",
        s["caption"]))

    story.append(Paragraph("4.1 Pizarro (T1w deep-learning screening)", s["h2"]))
    story.append(bullets([
        "Scope: all <b>385</b> T1w images (incl. new ses-02); 0 load errors; 246 images in priority review queue.",
        "Outputs: artifact probability, confidence, uncertainty (Monte Carlo dropout).",
        "Prioritisation queues visual review; <b>0 automatic exclusions</b>.",
        "Scientific Data framing: screening / prioritisation only; quantitative QC remains MRIQC.",
    ], s))
    story.append(fig(FIGS["pizarro"], max_h=70 * mm))
    story.append(Paragraph("Figure 7. Pizarro screening overview.", s["caption"]))

    story.append(PageBreak())
    story.append(Paragraph("4.2 MRIQC (anatomical + functional IQMs)", s["h2"]))
    story.append(bullets([
        "Software: MRIQC 24.0.2 with fault-tolerant wrapper in neuro_pipeline.",
        "Coverage (24 Jul 2026): subjects 84/84; complete sessions <b>120/124 (96.8%)</b>; T1w <b>354/356 (99.4%)</b>; magnitude BOLD <b>1494/1496 (99.9%)</b>; combined <b>1848/1852 (99.8%)</b>.",
        "Quality headlines: median BOLD fd_mean <b>0.176 mm</b>; median tSNR <b>20.9</b>.",
        "Engineering fix: mass failures from AFNI 3dFWHMx -acf; corrected patch forces classic FWHM (acf=False) — session completeness rose from ~78% to 96.8%.",
        "Four remaining missing IQMs are pathological / truncated acquisitions (2 BOLD with 3–4 volumes; 2 abnormal T1w) — MRIQC fails correctly; do not block deposit.",
    ], s))
    story.append(fig(FIGS["mriqc_cov"], max_h=72 * mm))
    story.append(Paragraph("Figure 8. MRIQC coverage summary.", s["caption"]))
    story.append(fig(FIGS["mriqc_prog"], max_h=55 * mm))
    story.append(Paragraph("Figure 9. MRIQC session completeness before vs after AFNI ACF patch.", s["caption"]))
    story.append(fig(FIGS["mriqc_gaps"], max_h=70 * mm))
    story.append(Paragraph("Figure 10. Four missing IQMs explained by BIDS evidence (not software failure).", s["caption"]))
    story.append(fig(FIGS["mriqc_one"], max_h=80 * mm))
    story.append(Paragraph("Figure 11. MRIQC quality one-pager.", s["caption"]))

    story.append(Paragraph("4.3 DWI QC (read-only technical validation)", s["h2"]))
    story.append(bullets([
        "Scope: <b>361</b> DWI scans / 82 subjects / 120 sessions.",
        "Integrity: NIfTI + bval + bvec + JSON <b>361/361 PASS</b>; volume/gradient length mismatches <b>0</b>.",
        "dwigradcheck: <b>250 PASS</b>, <b>111 REVIEW</b>, <b>0 FAIL</b>.",
        "REVIEW findings documented; <b>no gradient corrections applied</b> to distributed data.",
    ], s))
    story.append(fig(FIGS["dwi"], max_h=72 * mm))
    story.append(Paragraph("Figure 12. DWI QC overview.", s["caption"]))

    story.append(PageBreak())
    story.append(Paragraph("5. Public release package", s["h1"]))
    story.append(bullets([
        "Builder: <font face='Courier'>code/build_release.py</font> (--dry-run / --apply).",
        "Source trees bids/, derivatives/, raw_original/ are <b>never modified</b>.",
        "Output: ~/scratch/release_dataset — 84 subjects, 124 sessions, 17,101 files.",
        "Anatomicals: original T1w/FLAIR NIfTIs excluded; replaced by validated defaced files (481 replacements; identity-checked vs derivatives/defacing).",
        "Preflight validation: PASS. Post-build audit: <b>WARNING</b> only for publication metadata (Authors/Name/License placeholders).",
        "Structural integrity: PASS (manifest complete; no desc-defaced names; participants vs folders aligned).",
    ], s))

    story.append(Paragraph("6. What has been documented for Scientific Data / OpenNeuro", s["h1"]))
    story.append(bullets([
        "Data Record draft (inventory, organisation, modalities, events policy).",
        "De-identification Methods language + supplementary tag-action tables / figures.",
        "MRIQC Technical Validation English text (99.8%; four gaps justified).",
        "Pizarro Scientific Data statements (screening only; no exclusion).",
        "DWI technical validation report + PI talking points.",
        "Functional event validation report (456/507; irrecoverable audit for 51).",
        "Release build + anatomical replacement + release-dataset audit reports under reports/openneuro_release/.",
    ], s))

    story.append(Paragraph("7. OpenNeuro readiness checklist", s["h1"]))
    story.append(table(
        ["Requirement", "Status", "Notes"],
        [
            ["BIDS layout + sidecars", "<font color='#0E6B5C'><b>READY</b></font>", "BIDS 1.9.0; metadata cleaned"],
            ["Defaced anatomicals in public tree", "<font color='#0E6B5C'><b>READY</b></font>", "481 replacements; standard names"],
            ["Participant table", "<font color='#0E6B5C'><b>READY</b></font>", "84 IDs match folders"],
            ["QC documentation", "<font color='#0E6B5C'><b>READY</b></font>", "Pizarro + MRIQC + DWI"],
            ["Event policy documented", "<font color='#0E6B5C'><b>READY</b></font>", "456 released; 51 withheld intentionally"],
            ["De-ID / defacing documented", "<font color='#0E6B5C'><b>READY</b></font>", "Honest PS3.15 framing"],
            ["dataset_description.json Authors", "<font color='#B42318'><b>BLOCKER</b></font>", "Replace pipeline placeholder"],
            ["Licence (CC0 / CC-BY)", "<font color='#B42318'><b>BLOCKER</b></font>", "Field currently missing"],
            ["Dataset Name (final title)", "<font color='#A65D1A'><b>NEEDED</b></font>", "Still generic pipeline name"],
            ["Consent / ethics language", "<font color='#A65D1A'><b>PI</b></font>", "Confirm before upload"],
            ["Optional: convert remaining 11 ses-02", "<font color='#A65D1A'><b>IN PROGRESS</b></font>", "Improves completeness; not QC fail"],
            ["Optional: rebuild release after ses-02 + deface", "<font color='#A65D1A'><b>AFTER</b></font>", "Re-run build_release.py --apply"],
            ["bids-validator on release tree", "<font color='#A65D1A'><b>PENDING</b></font>", "Run before upload"],
        ],
        [58 * mm, 28 * mm, 84 * mm],
        s,
    ))

    story.append(Paragraph("8. Decisions requested from the PI", s["h1"]))
    story.append(bullets([
        "<b>Author list and order</b> for OpenNeuro dataset_description.json and the Scientific Data paper.",
        "Confirm <b>licence</b> (typically CC0 on OpenNeuro) and consent language for open redistribution.",
        "Confirm final <b>dataset title / Name</b>.",
        "Accept documenting MRIQC at <b>99.8%</b> with four pathological gaps in Technical Validation (recommended) versus delaying for 100%.",
        "Accept event release policy (456/507; no invented timing).",
        "Priority on finishing the <b>11 pending ses-02</b> conversions before freeze (recommended yes).",
        "Green light to finalise README + description JSON and proceed to OpenNeuro upload after blockers cleared.",
    ], s))

    story.append(Paragraph("Closing statement for the meeting", s["h1"]))
    story.append(Paragraph(
        "“We have a complete, documented BIDS pipeline: de-identified DICOMs, converted imaging, "
        "defaced anatomicals, three QC layers showing high coverage and usable quality metrics, and a "
        "built public release tree. The science package is ready to deposit. What we still need from you "
        "are the human metadata — authors, licence, consent — and a decision on whether to wait for "
        "the last eleven follow-up sessions before freezing the OpenNeuro version.”",
        s["quote"]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "<b>Primary paths:</b> bids/, release_dataset/, derivatives/{defacing,mriqc}, metadata/, "
        "reports/{openneuro_release, mriqc_publication_audit, mriqc_coverage_audit, dwi_qc, "
        "pizarro_qc_scientific_data, deidentification_figures, stimulus_validation, "
        "scientific_data_manuscript_draft, pi_pipeline_briefing}.",
        s["footer"]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, "Optic-nerve MRI dataset — OpenNeuro readiness | PI technical briefing | 24 July 2026")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title="OpenNeuro Publication Readiness — PI Technical Briefing",
        author="neuro_pipeline project",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"Wrote {OUT}")
    print(f"Size: {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    build()
