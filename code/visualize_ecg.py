#!/usr/bin/env python3
"""Visualize one raw Siemens MRI physiology ECG file (read-only).

Extracts numeric samples from a single ``.ecg`` file and plots amplitude vs
sample index. Sampling frequency is intentionally not assumed, so the x-axis
is sample index (not seconds).

Usage:
    python code/visualize_ecg.py /path/to/file.ecg

This script never modifies source files.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# Siemens ECG channels are multiplexed by adding a channel-specific offset.
# The baseline values below are removed only for visualization; no filtering,
# resampling, or timing assumption is applied.
_SIEMENS_CHANNELS = (
    ("ECG channel 1", 0, 4095, 2048),
    ("ECG channel 2", 8192, 12287, 10240),
    ("ECG channel 3", 17408, 21503, 18432),
    ("ECG channel 4", 25600, 29695, 26624),
)
_PMU_CONTROL_CODES = {"5000", "5002", "5003", "6000", "6002", "6003"}


def _is_numeric_token(token: str) -> bool:
    """Return True if token can be parsed as an int or float."""
    try:
        float(token)
    except ValueError:
        return False
    return True


def _siemens_payload(tokens: list[str]) -> list[int] | None:
    """Return PMU waveform integers while excluding information regions."""
    try:
        first_info = tokens.index("5002")
    except ValueError:
        return None

    values: list[int] = []
    in_info = False
    for token in tokens[first_info:]:
        if token == "5003":
            break
        if token == "5002":
            in_info = True
            continue
        if token == "6002":
            in_info = False
            continue
        if in_info or token in _PMU_CONTROL_CODES:
            continue
        try:
            values.append(int(token))
        except ValueError:
            continue
    return values


def load_ecg_channels(path: Path) -> list[tuple[str, np.ndarray]]:
    """Load and demultiplex ECG channels without modifying the source."""
    text = path.read_text(encoding="utf-8", errors="replace")
    tokens = text.split()
    payload = _siemens_payload(tokens)

    if payload is not None:
        channels: list[tuple[str, np.ndarray]] = []
        for name, low, high, baseline in _SIEMENS_CHANNELS:
            values = [value - baseline for value in payload if low <= value <= high]
            if values:
                channels.append((name, np.asarray(values, dtype=np.float64)))
        return channels

    # Generic text fallback: ignore complete non-numeric metadata lines.
    values: list[float] = []
    for line in text.splitlines():
        fields = line.split()
        if not fields or not all(_is_numeric_token(field) for field in fields):
            continue
        values.extend(float(field) for field in fields)
    if not values:
        return []
    return [("Raw ECG", np.asarray(values, dtype=np.float64))]


def print_summary(
    path: Path, channels: list[tuple[str, np.ndarray]], preview_n: int = 10
) -> bool:
    """Print per-channel statistics and return whether any channel varies."""
    print(f"file path: {path.resolve()}")
    print(f"number of channels loaded: {len(channels)}")
    has_variation = False
    for name, samples in channels:
        std = float(np.std(samples))
        has_variation = has_variation or std > 0
        preview = samples[:preview_n]
        print(f"\n{name}:")
        print(f"  number of samples loaded: {samples.size}")
        print(f"  first {preview.size} values: {preview.tolist()}")
        print(f"  min:  {float(np.min(samples)):.6g}")
        print(f"  max:  {float(np.max(samples)):.6g}")
        print(f"  mean: {float(np.mean(samples)):.6g}")
        print(f"  std:  {std:.6g}")
    print("note: x-axis is sample index (SamplingFrequency not assumed).")
    if not has_variation:
        print(
            "warning: all decoded ECG channels are flat. This recording does "
            "not contain an exploitable ECG waveform."
        )
    return has_variation


def plot_ecg(
    path: Path,
    channels: list[tuple[str, np.ndarray]],
    output: Path | None = None,
) -> None:
    """Plot each decoded ECG channel against its sample index."""
    fig, axes = plt.subplots(
        len(channels), 1, figsize=(13, max(4, 2.5 * len(channels))), squeeze=False
    )
    for ax, (name, samples) in zip(axes[:, 0], channels):
        ax.plot(np.arange(samples.size), samples, linewidth=0.7, color="#1f4e79")
        ax.set_ylabel(f"{name}\nraw amplitude")
        ax.grid(True, alpha=0.3)
    axes[-1, 0].set_xlabel("Sample index")
    fig.suptitle(f"Decoded Siemens ECG: {path.name}")
    fig.tight_layout()
    if output is None:
        plt.show()
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=160)
        print(f"plot saved to: {output.resolve()}")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only visualization of one raw MRI physiology ECG file."
    )
    parser.add_argument(
        "ecg_file",
        type=Path,
        help="Path to a single .ecg file (must exist; never modified).",
    )
    parser.add_argument(
        "--save",
        type=Path,
        metavar="OUTPUT.png",
        help="Save the plot to a PNG instead of opening an interactive window.",
    )
    args = parser.parse_args(argv)
    path: Path = args.ecg_file

    if not path.exists():
        print(f"error: file does not exist: {path}", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"error: path is not a file: {path}", file=sys.stderr)
        return 1

    try:
        channels = load_ecg_channels(path)
    except OSError as exc:
        print(f"error: could not read file: {path}\n{exc}", file=sys.stderr)
        return 1

    if not channels:
        print(f"file path: {path.resolve()}")
        print("number of samples loaded: 0")
        print(
            "No numeric waveform values were found.\n"
            "This file likely requires Siemens physiology parsing "
            "(ASCII PMU control stream or binary .pmu format) before "
            "ECG samples can be visualized."
        )
        return 2

    print_summary(path, channels)
    plot_ecg(path, channels, args.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
