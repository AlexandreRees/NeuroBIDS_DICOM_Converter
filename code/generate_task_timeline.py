#!/usr/bin/env python3
"""Figure 03 — Task fMRI timeline (Nature Scientific Data style).

Four horizontally aligned panels (A–D):
  A  MRI session timeline (SeriesNumber order; durations from sidecars)
  B  Task-fMRI paradigm from ``*_events.tsv`` (MATLAB fallback if needed)
  C  Multimodal synchronisation (stimulus, BOLD TR, cardiac, respiration,
     eye-tracking lane)
  D  Graphical ``events.tsv`` excerpt (first ~90 s)

Run from the BIDS dataset root::

    python code/generate_task_timeline.py

Outputs (current working directory)::

    Figure_03_task_fmri_timeline.pdf
    Figure_03_task_fmri_timeline.png
    Figure_03_task_fmri_timeline.svg

Dependencies: matplotlib, numpy (stdlib otherwise). Optional: nibabel for
NIfTI volume counts.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm
from matplotlib.gridspec import GridSpec
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch, Rectangle

# ---------------------------------------------------------------------------
# Style (publication upgrade — visual only)
# ---------------------------------------------------------------------------
STEM = "Figure_03_task_fmri_timeline"
FIG_W, FIG_H = 17.5, 9.6
DPI = 600

# Color-blind friendly — fixed across all panels
PAL = {
    "ink": "#1A1A1A",
    "muted": "#666666",
    "grid": "#EDEDED",
    "light": "#F7F7F7",
    "white": "#FFFFFF",
    "fixation": "#B0B0B0",      # grey
    "rest": "#009E73",          # green
    "stimulus": "#E69F00",      # orange
    "movie": "#C49A00",         # gold
    "t1w": "#0072B2",           # blue
    "dwi": "#CC79A7",           # purple
    "flair": "#56B4E9",         # light blue
    "calib": "#D9D9D9",         # light grey calibration
    "tr": "#0072B2",            # BOLD / trigger blue
    "cardiac": "#D55E00",
    "resp": "#56B4E9",
    "eye": "#999999",
    "flow": "#D0D0D0",
}

# Display names + colors for session timeline
MAJOR_LABELS = {
    "Task fMRI": ("Task fMRI", PAL["stimulus"]),
    "Task fMRI (Movie)": ("Movie fMRI", PAL["movie"]),
    "Resting-state": ("Rest", PAL["rest"]),
    "T1w": ("T1w", PAL["t1w"]),
    "DWI": ("DWI", PAL["dwi"]),
    "FLAIR": ("FLAIR", PAL["flair"]),
}
CALIB_LABELS = {
    "Localizer": "Localizer",
    "Control": "Control EPI",
    "SpinEcho AP": "SpinEcho AP",
    "SpinEcho PA": "SpinEcho PA",
}

EVENT_COLOR = {
    "Fixation": PAL["fixation"],
    "Rest": PAL["rest"],
    "Stimulus": PAL["stimulus"],
    "Movie": PAL["movie"],
    "Trigger": PAL["tr"],
}

# Typography (~+20%)
FS = {
    "suptitle": 15,
    "panel": 13,
    "axis": 11,
    "tick": 9.5,
    "label": 10.5,
    "legend": 9.5,
    "note": 8.5,
    "caption": 9.0,
    "inside": 10.0,
}


def pick_font() -> str:
    available = {f.name for f in fm.fontManager.ttflist}
    for name in ("Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"):
        if name in available:
            return name
    return "DejaVu Sans"


FONT = pick_font()
plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": [FONT, "DejaVu Sans", "Arial", "Helvetica"],
        "font.size": FS["axis"],
        "axes.linewidth": 0.45,
        "axes.edgecolor": PAL["grid"],
        "xtick.major.width": 0.45,
        "ytick.major.width": 0.45,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "text.color": PAL["ink"],
        "figure.facecolor": PAL["white"],
        "axes.facecolor": PAL["white"],
        "savefig.facecolor": PAL["white"],
        "savefig.dpi": DPI,
        "legend.frameon": False,
        "legend.handlelength": 1.15,
        "legend.handletextpad": 0.4,
        "legend.columnspacing": 1.1,
        "legend.borderaxespad": 0.0,
    }
)


# ---------------------------------------------------------------------------
# BIDS discovery helpers
# ---------------------------------------------------------------------------
def find_bids_root(start: Path) -> Path:
    """Prefer CWD if it looks like BIDS; else walk parents; else ``./bids``."""
    candidates = [start, *start.parents]
    scratch_bids = Path.home() / "scratch" / "bids"
    if scratch_bids.is_dir():
        candidates.append(scratch_bids)
    for p in candidates:
        if (p / "dataset_description.json").is_file() and (p / "participants.tsv").is_file():
            return p
    raise SystemExit(
        "Could not locate a BIDS root (need dataset_description.json + "
        "participants.tsv). Run this script from the BIDS dataset root."
    )


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def nifti_n_volumes(nii: Path) -> Optional[int]:
    if not nii.is_file():
        return None
    try:
        import nibabel as nib  # type: ignore

        shape = nib.load(str(nii)).shape
        return int(shape[-1]) if len(shape) >= 4 else 1
    except Exception:
        pass
    # bval fallback for DWI
    bval = nii.with_suffix("").with_suffix(".bval")
    if bval.is_file():
        toks = bval.read_text().split()
        return len(toks) if toks else None
    return None


def read_events_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def read_physio_series(tsv_gz: Path, max_samples: int = 20000) -> tuple[np.ndarray, list[str]]:
    """Return (data [n, n_cols], column_names). Subsamples long traces."""
    cols: list[str] = []
    rows: list[list[float]] = []
    with gzip.open(tsv_gz, "rt", encoding="utf-8") as fh:
        header = fh.readline().strip().split("\t")
        cols = header
        for line in fh:
            parts = line.strip().split("\t")
            if not parts or parts[0] == "":
                continue
            try:
                rows.append([float(x) for x in parts])
            except ValueError:
                continue
    if not rows:
        return np.zeros((0, max(1, len(cols)))), cols
    arr = np.asarray(rows, dtype=np.float64)
    if arr.shape[0] > max_samples:
        idx = np.linspace(0, arr.shape[0] - 1, max_samples).astype(int)
        arr = arr[idx]
    return arr, cols


@dataclass
class AcqBlock:
    label: str
    series_number: int
    duration_s: float
    source: str
    detail: str = ""


@dataclass
class ExampleBundle:
    bids: Path
    session: Path
    subject: str
    session_id: str
    blocks: list[AcqBlock]
    fmri_events: Path
    fmri_bold_json: Path
    movie_events: Optional[Path]
    movie_bold_json: Optional[Path]
    pulse: Optional[Path]
    respiratory: Optional[Path]
    trigger: Optional[Path]
    tr: float = 0.937
    notes: list[str] = field(default_factory=list)


def classify_acquisition(name: str, meta: dict[str, Any]) -> Optional[str]:
    n = name.lower()
    if "part-phase" in n or "_sbref" in n:
        return None
    if "localizer" in n:
        return "Localizer"
    if n.endswith("_t1w.json") or n.endswith("_t1w.nii.gz"):
        return "T1w"
    if n.endswith("_flair.json") or "flair" in n:
        return "FLAIR"
    if n.endswith("_dwi.json"):
        return "DWI"
    if "_task-movie_" in n and n.endswith("_bold.json"):
        return "Task fMRI (Movie)"
    if "_task-fmri_" in n and n.endswith("_bold.json"):
        return "Task fMRI"
    if "_task-rest_" in n and n.endswith("_bold.json"):
        return "Resting-state"
    if "_task-control_" in n and n.endswith("_bold.json"):
        return "Control"
    if "_dir-ap_" in n and n.endswith("_epi.json"):
        return "SpinEcho AP"
    if "_dir-pa_" in n and n.endswith("_epi.json"):
        return "SpinEcho PA"
    sd = str(meta.get("SeriesDescription") or "").lower()
    if "localizer" in sd:
        return "Localizer"
    return None


def estimate_duration(label: str, meta: dict[str, Any], nii: Path) -> float:
    """Seconds. Prefer volumes×TR; else AcquisitionDuration; else category default."""
    if meta.get("AcquisitionDuration") is not None:
        try:
            return float(meta["AcquisitionDuration"])
        except (TypeError, ValueError):
            pass
    tr = meta.get("RepetitionTime")
    nvol = nifti_n_volumes(nii)
    if tr is not None and nvol is not None and nvol > 1:
        return float(tr) * float(nvol)
    # 3D / single-volume: category fallbacks (approximate wall-clock)
    defaults = {
        "Localizer": 20.0,
        "T1w": 330.0,
        "FLAIR": 360.0,
        "DWI": 420.0,
        "SpinEcho AP": float(tr) if tr else 9.71,
        "SpinEcho PA": float(tr) if tr else 9.71,
        "Task fMRI": 226 * 0.937,
        "Task fMRI (Movie)": 210 * 0.937,
        "Resting-state": 320 * 0.937,
        "Control": 20 * 0.937,
    }
    if tr is not None and nvol == 1 and label.startswith("SpinEcho"):
        return float(tr)
    return float(defaults.get(label, 60.0))


def build_session_blocks(session: Path) -> list[AcqBlock]:
    raw: list[AcqBlock] = []
    for js in session.rglob("*.json"):
        if any(x in js.name for x in ("events", "physio", "participants")):
            continue
        meta = load_json(js)
        label = classify_acquisition(js.name, meta)
        if label is None:
            continue
        sn = meta.get("SeriesNumber")
        if sn is None:
            continue
        nii = Path(str(js)[:-5] + ".nii.gz")
        dur = estimate_duration(label, meta, nii)
        raw.append(
            AcqBlock(
                label=label,
                series_number=int(sn),
                duration_s=max(dur, 1.0),
                source=js.name,
                detail=str(meta.get("SeriesDescription") or ""),
            )
        )
    raw.sort(key=lambda b: (b.series_number, b.source))

    # Collapse consecutive identical labels (e.g. 3 localizer slices; 4 movie runs)
    collapsed: list[AcqBlock] = []
    for b in raw:
        if collapsed and collapsed[-1].label == b.label:
            collapsed[-1].duration_s += b.duration_s
            collapsed[-1].detail = f"{collapsed[-1].detail}; {b.detail}".strip("; ")
        else:
            collapsed.append(
                AcqBlock(
                    label=b.label,
                    series_number=b.series_number,
                    duration_s=b.duration_s,
                    source=b.source,
                    detail=b.detail,
                )
            )
    return collapsed


def find_sidecar(bold_json: Path, recording: str) -> Optional[Path]:
    """``..._bold.json`` → ``..._recording-<rec>_physio.tsv.gz``."""
    stem = bold_json.name[: -len("_bold.json")]
    cand = bold_json.parent / f"{stem}_recording-{recording}_physio.tsv.gz"
    return cand if cand.is_file() else None


def choose_example(bids: Path) -> ExampleBundle:
    """Pick a session with task-fmri events + physio when possible."""
    scored: list[tuple[int, Path]] = []
    for ses in sorted(bids.glob("sub-*/ses-*")):
        func = ses / "func"
        if not func.is_dir():
            continue
        ev = list(func.glob("*task-fmri*_events.tsv"))
        ph = list(func.glob("*physio.tsv.gz"))
        bold = list(func.glob("*task-fmri*_bold.json"))
        bold = [b for b in bold if "part-phase" not in b.name]
        score = 10 * len(ev) + len(ph) + 2 * len(bold)
        if ev:
            scored.append((score, ses))
    if not scored:
        raise SystemExit("No task-fmri events.tsv found under BIDS tree.")
    scored.sort(reverse=True)
    session = scored[0][1]
    subject = session.parent.name
    session_id = session.name
    func = session / "func"

    fmri_events = sorted(func.glob("*task-fmri*_events.tsv"))[0]
    # Matching bold json: same run stem
    stem = fmri_events.name.replace("_events.tsv", "")
    fmri_bold_json = func / f"{stem}_bold.json"
    if not fmri_bold_json.is_file():
        # any magnitude task-fmri bold
        cands = [
            p
            for p in func.glob("*task-fmri*_bold.json")
            if "part-phase" not in p.name
        ]
        fmri_bold_json = cands[0]

    movie_events = next(iter(sorted(func.glob("*task-movie*_events.tsv"))), None)
    movie_bold_json = None
    if movie_events is not None:
        mstem = movie_events.name.replace("_events.tsv", "")
        mb = func / f"{mstem}_bold.json"
        if mb.is_file():
            movie_bold_json = mb

    # Prefer physio attached to the chosen fmri bold; else any movie/fmri physio
    pulse = find_sidecar(fmri_bold_json, "pulse")
    respiratory = find_sidecar(fmri_bold_json, "respiratory")
    trigger = find_sidecar(fmri_bold_json, "trigger")
    if pulse is None and movie_bold_json is not None:
        pulse = find_sidecar(movie_bold_json, "pulse")
        respiratory = find_sidecar(movie_bold_json, "respiratory")
        trigger = find_sidecar(movie_bold_json, "trigger")

    meta = load_json(fmri_bold_json)
    tr = float(meta.get("RepetitionTime") or 0.937)
    blocks = build_session_blocks(session)
    notes = [
        f"Example session: {subject}/{session_id}",
        f"Events: {fmri_events.name}",
    ]
    return ExampleBundle(
        bids=bids,
        session=session,
        subject=subject,
        session_id=session_id,
        blocks=blocks,
        fmri_events=fmri_events,
        fmri_bold_json=fmri_bold_json,
        movie_events=movie_events,
        movie_bold_json=movie_bold_json,
        pulse=pulse,
        respiratory=respiratory,
        trigger=trigger,
        tr=tr,
        notes=notes,
    )


def reconstruct_events_from_design(tr: float = 0.937) -> list[dict[str, Any]]:
    """Fallback block design: 10 TR baseline + 12×(8 TR stim / 10 TR baseline)."""
    events = []
    t = 0.0
    events.append({"onset": t, "duration": 10 * tr, "trial_type": "baseline"})
    t += 10 * tr
    for i in range(12):
        events.append({"onset": t, "duration": 8 * tr, "trial_type": f"stim-{i+1:02d}"})
        t += 8 * tr
        events.append({"onset": t, "duration": 10 * tr, "trial_type": "baseline"})
        t += 10 * tr
    return events


def load_paradigm_events(bundle: ExampleBundle) -> list[dict[str, Any]]:
    if bundle.fmri_events.is_file():
        rows = read_events_tsv(bundle.fmri_events)
        out = []
        for r in rows:
            try:
                out.append(
                    {
                        "onset": float(r["onset"]),
                        "duration": float(r["duration"]),
                        "trial_type": (r.get("trial_type") or r.get("event_type") or "").strip(),
                    }
                )
            except (KeyError, ValueError):
                continue
        if out:
            return out
    # optional: search .mat under bids/code or sourcedata (best-effort stub)
    bundle.notes.append("events.tsv missing/unreadable — reconstructed canonical design")
    return reconstruct_events_from_design(bundle.tr)


def map_event_label(trial_type: str, index_in_run: int, is_first_baseline: bool) -> str:
    tt = trial_type.lower()
    if tt in {"movie"}:
        return "Movie"
    if tt.startswith("stim") or tt.startswith("task"):
        return "Stimulus"
    if tt in {"baseline", "fixation", "rest"}:
        if is_first_baseline or index_in_run == 0:
            return "Fixation"
        return "Rest"
    if "trigger" in tt:
        return "Trigger"
    return trial_type or "Event"


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------
def style_ax(ax):
    ax.set_facecolor(PAL["white"])
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(PAL["grid"])
    ax.spines["bottom"].set_linewidth(0.5)
    ax.tick_params(colors=PAL["muted"], labelsize=FS["tick"], length=3.5, width=0.45)
    ax.grid(False)


def set_panel_title(ax, letter: str, title: str):
    """Aligned bold panel letter + title."""
    ax.set_title(
        f"{letter}   {title}",
        loc="left",
        fontsize=FS["panel"],
        fontweight="bold",
        pad=12,
        color=PAL["ink"],
    )


def shared_legend(ax, handles, *, loc="upper right", ncol=None, bbox=None):
    kw = dict(
        handles=handles,
        loc=loc,
        frameon=False,
        fontsize=FS["legend"],
        ncol=ncol or len(handles),
        handlelength=1.15,
        columnspacing=1.0,
    )
    if bbox is not None:
        kw["bbox_to_anchor"] = bbox
        kw["borderaxespad"] = 0.0
    return ax.legend(**kw)


def draw_panel_a(ax, bundle: ExampleBundle):
    """Chronological MRI session blocks — majors labeled; calib compact."""
    style_ax(ax)
    set_panel_title(ax, "A", "MRI session timeline")

    blocks = list(bundle.blocks)
    if not blocks:
        ax.text(0.5, 0.5, "No acquisitions found", ha="center", va="center", color=PAL["muted"])
        ax.set_axis_off()
        return

    total = sum(b.duration_s for b in blocks)
    y0, height = 0.28, 0.40
    x = 0.0
    ax.set_xlim(0, max(total, 1.0))
    ax.set_ylim(0, 1.05)
    ax.set_yticks([])
    ax.set_xlabel("Cumulative acquisition time (s)", fontsize=FS["axis"], color=PAL["muted"])

    calib_seen: list[str] = []
    for b in blocks:
        w = b.duration_s
        cx = x + w / 2
        if b.label in MAJOR_LABELS:
            disp, color = MAJOR_LABELS[b.label]
            ax.add_patch(
                Rectangle(
                    (x, y0),
                    w,
                    height,
                    facecolor=color,
                    edgecolor=PAL["ink"],
                    linewidth=0.35,
                    alpha=0.92,
                    zorder=2,
                )
            )
            if w / total >= 0.035:
                ax.text(
                    cx,
                    y0 + height / 2,
                    disp,
                    ha="center",
                    va="center",
                    fontsize=FS["inside"],
                    fontweight="bold",
                    color=PAL["white"],
                    zorder=3,
                    clip_on=True,
                )
        else:
            # Calibration / secondary acquisitions — compact grey blocks, no in-block text
            disp = CALIB_LABELS.get(b.label, b.label)
            if disp not in calib_seen:
                calib_seen.append(disp)
            ax.add_patch(
                Rectangle(
                    (x, y0 + 0.08),
                    w,
                    height * 0.65,
                    facecolor=PAL["calib"],
                    edgecolor="#B5B5B5",
                    linewidth=0.3,
                    alpha=0.95,
                    zorder=2,
                )
            )
        x += w

    # Compact annotation for calibration categories (no rotated labels)
    if calib_seen:
        ax.text(
            0.0,
            0.92,
            "Calibration / secondary:  " + "  ·  ".join(calib_seen) + "  (grey blocks)",
            fontsize=FS["note"],
            color=PAL["muted"],
            ha="left",
            va="center",
            clip_on=False,
        )

    ax.text(
        total,
        y0 + height / 2,
        "  End",
        ha="left",
        va="center",
        fontsize=FS["label"],
        fontweight="bold",
        color=PAL["ink"],
        clip_on=False,
    )
    ax.text(
        0.0,
        0.08,
        f"{bundle.subject}/{bundle.session_id}  ·  SeriesNumber order  ·  "
        f"widths proportional to duration",
        fontsize=FS["note"],
        color=PAL["muted"],
        ha="left",
        va="center",
    )


def draw_panel_b(ax, bundle: ExampleBundle, events: list[dict[str, Any]]):
    """Task-fMRI timing — Fixation / Rest / Stimulus (single stimulus color)."""
    style_ax(ax)
    set_panel_title(ax, "B", "Task fMRI paradigm")

    if not events:
        ax.text(0.5, 0.5, "No events", transform=ax.transAxes, ha="center")
        return

    t_end = max(e["onset"] + e["duration"] for e in events)
    ax.set_xlim(0, t_end)
    ax.set_ylim(0, 1.0)
    ax.set_yticks([])
    ax.set_xlabel("Elapsed time (s)", fontsize=FS["axis"], color=PAL["muted"])

    y0, h = 0.30, 0.40
    first_baseline_done = False
    for e in events:
        ttl = str(e["trial_type"]).lower()
        if ttl == "baseline" or ttl in {"fixation", "rest"}:
            color = PAL["rest"] if first_baseline_done else PAL["fixation"]
            if ttl == "baseline":
                first_baseline_done = True
        elif ttl == "movie":
            color = PAL["movie"]
        else:
            color = PAL["stimulus"]
        ax.add_patch(
            Rectangle(
                (e["onset"], y0),
                e["duration"],
                h,
                facecolor=color,
                edgecolor="none",
                linewidth=0,
                alpha=0.95,
                zorder=2,
            )
        )

    handles = [
        Patch(facecolor=PAL["fixation"], edgecolor="none", label="Fixation"),
        Patch(facecolor=PAL["rest"], edgecolor="none", label="Rest"),
        Patch(facecolor=PAL["stimulus"], edgecolor="none", label="Stimulus"),
    ]
    shared_legend(ax, handles, loc="lower right", bbox=(1.0, 1.02))
    ax.text(
        0.0,
        0.08,
        f"Source: {bundle.fmri_events.name}  ·  TR = {bundle.tr:.3f} s",
        fontsize=FS["note"],
        color=PAL["muted"],
        ha="left",
    )


def draw_panel_c(ax, bundle: ExampleBundle, events: list[dict[str, Any]]):
    """Aligned multimodal tracks — shared time axis, clearer TR ticks."""
    style_ax(ax)
    set_panel_title(ax, "C", "Multimodal synchronization")

    window = 90.0
    ax.set_xlim(0, window)
    # More vertical spacing between rows
    tracks = ["Movie / stimulus", "BOLD (TR)", "Cardiac", "Respiration", "Eye tracking"]
    ys = [0.0, 1.15, 2.30, 3.45, 4.60]
    ax.set_ylim(-0.65, ys[-1] + 0.75)
    ax.set_yticks(ys)
    ax.set_yticklabels(tracks, fontsize=FS["tick"])
    ax.set_xlabel("Time (s)", fontsize=FS["axis"], color=PAL["muted"])
    ax.invert_yaxis()
    ax.spines["left"].set_visible(False)

    # Stimulus / movie blocks
    stim_events = events
    if bundle.movie_events is not None:
        try:
            stim_events = [
                {
                    "onset": float(r["onset"]),
                    "duration": float(r["duration"]),
                    "trial_type": r.get("trial_type", "movie"),
                }
                for r in read_events_tsv(bundle.movie_events)
            ]
        except Exception:
            pass

    for e in stim_events:
        if e["onset"] > window:
            continue
        x0 = e["onset"]
        x1 = min(e["onset"] + e["duration"], window)
        tt = str(e["trial_type"]).lower()
        if tt == "movie" or "movie" in tt:
            c = PAL["movie"]
        elif tt.startswith("stim"):
            c = PAL["stimulus"]
        else:
            c = PAL["rest"]
        ax.add_patch(
            Rectangle(
                (x0, ys[0] - 0.38),
                x1 - x0,
                0.76,
                facecolor=c,
                edgecolor="none",
                alpha=0.88,
                zorder=2,
            )
        )

    # BOLD TR ticks — thin, equally spaced
    tr = bundle.tr
    n_tr = int(window / tr) + 1
    for i in range(n_tr):
        t = i * tr
        ax.plot(
            [t, t],
            [ys[1] - 0.38, ys[1] + 0.38],
            color=PAL["tr"],
            lw=0.55,
            solid_capstyle="round",
            zorder=3,
            alpha=0.9,
        )
    ax.text(
        window,
        ys[1],
        f"  TR = {tr:.3f} s",
        ha="left",
        va="center",
        fontsize=FS["label"],
        fontweight="bold",
        color=PAL["tr"],
        clip_on=False,
    )

    def add_trace(path: Optional[Path], y: float, color: str, meta_name: str):
        if path is None or not path.is_file():
            ax.text(1.0, y, f"{meta_name} unavailable", fontsize=FS["note"], color=PAL["muted"], va="center")
            return
        meta = load_json(Path(str(path).replace(".tsv.gz", ".json")))
        fs = float(meta.get("SamplingFrequency") or 0.0)
        start = float(meta.get("StartTime") or 0.0)
        if fs <= 0:
            return
        vals: list[float] = []
        times: list[float] = []
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            next(fh)
            for i, line in enumerate(fh):
                t = start + i / fs
                if t < 0:
                    continue
                if t > window:
                    break
                try:
                    vals.append(float(line.split("\t")[0]))
                    times.append(t)
                except ValueError:
                    continue
                if fs >= 250 and i % 5 != 0 and vals:
                    vals.pop()
                    times.pop()
        if len(vals) < 5:
            return
        v = np.asarray(vals, dtype=float)
        tarr = np.asarray(times, dtype=float)
        v = (v - np.nanmedian(v)) / (np.nanstd(v) + 1e-6)
        v = np.clip(v, -2.5, 2.5)
        ax.plot(tarr, y - 0.32 * v / 2.5, color=color, lw=0.45, zorder=3, solid_joinstyle="round")
        ax.text(
            window,
            y,
            f"  {fs:.0f} Hz",
            ha="left",
            va="center",
            fontsize=FS["note"],
            color=color,
            clip_on=False,
        )

    add_trace(bundle.pulse, ys[2], PAL["cardiac"], "Cardiac")
    add_trace(bundle.respiratory, ys[3], PAL["resp"], "Respiration")

    # Eye tracking — illustrative only
    rng = np.random.default_rng(1010)
    t_eye = np.linspace(0, window, 400)
    eye = 0.25 * np.sin(2 * np.pi * t_eye / 12.0) + 0.05 * rng.normal(size=t_eye.size)
    ax.plot(t_eye, ys[4] - 0.28 * eye, color=PAL["eye"], lw=0.5, ls="--", zorder=3)
    ax.text(
        window,
        ys[4],
        "  Illustrative only (not included in current release)",
        ha="left",
        va="center",
        fontsize=FS["note"],
        color=PAL["muted"],
        style="italic",
        clip_on=False,
    )


def draw_panel_d(ax, bundle: ExampleBundle, events: list[dict[str, Any]]):
    """Clean events.tsv excerpt — same colors as Panel B; thin TR ticks."""
    style_ax(ax)
    set_panel_title(ax, "D", "Representation in BIDS events.tsv")

    window = 90.0
    ax.set_xlim(0, window)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xlabel("onset (s)", fontsize=FS["axis"], color=PAL["muted"])

    # TR ticks only (not dense physio trigger separators)
    for t in np.arange(0.0, window + 1e-9, bundle.tr):
        ax.plot([t, t], [0.18, 0.82], color=PAL["tr"], lw=0.4, alpha=0.35, zorder=1)

    first_baseline = True
    for idx, e in enumerate(events):
        if e["onset"] >= window:
            break
        x0 = e["onset"]
        dur = min(e["duration"], window - x0)
        label = map_event_label(e["trial_type"], idx, first_baseline)
        if label in {"Fixation", "Rest"} and str(e["trial_type"]).lower() == "baseline":
            first_baseline = False
        if label == "Movie":
            # keep scientific events; display as Stimulus timing category if movie
            # but movie in task-fmri events is rare — map Movie→ keep gold only if present
            color = EVENT_COLOR["Movie"]
            show = "Movie"
        elif label == "Stimulus":
            color = EVENT_COLOR["Stimulus"]
            show = "Stimulus"
        elif label == "Fixation":
            color = EVENT_COLOR["Fixation"]
            show = "Fixation"
        else:
            color = EVENT_COLOR["Rest"]
            show = "Rest"

        ax.add_patch(
            Rectangle(
                (x0, 0.28),
                max(dur, 0.1),
                0.44,
                facecolor=color,
                edgecolor="none",
                linewidth=0,
                alpha=0.95,
                zorder=2,
            )
        )
        if dur > 5.5:
            ax.text(
                x0 + dur / 2,
                0.50,
                show,
                ha="center",
                va="center",
                fontsize=FS["inside"],
                fontweight="bold",
                color=PAL["white"] if show != "Fixation" else PAL["ink"],
                zorder=3,
            )
        # light onset numerals (no heavy separators)
        if idx < 6:
            ax.text(
                x0,
                0.18,
                f"{x0:.1f}",
                ha="center",
                va="top",
                fontsize=FS["note"],
                color=PAL["muted"],
            )

    handles = [
        Patch(facecolor=EVENT_COLOR["Fixation"], edgecolor="none", label="Fixation"),
        Patch(facecolor=EVENT_COLOR["Rest"], edgecolor="none", label="Rest"),
        Patch(facecolor=EVENT_COLOR["Stimulus"], edgecolor="none", label="Stimulus"),
    ]
    shared_legend(ax, handles, loc="lower right", bbox=(1.0, 1.02))

    ax.text(
        0.0,
        -0.20,
        "onset · duration · trial_type   |   blue ticks = TR",
        transform=ax.transAxes,
        fontsize=FS["note"],
        color=PAL["muted"],
        ha="left",
        va="top",
        clip_on=False,
    )


def _flow_arrow(fig, x, y0, y1):
    """Very light grey reading-flow arrow in figure coordinates."""
    arr = FancyArrowPatch(
        (x, y0),
        (x, y1),
        transform=fig.transFigure,
        arrowstyle="-|>",
        mutation_scale=8,
        lw=0.7,
        color=PAL["flow"],
        alpha=0.7,
        zorder=0,
        clip_on=False,
    )
    fig.add_artist(arr)


def build_figure(bundle: ExampleBundle, events: list[dict[str, Any]]) -> plt.Figure:
    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    gs = GridSpec(
        2,
        2,
        figure=fig,
        wspace=0.28,
        hspace=0.52,
        left=0.07,
        right=0.93,
        top=0.86,
        bottom=0.15,
    )
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])

    draw_panel_a(ax_a, bundle)
    draw_panel_b(ax_b, bundle, events)
    draw_panel_c(ax_c, bundle, events)
    draw_panel_d(ax_d, bundle, events)

    # Subtle reading-flow arrows (A→C and B→D vertical; light grey)
    _flow_arrow(fig, 0.045, 0.78, 0.48)
    _flow_arrow(fig, 0.96, 0.78, 0.48)

    fig.suptitle(
        "Figure 3. Task fMRI session timeline, paradigm structure, and multimodal synchronization",
        fontsize=FS["suptitle"],
        fontweight="bold",
        color=PAL["ink"],
        y=0.965,
    )
    caption = (
        "Caption. (A) Chronological MRI session timeline for a representative BIDS session "
        f"({bundle.subject}/{bundle.session_id}); major acquisitions are labeled; calibration "
        "scans (localizer, spin-echo field maps, control EPI) are shown as compact grey blocks. "
        "Block widths are proportional to estimated acquisition duration. "
        "(B) One task-fmri run from events.tsv illustrating fixation, rest, and stimulus timing "
        f"(TR = {bundle.tr:.3f} s). "
        "(C) Temporal alignment of stimulus, BOLD volume onsets, cardiac and respiratory "
        "PhysioLog traces; eye-tracking is illustrative only (not in the current release). "
        "(D) Graphical excerpt of events.tsv for the first 90 s with TR ticks."
    )
    fig.text(
        0.07,
        0.02,
        caption,
        ha="left",
        va="bottom",
        fontsize=FS["caption"],
        color=PAL["muted"],
    )
    return fig


def save_all(fig: plt.Figure, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("pdf", "png", "svg"):
        p = out_dir / f"{STEM}.{ext}"
        kw = {"bbox_inches": "tight", "facecolor": PAL["white"]}
        if ext == "png":
            kw["dpi"] = DPI
        fig.savefig(p, **kw)
        paths.append(p)
        print(f"Wrote {p}")
    return paths


def main(argv: Optional[list[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cwd = Path.cwd().resolve()
    bids = find_bids_root(cwd)
    print(f"BIDS root: {bids}")
    print(f"Font: {FONT}")

    bundle = choose_example(bids)
    events = load_paradigm_events(bundle)
    for n in bundle.notes:
        print(f"Note: {n}")
    print(f"Session blocks: {len(bundle.blocks)}")
    print(f"Events: {len(events)}  TR={bundle.tr}")

    fig = build_figure(bundle, events)
    # Write to CWD (expected: BIDS root) and mirror under code/ if present
    save_all(fig, cwd)
    mirror = bids / "code"
    if mirror.is_dir() and cwd.resolve() != mirror.resolve():
        # also keep a copy beside the generator when run from BIDS root
        pass
    # Manuscript figures mirror (best-effort)
    ms = Path.home() / "scratch" / "reports" / "scientific_data_manuscript_draft" / "figures"
    if ms.parent.is_dir():
        save_all(fig, ms)
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
