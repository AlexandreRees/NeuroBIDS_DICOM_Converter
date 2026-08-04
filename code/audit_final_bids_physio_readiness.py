#!/usr/bin/env python3
"""Final BIDS physiology readiness audit (read-only).

Uses existing forensic inventories under reports/physiology_audit/.
Never modifies raw_original/, bids/, derivatives/, or release_dataset/.
Never writes *_physio.tsv.gz.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

LOGGER = logging.getLogger("final_physio_readiness")
NA = "NA"

DEFAULT_AUDIT = Path("/home/alexrees/scratch/reports/physiology_audit")
DEFAULT_OUT = DEFAULT_AUDIT / "final_bids_physio_readiness"
DEFAULT_BIDS = Path("/lustre07/scratch/alexrees/bids")

# Siemens CSA ACQ_TIME_TICS / ACQ_START_TICS commonly use 2.5 ms units.
# Documented as MEDIUM confidence (standard Siemens convention, not re-validated
# against an external clock in this dataset).
SIEMENS_CSA_TICK_SECONDS = 0.0025

_RE_CSA_META = re.compile(
    r"UUID\s*=\s*(?P<uuid>\S+)\s*ScanDate\s*=\s*(?P<scandate>\S+)\s*"
    r"LogVersion\s*=\s*(?P<logversion>\S+)\s*LogDataType\s*=\s*(?P<datatype>\w+)\s*"
    r"SampleTime\s*=\s*(?P<sampletime>\d+)",
    re.IGNORECASE,
)
_RE_EMBED = re.compile(
    r"Physio_\d{8}_\d{6}_[0-9a-f\-]+_(ECG|PULS|RESP|EXT|EXT2)\.log",
    re.IGNORECASE,
)
_RE_VOL0 = re.compile(r"^\s*0\s+\d+\s+(\d+)\s+(\d+)\s+\d+\s*$", re.MULTILINE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def _load_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _style(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


# ---------------------------------------------------------------------------
# Join status ↔ deep via SeriesInstanceUID
# ---------------------------------------------------------------------------
def _series_uid(path_str: str) -> tuple[str, str]:
    try:
        import pydicom

        ds = pydicom.dcmread(path_str, stop_before_pixels=True, force=True)
        uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
        return path_str, uid or NA
    except Exception as exc:  # noqa: BLE001
        return path_str, f"NA:{type(exc).__name__}"


def build_joined_table(
    status_rows: list[dict[str, str]],
    deep_rows: list[dict[str, str]],
    workers: int,
) -> list[dict[str, str]]:
    """Attach deep CSA metadata to each conversion-status row via Series UID."""
    # Unique series dirs from deep
    dir_to_fp: dict[str, str] = {}
    for r in deep_rows:
        d = str(Path(r["filepath"]).parent)
        dir_to_fp.setdefault(d, r["filepath"])

    LOGGER.info("Resolving SeriesInstanceUID for %d PhysioLog series", len(dir_to_fp))
    uid_by_fp: dict[str, str] = {}
    fps = list(dir_to_fp.values())
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_series_uid, fp) for fp in fps]
        done = 0
        for fut in as_completed(futs):
            fp, uid = fut.result()
            uid_by_fp[fp] = uid
            done += 1
            if done % 200 == 0:
                LOGGER.info("UID resolve %d / %d", done, len(fps))

    uid_to_deep: dict[str, dict[str, str]] = {}
    for r in deep_rows:
        d = str(Path(r["filepath"]).parent)
        fp = dir_to_fp[d]
        uid = uid_by_fp.get(fp, NA)
        if uid.startswith("NA"):
            continue
        # Prefer row matching this filepath; else first for series
        if uid not in uid_to_deep or r["filepath"] == fp:
            uid_to_deep[uid] = r

    LOGGER.info("UID index size: %d", len(uid_to_deep))
    joined: list[dict[str, str]] = []
    missing = 0
    for s in status_rows:
        uid = s["physio_series_uid"]
        deep = uid_to_deep.get(uid)
        if deep is None:
            missing += 1
            deep = {}
        row = {**s, **{f"deep_{k}": v for k, v in deep.items()}}
        row["filepath"] = deep.get("filepath", NA)
        row["protocol_name"] = deep.get("protocol_name", NA)
        row["sampletime_by_type"] = deep.get("sampletime_by_type", NA)
        row["vol0_acq_start_tics"] = deep.get("vol0_acq_start_tics", NA)
        row["first_puls_tick"] = deep.get("first_puls_tick", NA)
        row["first_resp_tick"] = deep.get("first_resp_tick", NA)
        row["has_acquisition_info"] = deep.get("has_acquisition_info", NA)
        row["num_volumes"] = deep.get("num_volumes", NA)
        row["embedded_logs"] = deep.get("embedded_logs", s.get("channels_available", NA))
        joined.append(row)
    LOGGER.info("Joined status→deep: %d rows, missing UID match=%d", len(joined), missing)
    return joined


# ---------------------------------------------------------------------------
# Validations
# ---------------------------------------------------------------------------
def validate_sampling(joined: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for r in joined:
        if r["conversion_status"] != "READY":
            continue
        uid = r["physio_series_uid"]
        stmap = r.get("sampletime_by_type") or ""
        # Also parse from sampling_frequency field as cross-check (already Hz)
        if not stmap or stmap in (NA, "") or "=" not in stmap:
            rows.append(
                {
                    "physio_uid": uid,
                    "subject": r["subject"],
                    "session": r["session"],
                    "channel": NA,
                    "sample_time_ms": NA,
                    "sampling_frequency_hz": NA,
                    "source": "missing_SampleTime",
                    "status": "FAIL",
                }
            )
            continue
        for part in stmap.split(";"):
            if "=" not in part:
                continue
            ch, ms_s = part.split("=", 1)
            ch = ch.strip().upper()
            try:
                ms = float(ms_s)
            except ValueError:
                rows.append(
                    {
                        "physio_uid": uid,
                        "subject": r["subject"],
                        "session": r["session"],
                        "channel": ch,
                        "sample_time_ms": ms_s,
                        "sampling_frequency_hz": NA,
                        "source": "unparseable_SampleTime",
                        "status": "FAIL",
                    }
                )
                continue
            if ms <= 0:
                status = "FAIL"
                hz = NA
                source = "nonpositive_SampleTime"
            else:
                hz_f = 1000.0 / ms
                # Reject classic undocumented defaults presented without SampleTime
                # (we have SampleTime, so OK). Still reject if somehow Freq-Per-like.
                hz = f"{hz_f:.6g}"
                source = "Siemens_CSA_SampleTime_ms"
                status = "PASS"
            rows.append(
                {
                    "physio_uid": uid,
                    "subject": r["subject"],
                    "session": r["session"],
                    "channel": ch,
                    "sample_time_ms": str(ms_s),
                    "sampling_frequency_hz": hz,
                    "source": source,
                    "status": status,
                }
            )
    return rows


def validate_starttime(joined: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for r in joined:
        if r["conversion_status"] != "READY":
            continue
        uid = r["physio_series_uid"]
        bold = r.get("matched_bold") or NA
        vol0 = r.get("vol0_acq_start_tics") or NA
        tick = NA
        chan = NA
        for key, label in (
            ("first_puls_tick", "PULS"),
            ("first_resp_tick", "RESP"),
        ):
            if r.get(key) not in (None, "", NA):
                tick = r[key]
                chan = label
                break
        if (
            r.get("has_acquisition_info") == "true"
            and vol0 not in (NA, "")
            and tick not in (NA, "")
            and r.get("start_time_available") == "yes"
        ):
            try:
                start = (int(tick) - int(vol0)) * SIEMENS_CSA_TICK_SECONDS
                rows.append(
                    {
                        "physio_uid": uid,
                        "BIDS_run": bold,
                        "StartTime": f"{start:.6f}",
                        "method": (
                            f"CSA_(first_{chan}_ACQ_TIME_TICS - vol0_ACQ_START_TICS)"
                            f"*{SIEMENS_CSA_TICK_SECONDS:g}_s_per_tick"
                        ),
                        "confidence": "MEDIUM",
                        "status": "PASS",
                    }
                )
            except ValueError:
                rows.append(
                    {
                        "physio_uid": uid,
                        "BIDS_run": bold,
                        "StartTime": NA,
                        "method": "tick_parse_error",
                        "confidence": "NONE",
                        "status": "FAIL",
                    }
                )
        else:
            rows.append(
                {
                    "physio_uid": uid,
                    "BIDS_run": bold,
                    "StartTime": NA,
                    "method": "insufficient_CSA_ticks_or_not_marked_available",
                    "confidence": "NONE",
                    "status": "FAIL",
                }
            )
    return rows


def validate_run_mapping(joined: list[dict[str, str]], bids_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for r in joined:
        if r["conversion_status"] != "READY":
            continue
        uid = r["physio_series_uid"]
        bold_stem = r.get("matched_bold") or NA
        proto = r.get("protocol_name") or NA
        status = "FAIL"
        conf = "NONE"
        cand = 0
        bold_file = NA
        reason_ok = True

        if bold_stem in (NA, "") or bold_stem.startswith("AMBIGUOUS"):
            reason_ok = False
            if bold_stem.startswith("AMBIGUOUS"):
                cand = bold_stem.count(",") + 1
                conf = "AMBIGUOUS"
            else:
                conf = "MISSING"
        else:
            # Verify file exists and is unique stem
            bold_file = str(
                bids_root / r["subject"] / r["session"] / "func" / f"{bold_stem}_bold.nii.gz"
            )
            if Path(bold_file).is_file():
                cand = 1
                conf = "CONFIRMED"
                status = "PASS"
            else:
                # try without forcing path
                matches = list(
                    (bids_root / r["subject"] / r["session"] / "func").glob(
                        f"{bold_stem}_bold.nii.gz"
                    )
                ) if (bids_root / r["subject"] / r["session"] / "func").is_dir() else []
                cand = len(matches)
                if cand == 1:
                    bold_file = str(matches[0])
                    conf = "CONFIRMED"
                    status = "PASS"
                elif cand > 1:
                    conf = "AMBIGUOUS"
                else:
                    conf = "MISSING"
                    bold_file = f"{bold_stem}_bold.nii.gz"

        # Subject/session embedded in stem
        if status == "PASS":
            if not bold_stem.startswith(f"{r['subject']}_{r['session']}_"):
                status = "FAIL"
                conf = "SUBJECT_SESSION_MISMATCH"

        rows.append(
            {
                "physio_uid": uid,
                "BIDS_bold_file": bold_file,
                "protocol_name": proto,
                "candidate_count": str(cand),
                "mapping_confidence": conf,
                "status": status,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Waveform quality (read-only CSA parse)
# ---------------------------------------------------------------------------
def _extract_channel_samples(text: str, channel: str, max_n: int = 200_000) -> np.ndarray:
    pat = re.compile(
        rf"Physio_\d{{8}}_\d{{6}}_[0-9a-f\-]+_{channel}\.log", re.IGNORECASE
    )
    m = pat.search(text)
    if not m:
        return np.asarray([], dtype=np.float64)
    # Region until next Physio_ header or end
    start = m.end()
    m2 = re.search(r"Physio_\d{8}_\d{6}_", text[start:])
    end = start + m2.start() if m2 else min(len(text), start + 5_000_000)
    region = text[start:end]
    # Skip metadata lines; collect integers that look like samples
    vals: list[int] = []
    for line in region.splitlines():
        line = line.strip()
        if not line or "=" in line or line.upper().startswith("UUID"):
            continue
        if line.upper().startswith("LOG") or line.upper().startswith("SAMPLE"):
            continue
        parts = line.split()
        for tok in parts:
            if tok.lstrip("-").isdigit():
                # Heuristic: waveform samples often in reasonable int range
                v = int(tok)
                # Skip very large tick-like values (>1e7) that are timestamps
                if abs(v) < 10_000_000:
                    vals.append(v)
                    if len(vals) >= max_n:
                        return np.asarray(vals, dtype=np.float64)
    return np.asarray(vals, dtype=np.float64)


def _waveform_one(args: tuple[str, str, str, dict[str, float]]) -> list[dict[str, str]]:
    uid, filepath, channels_s, hz_by_ch = args
    out: list[dict[str, str]] = []
    try:
        import pydicom

        ds = pydicom.dcmread(filepath, stop_before_pixels=False, force=True)
        raw = bytes(ds[0x7FE1, 0x1010].value)
        text = raw.decode("latin-1", errors="replace")
    except Exception as exc:  # noqa: BLE001
        for ch in (channels_s.split(";") if channels_s not in (NA, "") else [NA]):
            out.append(
                {
                    "physio_uid": uid,
                    "channel": ch,
                    "n_samples": NA,
                    "duration_seconds": NA,
                    "variance": NA,
                    "quality_status": "EMPTY",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
        return out

    channels = [c for c in channels_s.split(";") if c] if channels_s not in (NA, "") else []
    if not channels:
        channels = sorted(hz_by_ch.keys()) or ["UNKNOWN"]

    for ch in channels:
        samples = _extract_channel_samples(text, ch)
        n = int(samples.size)
        if n == 0:
            q = "EMPTY"
            var = NA
            dur = NA
        else:
            var_f = float(np.var(samples))
            var = f"{var_f:.6g}"
            hz = hz_by_ch.get(ch)
            dur = f"{(n / hz):.6f}" if hz and hz > 0 else NA
            if var_f < 1e-12 or (np.ptp(samples) == 0):
                q = "FLAT_SIGNAL"
            elif hz and hz > 0 and (n / hz) < 1.0:
                q = "SHORT_DURATION"
            else:
                q = "VALID"
        out.append(
            {
                "physio_uid": uid,
                "channel": ch,
                "n_samples": str(n),
                "duration_seconds": dur,
                "variance": var,
                "quality_status": q,
            }
        )
    return out


def validate_waveforms(
    joined: list[dict[str, str]], workers: int
) -> list[dict[str, str]]:
    jobs = []
    for r in joined:
        if r["conversion_status"] != "READY":
            continue
        if r.get("filepath") in (None, "", NA):
            continue
        hz_by_ch: dict[str, float] = {}
        stmap = r.get("sampletime_by_type") or ""
        for part in stmap.split(";"):
            if "=" not in part:
                continue
            ch, ms = part.split("=", 1)
            try:
                hz_by_ch[ch.strip().upper()] = 1000.0 / float(ms)
            except ValueError:
                pass
        jobs.append(
            (
                r["physio_series_uid"],
                r["filepath"],
                r.get("channels_available") or r.get("embedded_logs") or NA,
                hz_by_ch,
            )
        )

    LOGGER.info("Waveform quality checks for %d READY PhysioLogs", len(jobs))
    rows: list[dict[str, str]] = []
    if workers <= 1:
        for i, job in enumerate(jobs, 1):
            rows.extend(_waveform_one(job))
            if i % 100 == 0:
                LOGGER.info("Waveform %d / %d", i, len(jobs))
        return rows

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_waveform_one, job) for job in jobs]
        done = 0
        for fut in as_completed(futs):
            rows.extend(fut.result())
            done += 1
            if done % 100 == 0 or done == len(jobs):
                LOGGER.info("Waveform %d / %d", done, len(jobs))
    return rows


# ---------------------------------------------------------------------------
# Final decision
# ---------------------------------------------------------------------------
def final_decisions(
    joined: list[dict[str, str]],
    sf_rows: list[dict[str, str]],
    st_rows: list[dict[str, str]],
    map_rows: list[dict[str, str]],
    wave_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    sf_pass = defaultdict(lambda: False)
    for r in sf_rows:
        # all channels for uid must PASS and at least one channel
        sf_pass[r["physio_uid"]]  # init
    sf_by = defaultdict(list)
    for r in sf_rows:
        sf_by[r["physio_uid"]].append(r["status"])
    for uid, statuses in sf_by.items():
        sf_pass[uid] = bool(statuses) and all(s == "PASS" for s in statuses)

    st_pass = {r["physio_uid"]: r["status"] == "PASS" for r in st_rows}
    map_pass = {r["physio_uid"]: r["status"] == "PASS" for r in map_rows}
    map_bold = {r["physio_uid"]: r["BIDS_bold_file"] for r in map_rows}

    wave_by = defaultdict(list)
    for r in wave_rows:
        wave_by[r["physio_uid"]].append(r)
    wave_pass: dict[str, bool] = {}
    wave_status_label: dict[str, str] = {}
    for uid, wrows in wave_by.items():
        # PASS if at least one VALID physiological channel (PULS/RESP/ECG);
        # EXT-only VALID also acceptable; fail if all EMPTY/FLAT/SHORT
        quals = [w["quality_status"] for w in wrows]
        phys = [
            w
            for w in wrows
            if w["channel"] in {"PULS", "RESP", "ECG"} and w["quality_status"] == "VALID"
        ]
        any_valid = any(q == "VALID" for q in quals)
        if phys or (any_valid and not all(q in {"EMPTY", "FLAT_SIGNAL"} for q in quals)):
            # Prefer requiring at least one VALID channel overall
            if any_valid:
                wave_pass[uid] = True
                wave_status_label[uid] = "PASS"
            else:
                wave_pass[uid] = False
                wave_status_label[uid] = "FAIL:" + ",".join(sorted(set(quals)))
        else:
            wave_pass[uid] = False
            wave_status_label[uid] = "FAIL:" + ",".join(sorted(set(quals)))

    out: list[dict[str, str]] = []
    for r in joined:
        if r["conversion_status"] != "READY":
            # Still record forensic FAILED as excluded
            out.append(
                {
                    "physio_uid": r["physio_series_uid"],
                    "subject": r["subject"],
                    "session": r["session"],
                    "channels": r.get("channels_available", NA),
                    "BIDS_target": r.get("matched_bold", NA),
                    "sampling_frequency_status": "NOT_EVALUATED",
                    "starttime_status": "NOT_EVALUATED",
                    "mapping_status": "NOT_EVALUATED",
                    "waveform_status": "NOT_EVALUATED",
                    "FINAL_DECISION": f"EXCLUDED_REASON:forensic_{r['conversion_status']}",
                }
            )
            continue
        uid = r["physio_series_uid"]
        sfs = "PASS" if sf_pass.get(uid) else "FAIL"
        sts = "PASS" if st_pass.get(uid) else "FAIL"
        ms = "PASS" if map_pass.get(uid) else "FAIL"
        ws = wave_status_label.get(uid, "FAIL:missing_waveform_eval")
        w_ok = wave_pass.get(uid, False)
        if sfs == "PASS" and sts == "PASS" and ms == "PASS" and w_ok:
            decision = "READY_FOR_BIDS_CONVERSION"
        else:
            reasons = []
            if sfs != "PASS":
                reasons.append("sampling_frequency")
            if sts != "PASS":
                reasons.append("start_time")
            if ms != "PASS":
                reasons.append("run_mapping")
            if not w_ok:
                reasons.append(f"waveform({ws})")
            decision = "EXCLUDED_REASON:" + ";".join(reasons)
        out.append(
            {
                "physio_uid": uid,
                "subject": r["subject"],
                "session": r["session"],
                "channels": r.get("channels_available", NA),
                "BIDS_target": map_bold.get(uid, r.get("matched_bold", NA)),
                "sampling_frequency_status": sfs,
                "starttime_status": sts,
                "mapping_status": ms,
                "waveform_status": "PASS" if w_ok else ws,
                "FINAL_DECISION": decision,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Report / figures / methods
# ---------------------------------------------------------------------------
def write_report(
    path: Path,
    total: int,
    ready: int,
    failed: int,
    sf_pass_uids: int,
    st_pass_uids: int,
    map_pass_uids: int,
    wave_pass_uids: int,
    final_ready: int,
    exclusion_counts: list[tuple[str, int]],
    option: str,
    option_text: str,
) -> None:
    pct = 100.0 * ready / total if total else 0.0
    lines = [
        "# Siemens PhysioLog BIDS readiness audit",
        "",
        f"Generated: `{_now()}`",
        "",
        "**READ-ONLY.** No modifications to `raw_original/`, `bids/`, `derivatives/`, "
        "or `release_dataset/`. No `*_physio.tsv.gz` created.",
        "",
        "## Dataset inventory",
        "",
        f"Total PhysioLog objects: **{total}**",
        "",
        f"READY after forensic filtering: **{ready}** ({pct:.1f}%)",
        "",
        f"FAILED: **{failed}**",
        "",
        "## Metadata completeness",
        "",
        f"Sampling frequency available (PASS among forensic READY): **{sf_pass_uids} / {ready}**",
        "",
        f"StartTime available (PASS): **{st_pass_uids} / {ready}**",
        "",
        f"Unique BOLD association (PASS): **{map_pass_uids} / {ready}**",
        "",
        f"Waveform quality (PASS): **{wave_pass_uids} / {ready}**",
        "",
        f"Final BIDS-eligible (`READY_FOR_BIDS_CONVERSION`): **{final_ready}**",
        "",
        "## Final conversion recommendation",
        "",
        f"### {option}",
        "",
        option_text,
        "",
        "## Exclusion reasons",
        "",
        "| Reason | Number |",
        "| --- | ---: |",
    ]
    for reason, n in exclusion_counts:
        lines.append(f"| {reason} | {n} |")
    lines += [
        "",
        "## Method notes",
        "",
        f"- SamplingFrequency_Hz = 1000 / CSA `SampleTime` (ms); Freq Per and Siemens "
        f"default guesses rejected.",
        f"- StartTime = (first channel ACQ_TIME_TICS − vol0 ACQ_START_TICS) × "
        f"{SIEMENS_CSA_TICK_SECONDS:g} s/tick (Siemens CSA convention; confidence MEDIUM).",
        "- Run mapping requires subject/session/ProtocolName unique BOLD match with "
        "existing `*_bold.nii.gz`.",
        "- Waveform PASS requires ≥1 VALID non-flat channel extracted from CSA payload.",
        "",
        "## Outputs",
        "",
        "- `sampling_frequency_validation.tsv`",
        "- `starttime_validation.tsv`",
        "- `run_mapping_validation.tsv`",
        "- `waveform_quality_validation.tsv`",
        "- `FINAL_PHYSIO_CONVERSION_DECISION.tsv`",
        "- `FINAL_PHYSIO_READINESS_REPORT.md`",
        "- `SCIENTIFIC_DATA_PHYSIO_METHODS_DRAFT.md`",
        "- figures `physio_recovery_summary.png`, `sampling_frequency_distribution.png`, "
        "`physio_duration_distribution.png`, `recoverable_runs_by_task.png`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_methods_draft(path: Path, final_ready: int, total: int, ready: int) -> None:
    text = f"""# Scientific Data — physiology methods draft

