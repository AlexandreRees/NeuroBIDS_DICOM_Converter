#!/usr/bin/env python3
"""Generate Scientific Data Figure 2: Multimodal MRI dataset overview.

READ-ONLY with respect to BIDS. Writes only under
reports/dataset_overview_figure/ and optionally logs.

Example:
  python code/generate_dataset_overview_figure.py \\
    --bids-dir /home/alexrees/scratch/bids
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import nibabel as nib
import numpy as np
from nibabel.orientations import axcodes2ornt, io_orientation, ornt_transform

DEFAULT_BIDS = Path.home() / "scratch" / "bids"
DEFAULT_OUT = Path.home() / "scratch" / "reports" / "dataset_overview_figure"

SUFFIX_RE = re.compile(r"_([A-Za-z0-9]+)\.nii(?:\.gz)?$")
TASK_RE = re.compile(r"_task-([A-Za-z0-9]+)_")


def log(msg: str) -> None:
    print(msg, flush=True)


def inventory(bids: Path) -> dict[str, Any]:
    dd_path = bids / "dataset_description.json"
    dd = json.loads(dd_path.read_text(encoding="utf-8")) if dd_path.is_file() else {}
    parts_path = bids / "participants.tsv"
    n_participants = 0
    if parts_path.is_file():
        n_participants = max(0, len(parts_path.read_text(encoding="utf-8").strip().splitlines()) - 1)

    subjects = sorted(p.name for p in bids.glob("sub-*") if p.is_dir())
    sessions: set[str] = set()
    for sub in bids.glob("sub-*"):
        for ses in sub.glob("ses-*"):
            if ses.is_dir():
                sessions.add(f"{sub.name}/{ses.name}")

    by_suffix: Counter[str] = Counter()
    by_suffix_subj: dict[str, set[str]] = defaultdict(set)
    by_suffix_ses: dict[str, set[str]] = defaultdict(set)
    by_task_bold: Counter[str] = Counter()
    by_task_subj: dict[str, set[str]] = defaultdict(set)
    nii_paths: dict[str, list[Path]] = defaultdict(list)

    for p in bids.rglob("*.nii.gz"):
        if "derivatives" in p.parts:
            continue
        m = SUFFIX_RE.search(p.name)
        if not m:
            continue
        # Skip phase-only functional when counting magnitude modalities for display
        suf = m.group(1)
        by_suffix[suf] += 1
        sub = next((x for x in p.parts if x.startswith("sub-")), None)
        ses = next((x for x in p.parts if x.startswith("ses-")), None)
        if sub:
            by_suffix_subj[suf].add(sub)
        if sub and ses:
            by_suffix_ses[suf].add(f"{sub}/{ses}")
        nii_paths[suf].append(p)
        if suf == "bold" and "part-phase" not in p.name:
            tm = TASK_RE.search(p.name)
            if tm:
                by_task_bold[tm.group(1)] += 1
                if sub:
                    by_task_subj[tm.group(1)].add(sub)

    events = list(bids.rglob("*_events.tsv"))
    events = [p for p in events if "derivatives" not in p.parts]
    event_subs = {
        next(x for x in p.parts if x.startswith("sub-"))
        for p in events
        if any(x.startswith("sub-") for x in p.parts)
    }

    rows = []
    for suf in sorted(by_suffix, key=lambda s: (-by_suffix[s], s)):
        rows.append(
            {
                "modality": suf,
                "bids_suffix": suf,
                "n_subjects": len(by_suffix_subj[suf]),
                "n_sessions": len(by_suffix_ses[suf]),
                "n_files": by_suffix[suf],
            }
        )
    for task, n in sorted(by_task_bold.items()):
        rows.append(
            {
                "modality": f"bold_task-{task}",
                "bids_suffix": "bold",
                "n_subjects": len(by_task_subj[task]),
                "n_sessions": "",
                "n_files": n,
            }
        )
    rows.append(
        {
            "modality": "events",
            "bids_suffix": "events.tsv",
            "n_subjects": len(event_subs),
            "n_sessions": "",
            "n_files": len(events),
        }
    )

    return {
        "dataset_description": dd,
        "n_participants": n_participants,
        "n_subjects": len(subjects),
        "n_sessions": len(sessions),
        "by_suffix": dict(by_suffix),
        "by_suffix_subj": {k: len(v) for k, v in by_suffix_subj.items()},
        "by_suffix_ses": {k: len(v) for k, v in by_suffix_ses.items()},
        "by_task_bold": dict(by_task_bold),
        "by_task_subj": {k: len(v) for k, v in by_task_subj.items()},
        "nii_paths": nii_paths,
        "summary_rows": rows,
        "n_events": len(events),
        "n_event_subjects": len(event_subs),
    }


def prefer_paths(paths: list[Path], *, prefer_sub: str = "sub-001") -> list[Path]:
    preferred = [p for p in paths if prefer_sub in p.parts and "part-phase" not in p.name]
    if preferred:
        return sorted(preferred)
    clean = [p for p in paths if "part-phase" not in p.name]
    return sorted(clean) if clean else sorted(paths)


def to_ras(img: nib.Nifti1Image) -> nib.Nifti1Image:
    ornt_ras = axcodes2ornt("RAS")
    ornt_img = io_orientation(img.affine)
    transform = ornt_transform(ornt_img, ornt_ras)
    return img.as_reoriented(transform)


def mid_slice_axial(data: np.ndarray) -> np.ndarray:
    """Return axial mid-slice for RAS volume as rows=P→A, cols=L→R."""
    if data.ndim != 3:
        raise ValueError(f"Expected 3D, got {data.ndim}D")
    idx = data.shape[2] // 2
    # data[i,j,k] with RAS: i=L→R, j=P→A, k=I→S
    sl = np.asarray(data[:, :, idx], dtype=np.float64).T
    return sl


def robust_norm(sl: np.ndarray, p_lo: float = 1.0, p_hi: float = 99.0) -> np.ndarray:
    finite = sl[np.isfinite(sl)]
    if finite.size == 0:
        return np.zeros_like(sl)
    lo, hi = np.percentile(finite, [p_lo, p_hi])
    if hi <= lo:
        return np.zeros_like(sl)
    out = (sl - lo) / (hi - lo)
    return np.clip(out, 0, 1)


def load_slice_2d(path: Path, *, volume: int | None = None) -> tuple[np.ndarray, str]:
    img = to_ras(nib.load(str(path)))
    data = np.asanyarray(img.dataobj)
    note = path.name
    if data.ndim == 4:
        vol = 0 if volume is None else volume
        vol = min(vol, data.shape[3] - 1)
        data = data[..., vol]
        note += f" [vol={vol}]"
    elif data.ndim != 3:
        raise ValueError(f"Unexpected ndim={data.ndim} for {path}")
    sl = mid_slice_axial(data)
    return robust_norm(sl), note


def find_b0_index(bval_path: Path) -> int:
    if not bval_path.is_file():
        return 0
    vals = [float(x) for x in bval_path.read_text().split() if x.strip()]
    for i, v in enumerate(vals):
        if v < 50:
            return i
    return 0


def select_representatives(inv: dict[str, Any]) -> dict[str, Path | None]:
    paths: dict[str, list[Path]] = inv["nii_paths"]
    reps: dict[str, Path | None] = {
        "T1w": None,
        "FLAIR": None,
        "T2w": None,
        "DWI": None,
        "BOLD": None,
    }

    t1 = prefer_paths(paths.get("T1w", []))
    t1 = [p for p in t1 if "run-01" in p.name] or t1
    reps["T1w"] = t1[0] if t1 else None

    fl = prefer_paths(paths.get("FLAIR", []))
    reps["FLAIR"] = fl[0] if fl else None

    t2 = prefer_paths(paths.get("T2w", []))
    reps["T2w"] = t2[0] if t2 else None

    dwi = prefer_paths(paths.get("dwi", []))
    dwi_pref = [p for p in dwi if "run-01" in p.name] or dwi
    reps["DWI"] = dwi_pref[0] if dwi_pref else None

    bold = prefer_paths(paths.get("bold", []))
    rest = [p for p in bold if "task-rest" in p.name and "part-phase" not in p.name]
    reps["BOLD"] = (rest or bold)[0] if (rest or bold) else None
    return reps


def mean_bold_and_ts(path: Path, max_tp: int = 200) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    img = to_ras(nib.load(str(path)))
    data = np.asanyarray(img.dataobj)
    if data.ndim != 4:
        raise ValueError(f"BOLD must be 4D: {path}")
    nt = data.shape[3]
    if nt > max_tp:
        idx = np.linspace(0, nt - 1, max_tp).astype(int)
    else:
        idx = np.arange(nt)
    vol = data[..., idx].astype(np.float64)
    mean = vol.mean(axis=3)
    thr = np.percentile(mean[np.isfinite(mean)], 20)
    mask = mean > thr
    if not np.any(mask):
        mask = np.ones(mean.shape, dtype=bool)
    ts = vol.reshape(-1, vol.shape[3])[mask.ravel()].mean(axis=0)
    ts = ts - ts.mean()
    sl = mid_slice_axial(mean)
    return robust_norm(sl), ts, idx.astype(float)


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["modality", "bids_suffix", "n_subjects", "n_sessions", "n_files"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def build_figure(
    inv: dict[str, Any],
    reps: dict[str, Path | None],
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "axes.edgecolor": "#333333",
            "text.color": "#222222",
            "axes.labelcolor": "#222222",
            "xtick.color": "#222222",
            "ytick.color": "#222222",
        }
    )

    meta: dict[str, Any] = {"panels": {}, "errors": []}

    fig = plt.figure(figsize=(10.5, 10.0), dpi=150)
    fig.suptitle("Multimodal MRI dataset overview", fontsize=14, fontweight="semibold", y=0.98)

    # Rows: A-title, A, B-title, B, C-title, C
    outer = gridspec.GridSpec(
        6,
        1,
        figure=fig,
        height_ratios=[0.16, 1.35, 0.16, 1.25, 0.16, 1.35],
        hspace=0.10,
        left=0.09,
        right=0.97,
        top=0.94,
        bottom=0.08,
    )

    panel_a_mods: list[tuple[str, Path | None]] = [
        ("T1w", reps.get("T1w")),
        ("FLAIR", reps.get("FLAIR")),
    ]
    if reps.get("T2w") is not None:
        panel_a_mods.append(("T2w", reps.get("T2w")))
    if reps.get("DWI") is not None:
        panel_a_mods.append(("DWI b0", reps.get("DWI")))

    ax_at = fig.add_subplot(outer[0])
    ax_at.axis("off")
    ax_at.text(
        0.0,
        0.2,
        "A  Representative structural / diffusion contrasts",
        fontsize=11,
        ha="left",
        va="center",
        transform=ax_at.transAxes,
    )

    n_a = max(1, len(panel_a_mods))
    gs_a = gridspec.GridSpecFromSubplotSpec(1, n_a, subplot_spec=outer[1], wspace=0.08)
    for i, (label, path) in enumerate(panel_a_mods):
        ax = fig.add_subplot(gs_a[i])
        if path is None:
            ax.axis("off")
            continue
        try:
            if label.startswith("DWI"):
                bval = Path(str(path).replace(".nii.gz", ".bval").replace(".nii", ".bval"))
                b0 = find_b0_index(bval)
                sl, note = load_slice_2d(path, volume=b0)
            else:
                sl, note = load_slice_2d(path)
            ax.imshow(sl, cmap="gray", origin="lower", interpolation="nearest", aspect="equal")
            ax.set_title(label, fontsize=10, pad=3)
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)
            meta["panels"].setdefault("A", {})[label] = {"path": str(path), "note": note}
        except Exception as exc:  # noqa: BLE001
            ax.text(0.5, 0.5, f"{label}\nunavailable", ha="center", va="center")
            ax.axis("off")
            meta["errors"].append(f"A/{label}: {exc}")

    ax_bt = fig.add_subplot(outer[2])
    ax_bt.axis("off")
    ax_bt.text(
        0.0,
        0.2,
        "B  Functional MRI (resting-state example)",
        fontsize=11,
        ha="left",
        va="center",
        transform=ax_bt.transAxes,
    )

    gs_b = gridspec.GridSpecFromSubplotSpec(
        1, 2, subplot_spec=outer[3], wspace=0.28, width_ratios=[1.0, 1.4]
    )
    ax_b1 = fig.add_subplot(gs_b[0])
    ax_b2 = fig.add_subplot(gs_b[1])
    bold_path = reps.get("BOLD")
    if bold_path is not None:
        try:
            mean_sl, ts, idx = mean_bold_and_ts(bold_path, max_tp=180)
            ax_b1.imshow(
                mean_sl, cmap="gray", origin="lower", interpolation="nearest", aspect="equal"
            )
            ax_b1.set_title("Mean BOLD", fontsize=10)
            ax_b1.set_xticks([])
            ax_b1.set_yticks([])
            for spine in ax_b1.spines.values():
                spine.set_visible(False)

            tr = None
            js = Path(str(bold_path).replace(".nii.gz", ".json").replace(".nii", ".json"))
            if js.is_file():
                try:
                    tr = float(json.loads(js.read_text(encoding="utf-8")).get("RepetitionTime") or 0) or None
                except Exception:
                    tr = None
            x = idx * tr if tr else idx
            xlab = "Time (s)" if tr else "Volume index"
            ax_b2.plot(x, ts, color="#3d4f5f", lw=0.9)
            ax_b2.set_title("Representative BOLD time course", fontsize=10)
            ax_b2.set_xlabel(xlab)
            ax_b2.set_ylabel("Signal (a.u., demeaned)")
            ax_b2.spines["top"].set_visible(False)
            ax_b2.spines["right"].set_visible(False)
            ax_b2.grid(False)
            meta["panels"]["B"] = {"path": str(bold_path), "n_points": int(len(ts)), "tr": tr}
        except Exception as exc:  # noqa: BLE001
            ax_b1.axis("off")
            ax_b2.axis("off")
            meta["errors"].append(f"B: {exc}")
    else:
        ax_b1.axis("off")
        ax_b2.axis("off")

    ax_ct = fig.add_subplot(outer[4])
    ax_ct.axis("off")
    ax_ct.text(
        0.0,
        0.2,
        "C  Dataset modality summary",
        fontsize=11,
        ha="left",
        va="center",
        transform=ax_ct.transAxes,
    )
    ax_c = fig.add_subplot(outer[5])

    chart_items = [
        ("T1w", "T1w"),
        ("FLAIR", "FLAIR"),
        ("DWI", "dwi"),
        ("BOLD (all tasks)", "bold"),
        ("Field map (EPI)", "epi"),
        ("B1 map (TB1TFL)", "TB1TFL"),
    ]
    labels = []
    n_files = []
    n_subj = []
    for lab, key in chart_items:
        if key not in inv["by_suffix"]:
            continue
        labels.append(lab)
        n_files.append(inv["by_suffix"][key])
        n_subj.append(inv["by_suffix_subj"].get(key, 0))

    y = np.arange(len(labels))[::-1]
    colors = "#5b6e7a"
    bars = ax_c.barh(y, n_files[::-1], color=colors, height=0.65, edgecolor="none")
    ax_c.set_yticks(y)
    ax_c.set_yticklabels(labels[::-1])
    ax_c.set_xlabel("Number of NIfTI files")
    ax_c.spines["top"].set_visible(False)
    ax_c.spines["right"].set_visible(False)
    for bar, nf, ns in zip(bars, n_files[::-1], n_subj[::-1]):
        ax_c.text(
            bar.get_width() + max(n_files) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{nf} files · {ns} subjects",
            va="center",
            fontsize=8,
            color="#333333",
        )
    ax_c.set_xlim(0, max(n_files) * 1.35 if n_files else 1)

    footer = (
        f"Cohort: {inv['n_subjects']} subjects · {inv['n_sessions']} sessions · "
        f"BIDS {inv['dataset_description'].get('BIDSVersion', 'n/a')}"
    )
    tasks = inv.get("by_task_bold") or {}
    if tasks:
        task_bits = ", ".join(
            f"{t}={inv['by_task_subj'].get(t, 0)} subj" for t in sorted(tasks)
        )
        footer += f"\nBOLD tasks: {task_bits}"
    footer += (
        f"\nAuxiliary (source archive, not all in BIDS): physiology / eye-tracking / "
        f"stimuli inventoried separately; BIDS events.tsv: {inv['n_events']} files "
        f"({inv['n_event_subjects']} subjects)."
    )
    fig.text(0.09, 0.012, footer, fontsize=7.5, color="#444444", va="bottom")

    meta["panels"]["C"] = {"labels": labels, "n_files": n_files, "n_subjects": n_subj}

    png = out_dir / "Figure2_multimodal_MRI_overview.png"
    pdf = out_dir / "Figure2_multimodal_MRI_overview.pdf"
    svg = out_dir / "Figure2_multimodal_MRI_overview.svg"
    fig.savefig(png, dpi=300, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    fig.savefig(svg, bbox_inches="tight")
    plt.close(fig)
    meta["outputs"] = {"png": str(png), "pdf": str(pdf), "svg": str(svg)}
    return meta


def write_caption(path: Path, inv: dict[str, Any]) -> None:
    text = (
        "Figure 2. Multimodal MRI dataset overview. "
        "(A) Representative axial slices illustrating structural and diffusion contrasts "
        "available in the release (T1-weighted, FLAIR, and a diffusion b = 0 volume when present). "
        "(B) Example resting-state functional MRI: mean BOLD image and a demeaned whole-brain "
        "BOLD time course from one run (illustrative temporal fluctuations only; no statistical "
        "activation analysis). "
        f"(C) Counts of NIfTI acquisitions by modality across the cohort "
        f"({inv['n_subjects']} subjects, {inv['n_sessions']} sessions). "
        "Task labels for BOLD runs include rest, movie, fmri, and control protocols. "
        "Field maps (spin-echo EPI) and B1 mapping (TB1TFL) are included where acquired. "
        "The figure summarizes dataset composition for secondary use and does not present "
        "group comparisons or biological inferences."
    )
    path.write_text(text + "\n", encoding="utf-8")


def write_report(
    path: Path,
    inv: dict[str, Any],
    reps: dict[str, Path | None],
    meta: dict[str, Any],
    script: Path,
) -> None:
    dd = inv["dataset_description"]
    lines = [
        "# Figure 2 generation report",
        "",
        f"**Generated (UTC):** {datetime.now(timezone.utc).isoformat()}",
        f"**BIDS root:** read-only inventory under project `bids/`",
        f"**BIDSVersion:** {dd.get('BIDSVersion', 'n/a')}",
        f"**Dataset Name:** {dd.get('Name', 'n/a')}",
        f"**Pipeline GeneratedBy:** {dd.get('GeneratedBy', 'n/a')}",
        f"**Script:** `{script}`",
        "",
        "## Cohort",
        "",
        f"- Subjects: **{inv['n_subjects']}** (participants.tsv: {inv['n_participants']})",
        f"- Sessions: **{inv['n_sessions']}**",
        "",
        "## Modalities detected (NIfTI suffixes)",
        "",
        "| Suffix | Subjects | Sessions | Files |",
        "| --- | ---: | ---: | ---: |",
    ]
    for suf, n in sorted(inv["by_suffix"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(
            f"| `{suf}` | {inv['by_suffix_subj'].get(suf, 0)} | "
            f"{inv['by_suffix_ses'].get(suf, 0)} | {n} |"
        )
    lines += [
        "",
        "## BOLD tasks (magnitude bold only)",
        "",
    ]
    for t, n in sorted(inv["by_task_bold"].items()):
        lines.append(f"- `task-{t}`: {n} files · {inv['by_task_subj'].get(t, 0)} subjects")
    lines += [
        "",
        "## Representative files selected",
        "",
    ]
    for k, p in reps.items():
        lines.append(f"- **{k}:** `{p}`" if p else f"- **{k}:** not available")
    lines += [
        "",
        "## Outputs",
        "",
    ]
    for k, v in (meta.get("outputs") or {}).items():
        lines.append(f"- {k}: `{v}`")
    if meta.get("errors"):
        lines += ["", "## Errors / warnings", ""]
        for e in meta["errors"]:
            lines.append(f"- {e}")
    lines += [
        "",
        "## Limitations",
        "",
        "- No T2w suffix was detected; Panel A omits T2w.",
        "- Panel images are single mid-axial slices from one representative subject/session "
        "(`sub-001` preferred when present) and are not quality-control pass/fail decisions.",
        "- BOLD time course is a demeaned whole-brain mean signal for illustration only "
        "(no nuisance regression, GLM, or activation maps).",
        "- Auxiliary physiology / eye-tracking / stimulus files exist primarily in the "
        "source archive inventory; only a subset of `*_events.tsv` is currently in BIDS.",
        "- Counts exclude `derivatives/`.",
        "",
        "## Safety",
        "",
        "- BIDS inputs were not modified.",
        "- No new preprocessing derivatives were written into the BIDS tree.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Figure 2 multimodal overview.")
    p.add_argument("--bids-dir", type=Path, default=DEFAULT_BIDS)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--inventory-only",
        action="store_true",
        help="Print inventory and exit without rendering.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    bids = args.bids_dir
    out = args.output_dir
    if not bids.is_dir():
        log(f"ERROR: bids missing: {bids}")
        return 2

    log(f"Inventory (read-only): {bids}")
    inv = inventory(bids)
    log(f"Subjects={inv['n_subjects']} Sessions={inv['n_sessions']}")
    log("NIfTI by suffix:")
    for suf, n in sorted(inv["by_suffix"].items(), key=lambda kv: (-kv[1], kv[0])):
        log(
            f"  {suf:10s} files={n:5d} subjects={inv['by_suffix_subj'].get(suf,0):3d} "
            f"sessions={inv['by_suffix_ses'].get(suf,0):3d}"
        )
    log("BOLD tasks:")
    for t, n in sorted(inv["by_task_bold"].items()):
        log(f"  task-{t}: files={n} subjects={inv['by_task_subj'].get(t,0)}")

    # Coherence checks
    if inv["n_subjects"] < 1 or not inv["by_suffix"]:
        log("ERROR: incoherent inventory")
        return 2
    if inv["n_participants"] and inv["n_participants"] != inv["n_subjects"]:
        log(
            f"WARNING: participants.tsv ({inv['n_participants']}) != sub-* dirs ({inv['n_subjects']})"
        )

    out.mkdir(parents=True, exist_ok=True)
    write_tsv(out / "dataset_modality_summary.tsv", inv["summary_rows"])
    log(f"Wrote {out / 'dataset_modality_summary.tsv'}")

    if args.inventory_only:
        return 0

    reps = select_representatives(inv)
    log("Representatives:")
    for k, p in reps.items():
        log(f"  {k}: {p}")

    log("Rendering figure…")
    meta = build_figure(inv, reps, out)
    write_caption(out / "Figure2_caption.txt", inv)
    write_report(
        out / "Figure2_generation_report.md",
        inv,
        reps,
        meta,
        Path(__file__).resolve(),
    )
    log(f"Wrote figure outputs under {out}")
    for k, v in meta.get("outputs", {}).items():
        log(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
