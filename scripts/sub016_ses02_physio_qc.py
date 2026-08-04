#!/usr/bin/env python3
"""Physiological QC figure for sub-016 / ses-02 (BIDS physio preferred).

Produces:
  sub016_ses02_physio_qc.png
  sub016_ses02_physio_report.txt

Does not modify any raw / BIDS input files.

Example:
  python sub016_ses02_physio_qc.py \\
      --bids_dir /path/to/bids \\
      --output_dir ./physio_sub016_qc
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    from scipy.signal import butter, filtfilt, find_peaks, medfilt

    HAVE_SCIPY = True
except ImportError:  # pragma: no cover
    HAVE_SCIPY = False

try:
    import pandas as pd

    HAVE_PANDAS = True
except ImportError:  # pragma: no cover
    HAVE_PANDAS = False

SUBJECT = "sub-016"
SESSION = "ses-02"
PLOT_S = 60.0
DEFAULT_PMU_FS = 400.0

CARDIAC_COLS = ("cardiac", "pulse", "puls", "PULS", "Pulse")
RESP_COLS = ("respiratory", "respiration", "resp", "RESP", "Respiration")

# Prefer resting-state BOLD-linked physio when several runs exist.
TASK_PREFERENCE = ("rest", "fmri", "movie", "control")


@dataclass
class Channel:
    path: Path
    sidecar: Path | None
    label: str
    column: str
    samples: np.ndarray
    fs_hz: float
    fs_source: str
    acquisition: str  # e.g. task-rest_run-01


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _task_rank(name: str) -> tuple[int, str]:
    lower = name.lower()
    for i, tok in enumerate(TASK_PREFERENCE):
        if f"task-{tok}" in lower or f"_{tok}_" in lower:
            return i, lower
    return len(TASK_PREFERENCE), lower


def find_bids_physio_pair(bids_dir: Path) -> tuple[Path, Path] | None:
    """Locate pulse + respiratory *_physio.tsv.gz for SUBJECT/SESSION."""
    ses_dir = bids_dir / SUBJECT / SESSION
    if not ses_dir.is_dir():
        # Allow nested layouts / release trees.
        matches = list(bids_dir.rglob(f"{SUBJECT}_{SESSION}_*_physio.tsv.gz"))
        roots = {p.parent for p in matches}
        if not roots:
            return None
        ses_dir = next(iter(roots)).parent  # .../func -> ses

    func = ses_dir / "func"
    search_root = func if func.is_dir() else ses_dir

    pulse_files = sorted(
        search_root.rglob(f"{SUBJECT}_{SESSION}_*_recording-pulse_physio.tsv.gz"),
        key=lambda p: _task_rank(p.name),
    )
    # Also accept recording-cardiac naming variants.
    pulse_files += sorted(
        [
            p
            for p in search_root.rglob(f"{SUBJECT}_{SESSION}_*_physio.tsv.gz")
            if "recording-cardiac" in p.name.lower()
            or "recording-puls" in p.name.lower()
        ],
        key=lambda p: _task_rank(p.name),
    )
    # Deduplicate preserving order.
    seen: set[Path] = set()
    uniq_pulse: list[Path] = []
    for p in pulse_files:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq_pulse.append(p)

    for puls in uniq_pulse:
        # Sibling respiratory file with same stem entities.
        name = puls.name
        resp_name = (
            name.replace("recording-pulse", "recording-respiratory")
            .replace("recording-cardiac", "recording-respiratory")
            .replace("recording-puls", "recording-respiratory")
        )
        resp = puls.with_name(resp_name)
        if resp.is_file():
            return puls, resp
    return None


def find_siemens_pmu_pair(search_dirs: list[Path]) -> tuple[Path, Path] | None:
    """Fallback: Siemens .puls / .resp for this subject/session."""
    sub_tokens = ("sub-016", "sub016", "subc016", "subc16", "SUBC016", "SUBC16")
    ses_tokens = ("ses-02", "ses02", "session02", "session2", "session-2", "scan2")
    puls_hits: list[Path] = []
    for root in search_dirs:
        if not root.is_dir():
            continue
        for p in root.rglob("*.puls"):
            s = str(p)
            if not any(t.lower() in s.lower() for t in sub_tokens):
                continue
            if not any(t.lower() in s.lower() for t in ses_tokens):
                continue
            puls_hits.append(p)
    for puls in sorted(puls_hits):
        resp = puls.with_suffix(".resp")
        if resp.is_file():
            return puls, resp
    return None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _sidecar_path(tsv_gz: Path) -> Path:
    return Path(str(tsv_gz).replace(".tsv.gz", ".json"))


def _pick_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    lower_map = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def _acquisition_from_name(path: Path) -> str:
    m = re.search(r"(task-[a-zA-Z0-9]+_run-\d+)", path.name)
    if m:
        return m.group(1)
    return path.stem.replace("_physio", "").replace(".tsv", "")


def _read_physio_tsv_gz(tsv_gz: Path) -> tuple[list[str], np.ndarray]:
    """Read BIDS physio tsv.gz → (column_names, data 2D float)."""
    if HAVE_PANDAS:
        with gzip.open(tsv_gz, "rt", encoding="utf-8") as fh:
            df = pd.read_csv(fh, sep="\t")
        cols = [str(c) for c in df.columns]
        data = df.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
        return cols, data

    with gzip.open(tsv_gz, "rt", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        rows: list[list[float]] = []
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            row: list[float] = []
            for p in parts:
                try:
                    row.append(float(p))
                except ValueError:
                    row.append(np.nan)
            if row:
                rows.append(row)
    if not rows:
        raise ValueError(f"empty physio table: {tsv_gz}")
    return header, np.asarray(rows, dtype=np.float64)


def load_bids_channel(tsv_gz: Path, kind: str) -> Channel:
    """Load one BIDS physio channel (tsv.gz + json)."""
    side = _sidecar_path(tsv_gz)
    meta: dict = {}
    if side.is_file():
        meta = json.loads(side.read_text(encoding="utf-8"))

    cols, data = _read_physio_tsv_gz(tsv_gz)
    if data.ndim == 1:
        data = data.reshape(-1, 1)

    if kind == "cardiac":
        col = _pick_column(cols, CARDIAC_COLS)
    else:
        col = _pick_column(cols, RESP_COLS)
    if col is None and len(cols) == 1:
        col = cols[0]
    if col is None:
        raise ValueError(f"No {kind} column in {tsv_gz.name}; columns={cols}")

    idx = cols.index(col)
    samples = data[:, idx]
    samples = samples[np.isfinite(samples)]

    fs = meta.get("SamplingFrequency")
    if fs is None or float(fs) <= 0:
        raise ValueError(f"Missing/invalid SamplingFrequency in {side}")
    fs = float(fs)

    return Channel(
        path=tsv_gz,
        sidecar=side if side.is_file() else None,
        label=kind,
        column=col,
        samples=samples,
        fs_hz=fs,
        fs_source="json_SamplingFrequency",
        acquisition=_acquisition_from_name(tsv_gz),
    )


def _extract_siemens_waveform(text: str, max_keep: int) -> np.ndarray:
    """Minimal Siemens ASCII PMU extractor (leading samples after 6002)."""
    control = {5000, 5002, 5003, 6000, 6002, 6003}
    idx = text.find(" 6002 ")
    if idx < 0:
        idx = text.find("6002")
    if idx < 0:
        raise ValueError("no 6002 marker")
    i = idx
    n = len(text)
    while i < n and not text[i].isspace():
        i += 1
    values: list[int] = []
    while i < n and len(values) < max_keep:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        j = i
        if text[j] == "-":
            j += 1
        if j >= n or not text[j].isdigit():
            k = i
            while k < n and not text[k].isspace():
                k += 1
            tok = text[i:k]
            if tok == "5003" or tok.startswith("Log") or tok in {
                "ECG", "PULS", "RESP", "EXT", "EXT2", "NrTrig"
            }:
                break
            i = k
            continue
        while j < n and text[j].isdigit():
            j += 1
        v = int(text[i:j])
        i = j
        if v in control or abs(v) >= 10_000_000:
            if v == 5003:
                break
            continue
        values.append(v)
    if not values:
        raise ValueError("empty Siemens waveform")
    return np.asarray(values, dtype=np.float64)


def load_siemens_channel(path: Path, kind: str) -> Channel:
    text = path.read_bytes().decode("latin-1", errors="replace")
    fs = DEFAULT_PMU_FS
    samples = _extract_siemens_waveform(text, max_keep=int(fs * (PLOT_S + 30)) + 8)
    return Channel(
        path=path,
        sidecar=None,
        label=kind,
        column=path.suffix.lstrip("."),
        samples=samples,
        fs_hz=fs,
        fs_source=f"default_{DEFAULT_PMU_FS:g}Hz_Siemens_PMU",
        acquisition=path.stem,
    )


# ---------------------------------------------------------------------------
# Peak detection / rates (on processed copies only)
# ---------------------------------------------------------------------------


def _moving_average(x: np.ndarray, win: int) -> np.ndarray:
    win = max(1, int(win))
    if win == 1 or x.size < win:
        return x
    kernel = np.ones(win, dtype=np.float64) / win
    return np.convolve(x, kernel, mode="same")


def _butter_bandpass(x: np.ndarray, fs: float, lo: float, hi: float, order: int = 2) -> np.ndarray:
    x0 = x - np.mean(x)
    if not HAVE_SCIPY:
        # Lightweight fallback: moving-average high-pass + low-pass.
        hp = max(1, int(fs / max(lo, 1e-3)))
        lp = max(1, int(fs / max(hi, 1e-3)))
        trend = _moving_average(x0, hp)
        y = x0 - trend
        return _moving_average(y, max(1, lp // 4))
    nyq = 0.5 * fs
    lo_n = max(lo / nyq, 1e-5)
    hi_n = min(hi / nyq, 0.999)
    if lo_n >= hi_n:
        return x0
    b, a = butter(order, [lo_n, hi_n], btype="band")
    if x0.size < 3 * max(len(a), len(b)):
        return x0
    return filtfilt(b, a, x0)


def _find_peaks_numpy(x: np.ndarray, distance: int, height: float) -> np.ndarray:
    """Minimal local-maxima detector (scipy.find_peaks fallback)."""
    if x.size < 3:
        return np.asarray([], dtype=int)
    cand = np.where((x[1:-1] > x[:-2]) & (x[1:-1] >= x[2:]) & (x[1:-1] >= height))[0] + 1
    if cand.size == 0:
        return cand
    keep: list[int] = [int(cand[0])]
    for idx in cand[1:]:
        if idx - keep[-1] >= distance:
            keep.append(int(idx))
        elif x[idx] > x[keep[-1]]:
            keep[-1] = int(idx)
    return np.asarray(keep, dtype=int)


def detect_cardiac_peaks(raw: np.ndarray, fs: float) -> np.ndarray:
    """Peak indices on a demeaned / bandpassed copy (0.5–3 Hz).

    For clipped Siemens pulse (plateau near 4095), also fall back to
    rising-edge detection on the raw demeaned signal.
    """
    x = _butter_bandpass(raw.astype(np.float64), fs, 0.5, 3.0)
    # Min ~0.40 s between beats → max physiological HR ~150 bpm (avoids notch doubles).
    distance = max(1, int(0.40 * fs))
    height = max(float(np.std(x)) * 0.5, 1e-6)
    if HAVE_SCIPY:
        peaks, _ = find_peaks(x, distance=distance, height=height, prominence=height * 0.3)
    else:
        peaks = _find_peaks_numpy(x, distance=distance, height=height)

    # If still too dense (likely double peaks), keep strongest in each refractory window.
    if peaks.size >= 2:
        min_rr = 0.40 * fs
        kept = [int(peaks[0])]
        for p in peaks[1:]:
            if p - kept[-1] >= min_rr:
                kept.append(int(p))
            elif x[int(p)] > x[kept[-1]]:
                kept[-1] = int(p)
        peaks = np.asarray(kept, dtype=int)
    return peaks


def detect_respiratory_peaks(raw: np.ndarray, fs: float) -> np.ndarray:
    """Respiratory peaks on smoothed demeaned copy."""
    x = raw.astype(np.float64) - np.mean(raw)
    k = max(3, int(0.2 * fs) | 1)
    if HAVE_SCIPY and x.size > k:
        x = medfilt(x, kernel_size=k)
    else:
        x = _moving_average(x, k)
    x = _butter_bandpass(x, fs, 0.05, 0.5)
    distance = max(1, int(1.5 * fs))
    height = max(float(np.std(x)) * 0.3, 1e-6)
    if HAVE_SCIPY:
        peaks, _ = find_peaks(x, distance=distance, height=height, prominence=height * 0.2)
        return peaks
    return _find_peaks_numpy(x, distance=distance, height=height)


def instantaneous_rate(peak_idx: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (times_s at interval midpoints, rate in cycles/min)."""
    if peak_idx.size < 2:
        return np.asarray([]), np.asarray([])
    rr = np.diff(peak_idx) / fs
    # Drop physiologically impossible intervals
    rr = np.where(rr > 0, rr, np.nan)
    rate = 60.0 / rr
    t = (peak_idx[:-1] + peak_idx[1:]) / 2.0 / fs
    ok = np.isfinite(rate)
    return t[ok], rate[ok]


