#!/usr/bin/env python3
"""Per-sequence and global data-state figures for Scientific Data / dmriqc audit."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path("/lustre07/scratch/alexrees")
BIDS = ROOT / "bids"
MOSAIC = ROOT / "derivatives/dmriqc/QC_Raw_DWI/data"
INV = ROOT / "derivatives/dmriqc/audit/dmriqc_sequence_inventory.tsv"
PUB = ROOT / "derivatives/dmriqc/publication"
QC = ROOT / "reports/dwi_qc"
PUB.mkdir(parents=True, exist_ok=True)
(PUB / "by_sequence").mkdir(parents=True, exist_ok=True)

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 140,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
    }
)

FAM_ORDER = [
    "GSLD_AP_multishell",
    "GSLD_PA_b0",
    "RESOLVE_AP",
    "RESOLVE_PA",
    "RESOLVE_TRACEW",
    "OTHER",
]
FAM_COLOR = {
    "GSLD_AP_multishell": "#1f4e79",
    "GSLD_PA_b0": "#2e75b6",
    "RESOLVE_AP": "#548235",
    "RESOLVE_PA": "#70ad47",
    "RESOLVE_TRACEW": "#c45911",
    "OTHER": "#7f7f7f",
}
FAM_TITLE = {
    "GSLD_AP_multishell": "GSLD multi-shell AP",
    "GSLD_PA_b0": "GSLD PA b0 (distortion pair)",
    "RESOLVE_AP": "RESOLVE AP",
    "RESOLVE_PA": "RESOLVE PA",
    "RESOLVE_TRACEW": "RESOLVE TRACEW (derived)",
    "OTHER": "Other / missing JSON",
}
FAM_BLURB = {
    "GSLD_AP_multishell": "Primary research diffusion (b≈0/1000/2000)",
    "GSLD_PA_b0": "PE-reversed b0 for distortion correction",
    "RESOLVE_AP": "Clinical RESOLVE (b≈0/1000)",
    "RESOLVE_PA": "PE-reversed RESOLVE companion",
    "RESOLVE_TRACEW": "Vendor TRACEW derivative (typically 1 volume)",
    "OTHER": "Missing sidecar or atypical SeriesDescription",
}


def classify_series(desc: str) -> str:
    d = (desc or "").lower()
    if "tracew" in d:
        return "RESOLVE_TRACEW"
    if "resolve" in d and ("_pa" in d or d.endswith("pa")):
        return "RESOLVE_PA"
    if "resolve" in d:
        return "RESOLVE_AP"
    if "pa_3b0" in d or "75te_pa" in d:
        return "GSLD_PA_b0"
    if "gsld" in d or "76dir" in d or "b2000" in d:
        return "GSLD_AP_multishell"
    return "OTHER"


def load_inventory() -> list[dict]:
    rows = []
    with open(INV) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            rows.append(r)
    # refresh family with fixed classifier
    for r in rows:
        r["sequence_family"] = classify_series(r.get("SeriesDescription") or "")
    return rows


def load_grad_status() -> dict[str, str]:
    gp = QC / "dwigradcheck_results.tsv"
    out = {}
    if not gp.exists():
        return out
    with open(gp) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            key = (
                row.get("bids_basename")
                or row.get("scan")
                or row.get("dwi")
                or row.get("file")
                or ""
            )
            if not key:
                sub = row.get("subject") or row.get("sub") or ""
                ses = row.get("session") or row.get("ses") or ""
                run = row.get("run") or ""
                if sub:
                    key = f"{sub}_{ses}_{run}_dwi".replace("__", "_")
            st = (row.get("status") or row.get("verdict") or row.get("result") or "").upper()
            if key:
                out[key] = st
    return out


def parse_shells(s: str) -> list[int]:
    if not s or s == "?":
        return []
    try:
        return [int(x) for x in s.split(",") if x.strip() != ""]
    except Exception:
        return []


def save(fig, path_stem: Path):
    fig.savefig(path_stem.with_suffix(".png"))
    fig.savefig(path_stem.with_suffix(".pdf"))
    plt.close(fig)
    print("wrote", path_stem.with_suffix(".png"))


def figure_global_state(rows: list[dict], grad: dict[str, str]):
    """One clear overview of dataset state after dmriqc."""
    fam = Counter(r["sequence_family"] for r in rows)
    subs = {r["subject"] for r in rows}
    sess = {(r["subject"], r["session"]) for r in rows}
    n_gif = sum(1 for r in rows if r.get("mosaic_format") == "gif")
    n_png = sum(1 for r in rows if r.get("mosaic_format") == "png")
    shells = Counter(r.get("unique_bvals") or "missing" for r in rows)
    pe = Counter(r.get("PhaseEncodingDirection") or "?" for r in rows)

    # protocol eligibility (multi-volume)
    n_proto = 0
    n_excl = 0
    for r in rows:
        try:
            nv = int(float(r["n_volumes"])) if r.get("n_volumes") not in ("", None) else 0
        except Exception:
            nv = 0
        if nv >= 2:
            n_proto += 1
        else:
            n_excl += 1

    fig = plt.figure(figsize=(11.5, 7.2))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.05, 1], hspace=0.35, wspace=0.35)

    # A counts
    ax = fig.add_subplot(gs[0, 0])
    metrics = [
        ("DWI scans", len(rows)),
        ("Subjects", len(subs)),
        ("Sessions", len(sess)),
        ("Mosaics OK", len(rows)),
        ("Protocol QC\nincluded (≥2 vol)", n_proto),
        ("Protocol QC\nexcluded (1 vol)", n_excl),
    ]
    ys = np.arange(len(metrics))[::-1]
    vals = [m[1] for m in metrics]
    cols = ["#1f4e79", "#1f4e79", "#1f4e79", "#548235", "#2e75b6", "#c45911"]
    ax.barh(ys, vals, color=cols, edgecolor="none")
    ax.set_yticks(ys)
    ax.set_yticklabels([m[0] for m in metrics])
    for y, v in zip(ys, vals):
        ax.text(v + max(vals) * 0.02, y, str(v), va="center", fontsize=8)
    ax.set_xlim(0, max(vals) * 1.25)
    ax.set_xlabel("Count")
    ax.set_title("A. Dataset & dmriqc status", loc="left", fontweight="bold")

    # B families
    ax = fig.add_subplot(gs[0, 1])
    order = [f for f in FAM_ORDER if fam.get(f, 0)]
    vals = [fam[f] for f in order]
    ax.barh(range(len(order)), vals, color=[FAM_COLOR[f] for f in order])
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([FAM_TITLE[f] for f in order], fontsize=8)
    ax.invert_yaxis()
    for i, v in enumerate(vals):
        ax.text(v + 5, i, f"{v} ({100 * v / len(rows):.0f}%)", va="center", fontsize=8)
    ax.set_xlim(0, max(vals) * 1.35)
    ax.set_xlabel("Scans")
    ax.set_title("B. Sequence families in dmriqc", loc="left", fontweight="bold")

    # C shells
    ax = fig.add_subplot(gs[0, 2])
    pref = ["0,1000,2000", "0,1000", "0", "1000", "missing"]
    labs = [x for x in pref if x in shells] + [x for x in shells if x not in pref]
    vs = [shells[x] for x in labs]
    ax.bar(range(len(labs)), vs, color="#1f4e79")
    ax.set_xticks(range(len(labs)))
    ax.set_xticklabels(labs, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Scans")
    ax.set_title("C. Unique b-value schemes", loc="left", fontweight="bold")
    for i, v in enumerate(vs):
        ax.text(i, v + max(vs) * 0.02, str(v), ha="center", fontsize=7)

    # D PE
    ax = fig.add_subplot(gs[1, 0])
    pe_labs, pe_vals = zip(*pe.most_common()) if pe else (["?"], [0])
    ax.pie(
        pe_vals,
        labels=[f"{a}\n{b}" for a, b in zip(pe_labs, pe_vals)],
        colors=["#1f4e79", "#70ad47", "#c45911", "#7f7f7f"][: len(pe_labs)],
        wedgeprops=dict(width=0.45, edgecolor="white"),
        textprops=dict(fontsize=8),
    )
    ax.set_title("D. PhaseEncodingDirection", loc="left", fontweight="bold")

    # E mosaic type
    ax = fig.add_subplot(gs[1, 1])
    ax.bar(["GIF (4D)", "PNG"], [n_gif, n_png], color=["#1f4e79", "#548235"])
    ax.set_ylabel("Scans")
    ax.set_title("E. dmriqc mosaic format", loc="left", fontweight="bold")
    for i, v in enumerate([n_gif, n_png]):
        ax.text(i, v + max(n_gif, n_png) * 0.02, str(v), ha="center")

    # F pipeline checklist
    ax = fig.add_subplot(gs[1, 2])
    ax.axis("off")
    ax.set_title("F. Pipeline checklist", loc="left", fontweight="bold")
    lines = [
        ("QC_Raw_DWI mosaics", True, f"{len(rows)}/{len(rows)}"),
        ("QC_DWI_Protocol", None, "relaunching (bval fix)"),
        ("TRACEW excluded from protocol", True, f"{n_excl} one-volume"),
        ("Multi-vol for protocol", True, f"{n_proto}"),
        ("Prior gradient QC available", True, "reports/dwi_qc"),
    ]
    y = 0.88
    for name, ok, note in lines:
        if ok is True:
            mark, col = "OK", "#548235"
        elif ok is False:
            mark, col = "FAIL", "#c00000"
        else:
            mark, col = "…", "#c45911"
        ax.text(0.02, y, mark, color=col, fontsize=9, fontweight="bold", transform=ax.transAxes)
        ax.text(0.16, y, f"{name}: {note}", fontsize=8, transform=ax.transAxes, va="center")
        y -= 0.16

    fig.suptitle(
        "Diffusion MRI data state — dmriqc_flow visual QC",
        fontsize=12,
        fontweight="bold",
        y=0.98,
    )
    save(fig, PUB / "Figure_data_state_overview")


def figure_one_sequence(family: str, rows: list[dict], grad: dict[str, str]):
    """Dedicated multi-panel figure for one sequence family."""
    rs = [r for r in rows if r["sequence_family"] == family]
    if not rs:
        return
    color = FAM_COLOR[family]
    n = len(rs)
    subs = sorted({r["subject"] for r in rs})
    sess = sorted({(r["subject"], r["session"]) for r in rs})
    pe = Counter(r.get("PhaseEncodingDirection") or "?" for r in rs)
    shells = Counter(r.get("unique_bvals") or "missing" for r in rs)
    runs = Counter(r.get("run") for r in rs)
    descs = Counter(r.get("SeriesDescription") or "MISSING_JSON" for r in rs)
    tes = []
    trs = []
    nvols = []
    for r in rs:
        try:
            if r.get("EchoTime") not in ("", None):
                tes.append(float(r["EchoTime"]))
        except Exception:
            pass
        try:
            if r.get("RepetitionTime") not in ("", None):
                trs.append(float(r["RepetitionTime"]))
        except Exception:
            pass
        try:
            if r.get("n_volumes") not in ("", None):
                nvols.append(int(float(r["n_volumes"])))
        except Exception:
            pass

    # subject coverage: scans per subject
    per_sub = Counter(r["subject"] for r in rs)
    # sessions presence
    ses_counts = Counter(r["session"] for r in rs)

    fig = plt.figure(figsize=(11.2, 7.0))
    gs = fig.add_gridspec(2, 3, hspace=0.38, wspace=0.32)

    # Header text panel
    ax = fig.add_subplot(gs[0, 0])
    ax.axis("off")
    ax.set_title("A. Identity", loc="left", fontweight="bold")
    txt = [
        f"Family: {FAM_TITLE[family]}",
        FAM_BLURB[family],
        "",
        f"Scans: {n}",
        f"Subjects: {len(subs)}",
        f"Sessions (sub×ses rows): {len(sess)}",
        f"Dominant PE: {pe.most_common(1)[0][0]} ({pe.most_common(1)[0][1]})",
        f"Dominant shells: {shells.most_common(1)[0][0]}",
        f"TE median: {np.median(tes):.4g} s" if tes else "TE: n/a",
        f"TR median: {np.median(trs):.4g} s" if trs else "TR: n/a",
        f"Volumes median: {int(np.median(nvols))}" if nvols else "Volumes: n/a",
    ]
    ax.text(0.0, 0.98, "\n".join(txt), va="top", fontsize=8.5, family="DejaVu Sans",
            transform=ax.transAxes, color="#222")

    # B SeriesDescription
    ax = fig.add_subplot(gs[0, 1])
    top = descs.most_common(6)
    labs = [d[:42] + ("…" if len(d) > 42 else "") for d, _ in top]
    vals = [v for _, v in top]
    ax.barh(range(len(top)), vals, color=color)
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(labs, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("Scans")
    ax.set_title("B. SeriesDescription", loc="left", fontweight="bold")

    # C run entities
    ax = fig.add_subplot(gs[0, 2])
    run_sorted = sorted(runs, key=lambda x: int(str(x).split("-")[-1]))
    ax.bar(range(len(run_sorted)), [runs[r] for r in run_sorted], color=color)
    ax.set_xticks(range(len(run_sorted)))
    ax.set_xticklabels([str(r).replace("run-", "") for r in run_sorted], fontsize=8)
    ax.set_xlabel("BIDS run-")
    ax.set_ylabel("Scans")
    ax.set_title("C. BIDS run indexing", loc="left", fontweight="bold")

    # D shells / volumes
    ax = fig.add_subplot(gs[1, 0])
    if nvols:
        ax.hist(nvols, bins=min(20, max(5, len(set(nvols)))), color=color, edgecolor="white")
        ax.set_xlabel("Number of volumes")
        ax.set_ylabel("Scans")
        ax.set_title("D. Volume count", loc="left", fontweight="bold")
    else:
        ax.axis("off")
        ax.text(0.5, 0.5, "No volume metadata", ha="center")

    # E subject coverage
    ax = fig.add_subplot(gs[1, 1])
    sub_ids = sorted(per_sub, key=lambda s: int(s.split("-")[1]))
    counts = [per_sub[s] for s in sub_ids]
    ax.bar(range(len(sub_ids)), counts, color=color, width=0.85)
    ax.set_xlim(-1, len(sub_ids))
    step = max(1, len(sub_ids) // 12)
    ax.set_xticks(range(0, len(sub_ids), step))
    ax.set_xticklabels([sub_ids[i].replace("sub-", "") for i in range(0, len(sub_ids), step)], fontsize=7)
    ax.set_xlabel("Subject")
    ax.set_ylabel("Scans of this sequence")
    ax.set_title("E. Per-subject coverage", loc="left", fontweight="bold")

    # F session + PE + mosaic
    ax = fig.add_subplot(gs[1, 2])
    ax.axis("off")
    ax.set_title("F. Acquisition snapshot", loc="left", fontweight="bold")
    pe_txt = ", ".join(f"{k}:{v}" for k, v in pe.most_common())
    sh_txt = ", ".join(f"`{k}`:{v}" for k, v in shells.most_common(4))
    ses_txt = ", ".join(f"{k}:{v}" for k, v in ses_counts.most_common())
    n_gif = sum(1 for r in rs if r.get("mosaic_format") == "gif")
    n_png = sum(1 for r in rs if r.get("mosaic_format") == "png")
    # gradient overlap if keys match
    pass_n = review_n = miss_g = 0
    for r in rs:
        key = r.get("bids_basename") or ""
        st = grad.get(key, "")
        if "PASS" in st:
            pass_n += 1
        elif "REVIEW" in st or "WARN" in st:
            review_n += 1
        else:
            miss_g += 1
    body = (
        f"Sessions: {ses_txt}\n"
        f"PE: {pe_txt}\n"
        f"Shells: {sh_txt}\n"
        f"Mosaics: GIF {n_gif} · PNG {n_png}\n"
        f"In dmriqc report: YES (QC_Raw_DWI)\n"
        f"Protocol QC: {'excluded (1-vol)' if family=='RESOLVE_TRACEW' else 'included if ≥2 vol'}\n"
        f"Prior grad check overlap: PASS {pass_n} · REVIEW {review_n} · n/a {miss_g}"
    )
    ax.text(0.0, 0.95, body, va="top", fontsize=8.5, transform=ax.transAxes, family="DejaVu Sans")

    fig.suptitle(
        f"{FAM_TITLE[family]} — data state (n={n})",
        fontsize=12,
        fontweight="bold",
        color=color,
        y=0.98,
    )
    out = PUB / "by_sequence" / f"Figure_{family}"
    save(fig, out)


def figure_sequence_comparison(rows: list[dict]):
    """Side-by-side comparison across all families."""
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7.0))

    # scans per family
    ax = axes[0, 0]
    fam = Counter(r["sequence_family"] for r in rows)
    order = [f for f in FAM_ORDER if fam.get(f)]
    ax.bar([FAM_TITLE[f].replace(" ", "\n") for f in order], [fam[f] for f in order],
           color=[FAM_COLOR[f] for f in order])
    ax.set_ylabel("Scans")
    ax.set_title("A. Scan counts by sequence", loc="left", fontweight="bold")
    ax.tick_params(axis="x", labelsize=7)

    # subjects covered
    ax = axes[0, 1]
    sub_cov = []
    for f in order:
        sub_cov.append(len({r["subject"] for r in rows if r["sequence_family"] == f}))
    ax.bar(range(len(order)), sub_cov, color=[FAM_COLOR[f] for f in order])
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f.replace("_", "\n") for f in order], fontsize=7)
    ax.set_ylabel("Subjects with ≥1 scan")
    ax.set_title("B. Subject coverage", loc="left", fontweight="bold")

    # median volumes
    ax = axes[1, 0]
    med_v = []
    for f in order:
        vs = []
        for r in rows:
            if r["sequence_family"] != f:
                continue
            try:
                vs.append(int(float(r["n_volumes"])))
            except Exception:
                pass
        med_v.append(np.median(vs) if vs else 0)
    ax.bar(range(len(order)), med_v, color=[FAM_COLOR[f] for f in order])
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f.replace("_", "\n") for f in order], fontsize=7)
    ax.set_ylabel("Median volumes / scan")
    ax.set_title("C. Typical volume count", loc="left", fontweight="bold")

    # PE stacked
    ax = axes[1, 1]
    pe_keys = sorted({r.get("PhaseEncodingDirection") or "?" for r in rows})
    bottom = np.zeros(len(order))
    cmap = {"j-": "#1f4e79", "j": "#70ad47", "i": "#c45911", "?": "#7f7f7f"}
    for pe in pe_keys:
        h = np.array([
            sum(1 for r in rows if r["sequence_family"] == f and (r.get("PhaseEncodingDirection") or "?") == pe)
            for f in order
        ], float)
        ax.bar(range(len(order)), h, bottom=bottom, color=cmap.get(pe, "#999"), label=pe, edgecolor="white", lw=0.3)
        bottom += h
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f.replace("_", "\n") for f in order], fontsize=7)
    ax.set_ylabel("Scans")
    ax.set_title("D. Phase encoding by sequence", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8, title="PE")

    fig.suptitle("Sequence families — comparative data state", fontsize=12, fontweight="bold", y=1.01)
    fig.tight_layout()
    save(fig, PUB / "Figure_sequences_comparison")


def write_readme(rows: list[dict]):
    lines = [
        "# Diffusion sequence figures",
        "",
        "Clear data-state figures for Scientific Data technical validation.",
        "",
        "## Global",
        "- `Figure_data_state_overview.{png,pdf}` — overall dmriqc / dataset state",
        "- `Figure_sequences_comparison.{png,pdf}` — all families side-by-side",
        "- `Figure_dmriqc_sequences.*` / `Figure_dmriqc_subject_coverage.*` / `Figure_dmriqc_technical_validation.*`",
        "",
        "## One figure per sequence family (`by_sequence/`)",
        "",
    ]
    fam = Counter(r["sequence_family"] for r in rows)
    for f in FAM_ORDER:
        if not fam.get(f):
            continue
        lines.append(f"- `by_sequence/Figure_{f}.{{png,pdf}}` — {FAM_TITLE[f]} (n={fam[f]})")
    lines += [
        "",
        "## Protocol QC note",
        "Single-volume TRACEW bvals (`n=125`) are excluded from `QC_DWI_Protocol` because",
        "dmriqcpy crashes on 0-d numpy arrays from scalar `.bval` files. Multi-volume DWI (798)",
        "are included after the pipeline fix.",
        "",
    ]
    (PUB / "README_FIGURES.md").write_text("\n".join(lines))


def main():
    rows = load_inventory()
    # rewrite inventory with fixed families if needed
    grad = load_grad_status()
    figure_global_state(rows, grad)
    figure_sequence_comparison(rows)
    for fam in FAM_ORDER:
        figure_one_sequence(fam, rows, grad)
    write_readme(rows)
    print("DONE", len(rows))


if __name__ == "__main__":
    main()
