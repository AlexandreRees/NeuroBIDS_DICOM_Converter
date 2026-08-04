#!/usr/bin/env python3
"""Join verified events.tsv, recover SliceTiming from XA30 Enhanced DICOM, document longitudinal gaps.

Does not invent onsets, sampling rates, or SliceTiming from TR/slice-count heuristics.
Does not modify raw_original.
"""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pydicom

ROOT = Path("/home/alexrees/scratch")
BIDS = ROOT / "bids"
RC = ROOT / "release_candidate_level1"
REPORTS = ROOT / "reports" / "bids_validation_scientific_data"
SHARDS = ROOT / "reports" / "shards"
RAW = Path("/project/def-amirs/raw_original")

XA30_SESSIONS = [
    ("sub-054", "ses-02"),
    ("sub-056", "ses-01"),
    ("sub-061", "ses-01"),
    ("sub-062", "ses-01"),
    ("sub-063", "ses-01"),
]

# Prefer an existing readable path; Data_ON may live on project/lustre06 only.
# Historical scratch prefixes remain for remapping old inventory strings only.
DICOM_ROOT_CANDIDATES = [
    str(RAW) + "/",
    "/lustre06/project/6001995/raw_original/",
    "/project/def-amirs/raw_original/",
]
DICOM_PREFIXES = [
    "/project/def-amirs/raw_original/",
    "/lustre06/project/6001995/raw_original/",
    "/lustre07/scratch/alexrees/raw_original/",
    "/home/alexrees/scratch/raw_original/",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def remap_dicom_path(path: str) -> Path:
    """Resolve source_dicom to an existing file across known raw_original mounts."""
    original = Path(path)
    if original.exists():
        return original
    rel = None
    for prefix in DICOM_PREFIXES:
        if path.startswith(prefix):
            rel = path[len(prefix) :]
            break
    if rel is None:
        return original
    for root in DICOM_ROOT_CANDIDATES:
        cand = Path(root + rel)
        if cand.exists():
            return cand
    return Path(DICOM_ROOT_CANDIDATES[0] + rel)


def parse_dicom_dt(value: str) -> datetime:
    s = str(value)
    if "." in s:
        main, frac = s.split(".", 1)
        frac = (frac + "000000")[:6]
        return datetime.strptime(main + frac, "%Y%m%d%H%M%S%f")
    return datetime.strptime(s[:14], "%Y%m%d%H%M%S")


def slice_timing_from_enhanced(dcm_path: Path) -> list[float]:
    ds = pydicom.dcmread(
        str(dcm_path),
        stop_before_pixels=True,
        specific_tags=[
            "PerFrameFunctionalGroupsSequence",
            "NumberOfFrames",
            "RepetitionTime",
            "SOPClassUID",
        ],
        force=True,
    )
    if not hasattr(ds, "PerFrameFunctionalGroupsSequence"):
        raise ValueError("missing PerFrameFunctionalGroupsSequence")

    by_pos: dict[int, list[datetime]] = defaultdict(list)
    for fr in ds.PerFrameFunctionalGroupsSequence:
        ft = fr.FrameContentSequence[0]
        pos = int(ft.InStackPositionNumber)
        dt = parse_dicom_dt(ft.FrameAcquisitionDateTime)
        by_pos[pos].append(dt)
    if not by_pos:
        raise ValueError("no frames with InStackPositionNumber")
    # First-volume timing: earliest acquisition per slice position
    first_dt = {p: min(dts) for p, dts in by_pos.items()}
    positions = sorted(first_dt)
    t0 = min(first_dt.values())
    return [(first_dt[p] - t0).total_seconds() for p in positions]


def join_events(log_rows: list[dict]) -> dict:
    events = sorted(RC.glob("sub-*/ses-*/func/*_events.tsv"))
    n_copied = 0
    n_skip_exists = 0
    n_missing_bold = 0
    for src in events:
        rel = src.relative_to(RC)
        dest = BIDS / rel
        bold = dest.with_name(dest.name.replace("_events.tsv", "_bold.nii.gz"))
        if not bold.exists():
            n_missing_bold += 1
            log_rows.append(
                {
                    "action": "events_join",
                    "status": "missing_bold",
                    "source": str(src),
                    "dest": str(dest),
                    "bold": str(bold),
                }
            )
            continue
        if dest.exists():
            n_skip_exists += 1
            log_rows.append(
                {
                    "action": "events_join",
                    "status": "already_exists",
                    "source": str(src),
                    "dest": str(dest),
                    "bold": str(bold),
                }
            )
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        n_copied += 1
        log_rows.append(
            {
                "action": "events_join",
                "status": "copied",
                "source": str(src),
                "dest": str(dest),
                "bold": str(bold),
            }
        )
    return {
        "n_rc_events": len(events),
        "n_copied": n_copied,
        "n_skip_exists": n_skip_exists,
        "n_missing_bold": n_missing_bold,
    }


def load_conversion_index() -> tuple[dict[str, dict], dict[tuple[str, str, str], dict]]:
    """Map bids_filename stem -> record; also SeriesDescription key for fallbacks."""
    index: dict[str, dict] = {}
    by_series: dict[tuple[str, str, str], dict] = {}
    for report in sorted(SHARDS.glob("*/conversion_report.json")):
        data = json.loads(report.read_text())
        for rec in data.get("records", []):
            bf = rec.get("bids_filename")
            if not bf:
                continue
            rec = dict(rec)
            rec["_shard_report"] = str(report)
            index[bf] = rec
            # legacy invalid suffix seen in some conversion reports
            if bf.endswith("_bold_pha"):
                index[bf.replace("_bold_pha", "_part-phase_bold")] = rec
            sub = f"sub-{str(rec.get('participant_id') or rec.get('subject') or '').lstrip('sub-')}"
            # participant_id in reports may already be like 061 or sub-061
            pid = str(rec.get("participant_id") or "")
            if pid.startswith("sub-"):
                sub = pid
            elif pid.isdigit() or (pid and pid[:1].isdigit()):
                sub = f"sub-{int(pid):03d}" if pid.isdigit() else f"sub-{pid}"
            else:
                # fall back to parsing bids_filename
                parts = bf.split("_")
                sub = parts[0] if parts else sub
            ses = rec.get("session_label") or rec.get("session") or ""
            if ses and not str(ses).startswith("ses-"):
                ses = f"ses-{ses}"
            sd = rec.get("series_description") or ""
            if sub and ses and sd:
                by_series[(sub, ses, sd)] = rec
    return index, by_series


def recover_slicetiming(log_rows: list[dict]) -> dict:
    index, by_series = load_conversion_index()
    n_updated = 0
    n_fail = 0
    n_already = 0
    n_no_source = 0

    for sub, ses in XA30_SESSIONS:
        func = BIDS / sub / ses / "func"
        if not func.is_dir():
            continue
        for jpath in sorted(func.glob("*_bold.json")):
            meta = json.loads(jpath.read_text())
            if meta.get("SliceTiming"):
                n_already += 1
                log_rows.append(
                    {
                        "action": "slicetiming",
                        "status": "already_present",
                        "json": str(jpath),
                        "source_dicom": "",
                        "n_slices": len(meta["SliceTiming"]),
                        "detail": "",
                    }
                )
                continue

            # conversion records store bids_filename including modality suffix, e.g. ..._bold
            key = jpath.name.replace(".json", "")
            rec = index.get(key)
            if rec is None:
                sd = meta.get("SeriesDescription") or ""
                rec = by_series.get((sub, ses, sd))
            if rec is None:
                n_no_source += 1
                n_fail += 1
                log_rows.append(
                    {
                        "action": "slicetiming",
                        "status": "no_conversion_record",
                        "json": str(jpath),
                        "source_dicom": "",
                        "n_slices": "",
                        "detail": key,
                    }
                )
                continue

            src = remap_dicom_path(rec.get("source_dicom", ""))
            if not src.exists():
                n_no_source += 1
                n_fail += 1
                log_rows.append(
                    {
                        "action": "slicetiming",
                        "status": "dicom_missing",
                        "json": str(jpath),
                        "source_dicom": str(src),
                        "n_slices": "",
                        "detail": rec.get("source_dicom", ""),
                    }
                )
                continue

            try:
                st = slice_timing_from_enhanced(src)
                tr = float(meta.get("RepetitionTime", 0) or 0)
                if not st:
                    raise ValueError("empty SliceTiming")
                if min(st) < -1e-6:
                    raise ValueError(f"negative SliceTiming min={min(st)}")
                if tr > 0 and max(st) >= tr - 1e-6:
                    raise ValueError(f"SliceTiming max {max(st)} >= TR {tr}")
                # round for stable JSON (ms precision)
                st_out = [round(x, 6) for x in st]
                meta["SliceTiming"] = st_out
                jpath.write_text(json.dumps(meta, indent=2) + "\n")
                n_updated += 1
                log_rows.append(
                    {
                        "action": "slicetiming",
                        "status": "updated",
                        "json": str(jpath),
                        "source_dicom": str(src),
                        "n_slices": len(st_out),
                        "detail": f"max={max(st_out)};TR={tr};method=FrameAcquisitionDateTime+InStackPositionNumber;shard={rec.get('_shard_report','')}",
                    }
                )
            except Exception as exc:  # noqa: BLE001 — log and continue
                n_fail += 1
                log_rows.append(
                    {
                        "action": "slicetiming",
                        "status": "failed",
                        "json": str(jpath),
                        "source_dicom": str(src),
                        "n_slices": "",
                        "detail": str(exc),
                    }
                )

    return {
        "n_updated": n_updated,
        "n_fail": n_fail,
        "n_already": n_already,
        "n_no_source": n_no_source,
    }


def document_longitudinal() -> dict:
    subs = sorted(p.name for p in BIDS.glob("sub-*") if p.is_dir())
    rows = []
    both = only01 = only02 = neither = 0
    for sub in subs:
        has01 = (BIDS / sub / "ses-01").is_dir()
        has02 = (BIDS / sub / "ses-02").is_dir()
        if has01 and has02:
            coverage = "ses-01+ses-02"
            both += 1
        elif has01:
            coverage = "ses-01_only"
            only01 += 1
        elif has02:
            coverage = "ses-02_only"
            only02 += 1
        else:
            coverage = "none"
            neither += 1
        rows.append(
            {
                "participant_id": sub,
                "ses-01": "1" if has01 else "0",
                "ses-02": "1" if has02 else "0",
                "coverage": coverage,
            }
        )

    cov_tsv = REPORTS / "longitudinal_session_coverage.tsv"
    with cov_tsv.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["participant_id", "ses-01", "ses-02", "coverage"], delimiter="\t"
        )
        w.writeheader()
        w.writerows(rows)

    md = REPORTS / "LONGITUDINAL_COVERAGE.md"
    md.write_text(
        f"""# Incomplete longitudinal coverage

- Generated (UTC): `{utc_now()}`
- Subjects in `bids/`: **{len(subs)}**
- Both `ses-01` and `ses-02`: **{both}**
- `ses-01` only: **{only01}**
- `ses-02` only: **{only02}**
- Neither: **{neither}**

## Interpretation

This study is longitudinal (`ses-01`, `ses-02`), but **not every participant completed both sessions**. Missing sessions are real absences (not conversion failures to invent). BIDS validator warnings `MISSING_SESSION` and `INCONSISTENT_SUBJECTS` are therefore expected for this release.

Do **not** fabricate empty session folders or placeholder scans for missing visits.

## Machine-readable table

See `longitudinal_session_coverage.tsv` in this directory.
""",
        encoding="utf-8",
    )

    # Update bids/README (append section if not already present)
    readme = BIDS / "README"
    marker = "## Incomplete longitudinal coverage"
    section = f"""{marker}

This dataset includes two planned sessions (`ses-01`, `ses-02`), but longitudinal coverage is incomplete:

- {both}/{len(subs)} subjects have both sessions
- {only01}/{len(subs)} subjects have `ses-01` only
- {only02}/{len(subs)} subjects have `ses-02` only

Missing sessions reflect incomplete participant follow-up, not omitted files. Validator warnings `MISSING_SESSION` and `INCONSISTENT_SUBJECTS` are expected. Full table: `reports/bids_validation_scientific_data/longitudinal_session_coverage.tsv`.

## Task events

Verified `*_events.tsv` files (strict Level-1 release candidate) are included for a subset of `task-fmri` runs only. Movie/control task onsets that lack a unique verified protocol→BOLD mapping are intentionally withheld (no invented timings). Remaining `EVENTS_TSV_MISSING` warnings for those runs are expected until additional verified event files are released.

## SliceTiming (XA30)

For Siemens XA30 Enhanced MR sessions where dcm2niix did not export `SliceTiming`, values were recovered from DICOM `FrameAcquisitionDateTime` + `InStackPositionNumber` when available (see `reports/bids_validation_scientific_data/events_slicetiming_longitudinal_log.tsv`).
"""
    existing = readme.read_text(encoding="utf-8") if readme.exists() else ""
    if marker in existing:
        # replace from marker to end of file (our managed section)
        head = existing.split(marker)[0].rstrip() + "\n\n"
        readme.write_text(head + section, encoding="utf-8")
    else:
        readme.write_text(existing.rstrip() + "\n\n" + section, encoding="utf-8")

    return {
        "n_subjects": len(subs),
        "both": both,
        "ses01_only": only01,
        "ses02_only": only02,
        "coverage_tsv": str(cov_tsv),
        "coverage_md": str(md),
    }


def write_log(rows: list[dict], path: Path) -> None:
    fields = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    log_rows: list[dict] = []
    summary = {
        "generated_utc": utc_now(),
        "events": join_events(log_rows),
        "slicetiming": recover_slicetiming(log_rows),
        "longitudinal": document_longitudinal(),
    }
    log_path = REPORTS / "events_slicetiming_longitudinal_log.tsv"
    write_log(log_rows, log_path)
    summary_path = REPORTS / "events_slicetiming_longitudinal_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"log={log_path}")


if __name__ == "__main__":
    main()