def rate_stats(rate: np.ndarray) -> dict[str, float]:
    if rate.size == 0:
        return {"mean": np.nan, "std": np.nan, "min": np.nan, "max": np.nan}
    return {
        "mean": float(np.mean(rate)),
        "std": float(np.std(rate)),
        "min": float(np.min(rate)),
        "max": float(np.max(rate)),
    }


def quality_label(kind: str, n_peaks: int, rate: np.ndarray, duration_s: float) -> str:
    """Simple GOOD/POOR heuristic for the PI report."""
    if duration_s < 20 or n_peaks < 5 or rate.size == 0:
        return "POOR"
    mean = float(np.mean(rate))
    std = float(np.std(rate))
    if kind == "cardiac":
        # Expected ~40–160 bpm in scanner; stable enough for a QC example.
        if 40 <= mean <= 160 and std < 30 and n_peaks >= 0.5 * duration_s:
            return "GOOD"
        return "POOR"
    # respiration ~6–35 breaths/min
    if 6 <= mean <= 35 and std < 12 and n_peaks >= 0.05 * duration_s:
        return "GOOD"
    return "POOR"


# ---------------------------------------------------------------------------
# Figure + report
# ---------------------------------------------------------------------------


def make_figure(
    cardiac: Channel,
    resp: Channel,
    c_peaks: np.ndarray,
    r_peaks: np.ndarray,
    hr_t: np.ndarray,
    hr: np.ndarray,
    rr_t: np.ndarray,
    rr: np.ndarray,
    out_png: Path,
) -> None:
    def window(sig: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, int]:
        n = min(sig.size, int(PLOT_S * fs) + 1)
        t = np.arange(n, dtype=np.float64) / fs
        return t, sig[:n], n

    t_c, y_c, n_c = window(cardiac.samples, cardiac.fs_hz)
    t_r, y_r, n_r = window(resp.samples, resp.fs_hz)
    c_peaks_w = c_peaks[c_peaks < n_c]
    r_peaks_w = r_peaks[r_peaks < n_r]
    hr_mask = hr_t <= PLOT_S
    rr_mask = rr_t <= PLOT_S

    fig, axes = plt.subplots(
        4, 1, figsize=(10, 8), sharex=False, dpi=300, constrained_layout=True
    )
    fig.suptitle(
        f"{SUBJECT} {SESSION} · {cardiac.acquisition}",
        fontsize=11,
        fontweight="medium",
    )

    # Panel 1 — raw cardiac
    axes[0].plot(t_c, y_c, color="#2F6F6F", lw=0.7)
    if c_peaks_w.size:
        axes[0].plot(
            c_peaks_w / cardiac.fs_hz,
            y_c[c_peaks_w],
            "o",
            ms=3.5,
            color="#C45C26",
            label="detected peaks",
        )
        axes[0].legend(loc="upper right", fontsize=7, frameon=False)
    axes[0].set_title("Sub-016 ses-02: Peripheral pulse signal", loc="left", fontsize=10)
    axes[0].set_ylabel("ADC amplitude", fontsize=9)
    axes[0].set_xlim(0, PLOT_S)
    axes[0].spines["top"].set_visible(False)
    axes[0].spines["right"].set_visible(False)
    axes[0].grid(True, axis="y", color="#E8E8E8", lw=0.6)

    # Panel 2 — HR
    axes[1].plot(hr_t[hr_mask], hr[hr_mask], color="#1F4E5F", lw=1.0)
    axes[1].set_title("Derived heart rate", loc="left", fontsize=10)
    axes[1].set_ylabel("Heart rate (bpm)", fontsize=9)
    axes[1].set_xlabel("time (s)", fontsize=9)
    axes[1].set_xlim(0, PLOT_S)
    axes[1].spines["top"].set_visible(False)
    axes[1].spines["right"].set_visible(False)
    axes[1].grid(True, axis="y", color="#E8E8E8", lw=0.6)

    # Panel 3 — raw respiration
    axes[2].plot(t_r, y_r, color="#6B4E3D", lw=0.8)
    if r_peaks_w.size:
        axes[2].plot(
            r_peaks_w / resp.fs_hz,
            y_r[r_peaks_w],
            "o",
            ms=4.0,
            color="#2F6F6F",
            label="detected peaks",
        )
        axes[2].legend(loc="upper right", fontsize=7, frameon=False)
    axes[2].set_title("Respiratory belt signal", loc="left", fontsize=10)
    axes[2].set_ylabel("ADC amplitude", fontsize=9)
    axes[2].set_xlim(0, PLOT_S)
    axes[2].spines["top"].set_visible(False)
    axes[2].spines["right"].set_visible(False)
    axes[2].grid(True, axis="y", color="#E8E8E8", lw=0.6)

    # Panel 4 — respiratory rate
    axes[3].plot(rr_t[rr_mask], rr[rr_mask], color="#8B4513", lw=1.0)
    axes[3].set_title("Derived respiratory rate", loc="left", fontsize=10)
    axes[3].set_ylabel("Breaths/min", fontsize=9)
    axes[3].set_xlabel("time (s)", fontsize=9)
    axes[3].set_xlim(0, PLOT_S)
    axes[3].spines["top"].set_visible(False)
    axes[3].spines["right"].set_visible(False)
    axes[3].grid(True, axis="y", color="#E8E8E8", lw=0.6)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=300, facecolor="white")
    plt.close(fig)