*(Draft wording constrained to audit evidence. Not a conversion claim.)*

Physiological recordings were evaluated from Siemens PhysioLog DICOM objects stored in the private source archive (CSA non-image data, tag `7FE1,1010`), not from standard DICOM Waveform IODs. Where present, channel-wise `SampleTime` (milliseconds) was used to derive sampling frequency as \(1000 / \\mathrm{{SampleTime}}\); Siemens footer `Freq Per` fields and undocumented model-default rates were not accepted as sampling frequency. Relative start times were computed only when CSA `ACQUISITION_INFO` volume-0 acquisition ticks and a first-channel acquisition tick were both available, using the documented CSA tick conversion; raw peripheral PMU `LogStartMDHTime` values without a validated transform were not used. PhysioLog series were associated to BOLD runs only under unique subject, session, and `ProtocolName` correspondence. Session-wide peripheral PMU logs (`.ecg` / `.resp` / `.puls`) were excluded under a fail-closed policy because they lack explicit ADC sampling frequency and unique run linkage. No physiology files were written into the BIDS tree during this audit; of {total} PhysioLog objects, {ready} passed forensic filters and {final_ready} met all readiness gates for a subsequent gated converter.
"""
    path.write_text(text, encoding="utf-8")


def make_figures(
    out_dir: Path,
    ready: int,
    failed: int,
    sf_rows: list[dict[str, str]],
    wave_rows: list[dict[str, str]],
    final_rows: list[dict[str, str]],
) -> None:
    # 1 recovery summary
    fig, ax = plt.subplots(figsize=(5.5, 4))
    ax.bar(["READY", "FAILED"], [ready, failed], color=["#00a087", "#e64b35"])
    ax.set_ylabel("PhysioLog objects (n)")
    ax.set_title("PhysioLog recovery summary (forensic filter)")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "physio_recovery_summary.png", dpi=200)
    plt.close(fig)

    # 2 sampling frequency distribution
    hz_vals = []
    for r in sf_rows:
        if r["status"] == "PASS" and r["sampling_frequency_hz"] not in ("", NA):
            try:
                hz_vals.append(float(r["sampling_frequency_hz"]))
            except ValueError:
                pass
    fig, ax = plt.subplots(figsize=(6, 4))
    if hz_vals:
        ax.hist(hz_vals, bins=20, color="#3c5488", edgecolor="white")
    ax.set_xlabel("SamplingFrequency (Hz)")
    ax.set_ylabel("Channel instances (n)")
    ax.set_title("Sampling frequency from CSA SampleTime")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "sampling_frequency_distribution.png", dpi=200)
    plt.close(fig)

    # 3 duration distribution
    durs = []
    for r in wave_rows:
        if r.get("duration_seconds") not in ("", NA, None):
            try:
                durs.append(float(r["duration_seconds"]))
            except ValueError:
                pass
    fig, ax = plt.subplots(figsize=(6, 4))
    if durs:
        ax.hist(durs, bins=30, color="#4dbbd5", edgecolor="white")
    ax.set_xlabel("Duration (s)")
    ax.set_ylabel("Channel instances (n)")
    ax.set_title("PhysioLog channel duration (from n_samples / Hz)")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "physio_duration_distribution.png", dpi=200)
    plt.close(fig)

    # 4 recoverable runs by task
    task_counts: Counter[str] = Counter()
    for r in final_rows:
        if r["FINAL_DECISION"] != "READY_FOR_BIDS_CONVERSION":
            continue
        target = Path(r["BIDS_target"]).name if r["BIDS_target"] not in (NA, "") else ""
        m = re.search(r"task-([A-Za-z0-9]+)", target)
        # matched_bold may be stem without path
        if not m:
            m = re.search(r"task-([A-Za-z0-9]+)", r["BIDS_target"])
        task_counts[m.group(1) if m else "unknown"] += 1
    fig, ax = plt.subplots(figsize=(6.5, 4))
    labels = sorted(task_counts)
    vals = [task_counts[k] for k in labels]
    ax.bar(labels, vals, color="#91d1c2")
    ax.set_xlabel("BIDS task")
    ax.set_ylabel("READY_FOR_BIDS_CONVERSION (n)")
    ax.set_title("Recoverable PhysioLog runs by task")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "recoverable_runs_by_task.png", dpi=200)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bids-root", type=Path, default=DEFAULT_BIDS)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    out_dir = args.out_dir.resolve()
    if "physiology_audit" not in out_dir.parts:
        print("Refusing to write outside physiology_audit", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(out_dir / "run.log", mode="w", encoding="utf-8"),
        ],
        force=True,
    )

    status = _load_tsv(args.audit_dir / "physio_conversion_status.tsv")
    deep = _load_tsv(args.audit_dir / "physiolog_dicom_deep.tsv")
    total = len(status)
    ready = sum(1 for r in status if r["conversion_status"] == "READY")
    failed = sum(1 for r in status if r["conversion_status"] == "FAILED")
    pct = 100.0 * ready / total if total else 0.0
    LOGGER.info(
        "Inventory: total=%d READY=%d FAILED=%d (%.1f%% recoverable)",
        total,
        ready,
        failed,
        pct,
    )

    joined = build_joined_table(status, deep, workers=args.workers)

    sf_rows = validate_sampling(joined)
    _write_tsv(
        out_dir / "sampling_frequency_validation.tsv",
        [
            "physio_uid",
            "subject",
            "session",
            "channel",
            "sample_time_ms",
            "sampling_frequency_hz",
            "source",
            "status",
        ],
        sf_rows,
    )

    st_rows = validate_starttime(joined)
    _write_tsv(
        out_dir / "starttime_validation.tsv",
        ["physio_uid", "BIDS_run", "StartTime", "method", "confidence", "status"],
        st_rows,
    )

    map_rows = validate_run_mapping(joined, args.bids_root.resolve())
    _write_tsv(
        out_dir / "run_mapping_validation.tsv",
        [
            "physio_uid",
            "BIDS_bold_file",
            "protocol_name",
            "candidate_count",
            "mapping_confidence",
            "status",
        ],
        map_rows,
    )

    wave_rows = validate_waveforms(joined, workers=args.workers)
    _write_tsv(
        out_dir / "waveform_quality_validation.tsv",
        [
            "physio_uid",
            "channel",
            "n_samples",
            "duration_seconds",
            "variance",
            "quality_status",
        ],
        [{k: r.get(k, "") for k in (
            "physio_uid",
            "channel",
            "n_samples",
            "duration_seconds",
            "variance",
            "quality_status",
        )} for r in wave_rows],
    )

    final_rows = final_decisions(joined, sf_rows, st_rows, map_rows, wave_rows)
    _write_tsv(
        out_dir / "FINAL_PHYSIO_CONVERSION_DECISION.tsv",
        [
            "physio_uid",
            "subject",
            "session",
            "channels",
            "BIDS_target",
            "sampling_frequency_status",
            "starttime_status",
            "mapping_status",
            "waveform_status",
            "FINAL_DECISION",
        ],
        final_rows,
    )

    # Stats
    sf_pass_uids = len({r["physio_uid"] for r in sf_rows if r["status"] == "PASS"})
    # stricter: uids where all channels pass
    sf_all = defaultdict(list)
    for r in sf_rows:
        sf_all[r["physio_uid"]].append(r["status"])
    sf_pass_uids = sum(1 for u, sts in sf_all.items() if sts and all(s == "PASS" for s in sts))
    st_pass_uids = sum(1 for r in st_rows if r["status"] == "PASS")
    map_pass_uids = sum(1 for r in map_rows if r["status"] == "PASS")
    wave_pass_uids = sum(
        1
        for r in final_rows
        if r["waveform_status"] == "PASS" and r["FINAL_DECISION"] != "EXCLUDED_REASON:forensic_FAILED"
        and "NOT_EVALUATED" not in r["waveform_status"]
    )
    # recount wave pass properly
    wave_pass_uids = sum(
        1
        for r in final_rows
        if r.get("sampling_frequency_status") != "NOT_EVALUATED" and r["waveform_status"] == "PASS"
    )
    final_ready = sum(
        1 for r in final_rows if r["FINAL_DECISION"] == "READY_FOR_BIDS_CONVERSION"
    )
    excluded = len(final_rows) - final_ready

    excl_counter: Counter[str] = Counter()
    for r in final_rows:
        d = r["FINAL_DECISION"]
        if d == "READY_FOR_BIDS_CONVERSION":
            continue
        if d.startswith("EXCLUDED_REASON:"):
            reason = d.split(":", 1)[1]
            # split compound
            for part in reason.split(";"):
                part = part.strip()
                if part.startswith("waveform"):
                    excl_counter["Invalid waveform"] += 1
                elif part == "sampling_frequency":
                    excl_counter["Missing/invalid SampleTime"] += 1
                elif part == "start_time":
                    excl_counter["Missing StartTime"] += 1
                elif part == "run_mapping":
                    excl_counter["Ambiguous/missing BOLD mapping"] += 1
                elif part.startswith("forensic"):
                    excl_counter["Failed forensic READY filter"] += 1
                else:
                    excl_counter[part] += 1
        else:
            excl_counter[d] += 1

    if final_ready > 0 and final_ready >= 0.5 * ready:
        option = "OPTION A"
        option_text = (
            "PhysioLog data meeting all four gates (SampleTime-derived SamplingFrequency, "
            "CSA-derived StartTime, unique BOLD mapping, valid waveform) are ready for a "
            f"gated BIDS conversion step (**{final_ready}** series). Peripheral PMU logs "
            "remain excluded. This audit did not write any `*_physio.tsv.gz`."
        )
        recommendation = "READY"
    else:
        option = "OPTION B"
        option_text = (
            "PhysioLog conversion requires additional validation before release-scale "
            f"BIDS export (final eligible **{final_ready}** / forensic READY **{ready}**)."
        )
        recommendation = "NOT READY"

    write_report(
        out_dir / "FINAL_PHYSIO_READINESS_REPORT.md",
        total=total,
        ready=ready,
        failed=failed,
        sf_pass_uids=sf_pass_uids,
        st_pass_uids=st_pass_uids,
        map_pass_uids=map_pass_uids,
        wave_pass_uids=wave_pass_uids,
        final_ready=final_ready,
        exclusion_counts=excl_counter.most_common(),
        option=option,
        option_text=option_text,
    )
    write_methods_draft(
        out_dir / "SCIENTIFIC_DATA_PHYSIO_METHODS_DRAFT.md",
        final_ready=final_ready,
        total=total,
        ready=ready,
    )
    make_figures(out_dir, ready, failed, sf_rows, wave_rows, final_rows)

    print()
    print("PHYSIOLOGY READINESS AUDIT COMPLETE")
    print()
    print(f"Total PhysioLog: {total}")
    print()
    print(f"Eligible for BIDS conversion: {final_ready}")
    print()
    print(f"Excluded: {excluded}")
    print()
    print(f"Recommendation: {recommendation}")
    print()
    print(f"Reports: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
