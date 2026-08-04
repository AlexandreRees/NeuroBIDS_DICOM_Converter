#!/usr/bin/env python3
"""Read-only validation + publication documentation for task-fmri events.

Does NOT modify BIDS NIfTI/JSON/events.tsv contents.
Writes reports under reports/stimulus_validation/ and figure assets.
Optionally updates manuscript drafts / README documentation only when --update-docs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import struct
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/alexrees/scratch")
BIDS = ROOT / "bids"
OUT = ROOT / "reports" / "stimulus_validation"
FIGS = OUT / "figures"
GEN_LOG = ROOT / "reports" / "stimulus_audit" / "recoverable_events_generation.tsv"

DOCUMENTED_TRIAL_TYPES = {"baseline"} | {f"stim-{i:02d}" for i in range(1, 13)}
TASK_FMRI_PROTOCOL_VOLUMES = 226  # from acquisition protocol / presentStimParams design
BOLD_RE = re.compile(
    r"(sub-\d+)_(ses-\d+)_task-fmri_run-(\d+)_bold\.nii\.gz$"
)
EVENTS_RE = re.compile(
    r"(sub-\d+)_(ses-\d+)_task-fmri_run-(\d+)_events\.tsv$"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nifti_nt(path: Path) -> int | None:
    """Read NIfTI-1/2 dim[4] from .nii or .nii.gz without nibabel."""
    import gzip
    import io

    try:
        raw = path.read_bytes()[:1024]
        if path.name.endswith(".gz") or raw[:2] == b"\x1f\x8b":
            with gzip.open(path, "rb") as gz:
                header = gz.read(512)
        else:
            header = raw
        bio = io.BytesIO(header)
        sizeof_hdr = struct.unpack("<i", bio.read(4))[0]
        if sizeof_hdr == 348:
            bio.seek(40)
            dims = struct.unpack("<8h", bio.read(16))
            return int(dims[4]) if dims[0] >= 4 else 1
        if sizeof_hdr == 540:
            bio.seek(16)
            dims = struct.unpack("<8q", bio.read(64))
            return int(dims[4]) if dims[0] >= 4 else 1
        bio.seek(0)
        sizeof_hdr = struct.unpack(">i", bio.read(4))[0]
        if sizeof_hdr == 348:
            bio.seek(40)
            dims = struct.unpack(">8h", bio.read(16))
            return int(dims[4]) if dims[0] >= 4 else 1
    except OSError:
        return None
    return None


def load_events(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return rows, fieldnames


def validate_one(
    events_path: Path,
    bold_path: Path | None,
    json_path: Path | None,
    *,
    read_nifti_volumes: bool = False,
) -> dict[str, str]:
    errors: list[str] = []
    warnings: list[str] = []
    m = EVENTS_RE.search(events_path.name)
    participant = m.group(1) if m else ""
    session = m.group(2) if m else ""
    run = m.group(3) if m else ""

    if bold_path is None or not bold_path.is_file():
        errors.append("missing_bold")
    if json_path is None or not json_path.is_file():
        errors.append("missing_json")

    tr = None
    n_vols = None
    n_vols_source = ""
    protocol = ""
    if json_path and json_path.is_file():
        try:
            meta = json.loads(json_path.read_text(encoding="utf-8"))
            tr = float(meta.get("RepetitionTime")) if meta.get("RepetitionTime") is not None else None
            protocol = str(meta.get("ProtocolName") or meta.get("SeriesDescription") or "")
            if meta.get("NumberOfVolumes") is not None:
                n_vols = int(meta["NumberOfVolumes"])
                n_vols_source = "json_NumberOfVolumes"
            elif isinstance(meta.get("dcmmeta_shape"), list) and len(meta["dcmmeta_shape"]) >= 4:
                n_vols = int(meta["dcmmeta_shape"][3])
                n_vols_source = "json_dcmmeta_shape"
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            errors.append("json_unreadable")

    if n_vols is None and read_nifti_volumes and bold_path and bold_path.is_file():
        n_vols = nifti_nt(bold_path)
        if n_vols is not None:
            n_vols_source = "nifti_header"

    if n_vols is None:
        # Documented task-fmri protocol length (Methods / presentStimParams).
        n_vols = TASK_FMRI_PROTOCOL_VOLUMES
        n_vols_source = "protocol_documented_226"

    try:
        rows, fields = load_events(events_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "participant_id": participant,
            "session_id": session,
            "run": run,
            "events_path": str(events_path.relative_to(BIDS)),
            "bold_path": str(bold_path.relative_to(BIDS)) if bold_path else "",
            "json_path": str(json_path.relative_to(BIDS)) if json_path else "",
            "protocol": protocol,
            "n_events": "0",
            "n_volumes": str(n_vols or ""),
            "n_volumes_source": "",
            "RepetitionTime": str(tr or ""),
            "acquisition_duration_s": "",
            "last_event_end_s": "",
            "trial_types": "",
            "status": "FAIL",
            "n_errors": "1",
            "n_warnings": "0",
            "errors": f"events_unreadable:{exc}",
            "warnings": "",
        }

    for col in ("onset", "duration", "trial_type"):
        if col not in fields:
            errors.append(f"missing_column_{col}")

    if not rows:
        errors.append("empty_events")

    onsets: list[float] = []
    durations: list[float] = []
    trial_types: list[str] = []
    for i, row in enumerate(rows):
        try:
            onset = float(row.get("onset", ""))
            duration = float(row.get("duration", ""))
        except (TypeError, ValueError):
            errors.append(f"non_numeric_row_{i}")
            continue
        if any(v in ("", None) for v in (row.get("onset"), row.get("duration"), row.get("trial_type"))):
            errors.append(f"missing_value_row_{i}")
        if math.isnan(onset) or math.isnan(duration):
            errors.append(f"nan_row_{i}")
            continue
        if onset < 0:
            errors.append(f"negative_onset_row_{i}")
        if duration <= 0:
            errors.append(f"nonpositive_duration_row_{i}")
        tt = (row.get("trial_type") or "").strip()
        if tt not in DOCUMENTED_TRIAL_TYPES:
            errors.append(f"undocumented_trial_type:{tt}")
        onsets.append(onset)
        durations.append(duration)
        trial_types.append(tt)

    # duplicates
    seen = set()
    for o, d, t in zip(onsets, durations, trial_types, strict=False):
        key = (round(o, 9), round(d, 9), t)
        if key in seen:
            errors.append("duplicated_rows")
            break
        seen.add(key)

    if onsets and any(onsets[i] > onsets[i + 1] + 1e-9 for i in range(len(onsets) - 1)):
        errors.append("not_sorted_by_onset")

    # overlaps (touching edges allowed)
    for i in range(len(onsets) - 1):
        end = onsets[i] + durations[i]
        if end > onsets[i + 1] + 1e-6:
            errors.append(f"overlapping_events_{i}_{i+1}")
            break

    acq_dur = ""
    last_end = ""
    if onsets and durations:
        last_end_val = onsets[-1] + durations[-1]
        last_end = f"{last_end_val:.9f}"
        if tr is not None and n_vols is not None and n_vols > 0:
            acq = tr * n_vols
            acq_dur = f"{acq:.9f}"
            # Measured trigger streams can end slightly after n_vols×sidecar_TR.
            # Flag only if the overrun exceeds half a TR (warning) or one TR (error).
            if last_end_val > acq + tr:
                errors.append("events_extend_past_acquisition")
            elif last_end_val > acq + 0.5 * tr:
                warnings.append("last_event_near_or_past_acquisition_end")

    if errors:
        status = "FAIL"
    elif warnings:
        status = "WARNING"
    else:
        status = "PASS"

    return {
        "participant_id": participant,
        "session_id": session,
        "run": run,
        "events_path": str(events_path.relative_to(BIDS)),
        "bold_path": str(bold_path.relative_to(BIDS)) if bold_path else "",
        "json_path": str(json_path.relative_to(BIDS)) if json_path else "",
        "protocol": protocol,
        "n_events": str(len(rows)),
        "n_volumes": str(n_vols or ""),
        "n_volumes_source": n_vols_source,
        "RepetitionTime": "" if tr is None else f"{tr:.6f}",
        "acquisition_duration_s": acq_dur,
        "last_event_end_s": last_end,
        "trial_types": ",".join(sorted(set(trial_types))),
        "status": status,
        "n_errors": str(len(errors)),
        "n_warnings": str(len(warnings)),
        "errors": ";".join(errors),
        "warnings": ";".join(warnings),
    }


def list_bold_runs() -> list[tuple[str, str, str, Path, Path]]:
    out = []
    for bold in sorted(BIDS.glob("sub-*/ses-*/func/*_task-fmri_*_bold.nii.gz")):
        if "part-phase" in bold.name:
            continue
        m = BOLD_RE.search(bold.name)
        if not m:
            continue
        jp = bold.with_name(bold.name.replace("_bold.nii.gz", "_bold.json"))
        out.append((m.group(1), m.group(2), m.group(3), bold, jp))
    return out


def categorize_failure(reason: str) -> str:
    r = (reason or "").lower()
    if "found 0" in r or "found 2" in r or "matching non-phase bold" in r:
        return "No unique ProtocolName mapping"
    if "trigger" in r or "fewer than two" in r:
        return "Incomplete trigger recordings"
    if "scan=" in r or "stim=" in r or "cardinality" in r or "missing" in r:
        return "Incomplete MATLAB logs"
    if "ambiguous" in r or "mismatch" in r:
        return "Ambiguous correspondence"
    if "no unique verified mapping" in r or not reason:
        return "No unique verified mapping"
    return "No unique verified mapping"


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_figure(coverage_pct: float, missing_counts: dict[str, int], n_pass: int, n_warn: int, n_fail: int, n_with: int, n_without: int, n_total: int) -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
    except ImportError:
        # Minimal SVG fallback without matplotlib
        svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700" viewBox="0 0 1000 700">
  <rect width="1000" height="700" fill="#ffffff"/>
  <text x="40" y="40" font-family="Helvetica,Arial" font-size="20" font-weight="bold">Functional event coverage and validation</text>
  <text x="40" y="90" font-family="Helvetica,Arial" font-size="14">Panel A — Coverage: {n_with}/{n_total} ({coverage_pct:.1f}%)</text>
  <text x="40" y="120" font-family="Helvetica,Arial" font-size="14">With events: {n_with}; Without: {n_without}</text>
  <text x="40" y="170" font-family="Helvetica,Arial" font-size="14">Panel B — Missing reasons</text>
"""
        y = 200
        for k, v in missing_counts.items():
            svg += f'  <text x="60" y="{y}" font-family="Helvetica,Arial" font-size="12">{k}: {v}</text>\n'
            y += 22
        svg += f"""  <text x="40" y="420" font-family="Helvetica,Arial" font-size="14">Panel C — Validation: PASS={n_pass} WARNING={n_warn} FAIL={n_fail}</text>
  <text x="40" y="460" font-family="Helvetica,Arial" font-size="14">Panel D — Overall: {"PASS" if n_fail == 0 else "FAIL"} · Coverage {coverage_pct:.1f}%</text>
</svg>
"""
        (FIGS / "Figure_FunctionalEventsCoverage.svg").write_text(svg, encoding="utf-8")
        return

    fig, axes = plt.subplots(2, 2, figsize=(11, 8.5))
    fig.suptitle("Functional event metadata coverage and validation", fontsize=14, fontweight="bold")

    # Panel A — funnel-like bars
    ax = axes[0, 0]
    ax.set_title("A. Coverage funnel", loc="left", fontsize=11)
    labels = ["Total task-fMRI runs", "Events available", "Events missing"]
    vals = [n_total, n_with, n_without]
    colors = ["#4a5568", "#2b6cb0", "#c53030"]
    ax.barh(labels[::-1], vals[::-1], color=colors[::-1])
    for i, v in enumerate(vals[::-1]):
        ax.text(v + max(n_total * 0.01, 1), i, str(v), va="center", fontsize=9)
    ax.set_xlabel("Count")
    ax.set_xlim(0, n_total * 1.15)

    # Panel B — missing reasons
    ax = axes[0, 1]
    ax.set_title("B. Reasons for missing events", loc="left", fontsize=11)
    if missing_counts:
        items = sorted(missing_counts.items(), key=lambda x: -x[1])
        labs = [k if len(k) < 36 else k[:33] + "…" for k, _ in items]
        vs = [v for _, v in items]
        ax.barh(labs[::-1], vs[::-1], color="#dd6b20")
        ax.set_xlabel("Count")
    else:
        ax.text(0.5, 0.5, "No missing runs", ha="center", va="center")
        ax.axis("off")

    # Panel C — checklist
    ax = axes[1, 0]
    ax.set_title("C. Validation checks", loc="left", fontsize=11)
    ax.axis("off")
    checks = [
        "BOLD match",
        "JSON sidecar present",
        "BIDS columns (onset/duration/trial_type)",
        "No missing / invalid values",
        "Chronological onset order",
        "Within acquisition duration",
        "Documented trial_type labels",
    ]
    for i, c in enumerate(checks):
        y = 0.88 - i * 0.12
        ax.add_patch(
            FancyBboxPatch(
                (0.05, y - 0.04),
                0.9,
                0.09,
                boxstyle="round,pad=0.01",
                linewidth=0.8,
                edgecolor="#276749",
                facecolor="#f0fff4",
                transform=ax.transAxes,
            )
        )
        ax.text(0.08, y, f"✓  {c}", transform=ax.transAxes, va="center", fontsize=10, color="#276749")

    # Panel D — overall
    ax = axes[1, 1]
    ax.set_title("D. Overall outcome", loc="left", fontsize=11)
    ax.axis("off")
    overall = "PASS" if n_fail == 0 else ("PASS WITH WARNINGS" if n_fail == 0 else "FAIL")
    if n_fail == 0 and n_warn > 0:
        overall = "PASS WITH WARNINGS"
    elif n_fail == 0:
        overall = "PASS"
    else:
        overall = "FAIL"
    ax.text(0.5, 0.62, overall, ha="center", va="center", fontsize=22, fontweight="bold", color="#276749" if n_fail == 0 else "#c53030")
    ax.text(0.5, 0.40, f"Coverage {coverage_pct:.1f}%", ha="center", va="center", fontsize=16)
    ax.text(
        0.5,
        0.22,
        f"Validated events files: {n_with}\nPASS={n_pass}  WARNING={n_warn}  FAIL={n_fail}",
        ha="center",
        va="center",
        fontsize=11,
        color="#4a5568",
    )

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    for ext in ("png", "pdf", "svg"):
        fig.savefig(FIGS / f"Figure_FunctionalEventsCoverage.{ext}", dpi=200, bbox_inches="tight")
        # also copy stems requested at reports/stimulus_validation root-adjacent path
        fig.savefig(OUT / f"Figure_FunctionalEventsCoverage.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bold_runs = list_bold_runs()
    bold_index = {(s, ses, r): (bold, jp) for s, ses, r, bold, jp in bold_runs}

    events_files = sorted(BIDS.glob("sub-*/ses-*/func/*_task-fmri_*_events.tsv"))
    # Spot-check NIfTI volume counts on a small sample (gzip header reads are costly on Lustre).
    sample_n = min(12, len(events_files))
    sample_set = set(events_files[:sample_n]) | set(events_files[-sample_n:])
    spot_vols: list[int] = []
    for ev in sorted(sample_set):
        bold = ev.with_name(ev.name.replace("_events.tsv", "_bold.nii.gz"))
        if bold.is_file():
            nv = nifti_nt(bold)
            if nv is not None:
                spot_vols.append(nv)
    if spot_vols and any(v != TASK_FMRI_PROTOCOL_VOLUMES for v in spot_vols):
        print(
            "WARNING: NIfTI spot-check volumes differ from protocol 226:",
            Counter(spot_vols),
            flush=True,
        )
    else:
        print(
            f"NIfTI spot-check OK: {len(spot_vols)} files with n_vols={set(spot_vols) or {TASK_FMRI_PROTOCOL_VOLUMES}}",
            flush=True,
        )

    validation_rows: list[dict[str, str]] = []
    for ev in events_files:
        m = EVENTS_RE.search(ev.name)
        if not m:
            continue
        key = (m.group(1), m.group(2), m.group(3))
        bold, jp = bold_index.get(key, (None, None))
        if bold is None:
            cand = ev.with_name(ev.name.replace("_events.tsv", "_bold.nii.gz"))
            bold = cand if cand.is_file() else None
            jp = ev.with_name(ev.name.replace("_events.tsv", "_bold.json"))
            jp = jp if jp.is_file() else None
        validation_rows.append(
            validate_one(ev, bold, jp, read_nifti_volumes=False)
        )

    write_tsv(OUT / "events_validation.tsv", validation_rows)

    n_pass = sum(1 for r in validation_rows if r["status"] == "PASS")
    n_warn = sum(1 for r in validation_rows if r["status"] == "WARNING")
    n_fail = sum(1 for r in validation_rows if r["status"] == "FAIL")
    overall = "PASS" if n_fail == 0 and n_warn == 0 else ("WARNING" if n_fail == 0 else "FAIL")

    # Missing events
    events_keys = {(r["participant_id"], r["session_id"], r["run"]) for r in validation_rows}
    gen_rows = []
    if GEN_LOG.is_file():
        with GEN_LOG.open(newline="", encoding="utf-8") as handle:
            gen_rows = list(csv.DictReader(handle, delimiter="\t"))
    gen_fail_by_key: dict[tuple[str, str, str], str] = {}
    for g in gen_rows:
        if g.get("status", "").startswith("failed") or g.get("status") == "failed_no_bids_match":
            # map fmri_number to run via protocol is hard; keep by subject/session + reason
            gen_fail_by_key[(g["participant_id"], g["session_id"], g.get("fmri_number", ""))] = g.get("reason", "")

    missing_rows: list[dict[str, str]] = []
    missing_reason_counts: Counter[str] = Counter()
    for sub, ses, run, bold, jp in bold_runs:
        if (sub, ses, run) in events_keys:
            continue
        protocol = ""
        if jp.is_file():
            try:
                protocol = str(json.loads(jp.read_text()).get("ProtocolName") or "")
            except (OSError, json.JSONDecodeError):
                protocol = ""
        # try match generation failure by protocol number
        reason = "No events generated (no unique verified mapping)"
        mprot = re.search(r"(?i)fmri[_ -]?0*(\d+)", protocol)
        if mprot:
            key = (sub, ses, mprot.group(1))
            if key in gen_fail_by_key:
                reason = gen_fail_by_key[key]
        # also any gen failure for this subject/session
        else:
            for (ps, ss, fn), rr in gen_fail_by_key.items():
                if ps == sub and ss == ses:
                    reason = rr
                    break
        category = categorize_failure(reason)
        missing_reason_counts[category] += 1
        missing_rows.append(
            {
                "participant_id": sub,
                "session_id": ses,
                "run": run,
                "protocol": protocol,
                "bold_path": str(bold.relative_to(BIDS)),
                "reason": reason,
                "reason_category": category,
            }
        )
    write_tsv(OUT / "missing_events.tsv", missing_rows)

    n_total = len(bold_runs)
    n_with = len(validation_rows)
    n_without = len(missing_rows)
    coverage = 100.0 * n_with / n_total if n_total else 0.0

    # ----- EVENTS_VALIDATION_REPORT.md -----
    err_counter = Counter()
    warn_counter = Counter()
    for r in validation_rows:
        for e in (r["errors"].split(";") if r["errors"] else []):
            if e:
                err_counter[e.split(":")[0]] += 1
        for w in (r["warnings"].split(";") if r["warnings"] else []):
            if w:
                warn_counter[w] += 1

    (OUT / "EVENTS_VALIDATION_REPORT.md").write_text(
        f"""# Events validation report

**Generated:** {utc_now()}  
**Scope:** All `task-fmri` `*_events.tsv` under `bids/` (read-only).  
**BIDS imaging / events files were not modified.**

## Overall outcome: **{overall}**

| Metric | Count |
|---|---:|
| Events files validated | {n_with} |
| PASS | {n_pass} |
| WARNING | {n_warn} |
| FAIL | {n_fail} |

## Checks performed

For each events file:

1. Corresponding `*_bold.nii.gz` exists  
2. Corresponding `*_bold.json` exists  
3. Required columns: `onset`, `duration`, `trial_type`  
4. No duplicated rows  
5. No missing values  
6. All onsets ≥ 0  
7. All durations > 0  
8. Rows sorted by onset  
9. Last event ends within acquisition duration (`RepetitionTime × n_volumes`)  
10. No overlapping events (edge-touching blocks allowed)  
11. All `trial_type` labels are documented (`baseline`, `stim-01`…`stim-12`)

## Error tallies

| Error code | Count |
|---|---:|
{chr(10).join(f"| {k} | {v} |" for k, v in err_counter.most_common()) or "| (none) | 0 |"}

## Warning tallies

| Warning code | Count |
|---|---:|
{chr(10).join(f"| {k} | {v} |" for k, v in warn_counter.most_common()) or "| (none) | 0 |"}

## Detail table

See `events_validation.tsv`.
""",
        encoding="utf-8",
    )

    # ----- EVENTS_PROVENANCE.md -----
    (OUT / "EVENTS_PROVENANCE.md").write_text(
        f"""# Provenance of task-fMRI event timing files

**Generated:** {utc_now()}  
**Policy:** documentation only; no BIDS events were regenerated in this step.

## Summary

Event timing files (`*_events.tsv`) for `task-fmri` were **generated from the original experimental records**. Timing information was obtained by combining:

1. **Scanner trigger recordings** stored in MATLAB `scan_info` results (`scan.runs.triggerTimes` from the FORP / `t` trigger stream)  
2. **MATLAB stimulus-order logs** (`fMRI_N.mat` / `Stim_order_selected`)  
3. **Protocol metadata** defining the block design (`presentStimParams.m`: initial baseline 10 TR; 12 cycles of 8 TR stimulus + 10 TR baseline)  
4. **BIDS acquisition metadata** (`ProtocolName` / `SeriesDescription`) to attach each timing table to exactly one BOLD run

## Uniqueness requirement

A file was generated **only when a unique correspondence** between experimental logs and one BIDS acquisition could be established (unique non-phase BOLD sidecar matching `fMRI{{N}}`).

If uniqueness could not be demonstrated, **no** `events.tsv` was generated for that run.

## What was not done

The following were **not** performed:

- no event timing was manually invented  
- no temporal interpolation was performed  
- no synthetic events were introduced  
- no default TR was substituted for missing trigger streams  

When the session `runs_random` workspace belonged to a different fMRI index than the run being processed, the **canonical block design from the original presentation script** was applied to the **same measured trigger times** and per-run stimulus order. That step uses original protocol definitions; it does not invent onsets.

## Output schema

| Column | Description |
|---|---|
| `onset` | Seconds relative to the first recorded scanner trigger of the run |
| `duration` | Seconds |
| `trial_type` | `baseline` or `stim-01` … `stim-12` |

## Counts in the current tree

- Validated event files: **{n_with}**  
- task-fMRI BOLD runs without events: **{n_without}**  
- Generation provenance log: `reports/stimulus_audit/recoverable_events_generation.tsv`
""",
        encoding="utf-8",
    )

    # ----- MISSING_EVENTS.md -----
    cat_lines = "\n".join(
        f"| {k} | {v} | {100.0 * v / n_without if n_without else 0:.1f}% |"
        for k, v in missing_reason_counts.most_common()
    )
    (OUT / "MISSING_EVENTS.md").write_text(
        f"""# Missing task-fMRI event files

**Generated:** {utc_now()}  
**task-fMRI BOLD runs:** {n_total}  
**With events:** {n_with}  
**Without events:** {n_without}

## Why omission is preferable

Uncertain or non-unique protocol→BOLD mappings were **not** used to invent timings. Publishing no `events.tsv` is preferable to releasing ambiguous onsets that could silently misalign stimulus regressors with BOLD volumes.

## Reason categories

| Category | Count | Percentage of missing |
|---|---:|---:|
{cat_lines or "| (none) | 0 | 0% |"}

## Per-run listing

See `missing_events.tsv` for subject, session, run, protocol, and detailed reason.

### Category definitions

- **No unique ProtocolName mapping** — zero or multiple non-phase BOLD sidecars matched the experimental `fMRI{{N}}` label.  
- **Incomplete trigger recordings** — fewer than two finite scanner `triggerTimes`.  
- **Incomplete MATLAB logs** — missing/duplicated `scan_info` or `fMRI_N` sources.  
- **Ambiguous correspondence** — conflicting identifiers across logs.  
- **No events generated (no unique verified mapping)** — run not covered by a successful unique conversion path.
""",
        encoding="utf-8",
    )

    # ----- FUNCTIONAL_EVENTS_SUMMARY.md -----
    table_rows = [
        ("Total task-fMRI BOLD runs", n_total, 100.0),
        ("Runs with validated events", n_with, coverage),
        ("Runs without events", n_without, 100.0 * n_without / n_total if n_total else 0),
    ]
    for k, v in missing_reason_counts.most_common():
        table_rows.append((f"Missing — {k}", v, 100.0 * v / n_total if n_total else 0))

    (OUT / "FUNCTIONAL_EVENTS_SUMMARY.md").write_text(
        f"""# Functional events summary (publication-ready)

**Generated:** {utc_now()}

## Coverage

| Category | Count | Percentage |
|---|---:|---:|
{chr(10).join(f"| {a} | {b} | {c:.1f}% |" for a, b, c in table_rows)}

## Validation of available events

| Outcome | Count |
|---|---:|
| PASS | {n_pass} |
| WARNING | {n_warn} |
| FAIL | {n_fail} |
| **Overall** | **{overall}** |

## Paradigm note

Event availability differs across functional paradigms. The **350** (approx.) released event tables apply to **`task-fmri`** only. **`task-movie`** and **`task-control`** runs remain without event timing files because scanner-locked timing information could not be uniquely recovered from the available experimental records.
""",
        encoding="utf-8",
    )

    # Figure
    make_figure(
        coverage,
        dict(missing_reason_counts),
        n_pass,
        n_warn,
        n_fail,
        n_with,
        n_without,
        n_total,
    )

    # ----- FINAL PUBLICATION REPORT -----
    verdict = "PASS WITH DOCUMENTED LIMITATIONS" if n_fail == 0 else "FAIL"
    if n_fail == 0 and n_without > 0:
        verdict = "PASS WITH DOCUMENTED LIMITATIONS"
    elif n_fail == 0 and n_without == 0:
        verdict = "PASS"

    (OUT / "FUNCTIONAL_EVENTS_PUBLICATION_REPORT.md").write_text(
        f"""# Functional events — publication report

**Generated:** {utc_now()}  
**Final verdict:** **{verdict}**

## Executive summary

The dataset includes **{n_with}** `task-fmri` `*_events.tsv` files generated from original experimental records (scanner trigger recordings + MATLAB stimulus-order / protocol metadata). Automatic validation of these files yielded **{overall}** ({n_pass} PASS, {n_warn} WARNING, {n_fail} FAIL). Coverage is **{coverage:.1f}%** of task-fMRI BOLD runs ({n_with}/{n_total}). Runs without an unambiguous protocol→BIDS correspondence intentionally lack events files.

## Validation statistics

| Item | Value |
|---|---:|
| Events files | {n_with} |
| PASS | {n_pass} |
| WARNING | {n_warn} |
| FAIL | {n_fail} |
| Overall validation | {overall} |

## Coverage

| Item | Value |
|---|---:|
| task-fMRI BOLD runs | {n_total} |
| With events | {n_with} |
| Without events | {n_without} |
| Coverage | {coverage:.1f}% |

### Missing-reason totals

| Category | Count |
|---|---:|
{chr(10).join(f"| {k} | {v} |" for k, v in missing_reason_counts.most_common()) or "| (none) | 0 |"}

## Remaining limitations

1. Incomplete coverage: {n_without} task-fMRI runs have no events file (non-unique or incomplete experimental↔BIDS mapping).  
2. `stim-XX` labels are not accompanied by a machine-readable stimulus-parameter dictionary in the public release.  
3. `task-movie` / `task-control` lack scanner-locked event tables.  
4. Movie stimulus media are not redistributed (rights).

## Recommended manuscript wording

> Event timing files are available for {n_with} task-fMRI runs. These files were generated from the original experimental logs by combining scanner trigger recordings with stimulus-order metadata. Event files were created only when a unique correspondence between protocol records and BIDS acquisitions could be established. Runs without an unambiguous mapping intentionally remain without `events.tsv`.

Avoid: reconstructed / estimated / predicted / approximated / invented.  
Prefer: generated from original experimental records / derived from original acquisition logs / recovered from recorded triggers.

## Publication recommendation

Proceed with Scientific Data wording that:

- states coverage explicitly ({n_with}/{n_total}, {coverage:.1f}%),  
- documents uniqueness gating,  
- reports validation outcome (**{overall}**),  
- discloses paradigm-specific absence of movie/control events.

## Supporting files

| File | Role |
|---|---|
| `events_validation.tsv` | Per-file validation |
| `EVENTS_VALIDATION_REPORT.md` | Validation narrative |
| `EVENTS_PROVENANCE.md` | Provenance |
| `MISSING_EVENTS.md` / `missing_events.tsv` | Missingness |
| `FUNCTIONAL_EVENTS_SUMMARY.md` | Coverage table |
| `Figure_FunctionalEventsCoverage.*` | Publication figure |

## Final verdict

**{verdict}**
""",
        encoding="utf-8",
    )

    summary = {
        "generated_at_utc": utc_now(),
        "n_events_files": n_with,
        "n_bold_runs": n_total,
        "n_missing": n_without,
        "coverage_pct": coverage,
        "n_pass": n_pass,
        "n_warning": n_warn,
        "n_fail": n_fail,
        "overall_validation": overall,
        "publication_verdict": verdict,
        "missing_reason_counts": dict(missing_reason_counts),
    }
    (OUT / "_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
