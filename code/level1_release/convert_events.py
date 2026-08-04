#!/usr/bin/env python3
"""Strict MATLAB-to-BIDS events conversion for the Level-1 release.

No fallback TR, synthesized paradigm, or inferred run identity is permitted.
Only runs with mutually consistent scan_info, fMRI_N, and runs_random sources
are convertible.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


FMRI_RE = re.compile(r"(?i)fmri(?:_number_is|_)(\d+)")
SELECTED_RUN_RE = re.compile(r"(?i)selected_run_is_(\d+)")


@dataclass(frozen=True)
class StrictEventResult:
    status: str
    reason: str
    events: tuple[tuple[float, float, str], ...] = ()
    fmri_number: int | None = None
    selected_run: int | None = None


def _loadmat(path: Path, variable_names: list[str] | None = None) -> dict[str, Any]:
    import scipy.io as sio

    with path.open("rb") as handle:
        header = handle.read(128)
    if header.startswith(b"MATLAB 7.3"):
        raise ValueError("MATLAB 7.3 timing source requires manual converter validation")
    return sio.loadmat(
        str(path),
        variable_names=variable_names,
        squeeze_me=True,
        struct_as_record=False,
    )


def fmri_number(path: Path) -> int | None:
    match = FMRI_RE.search(path.stem) or FMRI_RE.search(path.name)
    return int(match.group(1)) if match else None


def selected_run(path: Path) -> int | None:
    match = SELECTED_RUN_RE.search(path.name)
    return int(match.group(1)) if match else None


def _scalar_int(value: Any) -> int:
    array = np.asarray(value).ravel()
    if array.size != 1 or not np.isfinite(float(array[0])):
        raise ValueError("expected one finite scalar integer")
    number = float(array[0])
    if not number.is_integer():
        raise ValueError(f"expected integer scalar, got {number}")
    return int(number)


def _stim_order(path: Path) -> np.ndarray:
    data = _loadmat(path, ["Stim_order_selected"])
    if "Stim_order_selected" not in data:
        raise ValueError("Stim_order_selected missing")
    order = np.asarray(data["Stim_order_selected"], dtype=float).ravel()
    if order.size == 0 or not np.all(np.isfinite(order)):
        raise ValueError("Stim_order_selected is empty/non-finite")
    if not np.all(order == np.round(order)):
        raise ValueError("Stim_order_selected contains non-integer values")
    return order.astype(int)


def _scan_triggers(path: Path) -> np.ndarray:
    data = _loadmat(path, ["scan", "triggerTimes"])
    triggers: Any = None
    if "scan" in data:
        runs = getattr(data["scan"], "runs", None)
        triggers = getattr(runs, "triggerTimes", None) if runs is not None else None
    if triggers is None and "triggerTimes" in data:
        triggers = data["triggerTimes"]
    if triggers is None:
        raise ValueError("actual scanner triggerTimes missing (VBL fallback prohibited)")
    array = np.asarray(triggers, dtype=float).ravel()
    array = array[np.isfinite(array)]
    if array.size < 2:
        raise ValueError("fewer than two finite scanner triggerTimes")
    if np.any(np.diff(array) <= 0):
        raise ValueError("scanner triggerTimes are not strictly increasing")
    return array


def _workspace(path: Path) -> tuple[int, int, np.ndarray, np.ndarray]:
    data = _loadmat(
        path,
        [
            "fMRI_number",
            "run_number",
            "runParadigmFinal",
            "paradigm",
            "Stim_order_selected",
        ],
    )
    if "fMRI_number" not in data or "run_number" not in data:
        raise ValueError("runs_random lacks explicit fMRI_number/run_number")
    number = _scalar_int(data["fMRI_number"])
    run = _scalar_int(data["run_number"])
    if "runParadigmFinal" in data:
        paradigm = np.asarray(data["runParadigmFinal"], dtype=float)
    elif "paradigm" in data:
        paradigm = np.asarray(data["paradigm"], dtype=float)
    else:
        raise ValueError("runs_random lacks recorded paradigm")
    if paradigm.ndim != 2 or paradigm.shape[1] < 2 or paradigm.shape[0] < 2:
        raise ValueError(f"invalid recorded paradigm shape {paradigm.shape}")
    if not np.all(np.isfinite(paradigm[:, :2])):
        raise ValueError("recorded paradigm contains non-finite values")
    if "Stim_order_selected" not in data:
        raise ValueError("runs_random lacks Stim_order_selected")
    order = np.asarray(data["Stim_order_selected"], dtype=float).ravel()
    if not np.all(np.isfinite(order)) or not np.all(order == np.round(order)):
        raise ValueError("runs_random Stim_order_selected is invalid")
    return number, run, paradigm[:, :2], order.astype(int)


def build_strict_events(
    *,
    scan_info: Path,
    stim_order: Path,
    runs_random: Path,
) -> StrictEventResult:
    try:
        scan_number = fmri_number(scan_info)
        stim_number = fmri_number(stim_order)
        chosen_run = selected_run(scan_info)
        if scan_number is None or stim_number is None or chosen_run is None:
            raise ValueError("run identity missing from source filenames")
        if scan_number != stim_number:
            raise ValueError(
                f"scan/stim fMRI_number mismatch ({scan_number} != {stim_number})"
            )
        triggers = _scan_triggers(scan_info)
        order = _stim_order(stim_order)
        workspace_number, workspace_run, paradigm, workspace_order = _workspace(
            runs_random
        )
        if workspace_number != scan_number:
            raise ValueError(
                f"runs_random belongs to fMRI {workspace_number}, not {scan_number}"
            )
        if workspace_run != chosen_run:
            raise ValueError(
                f"runs_random run_number {workspace_run} != selected_run {chosen_run}"
            )
        if not np.array_equal(order, workspace_order):
            raise ValueError("stimulus order differs between fMRI_N and runs_random")

        indices = paradigm[:, 0]
        if not np.all(indices == np.round(indices)):
            raise ValueError("paradigm time axis is not integer scanner-volume indices")
        indices = indices.astype(int)
        if np.any(indices < 0) or np.any(indices > triggers.size):
            raise ValueError(
                f"paradigm index outside trigger/terminal range 0..{triggers.size}"
            )
        if np.any(np.diff(indices) <= 0):
            raise ValueError("paradigm indices are not strictly increasing")

        relative = triggers - triggers[0]
        endpoint_note = ""
        if np.any(indices == triggers.size):
            intervals = np.diff(triggers)
            measured_tr = float(np.median(intervals))
            if measured_tr <= 0 or float(np.max(np.abs(intervals - measured_tr))) > (
                0.01 * measured_tr
            ):
                raise ValueError(
                    "terminal paradigm boundary needs extrapolation but measured TR is unstable"
                )
            relative = np.concatenate(
                [relative, [float(relative[-1] + measured_tr)]]
            )
            endpoint_note = (
                "; terminal boundary derived as final trigger + measured median TR"
            )
        events: list[tuple[float, float, str]] = []
        stim_index = 0
        for index in range(paradigm.shape[0] - 1):
            condition = int(round(float(paradigm[index, 1])))
            if condition == 2:
                continue
            onset = float(relative[indices[index]])
            end = float(relative[indices[index + 1]])
            duration = end - onset
            if onset < 0 or duration <= 0:
                raise ValueError("non-positive event duration or negative onset")
            if condition == 0:
                trial_type = "baseline"
            elif condition == 1:
                if stim_index >= order.size:
                    raise ValueError("paradigm has more stimulus blocks than stim order")
                trial_type = f"stim-{int(order[stim_index]):02d}"
                stim_index += 1
            else:
                raise ValueError(f"unsupported paradigm condition {condition}")
            events.append((onset, duration, trial_type))
        if stim_index != order.size:
            raise ValueError(
                f"used {stim_index} stimulus labels but order contains {order.size}"
            )
        return StrictEventResult(
            status="ready",
            reason=(
                "actual triggerTimes + recorded paradigm + matching stimulus order; "
                f"no default TR or synthesized timing{endpoint_note}"
            ),
            events=tuple(events),
            fmri_number=scan_number,
            selected_run=chosen_run,
        )
    except Exception as exc:  # noqa: BLE001 - dry run records all review reasons
        return StrictEventResult(status="requires_manual_review", reason=str(exc))


def write_events(path: Path, result: StrictEventResult) -> None:
    if result.status != "ready":
        raise ValueError(f"refusing non-ready events conversion: {result.reason}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["onset", "duration", "trial_type"])
        for onset, duration, trial_type in result.events:
            writer.writerow(
                [format(onset, ".9f"), format(duration, ".9f"), trial_type]
            )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Strict MATLAB events conversion.")
    parser.add_argument("--scan-info", required=True, type=Path)
    parser.add_argument("--stim-order", required=True, type=Path)
    parser.add_argument("--runs-random", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    outcome = build_strict_events(
        scan_info=args.scan_info,
        stim_order=args.stim_order,
        runs_random=args.runs_random,
    )
    print(f"{outcome.status}: {outcome.reason}")
    if args.output and outcome.status == "ready":
        write_events(args.output, outcome)
    raise SystemExit(0 if outcome.status == "ready" else 2)
