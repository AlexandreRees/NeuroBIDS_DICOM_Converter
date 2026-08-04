#!/usr/bin/env python3
"""Dataset publication status PDF — assembled from existing inventories/audits only.

No full BIDS / raw_original rescan. Sources listed in the PDF footer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path("/home/alexrees/scratch")
OUT_DIR = ROOT / "reports" / "pi_pipeline_briefing"
OUT = OUT_DIR / "Dataset_Publication_Status_Complete.pdf"

INK = colors.HexColor("#1C2430")
MUTED = colors.HexColor("#5A6570")
OK = colors.HexColor("#0E6B5C")
WARN = colors.HexColor("#A65D1A")
FAIL = colors.HexColor("#B42318")
SOFT = colors.HexColor("#F3F1EC")
RULE = colors.HexColor("#D4D0C8")
SOFT_OK = colors.HexColor("#E6F2EF")
SOFT_WARN = colors.HexColor("#F8EFE4")
SOFT_FAIL = colors.HexColor("#F7E8E6")


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=16, textColor=INK, spaceAfter=4, leading=20, alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=10, textColor=MUTED, spaceAfter=10, leading=13, alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=12.5, textColor=INK, spaceBefore=11, spaceAfter=5, leading=15,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=10.5, textColor=INK, spaceBefore=8, spaceAfter=3, leading=13,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=9.5, textColor=INK, spaceBefore=6, spaceAfter=2, leading=12,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.8, textColor=INK, leading=11.8, alignment=TA_JUSTIFY, spaceAfter=3,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.8, textColor=MUTED, leading=10.2, alignment=TA_LEFT, spaceAfter=2,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.6, textColor=INK, leading=11.2, leftIndent=2,
        ),
        "callout": ParagraphStyle(
            "callout", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, textColor=INK, leading=12, alignment=TA_JUSTIFY,
        ),
        "th": ParagraphStyle(
            "th", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=7.6, textColor=INK, leading=9.5,
        ),
        "td": ParagraphStyle(
            "td", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.4, textColor=INK, leading=9.4,
        ),
        "status_ok": ParagraphStyle(
            "status_ok", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.5, textColor=OK, leading=11,
        ),
        "status_warn": ParagraphStyle(
            "status_warn", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.5, textColor=WARN, leading=11,
        ),
        "status_fail": ParagraphStyle(
            "status_fail", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.5, textColor=FAIL, leading=11,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontName="Helvetica",
            fontSize=7, textColor=MUTED, leading=9,
        ),
    }


def P(text: str, style) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), style)


def bullets(items, style) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(i, style), leftIndent=8, bulletColor=INK) for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=12,
        spaceBefore=1,
        spaceAfter=4,
    )


def table(rows, col_widths, header=True):
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    style_cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("BACKGROUND", (0, 0), (-1, 0), SOFT) if header else ("SPAN", (0, 0), (0, 0)),
    ]
    if header:
        style_cmds.append(("BACKGROUND", (0, 0), (-1, 0), SOFT))
    # zebra
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FAFAF8")))
    t.setStyle(TableStyle(style_cmds))
    return t


def callout_box(story, text, style, bg=SOFT_WARN):
    data = [[P(text, style)]]
    t = Table(data, colWidths=[175 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BOX", (0, 0), (-1, -1), 0.6, RULE),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 4 * mm))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "Dataset Publication Status — inventaires existants seulement (pas de rescan complet)")
    canvas.drawRightString(192 * mm, 10 * mm, f"p. {doc.page}")
    canvas.restoreState()


def build():
    S = styles()
    story = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Cover / executive ─────────────────────────────────────────────
    story.append(P("État complet du dataset — prêt pour publication ?", S["title"]))
    story.append(
        P(
            f"Rapport de synthèse · {today} UTC · sources = inventaires, mappings et audits déjà produits "
            f"(pas de rescan filesystem de raw_original/ ni de bids/).",
            S["subtitle"],
        )
    )

    callout_box(
        story,
        "<b>Verdict publication aujourd’hui :</b> "
        "<font color='#A65D1A'><b>PAS PRÊT POUR UPLOAD OPENNEURO / SCIENTIFIC DATA AUJOURD’HUI</b></font> "
        "sur le plan <b>légal / metadata / packaging</b>. "
        "En revanche, le contenu technique (conversion imaging, défacing freeze, QC MRIQC/DWI/Pizarro, "
        "physio PhysioLog majoritaire, events movie/grating) est <font color='#0E6B5C'><b>largement prêt</b></font> "
        "à condition de documenter explicitement les trous et warnings ci-dessous.",
        S["callout"],
        SOFT_WARN,
    )

    story.append(P("1. Verdict exécutif et portes bloquantes", S["h1"]))
    story.append(
        P(
            "Ce document répond à la question : <i>si je publiais aujourd’hui, qu’est-ce que contient "
            "exactement mon dataset, pourquoi certains warnings existent, et que reste-t-il à faire ?</i>",
            S["body"],
        )
    )

    rows = [
        [P("Porte", S["th"]), P("Statut", S["th"]), P("Action requise", S["th"])],
        [P("Conversion BIDS imaging (research <font face='Courier'>bids/</font>)", S["td"]),
         P("<font color='#0E6B5C'><b>OK</b></font> — 84 sujets / 135 sessions", S["td"]),
         P("Aucune (garder comme source de vérité technique)", S["td"])],
        [P("Arbre public <font face='Courier'>release_dataset/</font> défacé", S["td"]),
         P("<font color='#A65D1A'><b>Vérifier</b></font> — snapshot juil. 29 = 135 dirs session ; freeze antérieur 124", S["td"]),
         P("Confirmer défacing des 11 ses-02 post-freeze avant affirmDefaced", S["td"])],
        [P("Authors / Name / License / consent", S["td"]),
         P("<font color='#B42318'><b>BLOQUANT</b></font>", S["td"]),
         P("Liste auteurs réelle ; titre final ; license (souvent CC0) + feu vert REB/PI", S["td"])],
        [P("QC MRIQC / DWI / Pizarro", S["td"]),
         P("<font color='#0E6B5C'><b>OK</b></font> avec disclosure", S["td"]),
         P("Inclure catalogue warnings ; ne pas exclure automatiquement", S["td"])],
        [P("Physiologie PhysioLog (pulse/resp)", S["td"]),
         P("<font color='#0E6B5C'><b>OK majoritaire</b></font> ; trous documentés", S["td"]),
         P("Documenter 305 PhysioLog exclus ; clarifier trigger/ECG ; PMU peripheral hors release", S["td"])],
        [P("Eye-tracking / stimuli MP4", S["td"]),
         P("<font color='#A65D1A'><b>Hors BIDS public</b></font>", S["td"]),
         P("Décider : v2 ou never ; ne pas redistribuer MP4 sans droits", S["td"])],
        [P("dmriqc <font face='Courier'>QC_DWI_Protocol</font>", S["td"]),
         P("<font color='#A65D1A'><b>ÉCHEC soft</b></font>", S["td"]),
         P("Optionnel — inventaire + Fig 3–6 déjà exploitables", S["td"])],
        [P("bids-validator final sur arbre d’upload", S["td"]),
         P("<font color='#A65D1A'><b>À rejouer</b></font>", S["td"]),
         P("0 erreur obligatoire avant dépôt", S["td"])],
    ]
    story.append(table(rows, [58 * mm, 55 * mm, 62 * mm]))
    story.append(Spacer(1, 3 * mm))

    story.append(P("2. Ce que contient le dataset (cartes des arbres)", S["h1"]))
    story.append(P("2.1 Trois arbres distincts", S["h2"]))
    story.append(
        bullets(
            [
                "<b>raw_original/</b> — archive immuable DICOM + MATLAB + périphériques "
                "(cohortes Control, Glaucoma, Data_ON, Data_TON). <b>Ne jamais uploader.</b>",
                "<b>bids/</b> — arbre de recherche face-intact + physio convertie + events. "
                "84 sujets, 135 sessions imaging (<font face='Courier'>sessions.tsv</font>).",
                "<b>release_dataset/</b> — candidat public défacé. Snapshot documentation "
                "2026-07-29 : 84 sujets ; modalités live (bold 3243, sbref 3118, epi/fmap 1066, "
                "dwi 399, T1w 385, TB1TFL 270, FLAIR 136) ; physio ~3620 sidecars tsv.gz.",
            ],
            S["bullet"],
        )
    )

    story.append(P("2.2 Cohorte", S["h2"]))
    rows = [
        [P("Cohorte", S["th"]), P("N sujets", S["th"]), P("Notes", S["th"])],
        [P("Control", S["td"]), P("56", S["td"]), P("Cohorte principale sains / contrôles", S["td"])],
        [P("Glaucoma", S["td"]), P("19", S["td"]), P("Pathologie glaucome", S["td"])],
        [P("Data_ON / DataON", S["td"]), P("7", S["td"]), P("Sous-cohorte optic neuritis (legacy folder Data_ON)", S["td"])],
        [P("Data_TON / DataTON", S["td"]), P("2", S["td"]), P("Sous-cohorte (legacy folder Data_TON)", S["td"])],
        [P("<b>Total</b>", S["td"]), P("<b>84</b>", S["td"]), P("ses-01 n=83 · ses-02 n=52 · 135 sessions imaging", S["td"])],
    ]
    story.append(table(rows, [45 * mm, 25 * mm, 105 * mm]))
    story.append(
        P(
            "Longitudinal : 51 sujets avec les deux sessions ; 32 ses-01 seulement ; 1 ses-02 seulement "
            "(d’après CURRENT_DATASET_STATE.json). Ce n’est <b>pas</b> un trou technique systématique — "
            "c’est la couverture visite réelle.",
            S["body"],
        )
    )

    story.append(P("2.3 raw_original → inventaire → mapping → BIDS", S["h2"]))
    story.append(
        P(
            "La chaîne de traçabilité repose sur des artefacts déjà produits : "
            "<font face='Courier'>metadata/session_mapping.csv</font> (≈10 026 lignes séries DICOM, "
            "84 sujets, 135 sessions), "
            "<font face='Courier'>metadata/participants.tsv</font>, "
            "<font face='Courier'>metadata/sessions.tsv</font>, "
            "inventaires cohortes (<font face='Courier'>inventory_Data_ON*.json</font>, etc.), "
            "et <font face='Courier'>reports/associated_data_inventory.tsv</font> (5 756 fichiers non-DICOM sous raw). "
            "Le mapping freeze (2026-07-20) est documenté comme PASS.",
            S["body"],
        )
    )
    story.append(
        bullets(
            [
                "Inventaire DICOM Narval : warnings mineurs (3× subject_identifier_not_present Data_ON) — "
                "identité prise depuis le dossier, pas un trou de données.",
                "Associated raw : eye_tracking 448 · physiology PMU 339 · stimulus 3716 · task_timing 1108 · unknown 145.",
                "Comparaison utile pour publication : tout ce qui est en BIDS a une généalogie raw ; "
                "tout ce qui est en raw n’est pas forcément en BIDS (PMU peripheral, eye-tracking, MP4, "
                "PhysioLog exclus, localizers éventuellement omis du dépôt public).",
            ],
            S["bullet"],
        )
    )

    story.append(PageBreak())
    story.append(P("3. Séquences MRI — contenu et explication", S["h1"]))
    story.append(
        P(
            "Scanner type : Siemens MAGNETOM Prisma 3 T, syngo MR E11 (extrait protocol sample). "
            "Functional BOLD partagé : TR 937 ms, TE 37 ms, flip 52°, voxels 2 mm iso (epfid2d1_104). "
            "Source catalogue : <font face='Courier'>MRI_SEQUENCE_INVENTORY.tsv</font>.",
            S["body"],
        )
    )

    story.append(P("3.1 Anatomie et calibration", S["h2"]))
    rows = [
        [P("Séquence", S["th"]), P("Rôle", S["th"]), P("Usage analytique", S["th"])],
        [P("Localizer", S["td"]),
         P("Scout GRE pour prescription de coupe (début + après bloc fonctionnel)", S["td"]),
         P("Planning uniquement ; rarement publié comme donnée primaire", S["td"])],
        [P("T1w_MPR", S["td"]),
         P("MPRAGE T1 haute résolution — référence anatomique", S["td"]),
         P("Surface corticale, registration, FreeSurfer-class", S["td"])],
        [P("WMn_MPRAGE_sagittal", S["td"]),
         P("MPRAGE white-matter-nulled — contraste thalamus / deep gray", S["td"]),
         P("Complément du T1w (couverture incomplète, voir §6)", S["td"])],
        [P("Sag Flair 3D-0.8", S["td"]),
         P("3D FLAIR T2 — CSF supprimé", S["td"]),
         P("Lésions WM / voie optique", S["td"])],
        [P("tfl_b1map_1mmiso (TB1TFL)", S["td"]),
         P("Cartographie B1+ avant RESOLVE", S["td"]),
         P("Correction quantitative ; décision include vs .bidsignore ouverte", S["td"])],
    ]
    story.append(table(rows, [40 * mm, 70 * mm, 65 * mm]))

    story.append(P("3.2 IRMf — paradigmes", S["h2"]))
    story.append(
        P(
            "Chaque run BOLD AP/PA est généralement accompagné d’un <b>SBRef</b> (single-band reference) "
            "et d’un <b>PhysioLog</b> Siemens (séries *_PhysioLog dans session_mapping).",
            S["body"],
        )
    )
    rows = [
        [P("Famille BIDS", S["th"]), P("Labels scanner", S["th"]), P("Explication", S["th"])],
        [P("task-fmri (Gratings)", S["td"]),
         P("fMRI1–4_AP (~226 vol)", S["td"]),
         P("Stimulation visuelle grating/checkerboard (≈3.5 min). Events Psycholtoolbox pour la majorité des runs ; "
           "553 bold magnitude, 514 events (39 sans events — mapping ambigu volontairement omis).", S["td"])],
        [P("task-movie", S["td"]),
         P("Movie1–4_AP (~210 vol)", S["td"]),
         P("Visionnage naturaliste de clips (~3.3 min). Events générés par politique protocole "
           "(onset=0, durée MP4≈196.8 s) — pas de logs triggerTimes Psychtoolbox pour movie.", S["td"])],
        [P("task-rest", S["td"]),
         P("REST1_AP (~320 vol)", S["td"]),
         P("Repos yeux ouverts, fixation centrale, ~5 min. Un run/session. Pas d’events (by design). "
           "Protocole MATLAB : fixation binoculaire (pas monovisuel comme movie/grating).", S["td"])],
        [P("task-control", S["td"]),
         P("Control1_PA, Control2_AP, Control3_PA (+ variantes rares)", S["td"]),
         P("Courts EPI (~20 vol / ~19 s) avec phase-encoding parfois inversée — références PE pour contrôle / SDC. "
           "Pas d’events de tâche cognitive.", S["td"])],
        [P("fmap SE", S["td"]),
         P("SpinEchoFieldMap_AP/PA", S["td"]),
         P("Paires opposées PE (souvent 2 paires/session) pour TOPUP / SDC des BOLD (et parfois séries EPI). "
           "Couverture : 135/135 sessions au niveau présence mapping.", S["td"])],
    ]
    story.append(table(rows, [38 * mm, 42 * mm, 95 * mm]))

    story.append(P("3.3 Diffusion", S["h2"]))
    rows = [
        [P("Famille", S["th"]), P("N scans (dmriqc)", S["th"]), P("Explication", S["th"])],
        [P("GSLD AP multi-shell", S["td"]), P("264", S["td"]),
         P("gsld_76dir_b2000_1mmiso_AP — recherche multi-directions (b≈0/1000/2000). Typiquement run-01 et run-02.", S["td"])],
        [P("GSLD PA b0", S["td"]), P("258", S["td"]),
         P("gsld_75TE_PA_3b0 — b0 reverse-PE pour correction susceptibilité (TOPUP/eddy) du GSLD AP.", S["td"])],
        [P("RESOLVE AP", S["td"]), P("132", S["td"]),
         P("RESOLVE readout-segmented — DWI clinique faible distorsion (souvent b0/1000).", S["td"])],
        [P("RESOLVE PA", S["td"]), P("132", S["td"]),
         P("Compagnon reverse-PE pour RESOLVE.", S["td"])],
        [P("RESOLVE TRACEW (+ dérivés)", S["td"]), P("125 TRACEW (+ FA/ADC/TENSOR…)", S["td"]),
         P("Traces / cartes dérivées scanner. TRACEW monovolume exclu de QC_DWI_Protocol (crash dmriqcpy).", S["td"])],
        [P("OTHER / MISSING_JSON", S["td"]), P("12", S["td"]),
         P("Cas atypiques / sidecars manquants — à divulguer, pas à « réparer » sans revue.", S["td"])],
    ]
    story.append(table(rows, [40 * mm, 35 * mm, 100 * mm]))
    story.append(
        P(
            "Total mosaïques dmriqc <font face='Courier'>QC_Raw_DWI</font> : <b>923/923</b> DWI BIDS. "
            "Métriques motion/SNR numériques : 396 (GSLD AP + RESOLVE AP). "
            "Validation technique parallèle dans <font face='Courier'>reports/dwi_qc/</font> "
            "(intégrité, dwigradcheck, signal robuste).",
            S["body"],
        )
    )

    story.append(PageBreak())
    story.append(P("4. Physiologie et canaux périphériques", S["h1"]))

    story.append(P("4.1 PhysioLog Siemens (par run BOLD) — EN BIDS", S["h2"]))
    story.append(
        P(
            "Source : objets DICOM PhysioLog (CSA non-image), pas des Waveform IOD classiques. "
            "Conversion gated (2026-07-27) : ~1256 BOLD stems avec ≥1 sidecar ; "
            "produits on-disk initialement 3575 tsv.gz+json ; snapshot release ultérieur "
            "rapporte ~3620. Recording types typiques :",
            S["body"],
        )
    )
    rows = [
        [P("recording-*", S["th"]), P("Canal Siemens", S["th"]), P("Contenu / utilité", S["th"]), P("Couverture approx.", S["th"])],
        [P("pulse", S["td"]), P("PULS", S["td"]),
         P("Pléthysmographie / pouls PPG — RETROICOR cardiaque, QC rythme", S["td"]),
         P("~1112–1127", S["td"])],
        [P("respiratory", S["td"]), P("RESP", S["td"]),
         P("Ceinture / respiration — RETROICOR respiratoire, QC", S["td"]),
         P("~1243–1258", S["td"])],
        [P("trigger", S["td"]), P("EXT / EXT2", S["td"]),
         P("<b>Problématique :</b> fichiers existants (~1223) = artefacts de parse "
           "(valeurs {1,8}), PAS un train de triggers volume utilisable. "
           "EXT source = flatline VALUE=1. Ne pas s’en servir pour synchronisation volume.", S["td"]),
         P("~1223 (qualité MINIMAL_SYNC_MARK)", S["td"])],
        [P("ecg", S["td"]), P("ECG", S["td"]),
         P("ECG rarement activé / converti — sparse", S["td"]),
         P("~12", S["td"])],
    ]
    story.append(table(rows, [28 * mm, 28 * mm, 90 * mm, 29 * mm]))

    story.append(P("4.2 PhysioLog exclus de la conversion BIDS", S["h2"]))
    rows = [
        [P("Classe d’exclusion", S["th"]), P("N", S["th"]), P("Cause exacte", S["th"]), P("Que faire ?", S["th"])],
        [P("EXT_ONLY_NO_STARTTIME", S["td"]), P("206", S["td"]),
         P("PhysioLog seulement canal EXT, sans StartTime CSA fiable ; EXT non informatif", S["td"]),
         P("Documenter exclusion définitive pour Level-1 ; ne pas convertir", S["td"])],
        [P("MAPPING_AMBIGUOUS", S["td"]), P("48", S["td"]),
         P("Association BOLD non unique (subject/session/ProtocolName)", S["td"]),
         P("Rester fail-closed ; éventuellement revue manuelle si PI priorise un run", S["td"])],
        [P("NO_SAMPLETIME_AND_NO_STARTTIME", S["td"]), P("38", S["td"]),
         P("Pas de SampleTime ni ticks canal → impossible de dériver Hz / StartTime "
           "sans inventer. Inclut sub-007/008/009 ses-01 (pas de PMU peripheral ses-01) "
           "et cas sub-042", S["td"]),
         P("Exclusion définitive Level-1 (clos 2026-07-29)", S["td"])],
        [P("NO_STARTTIME_WITH_PHYSIO_CHANNELS", S["td"]), P("13", S["td"]),
         P("PULS/RESP présents mais StartTime non dérivable", S["td"]),
         P("Documenter perte ; ne pas inventer l’horloge", S["td"])],
        [P("<b>Total exclus</b>", S["td"]), P("<b>305</b>", S["td"]),
         P("Sur ~1626 objets PhysioLog inventoriés", S["td"]),
         P("Disclosure Methods + Supplemental table", S["td"])],
    ]
    story.append(table(rows, [42 * mm, 16 * mm, 75 * mm, 42 * mm]))

    story.append(P("4.3 PMU périphériques session-wide (.puls / .resp / .ecg) — HORS BIDS", S["h2"]))
    story.append(
        P(
            "Sous raw_original : ~114 .puls + 114 .resp + 111 .ecg (associated_data_inventory). "
            "Ce sont des logs <b>session-wide</b>, sans fréquence ADC site-confirmée et sans découpe "
            "run validée → politique fail-closed : <b>pas convertis en BIDS run-wise</b>. "
            "Ils restent utiles en sourcedata privée / analyses internes si le site confirme Hz.",
            S["body"],
        )
    )

    story.append(P("4.4 Eye-tracking — inventorié, pas en BIDS public", S["h2"]))
    story.append(
        P(
            "~448 fichiers classés eye_tracking sous raw (surtout .m/.mat). "
            "<b>0</b> timeseries eyetrack dans l’arbre BIDS public. "
            "Décision PI requise : hors scope Scientific Data v1 (recommandé) vs chantier v2 "
            "(format, sync, PHI).",
            S["body"],
        )
    )

    story.append(P("4.5 Stimuli / movies", S["h2"]))
    story.append(
        P(
            "~104 MP4 + nombreux .mat/.m de stimulus sous raw. "
            "<b>Ne pas redistribuer les MP4</b> sans clearance droits. "
            "Pour le paper : publier identifiants, checksums, et instructions d’accès — "
            "pas les médias.",
            S["body"],
        )
    )

    story.append(PageBreak())
    story.append(P("5. Complétude sessionnelle (trous réels vs présents)", S["h1"]))
    story.append(
        P(
            "Dénominateur = participants imagés à la session (<font face='Courier'>sessions.tsv</font>). "
            "Présence = ≥1 série matchée dans <font face='Courier'>session_mapping.csv</font>. "
            "Chiffres alignés avec la figure PI de complétude (régénérée juil. 2026).",
            S["body"],
        )
    )
    rows = [
        [P("Famille", S["th"]), P("ses-01 present/denom", S["th"]), P("Manquants ses-01", S["th"]),
         P("ses-02 present/denom", S["th"]), P("Manquants ses-02", S["th"])],
        [P("T1 (±WMn)", S["td"]), P("82/83", S["td"]), P("sub-055", S["td"]),
         P("50/52", S["td"]), P("sub-049, 078", S["td"])],
        [P("FLAIR", S["td"]), P("79/83", S["td"]), P("018, 033, 055, 070", S["td"]),
         P("50/52", S["td"]), P("049, 078", S["td"])],
        [P("rest-fMRI", S["td"]), P("82/83", S["td"]), P("055", S["td"]),
         P("50/52", S["td"]), P("049, 078", S["td"])],
        [P("Gratings", S["td"]), P("82/83", S["td"]), P("063", S["td"]),
         P("52/52", S["td"]), P("—", S["td"])],
        [P("Control", S["td"]), P("83/83", S["td"]), P("—", S["td"]),
         P("52/52", S["td"]), P("—", S["td"])],
        [P("Movie", S["td"]), P("82/83", S["td"]), P("063", S["td"]),
         P("52/52", S["td"]), P("—", S["td"])],
        [P("GSLD AP", S["td"]), P("81/83", S["td"]), P("055, 070", S["td"]),
         P("49/52", S["td"]), P("008, 049, 078", S["td"])],
        [P("GSLD PA", S["td"]), P("80/83", S["td"]), P("033, 055, 070", S["td"]),
         P("50/52", S["td"]), P("049, 078", S["td"])],
        [P("RESOLVE AP/PA", S["td"]), P("80/83", S["td"]), P("033, 055, 070", S["td"]),
         P("50/52", S["td"]), P("049, 078", S["td"])],
        [P("Fieldmaps", S["td"]), P("83/83", S["td"]), P("—", S["td"]),
         P("52/52", S["td"]), P("—", S["td"])],
        [P("WMn", S["td"]), P("71/83", S["td"]),
         P("018,022,033,045,052,054,055,056,061,063,070,076", S["td"]),
         P("49/52", S["td"]), P("049, 064, 078", S["td"])],
        [P("B1 map", S["td"]), P("80/83", S["td"]), P("033, 055, 070", S["td"]),
         P("49/52", S["td"]), P("008, 049, 078", S["td"])],
    ]
    story.append(table(rows, [28 * mm, 32 * mm, 48 * mm, 32 * mm, 35 * mm]))
    story.append(
        P(
            "<b>Lecture :</b> Control et Fieldmaps sont complets. Les trous concentrés sur "
            "sub-055 / 070 / 033 (ses-01) et sub-049 / 078 (ses-02) reflètent des visites "
            "incomplètes ou protocoles abrégés — ce ne sont pas des échecs de conversion "
            "à « réparer » depuis raw (sauf preuve contraire dans une revue cas-par-cas). "
            "WMn a une couverture volontairement plus basse (ajout protocolaire non universel).",
            S["body"],
        )
    )

    story.append(P("5.1 Events fonctionnels", S["h2"]))
    rows = [
        [P("Task", S["th"]), P("BOLD mag (release snapshot)", S["th"]), P("Events", S["th"]), P("Commentaire", S["th"])],
        [P("fmri (grating)", S["td"]), P("553", S["td"]), P("514", S["td"]),
         P("39 manquants inventoriés (TWIN_OF_MAPPED_RUN / non acceptés) — omission intentionnelle mapping ambigu", S["td"])],
        [P("movie", S["td"]), P("536 (mag) / events policy 1072 écrits côté génération", S["td"]), P("536 (état release juil.29)", S["td"]),
         P("Onsets protocolaires (onset=0), pas psychtoolbox triggers", S["td"])],
        [P("rest / control", S["td"]), P("135 / 399", S["td"]), P("0 by design", S["td"]),
         P("Warnings validator EVENTS_TSV_MISSING attendus et OK si expliqués", S["td"])],
    ]
    story.append(table(rows, [30 * mm, 45 * mm, 30 * mm, 70 * mm]))

    story.append(PageBreak())
    story.append(P("6. Catalogue des warnings — causes et actions", S["h1"]))
    story.append(
        P(
            "Politique recommandée pour le Data Descriptor : "
            "<b>release inclusive</b> ; aucun warning n’est une exclusion automatique. "
            "Les exclusions appartiennent aux analyses secondaires.",
            S["body"],
        )
    )

    story.append(P("6.1 MRIQC", S["h2"]))
    rows = [
        [P("ID", S["th"]), P("Warning", S["th"]), P("Cause", S["th"]), P("Action publication", S["th"])],
        [P("W1", S["td"]), P("Missing IQM n=4", S["td"]),
         P("Acquisitions pathologiques : BOLD tronqués (sub-002 run-07=4 vol ; sub-011 run-03=3 vol) ; "
           "T1w hors protocole intensité/FOV (sub-039 ses-02 run-03 ; sub-058 ses-01 run-03). "
           "MRIQC RuntimeError data empty — comportement correct.", S["td"]),
         P("Lister en Technical Validation ; garder les fichiers BIDS", S["td"])],
        [P("W2", S["td"]), P("High motion fd≥0.5 mm n=23", S["td"]),
         P("Marqueur exploratoire (~1.7% des runs). Médiane cohort fd≈0.176 mm = qualité globale bonne.", S["td"]),
         P("Distribuer stats ; table en dérivés ; ne pas exclure du dépôt", S["td"])],
        [P("W3", S["td"]), P("Outliers IQM z/IQR 736 flags", S["td"]),
         P("Flags relatifs à CETTE cohorte (pas normes externes). 394 acq / 80 sujets touchés.", S["td"]),
         P("Exploratoire seulement — pas un taux d’échec", S["td"])],
    ]
    story.append(table(rows, [14 * mm, 38 * mm, 75 * mm, 48 * mm]))
    story.append(P("Couverture MRIQC historiquement ~1848/1852 (99.8%).", S["small"]))

    story.append(P("6.2 DWI QC", S["h2"]))
    rows = [
        [P("Warning", S["th"]), P("Cause", S["th"]), P("Correction données ?", S["th"])],
        [P("dwigradcheck REVIEW n=111", S["td"]),
         P("Enrichi run-02 ; suggestions flip/swap hétérogènes ; 0 FAIL. Artefact QC / ambiguïté ranking, "
           "pas table gradients corrompue démontrée.", S["td"]),
         P("<b>NON</b> — documenter seulement", S["td"])],
        [P("Negative mean b0 n=26", S["td"]),
         P("Reconstruction signée ± masque trop large — volumes non blancs/corrompus", S["td"]),
         P("<b>NON</b> — préférer métriques médiane", S["td"])],
        [P("PASS flip='0' classifier", S["td"]),
         P("Bug reporting interpret_dwigradcheck (≈3)", S["td"]),
         P("<b>NON</b> — fix logiciel optionnel", S["td"])],
        [P("Dice mask vs BET faible", S["td"]),
         P("Objectifs d’extraction différents ; sous-ensemble biaisé", S["td"]),
         P("<b>NON</b> — masks = aides QC", S["td"])],
        [P("SNR bimodal GSLD run-01 vs run-02", S["td"]),
         P("Collapse SNR QC sur second bloc AP (intensités signées / bruit MAD) — "
           "ne pas confondre avec PA (PA = autres runs)", S["td"]),
         P("Expliquer dans TV ; pas exclusion sujet", S["td"])],
        [P("QC_DWI_Protocol Nextflow FAIL", S["td"]),
         P("TRACEW monovolume puis SyntaxError heredoc du fix — pas de HTML protocole dmriqcpy", S["td"]),
         P("Optionnel à relancer ; inventaire+Fig3–6 suffisent", S["td"])],
    ]
    story.append(table(rows, [45 * mm, 85 * mm, 45 * mm]))

    story.append(P("6.3 Privacy / metadata / packaging", S["h2"]))
    rows = [
        [P("Item", S["th"]), P("Statut", S["th"]), P("Détail", S["th"])],
        [P("Authors placeholder", S["td"]), P("<font color='#B42318'><b>BLOQUANT</b></font>", S["td"]),
         P("« Neuro BIDS Pipeline » → liste réelle ordonnée", S["td"])],
        [P("License / consent share", S["td"]), P("<font color='#B42318'><b>BLOQUANT</b></font>", S["td"]),
         P("Pas de License ; confirmer REB 2020-5879 pour redistribution ouverte", S["td"])],
        [P("Name dataset", S["td"]), P("<font color='#A65D1A'><b>SOFT</b></font>", S["td"]),
         P("Titre placeholder à aligner sur l’article", S["td"])],
        [P("Docs physio count outdated", S["td"]),
         P("<font color='#A65D1A'><b>HIGH inconsistency</b></font>", S["td"]),
         P("extracted_metrics.md affiche encore 0 physio alors que ~3620 existent — refresh docs", S["td"])],
        [P("Free-text PHI release scan", S["td"]), P("<font color='#0E6B5C'><b>PASS</b></font>", S["td"]),
         P("0 hit Patient*/Institution*/dates sur audit release 2026-07-24", S["td"])],
        [P("Âge public", S["td"]), P("<font color='#0E6B5C'><b>DÉCIDÉ</b></font>", S["td"]),
         P("Pas d’âge dans participants.tsv public ; ne pas publier mean±SD", S["td"])],
        [P("TB1TFL", S["td"]), P("<font color='#A65D1A'><b>DÉCISION PI</b></font>", S["td"]),
         P("Fichiers présents ; .bidsignore possible — choisir include vs ignore", S["td"])],
    ]
    story.append(table(rows, [42 * mm, 40 * mm, 93 * mm]))

    story.append(PageBreak())
    story.append(P("7. Comparaison raw_original vs BIDS (ce qui manque où)", S["h1"]))
    rows = [
        [P("Contenu", S["th"]), P("Dans raw ?", S["th"]), P("Dans BIDS / release ?", S["th"]), P("Interprétation", S["th"])],
        [P("Séries MRI protocolaires (T1, FLAIR, BOLD, DWI, fmap…)", S["td"]),
         P("Oui (DICOM)", S["td"]), P("Oui (NIfTI+JSON) si présents en session", S["td"]),
         P("Trous = visites incomplètes (§5), pas inventaire cassé", S["td"])],
        [P("PhysioLog multi-canal PULS/RESP", S["td"]),
         P("Oui", S["td"]), P("Majorité convertie", S["td"]),
         P("305 UIDs exclus — raisons §4.2", S["td"])],
        [P("PhysioLog EXT-only", S["td"]), P("Oui", S["td"]), P("Non (et correct)", S["td"]),
         P("Canal plat / non utilisable", S["td"])],
        [P("PMU .puls/.resp/.ecg session", S["td"]), P("Oui (~339)", S["td"]), P("Non", S["td"]),
         P("Politique fail-closed ; sourcedata seulement", S["td"])],
        [P("Eye-tracking", S["td"]), P("Oui (~448)", S["td"]), P("Non", S["td"]),
         P("Hors scope v1 sauf décision contraire", S["td"])],
        [P("Movies MP4 + MATLAB stimulus", S["td"]), P("Oui", S["td"]), P("Code protocole sanitizé ; pas MP4", S["td"]),
         P("Droits d’auteur ; publier IDs/checksums", S["td"])],
        [P("Task timing MATLAB grating", S["td"]), P("Oui", S["td"]), P("Events pour 514/553", S["td"]),
         P("39 omissions mapping", S["td"])],
        [P("Dates / IDs identifiants / date-shift tables", S["td"]), P("Oui (PHI)", S["td"]), P("Non (privé)", S["td"]),
         P("Ne jamais déposer", S["td"])],
        [P("Localizers / cartes dérivées scanner RESOLVE", S["td"]),
         P("Oui", S["td"]), P("Partiel (FA/ADC… parfois présents)", S["td"]),
         P("Documenter ce qui est gardé", S["td"])],
    ]
    story.append(table(rows, [45 * mm, 30 * mm, 45 * mm, 55 * mm]))

    story.append(P("8. Ce qui est déjà OK (ne pas re-litiger)", S["h1"]))
    story.append(
        bullets(
            [
                "Mapping freeze PASS (84 sujets).",
                "Défacing + replacement anatomiques pour le freeze initial ; audit privacy free-text PASS.",
                "DWI technical validation PASS (0 FAIL gradients) ; mosaïques dmriqc 923/923.",
                "MRIQC prêt dépôt avec disclosure des 4 gaps.",
                "Pizarro screening complet (pas d’exclusion auto).",
                "PhysioLog pulse/resp majoritairement en BIDS ; PHI converter allowlist OK.",
                "Movie events + grating events documents + code protocole sous release_dataset/code/.",
                "Documentation readiness score global 21/22 (95.5%) — le point faible restant = Authors placeholder + refresh chiffres.",
            ],
            S["bullet"],
        )
    )

    story.append(P("9. Checklist actionnable — il reste à faire", S["h1"]))
    story.append(P("Bloquant avant upload", S["h2"]))
    story.append(
        bullets(
            [
                "Fournir Authors (ordre) + affiliations.",
                "Choisir Name final du dataset.",
                "Choisir License (recommandé CC0 si consentement ouvre) + confirmation PI/légal REB.",
                "Choisir snapshot : freeze documenté vs sync défacing 11 ses-02 (vérifier état défacing actuel).",
                "Re-run bids-validator sur l’arbre exact d’upload → 0 erreur.",
            ],
            S["bullet"],
        )
    )
    story.append(P("Fortement recommandé avant soumission manuscrit", S["h2"]))
    story.append(
        bullets(
            [
                "Refresh README / extracted_metrics (physio ≠ 0 ; MRIQC/DWI à jour).",
                "Disclosure Trigger : fichiers recording-trigger non exploitables comme trains volume.",
                "Table Supplemental des 305 PhysioLog exclus + 4 MRIQC unscored + 39 grating events omis.",
                "Décider TB1TFL include vs ignore.",
                "Décider derivatives OpenNeuro (MRIQC ± tables DWI) vs paper-only.",
                "Spot-check visuel défacing avant --affirmDefaced.",
                "Optionnel : fixer syntaxe et relancer QC_DWI_Protocol (non bloquant).",
            ],
            S["bullet"],
        )
    )
    story.append(P("Hors scope v1 (documenter seulement)", S["h2"]))
    story.append(
        bullets(
            [
                "Eye-tracking timeseries BIDS.",
                "PMU peripheral session-wide en run-wise BIDS.",
                "Redistribution MP4.",
                "Corrections bvec suite aux REVIEW dwigradcheck.",
                "Exclusions sujet basées uniquement sur motion / IQM outliers.",
            ],
            S["bullet"],
        )
    )

    story.append(P("10. Comment présenter dans le dataset paper (structure minimale)", S["h1"]))
    story.append(
        bullets(
            [
                "<b>Methods — Acquisition :</b> Prisma 3T ; catalogue §3 ; paradigmes fMRI ; GSLD+RESOLVE ; physio PhysioLog.",
                "<b>Methods — Preprocessing / curation :</b> de-id PS3.15-oriented subset ; mapping freeze ; défacing ; conversion BIDS.",
                "<b>Data Records :</b> 84 sujets, 135 sessions, modalités counts, events policy, physio channels + exclusions.",
                "<b>Technical Validation :</b> MRIQC coverage + 4 gaps ; DWI PASS/REVIEW ; complétude session ; Pizarro screening.",
                "<b>Usage Notes / Limitations :</b> trigger non utilisable ; peripheral PMU / eye hors dépôt ; movie onsets protocolaires ; WMn partiel.",
            ],
            S["bullet"],
        )
    )

    story.append(Spacer(1, 4 * mm))
    callout_box(
        story,
        "<b>Message une phrase :</b> Le dataset imaging+physio majoritaire est techniquement matur pour un "
        "Data Descriptor, mais un dépôt OpenNeuro aujourd’hui est encore bloqué par authorship/license/consent "
        "et par la confirmation packaging/défacing — pas par l’absence de figures QC ou d’inventaire.",
        S["callout"],
        SOFT_OK,
    )

    story.append(P("Sources utilisées (pas de rescan)", S["h2"]))
    story.append(
        P(
            "metadata/{participants,sessions,session_mapping,inventory_*}.tsv|csv|json · "
            "reports/release_documentation_audit/{SCIENTIFIC_DATA_READINESS_REPORT.md,CURRENT_DATASET_STATE.json} · "
            "reports/pi_pipeline_briefing/Remaining_Decisions_Before_OpenNeuro.md · "
            "reports/mri_protocol/MRI_SEQUENCE_INVENTORY.tsv · "
            "reports/functional_mri_paradigm_report.md · "
            "reports/associated_data_summary.md · "
            "reports/physiology_audit/final_bids_physio_readiness/* · "
            "reports/physiology_audit/trigger_audit/TRIGGER_AUDIT_REPORT.md · "
            "reports/mriqc_publication_audit/MRIQC_WARNINGS_AND_JUSTIFICATIONS.md · "
            "reports/dwi_qc/{DWI_WARNING_RESOLUTION,DWI_PUBLICATION_RECOMMENDATION,Technical_Validation_DWI}.md · "
            "derivatives/dmriqc/audit/* · reports/grating_rest_publication_audit · "
            "reports/movie_events_generation/MOVIE_EVENTS_GENERATION_REPORT.md · "
            "rapports dates principalement 2026-07-14 → 2026-07-31.",
            S["small"],
        )
    )

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title="Dataset Publication Status Complete",
        author="dataset status synthesis",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("Wrote", OUT)


if __name__ == "__main__":
    build()