def write_report(
    out_txt: Path,
    cardiac: Channel,
    resp: Channel,
    c_peaks: np.ndarray,
    r_peaks: np.ndarray,
    hr_stats: dict[str, float],
    rr_stats: dict[str, float],
    q_card: str,
    q_resp: str,
    source_mode: str,
) -> None:
    dur_c = (cardiac.samples.size - 1) / cardiac.fs_hz if cardiac.samples.size > 1 else 0.0
    dur_r = (resp.samples.size - 1) / resp.fs_hz if resp.samples.size > 1 else 0.0
    lines = [
        "Physiological QC report",
        "=======================",
        "",
        f"Participant: {SUBJECT}",
        f"Session: {SESSION}",
        f"Acquisition (selected): {cardiac.acquisition}",
        f"Source mode: {source_mode}",
        "",
        "Selected file paths:",
        f"  Cardiac     : {cardiac.path}",
        f"  Respiratory : {resp.path}",
        f"  Cardiac JSON: {cardiac.sidecar if cardiac.sidecar else 'n/a'}",
        f"  Resp JSON   : {resp.sidecar if resp.sidecar else 'n/a'}",
        "",
        f"Cardiac column      : {cardiac.column}",
        f"Respiratory column  : {resp.column}",
        f"Cardiac duration (s): {dur_c:.3f}",
        f"Resp duration (s)   : {dur_r:.3f}",
        f"Cardiac SamplingFrequency: {cardiac.fs_hz:g} Hz ({cardiac.fs_source})",
        f"Resp SamplingFrequency   : {resp.fs_hz:g} Hz ({resp.fs_source})",
        "",
        f"Number of cardiac peaks     : {c_peaks.size}",
        f"Mean heart rate (bpm)       : {hr_stats['mean']:.2f}",
        f"HR std / min / max (bpm)    : {hr_stats['std']:.2f} / {hr_stats['min']:.2f} / {hr_stats['max']:.2f}",
        "",
        f"Respiratory cycles detected : {r_peaks.size}",
        f"Mean respiratory rate       : {rr_stats['mean']:.2f} breaths/min",
        f"RR std / min / max          : {rr_stats['std']:.2f} / {rr_stats['min']:.2f} / {rr_stats['max']:.2f}",
        "",
        "Quality assessment:",
        f"  Cardiac signal    : {q_card}",
        f"  Respiratory signal: {q_resp}",
        "",
        "Notes:",
        "  - Raw traces in the figure are unfiltered.",
        "  - Peak detection uses demeaned / lightly filtered copies only.",
        "  - ADC amplitude = Siemens converter counts (not calibrated physio units).",
        "  - Figure shows the first 60 seconds of the selected run-linked recording.",
        f"  - Peak detection backend: {'scipy.signal' if HAVE_SCIPY else 'numpy fallback'}.",
        "",
    ]
    if "default_" in cardiac.fs_source or "default_" in resp.fs_source:
        lines.append(
            f"  - ASSUMPTION: default {DEFAULT_PMU_FS:g} Hz used for Siemens PMU "
            "files lacking SamplingFrequency."
        )
        lines.append("")
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"Physio QC figure for {SUBJECT} / {SESSION}"
    )
    p.add_argument(
        "--bids_dir",
        type=Path,
        required=True,
        help="BIDS root containing sub-016/ses-02 physio recordings",
    )
    p.add_argument(
        "--output_dir",
        type=Path,
        default=Path("./physio_sub016_qc"),
        help="Output directory for PNG + report",
    )
    p.add_argument(
        "--pmu_fallback_dir",
        type=Path,
        default=None,
        help="Optional root to search for Siemens .puls/.resp if BIDS physio missing",
    )
    p.add_argument(
        "--prefer_task",
        type=str,
        default="rest",
        help="Preferred task entity (default: rest)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bids_dir = args.bids_dir.expanduser().resolve()
    out_dir = args.output_dir.expanduser().resolve()

    if not bids_dir.is_dir():
        print(f"ERROR: bids_dir not found: {bids_dir}", file=sys.stderr)
        return 2

    # Honour --prefer_task by temporarily reordering preference list.
    global TASK_PREFERENCE
    pref = tuple(
        [args.prefer_task.lower()]
        + [t for t in TASK_PREFERENCE if t != args.prefer_task.lower()]
    )
    TASK_PREFERENCE = pref

    source_mode = "bids_physio_tsv_gz"
    pair = find_bids_physio_pair(bids_dir)
    if pair is None:
        print("BIDS *_physio.tsv.gz pair not found; trying Siemens .puls/.resp …")
        search = [bids_dir]
        if args.pmu_fallback_dir is not None:
            search.append(args.pmu_fallback_dir.expanduser().resolve())
        # Common project raw tree (read-only).
        search.append(Path("/lustre06/project/6001995/raw_original"))
        pmu = find_siemens_pmu_pair(search)
        if pmu is None:
            print("ERROR: no BIDS physio and no Siemens .puls/.resp pair found.", file=sys.stderr)
            return 1
        source_mode = "siemens_pmu_ascii"
        cardiac = load_siemens_channel(pmu[0], "cardiac")
        resp = load_siemens_channel(pmu[1], "respiratory")
    else:
        print(f"Selected cardiac     : {pair[0]}")
        print(f"Selected respiratory : {pair[1]}")
        cardiac = load_bids_channel(pair[0], "cardiac")
        resp = load_bids_channel(pair[1], "respiratory")

    print(
        f"Loaded {cardiac.acquisition}: "
        f"cardiac fs={cardiac.fs_hz:g} Hz ({cardiac.fs_source}), "
        f"resp fs={resp.fs_hz:g} Hz ({resp.fs_source})"
    )

    c_peaks = detect_cardiac_peaks(cardiac.samples, cardiac.fs_hz)
    r_peaks = detect_respiratory_peaks(resp.samples, resp.fs_hz)
    hr_t, hr = instantaneous_rate(c_peaks, cardiac.fs_hz)
    rr_t, rr = instantaneous_rate(r_peaks, resp.fs_hz)
    # Physiological plausibility clip for display / summary stats.
    if hr.size:
        ok = (hr >= 30) & (hr <= 180)
        hr_t, hr = hr_t[ok], hr[ok]
    if rr.size:
        ok = (rr >= 4) & (rr <= 40)
        rr_t, rr = rr_t[ok], rr[ok]

    hr_stats = rate_stats(hr)
    rr_stats = rate_stats(rr)
    dur_c = (cardiac.samples.size - 1) / cardiac.fs_hz if cardiac.samples.size > 1 else 0.0
    dur_r = (resp.samples.size - 1) / resp.fs_hz if resp.samples.size > 1 else 0.0
    q_card = quality_label("cardiac", int(c_peaks.size), hr, dur_c)
    q_resp = quality_label("resp", int(r_peaks.size), rr, dur_r)

    out_png = out_dir / "sub016_ses02_physio_qc.png"
    out_txt = out_dir / "sub016_ses02_physio_report.txt"
    make_figure(cardiac, resp, c_peaks, r_peaks, hr_t, hr, rr_t, rr, out_png)
    write_report(
        out_txt,
        cardiac,
        resp,
        c_peaks,
        r_peaks,
        hr_stats,
        rr_stats,
        q_card,
        q_resp,
        source_mode,
    )
    print(f"Wrote {out_png}")
    print(f"Wrote {out_txt}")
    print(f"Cardiac quality: {q_card} | Respiratory quality: {q_resp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
