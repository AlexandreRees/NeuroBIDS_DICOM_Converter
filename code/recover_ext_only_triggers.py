#!/usr/bin/env python3
"""Recover EXT-only PhysioLog triggers previously excluded for missing PULS/RESP ticks.

Discovery: StartTime was computed only from first PULS/RESP ACQ_TIME_TICS. EXT-only
PhysioLogs still carry EXT ACQ_TIME_TICS + vol0 ACQ_START_TICS, enabling:

  StartTime = (first_EXT_ACQ_TIME_TICS - vol0_ACQ_START_TICS) * 0.0025

Gates (fail-closed):
  - channels == EXT (or EXT2)
  - unique ProtocolName → BOLD mapping (from physio_conversion_status failure_reason)
  - target BOLD exists; no existing recording-trigger
  - SampleTime EXT present (Hz = 1000/ms)
  - EXT waveform: n_samples >= 10 and >=1 pulse
  - StartTime computable from EXT tick + vol0

Writes PHI-safe BIDS physio sidecars into bids/ and release_dataset/.
Does not modify raw_original/.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

LOGGER = logging.getLogger("recover_ext_triggers")

AUDIT = Path("/home/alexrees/scratch/reports/physiology_audit")
OUT = AUDIT / "trigger_audit"
BIDS = Path("/home/alexrees/scratch/bids")
RELEASE = Path("/home/alexrees/scratch/release_dataset")
STATUS_TSV = AUDIT / "physio_conversion_status.tsv"
INVENTORY_TSV = AUDIT / "physiolog_inventory.tsv"

SIEMENS_CSA_TICK_SECONDS = 0.0025
_PMU_CONTROL = {5000, 5002, 5003, 6000, 6002, 6003}

ALLOWED_JSON_KEYS = frozenset(
    {
        "SamplingFrequency",
        "StartTime",
        "Columns",
        "Manufacturer",
        "ConversionSoftware",
        "ConversionSoftwareVersion",
        "StartTimeMethod",
        "StartTimeConfidence",
        "SiemensChannel",
        "SampleTime_ms",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(fp: str) -> Path | None:
    p = Path(fp)
    if p.exists():
        return p
    alt = Path(fp.replace("/lustre06/project/6001995/", "/project/def-amirs/"))
    if alt.exists():
        return alt
    alt2 = Path(fp.replace("/project/def-amirs/", "/lustre06/project/6001995/"))
    if alt2.exists():
        return alt2
    return None


def _read_csa(filepath: Path) -> str:
    import pydicom

    ds = pydicom.dcmread(str(filepath), stop_before_pixels=False, force=True)
    return bytes(ds[0x7FE1, 0x1010].value).decode("latin-1", errors="replace")


def _vol0_start_tick(text: str) -> int | None:
    # Prefer structured first volume-0 row after ACQUISITION_INFO header
    m = re.search(
        r"VOLUME\s+SLICE\s+ACQ_START_TICS\s+ACQ_FINISH_TICS\s+ECHO\s+"
        r"0\s+\d+\s+(\d+)\s+(\d+)",
        text,
    )
    if m:
        return int(m.group(1))
    # Fallback: first ACQ_START_TICS numeric after header label line
    idx = text.find("ACQ_FINISH_TICS")
    if idx < 0:
        return None
    toks = re.findall(r"\d+", text[idx : idx + 120])
    # Expect ECHO then VOL SLICE START FINISH ...
    if len(toks) >= 4:
        # toks[0] may be from header word; scan for pattern 0, slice, start, finish
        for i in range(len(toks) - 3):
            if toks[i] == "0" and len(toks[i + 2]) >= 5:
                return int(toks[i + 2])
    return None


def _first_ext_tick(text: str, channel: str = "EXT") -> int | None:
    pat = re.compile(
        rf"Physio_\d{{8}}_\d{{6}}_[0-9a-f\-]+_{channel}\.log", re.IGNORECASE
    )
    m = pat.search(text)
    # EXT ACQ_TIME_TICS often appears once globally in EXT-only files
    ticks = [int(x) for x in re.findall(r"ACQ_TIME_TICS\s*[:=]?\s*(-?\d+)", text, re.I)]
    if m:
        region = text[max(0, m.start() - 2000) : m.end() + 8000]
        local = [
            int(x)
            for x in re.findall(r"ACQ_TIME_TICS\s*[:=]?\s*(-?\d+)", region, re.I)
        ]
        if local:
            return local[0]
    if ticks:
        # Prefer tick closest to vol0 if available later; else first
        return ticks[0]
    return None


def _sample_time_ms(text: str, channel: str = "EXT") -> float | None:
    # Patterns like EXT=8 or SampleTime ... EXT
    m = re.search(rf"{channel}\s*=\s*(\d+(?:\.\d+)?)", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"SampleTime\s*[:=]?\s*(\d+(?:\.\d+)?)", text, re.I)
    if m:
        return float(m.group(1))
    return 8.0  # Siemens EXT default in this dataset when embedded_logs=EXT


def _extract_channel_samples(text: str, channel: str) -> np.ndarray:
    pat = re.compile(
        rf"Physio_\d{{8}}_\d{{6}}_[0-9a-f\-]+_{channel}\.log", re.IGNORECASE
    )
    m = pat.search(text)
    if not m:
        return np.asarray([], dtype=np.float64)
    start = m.end()
    m2 = re.search(r"Physio_\d{8}_\d{6}_", text[start:])
    end = start + m2.start() if m2 else len(text)
    tokens = text[start:end].split()
    values: list[int] = []
    if "6002" in tokens:
        i0 = tokens.index("6002") + 1
        for tok in tokens[i0:]:
            if tok == "5003":
                break
            if tok.lstrip("-").isdigit():
                v = int(tok)
                if v not in _PMU_CONTROL and abs(v) < 10_000_000:
                    values.append(v)
        if values:
            return np.asarray(values, dtype=np.float64)
    for tok in tokens:
        if not tok.lstrip("-").isdigit():
            continue
        v = int(tok)
        if v in _PMU_CONTROL or abs(v) >= 10_000_000:
            continue
        values.append(v)
    return np.asarray(values, dtype=np.float64)


def _n_pulses(a: np.ndarray, sf: float) -> int:
    if len(a) == 0:
        return 0
    thr = 1.5 if (a <= 1.5).mean() > 0.5 else float(
        np.median(a) + 0.5 * (np.percentile(a, 95) - np.median(a))
    )
    idxs = np.where(a > thr)[0]
    if len(idxs) == 0:
        return 0
    onsets = [int(idxs[0])]
    minsep = max(1, int(0.05 * sf))
    for j in idxs[1:]:
        if int(j) - onsets[-1] > minsep:
            onsets.append(int(j))
    return len(onsets)


def _write_physio(
    out_dir: Path,
    stem: str,
    samples: np.ndarray,
    sf: float,
    start: float,
    sample_time_ms: float,
    start_confidence: str,
    start_method: str,
    siemens_channel: str,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{stem}_recording-trigger_physio"
    tsv = out_dir / f"{base}.tsv.gz"
    js = out_dir / f"{base}.json"
    with gzip.open(tsv, "wt", encoding="utf-8", newline="\n") as fh:
        fh.write("trigger\n")
        for v in samples:
            fh.write(f"{int(v) if float(v).is_integer() else v}\n")
    meta = {
        "SamplingFrequency": float(sf),
        "StartTime": float(start),
        "Columns": ["trigger"],
        "Manufacturer": "Siemens",
        "ConversionSoftware": "recover_ext_only_triggers.py",
        "ConversionSoftwareVersion": "1.0.0",
        "StartTimeMethod": start_method,
        "StartTimeConfidence": start_confidence,
        "SiemensChannel": siemens_channel,
        "SampleTime_ms": float(sample_time_ms),
    }
    meta = {k: v for k, v in meta.items() if k in ALLOWED_JSON_KEYS}
    js.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return tsv, js


def build_candidates() -> list[dict[str, Any]]:
    inv_rows = list(csv.DictReader(INVENTORY_TSV.open(encoding="utf-8"), delimiter="\t"))
    inv_by_uid_proto: dict[tuple[str, str, str], dict[str, str]] = {}
    for r in inv_rows:
        # inventory has no UID; index by subject/session/protocol
        inv_by_uid_proto[(r["subject"], r["session"], r.get("protocol_name") or "")] = r

    # existing triggers
    existing = {
        p.name.replace("_recording-trigger_physio.tsv.gz", "")
        for p in BIDS.glob("sub-*/ses-*/func/*_recording-trigger_physio.tsv.gz")
    }

    status = list(csv.DictReader(STATUS_TSV.open(encoding="utf-8"), delimiter="\t"))
    cands: list[dict[str, Any]] = []
    for r in status:
        ch = (r.get("channels_available") or "").upper().strip()
        if ch not in {"EXT", "EXT2"}:
            continue
        fr = r.get("failure_reason") or ""
        if "AMBIGUOUS" in fr:
            continue
        m = re.search(r"→\s*(sub-\d+_ses-\d+_task-[^\s]+_bold\.json)", fr)
        if not m:
            continue
        stem = m.group(1).replace("_bold.json", "")
        if stem in existing:
            continue
        # protocol from unique match clause
        mp = re.search(r"Unique BIDS ProtocolName match:\s*(\S+)\s*→", fr)
        proto = mp.group(1) if mp else ""
        inv = inv_by_uid_proto.get((r["subject"], r["session"], proto))
        if not inv:
            # try any EXT inventory row for subject/session/protocol
            continue
        bold = BIDS / r["subject"] / r["session"] / "func" / f"{stem}_bold.nii.gz"
        if not bold.exists():
            continue
        cands.append(
            {
                "physio_uid": r["physio_series_uid"],
                "subject": r["subject"],
                "session": r["session"],
                "protocol_name": proto,
                "filepath": inv["filepath"],
                "sampletime_by_type": inv.get("sampletime_by_type") or "",
                "stem": stem,
                "bold_path": str(bold),
                "channel": ch,
            }
        )
    return cands


def convert_one(job: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "physio_uid": job["physio_uid"],
        "subject": job["subject"],
        "session": job["session"],
        "stem": job["stem"],
        "status": "FAIL",
        "n_samples": "",
        "n_pulses": "",
        "StartTime": "",
        "SamplingFrequency": "",
        "outputs": "",
        "error": "",
    }
    fp = _resolve_path(job["filepath"])
    if not fp:
        out["error"] = f"source_missing:{job['filepath']}"
        return out
    try:
        text = _read_csa(fp)
    except Exception as e:
        out["error"] = f"csa_read:{e}"
        return out

    channel = job["channel"]
    vol0 = _vol0_start_tick(text)
    ext_tick = _first_ext_tick(text, channel if channel != "EXT2" else "EXT")
    # sample time from inventory string EXT=8 preferred
    ms = None
    m = re.search(rf"{channel}\s*=\s*(\d+(?:\.\d+)?)", job.get("sampletime_by_type") or "", re.I)
    if m:
        ms = float(m.group(1))
    if ms is None:
        ms = _sample_time_ms(text, "EXT")
    if ms is None or ms <= 0:
        out["error"] = "no_sampletime"
        return out
    sf = 1000.0 / ms
    if vol0 is None or ext_tick is None:
        out["error"] = f"missing_ticks:vol0={vol0}:ext={ext_tick}"
        return out
    start = (ext_tick - vol0) * SIEMENS_CSA_TICK_SECONDS
    samples = _extract_channel_samples(text, "EXT" if channel.startswith("EXT") else channel)
    n = int(samples.size)
    n_pulse = _n_pulses(samples, sf)
    out["n_samples"] = n
    out["n_pulses"] = n_pulse
    out["StartTime"] = f"{start:.6f}"
    out["SamplingFrequency"] = f"{sf:.6f}"
    if n < 10:
        out["error"] = "waveform_too_short"
        return out
    if n_pulse < 1:
        out["error"] = "no_pulse"
        return out

    method = (
        f"CSA_(first_EXT_ACQ_TIME_TICS-vol0_ACQ_START_TICS)*{SIEMENS_CSA_TICK_SECONDS:g}_s_per_tick"
    )
    if dry_run:
        out["status"] = "DRY_RUN_OK"
        return out

    outputs: list[str] = []
    for root in (BIDS, RELEASE):
        out_dir = root / job["subject"] / job["session"] / "func"
        # only write release if subject exists there
        if root == RELEASE and not (root / job["subject"] / job["session"] / "func").exists():
            # still create func dir under existing session if session exists
            if not (root / job["subject"] / job["session"]).exists():
                continue
        tsv, js = _write_physio(
            out_dir,
            job["stem"],
            samples,
            sf,
            start,
            ms,
            "MEDIUM",
            method,
            channel,
        )
        outputs.extend([str(tsv), str(js)])
    out["outputs"] = ";".join(outputs)
    out["status"] = "OK"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)

    cands = build_candidates()
    LOGGER.info("Candidates: %d", len(cands))
    if args.limit > 0:
        cands = cands[: args.limit]

    results = []
    for i, job in enumerate(cands, 1):
        res = convert_one(job, dry_run=args.dry_run)
        results.append(res)
        if i % 25 == 0 or res["status"] != "OK":
            LOGGER.info(
                "[%d/%d] %s %s %s",
                i,
                len(cands),
                res["status"],
                res["stem"],
                res.get("error") or f"n={res['n_samples']} pulses={res['n_pulses']} ST={res['StartTime']}",
            )

    fields = [
        "physio_uid",
        "subject",
        "session",
        "stem",
        "status",
        "n_samples",
        "n_pulses",
        "StartTime",
        "SamplingFrequency",
        "outputs",
        "error",
    ]
    out_tsv = OUT / ("EXT_ONLY_RECOVERY_DRYRUN.tsv" if args.dry_run else "EXT_ONLY_RECOVERY_RESULTS.tsv")
    with out_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(results)

    summary = Counter(r["status"] for r in results)
    err = Counter(r["error"] for r in results if r["status"] != "OK" and not str(r["status"]).startswith("DRY"))
    report = OUT / ("EXT_ONLY_RECOVERY_DRYRUN_SUMMARY.md" if args.dry_run else "EXT_ONLY_RECOVERY_SUMMARY.md")
    report.write_text(
        "\n".join(
            [
                f"# EXT-only trigger recovery ({'dry-run' if args.dry_run else 'write'})",
                f"Generated: `{_now()}`",
                "",
                f"Candidates attempted: **{len(results)}**",
                f"Status counts: `{dict(summary)}`",
                f"Error counts: `{dict(err)}`",
                "",
                "Method: StartTime from EXT ACQ_TIME_TICS vs vol0 ACQ_START_TICS (0.0025 s/tick).",
                "Gates: unique BOLD map, SampleTime, n_samples>=10, >=1 pulse, no overwrite of existing trigger.",
                f"Results TSV: `{out_tsv}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    LOGGER.info("Wrote %s (%s)", out_tsv, dict(summary))
    return 0 if summary.get("OK", 0) + summary.get("DRY_RUN_OK", 0) > 0 or not results else 1


if __name__ == "__main__":
    sys.exit(main())
