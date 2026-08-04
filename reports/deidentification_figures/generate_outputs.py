#!/usr/bin/env python3
"""Generate de-identification publication figures and supplementary tables."""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

OUT = Path(__file__).resolve().parent

# Nature-like palette (avoid purple/glow defaults)
C_RAW = "#2C3E50"
C_DERIVED = "#1F6F8B"
C_ACTION = "#C0392B"
C_PRESERVE = "#1E8449"
C_NEUTRAL = "#5D6D7E"
C_BG = "#F7F9FB"
C_BOX = "#FFFFFF"
C_EDGE = "#34495E"

# ---------------------------------------------------------------------------
# Tag table from deidentification_report / mri_anonymization constants
# ---------------------------------------------------------------------------
TAG_ROWS: list[dict[str, str]] = [
    # Pseudonymized
    {"tag": "(0010,0010)", "keyword": "PatientName", "action": "Pseudonymized",
     "reason": "Replace scanner identity with mapped study code",
     "relevance": "Prevents direct nominal identification while retaining a stable study key"},
    {"tag": "(0010,0020)", "keyword": "PatientID", "action": "Pseudonymized",
     "reason": "Replace scanner identity with mapped study code",
     "relevance": "Aligns DICOM identity with approved participant mapping"},
    # Cleared PHI
    {"tag": "(0010,0030)", "keyword": "PatientBirthDate", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes precise age/birth identifiers from headers"},
    {"tag": "(0010,1000)", "keyword": "OtherPatientIDs", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes secondary identity linkage fields"},
    {"tag": "(0010,1001)", "keyword": "OtherPatientNames", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes alternate name fields"},
    {"tag": "(0010,2160)", "keyword": "EthnicGroup", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes sensitive demographic free text from DICOM"},
    {"tag": "(0010,2180)", "keyword": "Occupation", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes potentially identifying occupational text"},
    {"tag": "(0010,21B0)", "keyword": "AdditionalPatientHistory", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes free-text clinical history from headers"},
    {"tag": "(0010,4000)", "keyword": "PatientComments", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes free-text comments that may contain identifiers"},
    {"tag": "(0008,0080)", "keyword": "InstitutionName", "action": "Cleared",
     "reason": "Protected health information / site identity",
     "relevance": "Limits site-level identification via headers"},
    {"tag": "(0008,0081)", "keyword": "InstitutionAddress", "action": "Cleared",
     "reason": "Protected health information / site identity",
     "relevance": "Removes geographic institutional identifiers"},
    {"tag": "(0008,0090)", "keyword": "ReferringPhysicianName", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes clinician identifiers"},
    {"tag": "(0008,0092)", "keyword": "ReferringPhysicianAddress", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes clinician contact information"},
    {"tag": "(0008,0094)", "keyword": "ReferringPhysicianTelephoneNumbers", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes clinician contact information"},
    {"tag": "(0008,1048)", "keyword": "PhysiciansOfRecord", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes clinician identifiers"},
    {"tag": "(0008,1050)", "keyword": "PerformingPhysicianName", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes clinician identifiers"},
    {"tag": "(0008,1060)", "keyword": "NameOfPhysiciansReadingStudy", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes clinician identifiers"},
    {"tag": "(0008,1070)", "keyword": "OperatorsName", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes operator identifiers"},
    {"tag": "(0008,1010)", "keyword": "StationName", "action": "Cleared",
     "reason": "Protected health information / device identity",
     "relevance": "Reduces linkage via console/station names"},
    {"tag": "(0008,1030)", "keyword": "StudyDescription", "action": "Cleared",
     "reason": "May contain protected health information",
     "relevance": "Removes free-text study labels that may identify participants or sites"},
    {"tag": "(0008,0050)", "keyword": "AccessionNumber", "action": "Cleared",
     "reason": "Protected health information / clinical workflow ID",
     "relevance": "Breaks linkage to clinical accession systems"},
    {"tag": "(0018,1000)", "keyword": "DeviceSerialNumber", "action": "Cleared",
     "reason": "Protected health information / device identity",
     "relevance": "Reduces hardware-based re-identification risk"},
    {"tag": "(0020,0010)", "keyword": "StudyID", "action": "Cleared",
     "reason": "Protected health information / study identity",
     "relevance": "Removes local study identifiers"},
    {"tag": "(0032,1032)", "keyword": "RequestingPhysician", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes clinician identifiers"},
    {"tag": "(0032,1060)", "keyword": "RequestedProcedureDescription", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes free-text procedure descriptions"},
    {"tag": "(0040,0241)", "keyword": "PerformedStationAETitle", "action": "Cleared",
     "reason": "Protected health information / site–device identity",
     "relevance": "Removes DICOM network identity strings"},
    {"tag": "(0040,0242)", "keyword": "PerformedStationName", "action": "Cleared",
     "reason": "Protected health information / site–device identity",
     "relevance": "Removes station names"},
    {"tag": "(0040,0243)", "keyword": "PerformedLocation", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes location descriptors"},
    {"tag": "(0040,A075)", "keyword": "VerifyingObserverName", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes observer names"},
    {"tag": "(0040,A123)", "keyword": "PersonName", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes person-name fields"},
    {"tag": "(0020,4000)", "keyword": "ImageComments", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes free-text image comments"},
    {"tag": "(0032,4000)", "keyword": "StudyComments", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes free-text study comments"},
    {"tag": "(4008,010C)", "keyword": "IdentifyingComments", "action": "Cleared",
     "reason": "Protected health information",
     "relevance": "Removes identifying comment fields"},
    {"tag": "(4008,0111)", "keyword": "UniformResourceLocator", "action": "Cleared",
     "reason": "Protected health information / linkage risk",
     "relevance": "Removes URLs that may link to identifiable systems"},
    # Date shifted
    {"tag": "(0008,0020)", "keyword": "StudyDate", "action": "Date shifted",
     "reason": "Remove absolute calendar dates; preserve relative intervals",
     "relevance": "Protects visit timing while supporting longitudinal analyses"},
    {"tag": "(0008,0021)", "keyword": "SeriesDate", "action": "Date shifted",
     "reason": "Remove absolute calendar dates; preserve relative intervals",
     "relevance": "Protects timing metadata at series level"},
    {"tag": "(0008,0022)", "keyword": "AcquisitionDate", "action": "Date shifted",
     "reason": "Remove absolute calendar dates; preserve relative intervals",
     "relevance": "Protects acquisition calendar dates"},
    {"tag": "(0008,0023)", "keyword": "ContentDate", "action": "Date shifted",
     "reason": "Remove absolute calendar dates; preserve relative intervals",
     "relevance": "Protects content calendar dates"},
    {"tag": "(0008,0012)", "keyword": "InstanceCreationDate", "action": "Date shifted",
     "reason": "Remove absolute calendar dates; preserve relative intervals",
     "relevance": "Protects instance creation dates"},
    {"tag": "(0040,0244)", "keyword": "PerformedProcedureStepStartDate", "action": "Date shifted",
     "reason": "Remove absolute calendar dates; preserve relative intervals",
     "relevance": "Protects procedure-step dates"},
    {"tag": "(0040,0250)", "keyword": "PerformedProcedureStepEndDate", "action": "Date shifted",
     "reason": "Remove absolute calendar dates; preserve relative intervals",
     "relevance": "Protects procedure-step dates"},
    {"tag": "(0008,002A)", "keyword": "AcquisitionDateTime", "action": "Date shifted",
     "reason": "Remove absolute calendar dates; preserve relative intervals",
     "relevance": "Protects combined date–time stamps"},
    # Note: PatientBirthDate also listed for shift-if-retained; action Cleared above
    # UID remapped
    {"tag": "(0020,000D)", "keyword": "StudyInstanceUID", "action": "UID remapped",
     "reason": "Prevent linkage via original study UIDs",
     "relevance": "Breaks external linkage while keeping within-study consistency"},
    {"tag": "(0020,000E)", "keyword": "SeriesInstanceUID", "action": "UID remapped",
     "reason": "Prevent linkage via original series UIDs",
     "relevance": "Preserves series grouping under new identifiers"},
    {"tag": "(0008,0018)", "keyword": "SOPInstanceUID", "action": "UID remapped",
     "reason": "Prevent linkage via original instance UIDs",
     "relevance": "Unique instance identity without original UID leakage"},
    {"tag": "(0002,0003)", "keyword": "MediaStorageSOPInstanceUID", "action": "UID remapped",
     "reason": "Keep file-meta UID consistent with remapped SOPInstanceUID",
     "relevance": "Maintains valid DICOM file-meta linkage"},
    {"tag": "(0020,0052)", "keyword": "FrameOfReferenceUID", "action": "UID remapped",
     "reason": "Prevent linkage via frame-of-reference UIDs",
     "relevance": "Supports co-registration relationships under remapped UIDs"},
    {"tag": "(0008,1155)", "keyword": "ReferencedSOPInstanceUID", "action": "UID remapped",
     "reason": "Prevent linkage via referenced instance UIDs",
     "relevance": "Updates nested references consistently"},
    {"tag": "(0020,0200)", "keyword": "SynchronizationFrameOfReferenceUID", "action": "UID remapped",
     "reason": "Prevent linkage via synchronization UIDs",
     "relevance": "Updates synchronization references when present"},
    {"tag": "(0020,0051)", "keyword": "RelatedFrameOfReferenceUID", "action": "UID remapped",
     "reason": "Prevent linkage via related frame-of-reference UIDs",
     "relevance": "Updates related FoR references when present"},
    # Preserved (explicit policy)
    {"tag": "(0010,0040)", "keyword": "PatientSex", "action": "Preserved",
     "reason": "Retained by default for demographic tables",
     "relevance": "Supports cohort description without names or birth dates"},
    {"tag": "(0008,0016)", "keyword": "SOPClassUID", "action": "Preserved",
     "reason": "Standard class must remain for DICOM validity",
     "relevance": "Required for converters and standards-compliant reading"},
    {"tag": "(0008,0030)", "keyword": "StudyTime", "action": "Preserved",
     "reason": "Clock times are not day-shifted",
     "relevance": "Preserves within-day acquisition order"},
    {"tag": "(0008,0031)", "keyword": "SeriesTime", "action": "Preserved",
     "reason": "Clock times are not day-shifted",
     "relevance": "Preserves series order within a session"},
    {"tag": "(0008,0032)", "keyword": "AcquisitionTime", "action": "Preserved",
     "reason": "Clock times are not day-shifted",
     "relevance": "Supports fine-grained temporal ordering"},
    {"tag": "(0008,0033)", "keyword": "ContentTime", "action": "Preserved",
     "reason": "Clock times are not day-shifted",
     "relevance": "Supports content timing within a day"},
    {"tag": "(0040,0245)", "keyword": "PerformedProcedureStepStartTime", "action": "Preserved",
     "reason": "Clock times are not day-shifted",
     "relevance": "Preserves procedure-step timing"},
    {"tag": "(0040,0251)", "keyword": "PerformedProcedureStepEndTime", "action": "Preserved",
     "reason": "Clock times are not day-shifted",
     "relevance": "Preserves procedure-step timing"},
    {"tag": "(0008,103E)", "keyword": "SeriesDescription", "action": "Preserved",
     "reason": "Required for modality/task labelling; not on PHI clear list",
     "relevance": "Enables BIDS entity assignment and protocol interpretation"},
    {"tag": "(0018,0080)", "keyword": "RepetitionTime", "action": "Preserved",
     "reason": "Acquisition parameter retained by omission from clear lists",
     "relevance": "Essential for fMRI modelling and sequence description"},
    {"tag": "(0018,0081)", "keyword": "EchoTime", "action": "Preserved",
     "reason": "Acquisition parameter retained by omission from clear lists",
     "relevance": "Essential for contrast and sequence description"},
    {"tag": "(0018,1314)", "keyword": "FlipAngle", "action": "Preserved",
     "reason": "Acquisition parameter retained by omission from clear lists",
     "relevance": "Required for sequence methods reporting"},
    {"tag": "(0028,0030)", "keyword": "PixelSpacing", "action": "Preserved",
     "reason": "Geometric parameter retained by omission from clear lists",
     "relevance": "Required for spatial normalization and analysis"},
    {"tag": "(0018,0050)", "keyword": "SliceThickness", "action": "Preserved",
     "reason": "Geometric parameter retained by omission from clear lists",
     "relevance": "Required for volumetric geometry"},
    {"tag": "(7FE0,0010)", "keyword": "PixelData", "action": "Pixel data unchanged",
     "reason": "Header-only de-identification; image matrix not altered",
     "relevance": "Preserves quantitative imaging content for analysis"},
    {"tag": "odd-group private", "keyword": "Private tags (all)", "action": "Removed private tags",
     "reason": "Vendor private elements may contain identifiers or linkage data",
     "relevance": "Reduces residual PHI risk; may remove some vendor-specific fields"},
    {"tag": "(0012,0062)", "keyword": "PatientIdentityRemoved", "action": "Set (provenance)",
     "reason": "Record that identity removal was performed",
     "relevance": "Standards-facing de-identification provenance"},
    {"tag": "(0012,0063)", "keyword": "DeidentificationMethod", "action": "Set (provenance)",
     "reason": "Record de-identification method description",
     "relevance": "Supports auditability of the confidentiality process"},
]


def write_csv_and_xlsx() -> None:
    csv_path = OUT / "Supplementary_Table_DICOM_Deidentification.csv"
    xlsx_path = OUT / "Supplementary_Table_DICOM_Deidentification.xlsx"
    fieldnames = ["DICOM tag", "Keyword", "Action", "Reason", "Scientific relevance"]
    rows = [
        {
            "DICOM tag": r["tag"],
            "Keyword": r["keyword"],
            "Action": r["action"],
            "Reason": r["reason"],
            "Scientific relevance": r["relevance"],
        }
        for r in TAG_ROWS
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    _write_minimal_xlsx(xlsx_path, fieldnames, rows)
    print(f"Wrote {csv_path.name}, {xlsx_path.name}")


def _write_minimal_xlsx(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    """Write a simple Office Open XML workbook without openpyxl."""

    def col_letter(idx: int) -> str:
        # 0-based -> A, B, ...
        return chr(ord("A") + idx)

    sheet_rows = [headers] + [[r[h] for h in headers] for r in rows]
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    for r_idx, values in enumerate(sheet_rows, start=1):
        lines.append(f'<row r="{r_idx}">')
        for c_idx, value in enumerate(values):
            ref = f"{col_letter(c_idx)}{r_idx}"
            text = escape(str(value))
            lines.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'
            )
        lines.append("</row>")
    lines.extend(["</sheetData>", "</worksheet>"])
    sheet_xml = "\n".join(lines)

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="DICOM_deidentification" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def action_counts() -> dict[str, int]:
    # Categories requested for Figure 2
    counts = {
        "Cleared": 0,
        "Pseudonymized": 0,
        "UID remapped": 0,
        "Date shifted": 0,
        "Preserved": 0,
        "Removed private tags": 0,
        "Pixel data unchanged": 0,
    }
    for row in TAG_ROWS:
        action = row["action"]
        if action in counts:
            counts[action] += 1
        elif action == "Set (provenance)":
            continue  # provenance tags are not an "action category" bar
    return counts


def style_axes(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors=C_NEUTRAL)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(C_EDGE)


def draw_box(ax, xy, w, h, text, *, fc=C_BOX, ec=C_EDGE, fontsize=9, bold=False, text_color=C_RAW):
    x, y = xy
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.02",
        linewidth=1.4,
        edgecolor=ec,
        facecolor=fc,
        mutation_aspect=0.5,
        zorder=2,
    )
    ax.add_patch(box)
    weight = "bold" if bold else "normal"
    ax.text(
        x + w / 2, y + h / 2, text,
        ha="center", va="center", fontsize=fontsize,
        color=text_color, fontweight=weight, wrap=True, zorder=3,
        linespacing=1.25,
    )
    return box


def arrow(ax, start, end, color=C_EDGE):
    ax.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.5, mutation_scale=12),
        zorder=1,
    )


def figure_workflow() -> None:
    fig, ax = plt.subplots(figsize=(8.5, 11.2), dpi=300)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 15)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.add_patch(
        FancyBboxPatch(
            (0.3, 10.6), 2.6, 3.8,
            boxstyle="round,pad=0.02,rounding_size=0.03",
            facecolor="#EBF5FB", edgecolor=C_RAW, linewidth=1.8, linestyle=(0, (4, 3)),
        )
    )
    ax.text(
        1.6, 14.05, "Original acquisitions\nremain untouched",
        ha="center", fontsize=8.5, color=C_RAW, fontweight="bold",
    )
    draw_box(
        ax, (0.5, 11.4), 2.2, 1.6, "Raw DICOM\nrepository",
        fc="#D4E6F1", ec=C_RAW, bold=True, fontsize=10,
    )

    steps_main = [
        (11.6, "Non-destructive inventory\n(metadata catalogue only)", "#FCF3CF"),
        (10.0, "Participant–session mapping\n(approved identity tables)", "#FCF3CF"),
        (8.0, "Automated DICOM de-identification\non derived copies", "#F5B7B1"),
    ]
    x0, w = 3.5, 6.0
    for y, text, fc in steps_main:
        draw_box(ax, (x0, y), w, 1.25, text, fc=fc, ec=C_EDGE, bold=True, fontsize=9.5)

    for y1, y2 in [(11.6, 11.25), (10.0, 9.65), (8.0, 7.55)]:
        arrow(ax, (6.5, y1), (6.5, y2))

    ax.annotate(
        "",
        xy=(3.5, 12.2),
        xytext=(2.7, 12.2),
        arrowprops=dict(arrowstyle="-|>", color=C_RAW, lw=1.3, linestyle="--", mutation_scale=11),
    )
    ax.text(3.05, 12.45, "read-only", fontsize=7.5, color=C_RAW, ha="center")

    ax.annotate(
        "",
        xy=(3.5, 8.5),
        xytext=(1.6, 11.4),
        arrowprops=dict(
            arrowstyle="-|>", color=C_ACTION, lw=1.4,
            connectionstyle="arc3,rad=0.25", mutation_scale=11,
        ),
    )
    ax.text(
        1.55, 9.5, "copy &\ntransform", fontsize=7.5,
        color=C_ACTION, ha="center", fontweight="bold",
    )

    draw_box(ax, (3.5, 5.85), 2.9, 0.85, "PHI removal", fc="#FADBD8", ec=C_ACTION, fontsize=8.5)
    draw_box(ax, (6.6, 5.85), 2.9, 0.85, "Date shifting", fc="#FADBD8", ec=C_ACTION, fontsize=8.5)
    draw_box(ax, (3.5, 4.75), 2.9, 0.85, "UID remapping", fc="#FADBD8", ec=C_ACTION, fontsize=8.5)
    draw_box(ax, (6.6, 4.75), 2.9, 0.85, "Private tag removal", fc="#FADBD8", ec=C_ACTION, fontsize=8.5)
    for x in (4.95, 8.05):
        arrow(ax, (6.5, 8.0), (x, 6.7))

    draw_box(
        ax, (3.5, 3.35), 6.0, 1.05,
        "De-identified DICOM repository\n(provenance retained; pixels unchanged)",
        fc="#D5F5E3", ec=C_PRESERVE, bold=True, fontsize=9.5,
    )
    arrow(ax, (6.5, 4.75), (6.5, 4.4))

    draw_box(
        ax, (3.5, 2.0), 6.0, 0.95,
        "DICOM-to-NIfTI conversion → BIDS dataset",
        fc="#D6EAF8", ec=C_DERIVED, bold=True, fontsize=9.5,
    )
    arrow(ax, (6.5, 3.35), (6.5, 2.95))

    draw_box(
        ax, (3.5, 0.55), 6.0, 0.95,
        "Quality control & validation",
        fc="#D5DBDB", ec=C_EDGE, bold=True, fontsize=9.5,
    )
    arrow(ax, (6.5, 2.0), (6.5, 1.5))

    ax.text(
        5.0, 14.55,
        "De-identification workflow for research release preparation",
        ha="center", fontsize=12, fontweight="bold", color=C_RAW,
    )
    ax.text(
        5.0, 14.15,
        "Downstream processing uses derived copies; the raw archive is never overwritten",
        ha="center", fontsize=8.5, color=C_NEUTRAL, style="italic",
    )

    fig.tight_layout()
    png = OUT / "figure_deidentification_workflow.png"
    svg = OUT / "figure_deidentification_workflow.svg"
    fig.savefig(png, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Wrote {png.name}, {svg.name}")


def figure_tag_actions() -> None:
    counts = action_counts()
    # Order as scientifically narrative
    order = [
        "Cleared",
        "Pseudonymized",
        "UID remapped",
        "Date shifted",
        "Preserved",
        "Removed private tags",
        "Pixel data unchanged",
    ]
    values = [counts[k] for k in order]
    colors = [
        "#C0392B", "#E67E22", "#8E44AD", "#2980B9",
        "#1E8449", "#7F8C8D", "#16A085",
    ]

    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=300)
    fig.patch.set_facecolor("white")
    y = np.arange(len(order))
    bars = ax.barh(y, values, color=colors, edgecolor=C_EDGE, height=0.68)
    ax.set_yticks(y)
    ax.set_yticklabels(order, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("Number of explicitly catalogued DICOM fields / categories", fontsize=10)
    ax.set_title(
        "Summary of DICOM metadata transformations during de-identification",
        fontsize=12, fontweight="bold", color=C_RAW, pad=12,
    )
    style_axes(ax)
    xmax = max(values) + 4
    ax.set_xlim(0, xmax)
    for bar, val in zip(bars, values):
        ax.text(
            val + 0.15, bar.get_y() + bar.get_height() / 2,
            str(val), va="center", ha="left", fontsize=9.5, color=C_RAW, fontweight="bold",
        )
    ax.text(
        0.99, -0.18,
        "Counts reflect the documented tag policy. "
        "‘Removed private tags’ and ‘Pixel data unchanged’ are single policy categories "
        "(all private tags removed; pixel matrices unaltered).",
        transform=ax.transAxes, ha="right", va="top", fontsize=7.5, color=C_NEUTRAL,
    )
    fig.tight_layout()
    png = OUT / "figure_dicom_tag_actions.png"
    svg = OUT / "figure_dicom_tag_actions.svg"
    fig.savefig(png, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Wrote {png.name} counts={counts}")


def figure_before_after() -> None:
    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=300)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(6, 7.55, "Illustrative DICOM header transformation (synthetic example)",
            ha="center", fontsize=12, fontweight="bold", color=C_RAW)
    ax.text(6, 7.15, "No real participant identifiers are shown",
            ha="center", fontsize=8.5, color=C_NEUTRAL, style="italic")

    # Before panel
    ax.add_patch(FancyBboxPatch((0.4, 0.6), 5.0, 6.1, boxstyle="round,pad=0.02,rounding_size=0.03",
                                facecolor="#FDEDEC", edgecolor=C_ACTION, linewidth=1.8))
    ax.text(2.9, 6.3, "Before de-identification", ha="center", fontsize=11, fontweight="bold", color=C_ACTION)

    before_lines = [
        ("PatientName", "SUBXYZ_VisitA_YYYYMMDD"),
        ("PatientID", "SCANNER_LOCAL_ID_12345"),
        ("StudyDate", "20230505"),
        ("StudyInstanceUID", "1.2.840.113619.2.xx.original"),
    ]
    y = 5.5
    for key, val in before_lines:
        ax.text(0.7, y, key, fontsize=9, fontweight="bold", color=C_RAW)
        ax.text(0.7, y - 0.35, val, fontsize=8.5, color=C_NEUTRAL, family="monospace")
        y -= 1.25

    # After panel
    ax.add_patch(FancyBboxPatch((6.6, 0.6), 5.0, 6.1, boxstyle="round,pad=0.02,rounding_size=0.03",
                                facecolor="#E8F8F5", edgecolor=C_PRESERVE, linewidth=1.8))
    ax.text(9.1, 6.3, "After de-identification", ha="center", fontsize=11, fontweight="bold", color=C_PRESERVE)

    after_lines = [
        ("PatientName", "SUBC000  (canonical study code)"),
        ("PatientID", "SUBC000  (canonical study code)"),
        ("StudyDate", "20141212  (shifted by fixed offset)"),
        ("StudyInstanceUID", "2.25.9062200888896994…"),
    ]
    y = 5.5
    for key, val in after_lines:
        ax.text(6.9, y, key, fontsize=9, fontweight="bold", color=C_RAW)
        ax.text(6.9, y - 0.35, val, fontsize=8.5, color=C_NEUTRAL, family="monospace")
        y -= 1.25

    ax.annotate(
        "",
        xy=(6.5, 3.6),
        xytext=(5.5, 3.6),
        arrowprops=dict(arrowstyle="-|>", color=C_EDGE, lw=2.2, mutation_scale=16),
    )
    ax.text(6.0, 4.0, "transform", ha="center", fontsize=8, color=C_EDGE, fontweight="bold")

    fig.tight_layout()
    png = OUT / "figure_before_after_deidentification.png"
    svg = OUT / "figure_before_after_deidentification.svg"
    fig.savefig(png, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Wrote {png.name}")


def figure_provenance() -> None:
    fig, ax = plt.subplots(figsize=(7.8, 11.0), dpi=300)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 14)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(5, 13.5, "Data provenance and integrity", ha="center",
            fontsize=13, fontweight="bold", color=C_RAW)
    ax.text(5, 13.05, "Original acquisitions remain untouched throughout",
            ha="center", fontsize=9, color=C_PRESERVE, fontweight="bold", style="italic")

    # Persistent raw box on left spanning
    ax.add_patch(
        FancyBboxPatch(
            (0.35, 1.0), 2.7, 11.5,
            boxstyle="round,pad=0.02,rounding_size=0.03",
            facecolor="#EBF5FB", edgecolor=C_RAW, linewidth=2.0, linestyle=(0, (5, 3)),
        )
    )
    ax.text(1.7, 11.9, "Immutable\nraw DICOM", ha="center", fontsize=10,
            fontweight="bold", color=C_RAW)
    ax.text(1.7, 10.6, "Never\noverwritten", ha="center", fontsize=8.5, color=C_NEUTRAL)
    ax.text(1.7, 3.0, "Integrity\nsnapshots\nchecked before\nconversion", ha="center",
            fontsize=8, color=C_RAW)

    stages = [
        (11.2, "Inventory\n(metadata extraction)"),
        (9.7, "Participant–session\nmapping"),
        (8.2, "De-identification\n(derived copies)"),
        (6.7, "Privacy validation"),
        (5.2, "BIDS conversion"),
        (3.7, "Dataset validation"),
        (2.2, "Quality control"),
        (0.7, "Open research\ndataset"),
    ]
    for y, label in stages:
        fc = "#D5F5E3" if "Open" in label else "#FFFFFF"
        ec = C_PRESERVE if "Open" in label else C_DERIVED
        draw_box(ax, (4.0, y), 5.4, 1.15, label, fc=fc, ec=ec, bold=True, fontsize=9.5)

    for i in range(len(stages) - 1):
        y_top = stages[i][0]
        y_bot = stages[i + 1][0] + 1.15
        arrow(ax, (6.7, y_top), (6.7, y_bot))

    # dashed read links from raw
    for y in (11.7, 8.7):
        ax.annotate(
            "",
            xy=(4.0, y),
            xytext=(3.05, y),
            arrowprops=dict(arrowstyle="-|>", color=C_RAW, lw=1.1, linestyle="--", mutation_scale=9),
        )

    ax.text(3.4, 12.0, "source", fontsize=7, color=C_RAW, rotation=0)
    ax.text(3.25, 9.0, "copy", fontsize=7, color=C_RAW)

    fig.tight_layout()
    png = OUT / "figure_data_provenance.png"
    svg = OUT / "figure_data_provenance.svg"
    fig.savefig(png, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Wrote {png.name}")


def write_counts_sidecar() -> None:
    counts = action_counts()
    path = OUT / "dicom_tag_action_counts.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Action category", "Count"])
        for k, v in counts.items():
            w.writerow([k, v])
    print(f"Wrote {path.name}: {counts}")


def main() -> None:
    write_csv_and_xlsx()
    write_counts_sidecar()
    figure_workflow()
    figure_tag_actions()
    figure_before_after()
    figure_provenance()


if __name__ == "__main__":
    main()
