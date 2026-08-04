#!/usr/bin/env python3
"""Select the best Siemens .puls / .resp pair and plot a publication QC figure.

Does not modify any raw files. Read-only on --input_dir.

Example:
  python generate_physio_example_figure.py \\
      --input_dir /path/to/raw_original \\
      --output_dir ./physio_qc_example
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Siemens PMU control / marker tokens (excluded from the waveform).
PMU_CONTROL = {5000, 5002, 5003, 6000, 6002, 6003}

DEFAULT_FS_HZ = 400.0  # used only when frequency cannot be inferred
MIN_DURATION_S = 30.0
PLOT_DURATION_S = 60.0
REST_TOKENS = ("rest", "resting", "task-rest", "bold")

RE_LOGSTART_MDH = re.compile(r"LogStartMDHTime:\s*(-?\d+)", re.IGNORECASE)
RE_LOGSTOP_MDH = re.compile(r"LogStopMDHTime:\s*(-?\d+)", re.IGNORECASE)
RE_SAMPLETIME = re.compile(
    r"(?:SampleTime|SamplePeriod|SamplingInterval)\s*[:=]\s*(\d+(?:\.\d+)?)\s*(ms|s)?",
    re.IGNORECASE,
)
RE_SAMPLING_HZ = re.compile(
    r"(?:SamplingFrequency|Sampling[_ ]?Rate|Sample[_ ]?Rate|ADC[_ ]?Frequency)"
    r"\s*[:=]\s*(\d+(?:\.\d+)?)\s*(?:Hz)?",
    re.IGNORECASE,
)
RE_SUB = re.compile(
    r"(?:^|[/_\-])((?:sub[-_]?)?(?:C|c)?\d{1,3}|SUBC?\d{1,3})(?:$|[/_\-])",
    re.IGNORECASE,
)
RE_SES = re.compile(
    r"(ses[-_]?\d+|session[-_]?\d+|Scan[-_]?\d+|SESSION[-_]?\d+)",
    re.IGNORECASE,
)
RE_EXCLUDE = re.compile(r"(?:^|[/_\-])(test|phantom|discard|tmp)(?:$|[/_\-])", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LoadedSignal:
    path: Path
    samples: np.ndarray
    fs_hz: float
    fs_source: str  # "header" | "mdh_estimate" | "default_400Hz"
    duration_s: float
    n_samples: int
    mean: float
    std: float
    vmin: float
    vmax: float
    pct_nonzero: float
    longest_flat_frac: float
    has_nan: bool


@dataclass
class CandidatePair:
    puls_path: Path
    resp_path: Path
    subject: str
    session: str
    acquisition: str
    is_rest_preferred: bool
    score: float = float("-inf")
    reject_reason: str = ""
    puls: LoadedSignal | None = None
    resp: LoadedSignal | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Siemens ASCII PMU parsing
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    """Read a Siemens physio file as Latin-1 text (robust to odd bytes)."""
    raw = path.read_bytes()
    if not raw:
        raise ValueError("empty file")
    # Reject obvious binary dumps (null-heavy).
    head = raw[:512]
    if head and (sum(1 for b in head if 9 <= b <= 13 or 32 <= b <= 126) / len(head) < 0.7):
        raise ValueError("binary / unreadable as Siemens ASCII PMU")
    return raw.decode("latin-1", errors="replace")


def _mdh_duration_s(text: str) -> float | None:
    """Duration from LogStart/Stop MDH footer times (milliseconds → seconds)."""
    # Search footer only (last 4 KB) — much faster on multi-MB dumps.
    footer = text[-4096:] if len(text) > 4096 else text
    m0 = RE_LOGSTART_MDH.search(footer)
    m1 = RE_LOGSTOP_MDH.search(footer)
    if not (m0 and m1):
        return None
    dt_ms = int(m1.group(1)) - int(m0.group(1))
    if dt_ms <= 0:
        return None
    return dt_ms / 1000.0


def _extract_waveform(
    text: str, max_keep: int
) -> tuple[np.ndarray, int | None]:
    """Extract leading waveform samples after the 6002 marker.

    Returns (kept_samples, total_sample_count_or_None).
    total_sample_count is estimated later from MDH duration × fs when not
    counted exhaustively (avoids tokenizing multi-million-sample dumps).
    """
    # Prefer the data marker; fall back to LOGVERSION / 5002.
    idx = text.find(" 6002 ")
    if idx < 0:
        idx = text.find("6002")
    if idx < 0:
        idx = text.find("5002")
    if idx < 0:
        raise ValueError("no 6002/5002 waveform marker found")

    # Scan forward with a lightweight integer tokenizer (no full split()).
    values: list[int] = []
    i = idx
    n = len(text)
    # Skip the marker token itself.
    while i < n and not text[i].isspace():
        i += 1

    while i < n and len(values) < max_keep:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        j = i
        if text[j] == "-":
            j += 1
        if j >= n or not text[j].isdigit():
            # Non-numeric token: stop at footer keywords; otherwise skip token.
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
        # Require token end (space / EOL) so we do not clip larger numbers.
        if j < n and not text[j].isspace() and text[j] not in "\r\n":
            i = j
            while i < n and not text[i].isspace():
                i += 1
            continue
        v = int(text[i:j])
        i = j
        if v in PMU_CONTROL or abs(v) >= 10_000_000:
            if v == 5003:
                break
            continue
        values.append(v)

    if not values:
        raise ValueError("no waveform samples found after marker")
    return np.asarray(values, dtype=np.float64), None


def _detect_fs_hz(text: str) -> tuple[float, str]:
    """Detect sampling frequency from header labels, else default 400 Hz."""
    head = text[:8192]
    foot = text[-8192:] if len(text) > 8192 else text
    probe = head + "\n" + foot

    m = RE_SAMPLING_HZ.search(probe)
    if m:
        hz = float(m.group(1))
        if hz > 0:
            return hz, "header"

    m = RE_SAMPLETIME.search(probe)
    if m:
        val = float(m.group(1))
        unit = (m.group(2) or "ms").lower()
        if val > 0:
            hz = (1000.0 / val) if unit == "ms" else (1.0 / val)
            if hz > 0:
                return hz, "header"

    # Siemens 'Freq Per' is physiological rate/period — deliberately ignored.
    return DEFAULT_FS_HZ, "default_400Hz"


def _longest_flat_fraction(x: np.ndarray) -> float:
    """Fraction of samples occupied by the longest constant run."""
    if x.size == 0:
        return 1.0
    # Run-length on equality of consecutive samples.
    change = np.flatnonzero(np.diff(x) != 0)
    # Boundaries of constant segments
    bounds = np.concatenate(([0], change + 1, [x.size]))
    lengths = np.diff(bounds)
    return float(lengths.max() / x.size)


def load_siemens_physio(
    path: Path, *, max_keep: int | None = None
) -> LoadedSignal:
    """Load one Siemens .puls / .resp ASCII file into a LoadedSignal.

    Only the leading `max_keep` samples are retained (enough for QC + 60 s
    plot). Full-session duration is taken from MDH footer times when present.
    """
    text = _read_text(path)
    fs, fs_source = _detect_fs_hz(text)
    keep = max_keep if max_keep is not None else int(fs * (PLOT_DURATION_S + 30.0)) + 16
    samples, _ = _extract_waveform(text, max_keep=keep)
    finite = samples[np.isfinite(samples)]
    if finite.size == 0:
        raise ValueError("all samples non-finite")

    mdh_dur = _mdh_duration_s(text)
    if mdh_dur is not None and mdh_dur > 0:
        duration_s = mdh_dur
        n_samples = int(round(duration_s * fs)) + 1
    else:
        # Fall back to kept-sample length (short files / missing footer).
        duration_s = (finite.size - 1) / fs if finite.size > 1 else 0.0
        n_samples = int(finite.size)

    pct_nonzero = float(np.count_nonzero(finite) / finite.size)
    return LoadedSignal(
        path=path,
        samples=finite.astype(np.float64, copy=False),
        fs_hz=float(fs),
        fs_source=fs_source,
        duration_s=float(duration_s),
        n_samples=int(n_samples),
        mean=float(np.mean(finite)),
        std=float(np.std(finite)),
        vmin=float(np.min(finite)),
        vmax=float(np.max(finite)),
        pct_nonzero=pct_nonzero,
        longest_flat_frac=_longest_flat_fraction(finite),
        has_nan=bool(np.isnan(samples).any()),
    )


# ---------------------------------------------------------------------------
# Discovery / pairing
# ---------------------------------------------------------------------------


def discover_physio_files(input_dir: Path) -> tuple[list[Path], list[Path]]:
    """Recursively find *.puls and *.resp under input_dir (skip test/phantom)."""
    puls = sorted(p for p in input_dir.rglob("*.puls") if not _is_excluded_path(p))
    resp = sorted(p for p in input_dir.rglob("*.resp") if not _is_excluded_path(p))
    return puls, resp


def _path_is_rest_preferred(path: Path) -> bool:
    s = str(path).lower()
    return any(tok in s for tok in REST_TOKENS)


def _infer_ids(path: Path) -> tuple[str, str, str]:
    """Best-effort subject / session / acquisition labels from the path."""
    blob = str(path)
    subject = "unknown"
    session = "unknown"

    # Prefer folder names like SUBC01-Session2-2023NOV08
    m = re.search(r"SUBC?(\d{1,3})", blob, flags=re.IGNORECASE)
    if m:
        subject = f"sub-{int(m.group(1)):03d}"
    else:
        m = re.search(r"sub[-_]?(\d{1,3})", blob, flags=re.IGNORECASE)
        if m:
            subject = f"sub-{int(m.group(1)):03d}"

    m = re.search(
        r"(?:ses(?:sion)?[-_ ]?)(\d{1,2})|(?:scan[-_ ]?)(\d{1,2})",
        blob,
        flags=re.IGNORECASE,
    )
    if m:
        ses_num = m.group(1) or m.group(2)
        session = f"ses-{int(ses_num):02d}"

    acquisition = path.stem
    return subject, session, acquisition


def _is_excluded_path(path: Path) -> bool:
    """Drop obvious non-cohort test / phantom recordings."""
    return RE_EXCLUDE.search(str(path)) is not None


def pair_physio_files(puls_files: list[Path], resp_files: list[Path]) -> list[CandidatePair]:
    """Pair .puls and .resp that belong to the same acquisition/session."""
    resp_by_stem: dict[tuple[Path, str], Path] = {}
    resp_by_dir: dict[Path, list[Path]] = {}
    for r in resp_files:
        resp_by_stem[(r.parent.resolve(), r.stem.lower())] = r
        resp_by_dir.setdefault(r.parent.resolve(), []).append(r)

    pairs: list[CandidatePair] = []
    used_resp: set[Path] = set()

    for p in puls_files:
        parent = p.parent.resolve()
        key = (parent, p.stem.lower())
        r = resp_by_stem.get(key)
        if r is None:
            # Same folder, single unmatched .resp → pair opportunistically.
            candidates = [x for x in resp_by_dir.get(parent, []) if x not in used_resp]
            if len(candidates) == 1:
                r = candidates[0]
            else:
                continue
        used_resp.add(r)
        sub, ses, acq = _infer_ids(p)
        is_rest = _path_is_rest_preferred(p) or _path_is_rest_preferred(r)
        pairs.append(
            CandidatePair(
                puls_path=p,
                resp_path=r,
                subject=sub,
                session=ses,
                acquisition=acq,
                is_rest_preferred=is_rest,
            )
        )
    return pairs


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------


def _channel_score(sig: LoadedSignal) -> tuple[float, str]:
    """Score one channel; return (score, reject_reason). Reject → reason != ''."""
    if sig.has_nan:
        return -np.inf, "NaN/corrupted values"
    if sig.duration_s < MIN_DURATION_S:
        return -np.inf, f"duration {sig.duration_s:.1f}s < {MIN_DURATION_S:.0f}s"
    if sig.std < 1e-6 or (sig.vmax - sig.vmin) < 1e-6:
        return -np.inf, "almost no variation"
    if sig.pct_nonzero < 0.05:
        return -np.inf, "mostly zeros"
    if sig.longest_flat_frac > 0.85:
        return -np.inf, "long flat segments"

    # Higher is better. Terms are roughly unit-scaled.
    duration_term = min(sig.duration_s / 120.0, 3.0)  # cap at ~6 min
    variance_term = min(np.log10(sig.std + 1.0), 4.0)
    nonzero_term = sig.pct_nonzero
    flat_penalty = sig.longest_flat_frac
    score = (
        2.0 * duration_term
        + 1.5 * variance_term
        + 1.0 * nonzero_term
        - 2.0 * flat_penalty
    )
    return float(score), ""


def evaluate_pair(pair: CandidatePair) -> CandidatePair:
    """Load both channels and assign a combined quality score."""
    try:
        pair.puls = load_siemens_physio(pair.puls_path)
        pair.resp = load_siemens_physio(pair.resp_path)
    except Exception as exc:  # noqa: BLE001 — keep scanning other pairs
        pair.reject_reason = f"load error: {exc}"
        pair.score = float("-inf")
        return pair

    assert pair.puls is not None and pair.resp is not None
    sp, rp = _channel_score(pair.puls), _channel_score(pair.resp)
    if sp[1]:
        pair.reject_reason = f".puls: {sp[1]}"
        pair.score = float("-inf")
        return pair
    if rp[1]:
        pair.reject_reason = f".resp: {rp[1]}"
        pair.score = float("-inf")
        return pair

    pair.score = sp[0] + rp[0]
    # Soft preference for resting-state / bold-associated paths.
    if pair.is_rest_preferred:
        pair.score += 1.5
        pair.notes.append("rest/bold path bonus applied")
    for sig, label in ((pair.puls, "puls"), (pair.resp, "resp")):
        if sig.fs_source == "default_400Hz":
            pair.notes.append(f"{label}: sampling frequency assumed {DEFAULT_FS_HZ:g} Hz")
        else:
            pair.notes.append(f"{label}: fs={sig.fs_hz:.4g} Hz ({sig.fs_source})")
    return pair


def select_best_pair(pairs: list[CandidatePair]) -> CandidatePair:
    """Evaluate all pairs; prefer rest-associated among valid scores, else best any."""
    evaluated = [evaluate_pair(p) for p in pairs]
    valid = [p for p in evaluated if np.isfinite(p.score)]
    if not valid:
        # Summarize reject reasons to help debugging.
        reasons = {}
        for p in evaluated:
            reasons[p.reject_reason or "unknown"] = reasons.get(p.reject_reason or "unknown", 0) + 1
        detail = "; ".join(f"{k} (n={v})" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:8])
        raise RuntimeError(f"No valid .puls/.resp pair found. Reject reasons: {detail}")

    rest_valid = [p for p in valid if p.is_rest_preferred]
    pool = rest_valid if rest_valid else valid
    pool.sort(key=lambda p: p.score, reverse=True)
    return pool[0]


# ---------------------------------------------------------------------------
# Figure + report
# ---------------------------------------------------------------------------


def plot_physio_example(pair: CandidatePair, out_png: Path) -> None:
    """Two-panel raw-signal figure for the first PLOT_DURATION_S seconds."""
    assert pair.puls is not None and pair.resp is not None
    puls, resp = pair.puls, pair.resp

    def window(sig: LoadedSignal) -> tuple[np.ndarray, np.ndarray]:
        n = min(sig.samples.size, int(PLOT_DURATION_S * sig.fs_hz) + 1)
        y = sig.samples[:n]
        t = np.arange(n, dtype=np.float64) / sig.fs_hz
        return t, y

    t_p, y_p = window(puls)
    t_r, y_r = window(resp)

    fig, axes = plt.subplots(
        2, 1, figsize=(10, 5), sharex=True, dpi=300, constrained_layout=True
    )
    fig.suptitle(
        f"{pair.subject} · {pair.session} · {pair.acquisition}",
        fontsize=11,
        fontweight="medium",
    )

    axes[0].plot(t_p, y_p, color="#2F6F6F", linewidth=0.6)
    axes[0].set_title("Peripheral pulse oximeter signal (.puls)", fontsize=10, loc="left")
    axes[0].set_ylabel("Pulse amplitude", fontsize=9)
    axes[0].spines["top"].set_visible(False)
    axes[0].spines["right"].set_visible(False)
    axes[0].grid(True, axis="y", color="#E6E6E6", linewidth=0.6)

    axes[1].plot(t_r, y_r, color="#6B4E3D", linewidth=0.6)
    axes[1].set_title("Respiratory belt signal (.resp)", fontsize=10, loc="left")
    axes[1].set_ylabel("Respiratory amplitude", fontsize=9)
    axes[1].set_xlabel("Time (s)", fontsize=9)
    axes[1].spines["top"].set_visible(False)
    axes[1].spines["right"].set_visible(False)
    axes[1].grid(True, axis="y", color="#E6E6E6", linewidth=0.6)
    axes[1].set_xlim(0, PLOT_DURATION_S)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=300, facecolor="white")
    plt.close(fig)


def write_report(pair: CandidatePair, out_txt: Path, n_candidates: int, n_valid: int) -> None:
    """Write physio_example_selection_report.txt."""
    assert pair.puls is not None and pair.resp is not None
    lines = [
        "Physiological example selection report",
        "======================================",
        "",
        f"Selected subject ID : {pair.subject}",
        f"Session             : {pair.session}",
        f"Acquisition name    : {pair.acquisition}",
        f"Rest/bold preferred : {pair.is_rest_preferred}",
        f"Quality score       : {pair.score:.4f}",
        f"Candidates scanned  : {n_candidates}",
        f"Valid after QC      : {n_valid}",
        "",
        f".puls path : {pair.puls_path}",
        f".resp path : {pair.resp_path}",
        "",
        "--- Pulse (.puls) ---",
        f"Duration (s)        : {pair.puls.duration_s:.3f}",
        f"Sampling frequency  : {pair.puls.fs_hz:.6g} Hz ({pair.puls.fs_source})",
        f"N samples           : {pair.puls.n_samples}",
        f"mean                : {pair.puls.mean:.6g}",
        f"standard deviation  : {pair.puls.std:.6g}",
        f"min                 : {pair.puls.vmin:.6g}",
        f"max                 : {pair.puls.vmax:.6g}",
        f"% non-zero          : {100 * pair.puls.pct_nonzero:.2f}",
        f"longest flat frac   : {pair.puls.longest_flat_frac:.4f}",
        "",
        "--- Respiratory (.resp) ---",
        f"Duration (s)        : {pair.resp.duration_s:.3f}",
        f"Sampling frequency  : {pair.resp.fs_hz:.6g} Hz ({pair.resp.fs_source})",
        f"N samples           : {pair.resp.n_samples}",
        f"mean                : {pair.resp.mean:.6g}",
        f"standard deviation  : {pair.resp.std:.6g}",
        f"min                 : {pair.resp.vmin:.6g}",
        f"max                 : {pair.resp.vmax:.6g}",
        f"% non-zero          : {100 * pair.resp.pct_nonzero:.2f}",
        f"longest flat frac   : {pair.resp.longest_flat_frac:.4f}",
        "",
        "Notes:",
    ]
    lines.extend(f"  - {n}" for n in pair.notes)
    if any(s.fs_source == "default_400Hz" for s in (pair.puls, pair.resp)):
        lines.append(
            f"  - ASSUMPTION: default sampling frequency of {DEFAULT_FS_HZ:g} Hz was used "
            "where the Siemens header did not provide an explicit ADC rate. "
            "Siemens 'Freq Per' footer fields are physiological rates, not ADC Hz, and were ignored."
        )
    lines.append("")
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Select best Siemens .puls/.resp pair and generate a QC figure."
    )
    p.add_argument(
        "--input_dir",
        type=Path,
        required=True,
        help="Root directory to search recursively for *.puls and *.resp",
    )
    p.add_argument(
        "--output_dir",
        type=Path,
        default=Path("./physio_qc_example"),
        help="Directory for PNG + selection report (created if needed)",
    )
    p.add_argument(
        "--max-pairs",
        type=int,
        default=0,
        help="Optional cap on number of pairs to evaluate (0 = all)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    if not input_dir.is_dir():
        print(f"ERROR: input_dir does not exist: {input_dir}", file=sys.stderr)
        return 2

    print(f"Searching under: {input_dir}")
    puls_files, resp_files = discover_physio_files(input_dir)
    print(f"Found {len(puls_files)} .puls and {len(resp_files)} .resp files")
    if not puls_files or not resp_files:
        print("ERROR: need at least one .puls and one .resp file.", file=sys.stderr)
        return 1

    pairs = pair_physio_files(puls_files, resp_files)
    print(f"Paired acquisitions: {len(pairs)}")
    if not pairs:
        print("ERROR: could not pair any .puls/.resp files.", file=sys.stderr)
        return 1

    if args.max_pairs and args.max_pairs > 0:
        # Evaluate rest-preferred first, then others.
        pairs.sort(key=lambda p: (not p.is_rest_preferred, str(p.puls_path)))
        pairs = pairs[: args.max_pairs]
        print(f"Evaluating first {len(pairs)} pairs (--max-pairs)")

    # Evaluate (this may take a while on large session-wide PMU dumps).
    evaluated: list[CandidatePair] = []
    for i, pair in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] {pair.puls_path.name} …", flush=True)
        evaluated.append(evaluate_pair(pair))

    valid = [p for p in evaluated if np.isfinite(p.score)]
    rest_valid = [p for p in valid if p.is_rest_preferred]
    pool = rest_valid if rest_valid else valid
    if not pool:
        reasons = {}
        for p in evaluated:
            reasons[p.reject_reason or "unknown"] = reasons.get(p.reject_reason or "unknown", 0) + 1
        detail = "; ".join(f"{k} (n={v})" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:8])
        print(f"ERROR: no valid pair. Reject reasons: {detail}", file=sys.stderr)
        return 1

    best = max(pool, key=lambda p: p.score)
    print(
        f"Selected: {best.subject} / {best.session} / {best.acquisition} "
        f"(score={best.score:.3f}, rest={best.is_rest_preferred})"
    )

    out_png = output_dir / "physio_example_best_subject.png"
    out_txt = output_dir / "physio_example_selection_report.txt"
    plot_physio_example(best, out_png)
    write_report(best, out_txt, n_candidates=len(pairs), n_valid=len(valid))
    print(f"Wrote {out_png}")
    print(f"Wrote {out_txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
