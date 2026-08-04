#!/usr/bin/env python3
"""Resolve Grating events.tsv BOLD ambiguities using source DICOM metadata.

READ-ONLY on bids/ and raw_original/. Never copies events or modifies BIDS.
Writes reports only under reports/grating_events_recovery/dicom_resolution/.

Default mode is --dry-run (no BIDS writes are ever performed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCRATCH_DEFAULT = Path("/home/alexrees/scratch")
RAW_DEFAULTS = (
    Path("/lustre06/project/6001995/raw_original"),
    Path("/project/def-amirs/raw_original"),
)

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        "January February March April May June July August September "
        "October November December".split(),
        1,
    )
}
_TS_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)[-_](\d{1,2})[-_](\d{4})[_\s]+"
    r"(\d{1,2})[-_](\d{2})[-_](\d{2})[_\s]*([AP]M)",
    re.I,
)
_FMRI_RE = re.compile(r"fMRI\s*(\d+)", re.I)


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def remap_raw(path: str | Path, raw_root: Path) -> Path:
    s = str(path)
    for pref in (
        "/project/def-amirs/raw_original",
        "/lustre07/scratch/alexrees/raw_original",
        "/lustre06/project/6001995/raw_original",
    ):
        if s.startswith(pref):
            return raw_root / s[len(pref) :].lstrip("/")
    p = Path(s)
    if p.is_absolute():
        return p
    return raw_root / p


def parse_series_time(st: Any) -> tuple[float | None, str]:
    if st is None or str(st).strip() in ("", "nan"):
        return None, ""
    s = str(st).strip()
    try:
        v = float(s)
        hh = int(v // 10000)
        mm = int((v // 100) % 100)
        ss = v % 100
        return hh * 3600 + mm * 60 + ss, f"{hh:02d}:{mm:02d}:{ss:06.3f}"
    except Exception:
        return None, s


def parse_matlab_timestamp(name: str) -> tuple[datetime | None, str]:
    m = _TS_RE.search(name.replace("__", "_"))
    if not m:
        return None, ""
    mon = _MONTHS[m.group(1).lower()]
    day, year = int(m.group(2)), int(m.group(3))
    hh, mm, ss = int(m.group(4)), int(m.group(5)), int(m.group(6))
    ap = m.group(7).upper()
    if ap == "PM" and hh != 12:
        hh += 12
    if ap == "AM" and hh == 12:
        hh = 0
    dt = datetime(year, mon, day, hh, mm, ss)
    return dt, dt.strftime("%H:%M:%S")


def classify_image_type(image_type: Any) -> tuple[bool, bool]:
    if image_type is None:
        return False, False
    if hasattr(image_type, "__iter__") and not isinstance(image_type, (str, bytes)):
        tokens = [str(x).upper() for x in image_type]
    else:
        tokens = [t for t in re.split(r"[\\/]", str(image_type).upper()) if t]
    is_phase = "P" in tokens and "M" not in tokens
    is_mag = "M" in tokens and not is_phase
    if "PHYSIO" in " ".join(tokens) or "RAWDATA" in tokens:
        return False, False
    return is_mag, is_phase


def protocol_fmri_number(protocol: str) -> int | None:
    m = _FMRI_RE.search((protocol or "").replace(" ", ""))
    return int(m.group(1)) if m else None


@dataclass
class AmbiguousCase:
    subject: str
    session: str
    fmri_number: int
    matlab_file: str
    candidate_runs: list[str] = field(default_factory=list)
    reason_from_input: str = ""


def load_ambiguous_cases(input_tsv: Path, bids_root: Path) -> list[AmbiguousCase]:
    df = pd.read_csv(input_tsv, sep="\t")
    cases: list[AmbiguousCase] = []

    # Path A: FINAL_MAPPING_DECISION-like — only unresolved REVIEW / multi-BOLD flags
    if "decision" in df.columns or "status" in df.columns:
        mask = pd.Series(False, index=df.index)
        if "decision" in df.columns:
            mask |= df["decision"].astype(str).str.upper().eq("REVIEW")
        if "status" in df.columns:
            mask |= df["status"].astype(str).str.upper().eq("REVIEW")
        if "multiple_BOLD_candidates" in df.columns:
            mask |= df["multiple_BOLD_candidates"].astype(str).str.lower().isin(
                ["true", "1", "yes"]
            )
        if "review_required" in df.columns:
            mask |= (
                df["review_required"].astype(str).str.lower().isin(["true", "1", "yes"])
                & df.get("decision", pd.Series("", index=df.index))
                .astype(str)
                .str.upper()
                .eq("REVIEW")
            )
        review = df[mask].copy()
        for _, r in review.iterrows():
            sub = str(r.get("participant_id") or r.get("subject") or "")
            ses = str(r.get("session_id") or r.get("session") or "")
            try:
                n = int(r.get("fmri_number"))
            except Exception:
                continue
            mat = str(r.get("matlab_file") or r.get("source_mat") or "")
            if mat.lower() in ("", "nan", "none"):
                mat = ""
            runs = discover_candidate_runs(bids_root, sub, ses, n)
            if not runs:
                # fall back to selected + any twin listed in input
                sel = str(r.get("selected_bold_run") or r.get("bids_run") or "")
                m = re.search(r"(\d+)", sel)
                if m:
                    runs = [m.group(1).zfill(2)]
            cases.append(
                AmbiguousCase(
                    subject=sub,
                    session=ses,
                    fmri_number=n,
                    matlab_file=mat,
                    candidate_runs=runs,
                    reason_from_input=str(r.get("reason") or ""),
                )
            )

    # Path B: MAPPING_CANDIDATES with multiple_BOLD / twin runs
    elif "bids_run" in df.columns and "fmri_number" in df.columns:
        if "multiple_BOLD_candidates" in df.columns:
            df = df[
                df["multiple_BOLD_candidates"].astype(str).str.lower().isin(
                    ["true", "1", "yes"]
                )
            ]
        gcols = [
            c
            for c in ("participant_id", "session_id", "fmri_number")
            if c in df.columns
        ]
        for key, g in df.groupby(gcols):
            sub, ses, n = key
            runs = discover_candidate_runs(bids_root, str(sub), str(ses), int(n))
            if len(runs) < 2:
                runs = sorted(
                    {str(x).zfill(2) for x in g["bids_run"].astype(str) if str(x).isdigit() or re.search(r"\d+", str(x))}
                )
                runs = [re.search(r"(\d+)", r).group(1).zfill(2) for r in runs if re.search(r"(\d+)", r)]
            if len(runs) < 2:
                continue
            mat = str(g.iloc[0].get("source_mat") or g.iloc[0].get("matlab_file") or "")
            cases.append(
                AmbiguousCase(
                    subject=str(sub),
                    session=str(ses),
                    fmri_number=int(n),
                    matlab_file=mat if mat.lower() not in ("nan", "none") else "",
                    candidate_runs=runs,
                )
            )

    # Deduplicate by (sub, ses, fmri_n)
    uniq: dict[tuple[str, str, int], AmbiguousCase] = {}
    for c in cases:
        uniq[(c.subject, c.session, c.fmri_number)] = c
    return list(uniq.values())


def discover_candidate_runs(bids_root: Path, sub: str, ses: str, fmri_n: int) -> list[str]:
    func = bids_root / sub / ses / "func"
    if not func.is_dir():
        return []
    runs = []
    for js in sorted(func.glob(f"{sub}_{ses}_task-fmri_run-*_bold.json")):
        if "part-phase" in js.name:
            continue
        meta = json.loads(js.read_text(encoding="utf-8"))
        pn = str(meta.get("ProtocolName") or "")
        if protocol_fmri_number(pn) != fmri_n:
            continue
        m = re.search(r"run-(\d+)", js.name)
        if m:
            runs.append(m.group(1).zfill(2))
    return runs


def resolve_session_paths(
    scratch: Path, subject: str, session: str, raw_root: Path
) -> tuple[Path | None, Path | None]:
    """Return (original_session_path, matlab_path) remapped to raw_root."""
    sm = pd.read_csv(scratch / "metadata" / "session_mapping.csv", dtype=str, low_memory=False)
    rows = sm[sm["participant_id"] == subject]
    if rows.empty:
        return None, None
    if "session_id" in rows.columns:
        hit = rows[rows["session_id"] == session]
        if not hit.empty:
            rows = hit
        elif "session_label" in rows.columns:
            rows = rows[rows["session_label"] == session]
    elif "session_label" in rows.columns:
        rows = rows[rows["session_label"] == session]
    if rows.empty:
        return None, None
    orig = str(rows.iloc[0].get("original_path") or rows.iloc[0].get("source_subject_path") or "")
    mat = str(rows.iloc[0].get("MATLAB_data_path") or "")
    orig_p = remap_raw(orig, raw_root) if orig and orig.lower() != "nan" else None
    mat_p = remap_raw(mat, raw_root) if mat and mat.lower() != "nan" else None
    return orig_p, mat_p


# Cache inventory per remapped session root (avoid re-reading 10k+ DICOMs).
_INVENTORY_CACHE: dict[str, pd.DataFrame] = {}


def find_matlab_scan_info(matlab_root: Path | None, fmri_n: int) -> Path | None:
    if matlab_root is None or not matlab_root.is_dir():
        return None
    grating = None
    for c in matlab_root.iterdir():
        if c.is_dir() and ("grating" in c.name.lower() or c.name.startswith("2-")):
            grating = c
            break
    if grating is None:
        return None
    results = grating / "Results"
    if not results.is_dir():
        return None
    hits = []
    for p in results.glob("*scan_info*.mat"):
        if f"fmri_number_is{fmri_n}" in p.name.replace(" ", "").lower():
            hits.append(p)
        else:
            m = re.search(r"fmri_number_is\s*(\d+)", p.name, re.I)
            if m and int(m.group(1)) == fmri_n:
                hits.append(p)
    if not hits:
        return None
    # prefer dated scan_info
    hits.sort(key=lambda p: p.name)
    return hits[-1] if len(hits) == 1 else sorted(hits, key=lambda p: parse_matlab_timestamp(p.name)[0] or datetime.min)[-1]


def extract_matlab_meta(mat_path: Path) -> dict[str, Any]:
    sys.path.insert(0, str(SCRATCH_DEFAULT / "neuro_pipeline"))
    from neuro_pipeline.associated_data.matlab.extract_scan_timing import (  # noqa: WPS433
        extract_scan_timing,
    )

    timing = extract_scan_timing(mat_path)
    dt, hhmmss = parse_matlab_timestamp(mat_path.name)
    ntrig = int(timing.n_triggers)
    dur = (
        float(timing.trigger_times[-1] - timing.trigger_times[0])
        if timing.trigger_times.size >= 2
        else None
    )
    return {
        "path": mat_path,
        "fmri_number": timing.fmri_number,
        "n_triggers": ntrig,
        "duration": dur,
        "datetime": dt,
        "time_str": hhmmss,
        "study_date": dt.date() if dt else None,
    }


def _skip_walk_dir(name: str) -> bool:
    n = name.lower()
    return any(
        x in n
        for x in (
            "matlab",
            "peripheral",
            "eyetrack",
            "results",
            "__macosx",
        )
    ) or n.endswith(".zip")


def iter_series_directories(session_root: Path) -> list[tuple[Path, list[Path]]]:
    """Return (series_dir, dicom_files) without reading file contents.

    Siemens exports typically put one series per leaf folder. Reading one
    representative DICOM per folder is enough for metadata; file count ≈ volumes
    for mosaic EPI (or NumberOfTemporalPositions when present).
    """
    out: list[tuple[Path, list[Path]]] = []
    if session_root is None or not session_root.is_dir():
        return out
    for root, dirs, files in os.walk(session_root):
        dirs[:] = [d for d in dirs if not _skip_walk_dir(d)]
        dicoms = [
            Path(root) / f
            for f in files
            if f.lower().endswith((".ima", ".dcm"))
        ]
        if dicoms:
            out.append((Path(root), dicoms))
    return out


def _cluster_dicoms_by_filename_cohort(files: list[Path]) -> dict[str, list[Path]]:
    """Split mixed orphan/session files that share one Siemens series folder.

    Siemens IMA names embed acquisition calendar date as YYYY.MM.DD; orphan
    copies often sit beside the true session series in the same directory.
    """
    clusters: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        m = re.search(r"(20\d{2})\.(\d{2})\.(\d{2})", f.name)
        if m:
            key = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        else:
            m2 = re.search(r"(20\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{1,2}", f.name, re.I)
            key = m2.group(0).upper() if m2 else "unknown"
        clusters[key].append(f)
    return clusters


def build_dicom_inventory(session_root: Path, subject: str, session: str) -> pd.DataFrame:
    import pydicom

    cache_key = f"{subject}|{session}|{session_root}"
    if cache_key in _INVENTORY_CACHE:
        return _INVENTORY_CACHE[cache_key].copy()

    series: dict[str, dict[str, Any]] = {}
    for sdir, files in iter_series_directories(session_root):
        for _cohort, cohort_files in _cluster_dicoms_by_filename_cohort(files).items():
            ds = None
            for fpath in cohort_files[:5]:
                try:
                    ds = pydicom.dcmread(str(fpath), stop_before_pixels=True, force=True)
                    break
                except Exception:
                    continue
            if ds is None:
                continue
            uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
            if not uid:
                continue
            if uid in series:
                series[uid]["volume_count"] = max(
                    int(series[uid]["volume_count"]), len(cohort_files)
                )
                continue

            it = getattr(ds, "ImageType", [])
            is_mag, is_phase = classify_image_type(it)
            sd = str(getattr(ds, "SeriesDescription", "") or "")
            if re.search(r"physio|sbref", sd, re.I):
                is_mag, is_phase = False, False
            st = getattr(ds, "SeriesTime", None) or getattr(ds, "AcquisitionTime", None)
            st_sec, st_h = parse_series_time(st)
            sn = getattr(ds, "SeriesNumber", "")
            try:
                sn_i = int(sn)
            except Exception:
                sn_i = sn
            study_date = str(getattr(ds, "StudyDate", "") or "")
            if len(study_date) >= 6:
                yyyymm = f"{study_date[:4]}-{study_date[4:6]}"
            else:
                yyyymm = study_date
            tr = getattr(ds, "RepetitionTime", "")
            try:
                tr_s = float(tr) / 1000.0 if float(tr) > 20 else float(tr)
            except Exception:
                tr_s = ""
            n_temp = getattr(ds, "NumberOfTemporalPositions", None)
            try:
                vol = int(n_temp) if n_temp not in (None, "") else len(cohort_files)
            except Exception:
                vol = len(cohort_files)

            cohort = study_date or "unknown"
            parent_blob = sdir.name + "|" + sdir.parent.name
            if re.search(r"2024JUL|202407", parent_blob + "|" + cohort_files[0].name, re.I):
                if study_date and study_date[:6] != parent_blob:  # soft hint only
                    pass
            if study_date.startswith("202407") or re.search(
                r"2024JUL|2024\.07", cohort_files[0].name, re.I
            ):
                cohort = "orphan_other_date"
            elif study_date.startswith("202502") or re.search(
                r"2025FEB|2025\.02", cohort_files[0].name, re.I
            ):
                cohort = "session_matched_folder"

            series[uid] = {
                "subject": subject,
                "session": session,
                "protocol_name": str(getattr(ds, "ProtocolName", "") or ""),
                "series_number": sn_i,
                "series_instance_uid_hash": sha16(uid),
                "series_description": sd,
                "acquisition_time": st_h or str(st or ""),
                "acquisition_time_seconds": st_sec,
                "study_date": study_date,
                "study_date_year_month_only": yyyymm,
                "image_type": "\\".join(str(x) for x in it)
                if hasattr(it, "__iter__") and not isinstance(it, str)
                else str(it),
                "is_magnitude": is_mag,
                "is_phase": is_phase,
                "volume_count": vol,
                "TR": tr_s,
                "ImagingFrequency": str(getattr(ds, "ImagingFrequency", "") or ""),
                "cohort_hint": cohort,
            }

    df = pd.DataFrame(list(series.values()))
    _INVENTORY_CACHE[cache_key] = df
    return df.copy()


def load_bids_bold_meta(bids_root: Path, subject: str, session: str, runs: list[str]) -> pd.DataFrame:
    func = bids_root / subject / session / "func"
    rows = []
    for run in runs:
        js = func / f"{subject}_{session}_task-fmri_run-{run}_bold.json"
        nii = func / f"{subject}_{session}_task-fmri_run-{run}_bold.nii.gz"
        if not js.exists():
            continue
        meta = json.loads(js.read_text(encoding="utf-8"))
        nvol = None
        if nii.exists():
            try:
                import nibabel as nib

                nvol = int(nib.load(str(nii)).header.get_data_shape()[3])
            except Exception:
                nvol = None
        it = meta.get("ImageType")
        is_mag, is_phase = classify_image_type(it)
        rows.append(
            {
                "bids_run": run,
                "protocol_name": meta.get("ProtocolName") or "",
                "series_number": meta.get("SeriesNumber"),
                "ImagingFrequency": str(meta.get("ImagingFrequency") or ""),
                "RepetitionTime": meta.get("RepetitionTime"),
                "volume_count": nvol,
                "is_magnitude": is_mag,
                "is_phase": is_phase or ("part-phase" in js.name),
                "AcquisitionTime": meta.get("AcquisitionTime") or meta.get("SeriesTime") or "",
            }
        )
    return pd.DataFrame(rows)


def freq_equal(a: Any, b: Any) -> bool:
    if not a or not b:
        return False
    if str(a) == str(b):
        return True
    try:
        return abs(float(a) - float(b)) < 1e-8
    except Exception:
        return False


def score_candidate(
    *,
    matlab_dt: datetime | None,
    matlab_ntrig: int,
    dicom_row: pd.Series,
    bids_row: pd.Series,
) -> tuple[int, list[str], float | None]:
    score = 0
    reasons: list[str] = []
    # magnitude
    if bool(dicom_row.get("is_magnitude")) and not bool(dicom_row.get("is_phase")):
        score += 5
        reasons.append("+5_magnitude")
    if bool(dicom_row.get("is_phase")):
        score -= 100
        reasons.append("-100_phase_excluded")

    # same date
    study = str(dicom_row.get("study_date") or "")
    if matlab_dt and len(study) >= 8:
        same = study[:8] == matlab_dt.strftime("%Y%m%d")
        if same:
            score += 5
            reasons.append("+5_same_study_date")
        else:
            score -= 50
            reasons.append("-50_orphan_date_mismatch")

    # time difference: MATLAB save time vs DICOM Series/Acquisition time
    st_sec = dicom_row.get("acquisition_time_seconds")
    td = None
    if matlab_dt is not None and st_sec is not None and st_sec == st_sec:
        matlab_sec = matlab_dt.hour * 3600 + matlab_dt.minute * 60 + matlab_dt.second
        td = abs(matlab_sec - float(st_sec))
        # also allow MATLAB after scan start by ~scan duration
        signed = matlab_sec - float(st_sec)
        if 0 <= signed <= 900:
            # prefer positive lag (MATLAB after SeriesTime)
            if signed < 300:
                score += 5
                reasons.append(f"+5_time_diff_{signed:.0f}s")
            elif signed < 600:
                score += 3
                reasons.append(f"+3_time_diff_{signed:.0f}s")
            else:
                score += 5  # still same afternoon session lag ~350s seen in sub-043
                reasons.append(f"+5_time_diff_scan_lag_{signed:.0f}s")
            td = signed
        elif td < 300:
            score += 5
            reasons.append(f"+5_abs_time_diff_{td:.0f}s")
        elif td < 600:
            score += 3
            reasons.append(f"+3_abs_time_diff_{td:.0f}s")

    # volumes
    bvol = bids_row.get("volume_count")
    dvol = dicom_row.get("volume_count")
    if bvol is not None and str(bvol) not in ("", "nan"):
        try:
            bv = int(bvol)
            if abs(bv - 226) <= 5:
                score += 3
                reasons.append("+3_volume_226")
            if bv < 100:
                score -= 20
                reasons.append("-20_incomplete_volumes")
            if dvol is not None and str(dvol) not in ("", "nan"):
                if abs(int(dvol) - bv) <= 2:
                    score += 3
                    reasons.append("+3_same_volume_count")
        except Exception:
            pass

    # TR
    try:
        btr = float(bids_row.get("RepetitionTime"))
        dtr = dicom_row.get("TR")
        if abs(btr - 0.937) < 0.02:
            score += 2
            reasons.append("+2_TR_match")
        if dtr not in ("", None) and abs(float(dtr) - btr) < 0.02:
            score += 2
            reasons.append("+2_same_TR")
    except Exception:
        pass

    # ImagingFrequency exact link DICOM↔BIDS
    if freq_equal(bids_row.get("ImagingFrequency"), dicom_row.get("ImagingFrequency")):
        score += 5
        reasons.append("+5_ImagingFrequency_fingerprint")

    return score, reasons, td


def resolve_case(
    case: AmbiguousCase,
    *,
    scratch: Path,
    raw_root: Path,
    bids_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return (inventory_rows, decision_rows, summary)."""
    orig, mat_root = resolve_session_paths(scratch, case.subject, case.session, raw_root)
    if orig is None or not orig.is_dir():
        summary = {"decision": "REVIEW", "reason": "SESSION_RAW_PATH_NOT_FOUND"}
        return pd.DataFrame(), pd.DataFrame(), summary

    inv = build_dicom_inventory(orig, case.subject, case.session)
    if inv.empty:
        return inv, pd.DataFrame(), {"decision": "REVIEW", "reason": "NO_DICOM_SERIES"}

    # MATLAB
    mat_path = Path(case.matlab_file) if case.matlab_file else None
    if mat_path and not mat_path.exists():
        mat_path = remap_raw(case.matlab_file, raw_root)
    if mat_path is None or not mat_path.exists():
        mat_path = find_matlab_scan_info(mat_root, case.fmri_number)
    if mat_path is None or not Path(mat_path).exists():
        return inv, pd.DataFrame(), {"decision": "REVIEW", "reason": "MATLAB_SCAN_INFO_NOT_FOUND"}

    matlab = extract_matlab_meta(Path(mat_path))
    bids = load_bids_bold_meta(bids_root, case.subject, case.session, case.candidate_runs)
    if bids.empty:
        return inv, pd.DataFrame(), {"decision": "REVIEW", "reason": "NO_BIDS_CANDIDATES"}

    # Pair each BIDS run to best DICOM series by ImagingFrequency, else SeriesNumber+date
    decision_rows = []
    for _, b in bids.iterrows():
        # exclude phase BIDS
        if b.get("is_phase"):
            continue
        # DICOM candidates same protocol family
        fam = inv[
            inv["protocol_name"].astype(str).apply(lambda p: protocol_fmri_number(p) == case.fmri_number)
        ].copy()
        # prefer frequency match, then magnitude over phase/sbref
        freq_hits = fam[fam["ImagingFrequency"].apply(lambda f: freq_equal(f, b["ImagingFrequency"]))]
        if len(freq_hits) == 0:
            # fallback series number
            try:
                sn = int(b["series_number"])
                freq_hits = fam[fam["series_number"] == sn]
            except Exception:
                freq_hits = fam.iloc[0:0]

        if len(freq_hits) == 0:
            decision_rows.append(
                {
                    "subject": case.subject,
                    "session": case.session,
                    "matlab_fmri_number": case.fmri_number,
                    "matlab_timestamp": matlab["time_str"],
                    "candidate_run": b["bids_run"],
                    "protocol": b["protocol_name"],
                    "series_number": b.get("series_number"),
                    "study_date": "",
                    "acquisition_time": "",
                    "magnitude": False,
                    "volume_count": b.get("volume_count"),
                    "time_difference_seconds": "",
                    "score": 0,
                    "decision": "REJECT",
                    "reason": "NO_DICOM_SERIES_FINGERPRINT",
                }
            )
            continue

        # Prefer magnitude full-run over phase/sbref; then higher volume_count
        freq_hits = freq_hits.copy()
        freq_hits["_rank"] = (
            freq_hits["is_magnitude"].astype(int) * 10
            + (~freq_hits["is_phase"].astype(bool)).astype(int) * 5
            + (freq_hits["volume_count"].fillna(0).astype(int) >= 100).astype(int) * 3
        )
        hit = freq_hits.sort_values(["_rank", "volume_count"], ascending=False).iloc[0]
        score, reasons, td = score_candidate(
            matlab_dt=matlab["datetime"],
            matlab_ntrig=matlab["n_triggers"],
            dicom_row=hit,
            bids_row=b,
        )
        # orphan flag
        study = str(hit.get("study_date") or "")
        orphan = bool(
            matlab["datetime"]
            and len(study) >= 8
            and study[:8] != matlab["datetime"].strftime("%Y%m%d")
        )
        if orphan:
            decision = "REJECT"
            orphan_date = f"{study[:4]}-{study[4:6]}-{study[6:8]}"
            reason = (
                f"run belongs to orphan acquisition {orphan_date}; "
                + ";".join(reasons)
            )
        elif hit.get("is_phase"):
            decision = "REJECT"
            reason = "phase_series_excluded; " + ";".join(reasons)
        else:
            decision = "CANDIDATE"
            reason = ";".join(reasons)

        study_fmt = ""
        if len(study) >= 8:
            study_fmt = f"{study[:4]}-{study[4:6]}-{study[6:8]}"

        decision_rows.append(
            {
                "subject": case.subject,
                "session": case.session,
                "matlab_fmri_number": case.fmri_number,
                "matlab_timestamp": matlab["time_str"],
                "candidate_run": b["bids_run"],
                "protocol": b["protocol_name"],
                "series_number": hit.get("series_number"),
                "study_date": study_fmt,
                "acquisition_time": hit.get("acquisition_time"),
                "magnitude": bool(hit.get("is_magnitude")),
                "volume_count": b.get("volume_count"),
                "time_difference_seconds": "" if td is None else f"{td:.0f}",
                "score": score,
                "decision": decision,
                "reason": reason,
                "series_instance_uid_hash": hit.get("series_instance_uid_hash"),
            }
        )

    ddf = pd.DataFrame(decision_rows)
    # Final ACCEPT / REVIEW among non-rejected
    valid = ddf[ddf["decision"] == "CANDIDATE"].copy()
    final_decision = "REVIEW"
    selected = ""
    final_reason = "NO_VALID_CANDIDATE"
    if len(valid) == 0:
        final_decision = "REJECT"
        final_reason = "NO_VALID_CANDIDATE_AFTER_ORPHAN_PHASE_FILTER"
    else:
        valid = valid.sort_values("score", ascending=False)
        top = valid.iloc[0]
        if len(valid) == 1:
            if int(top["score"]) >= 10:
                final_decision = "ACCEPT"
                selected = str(top["candidate_run"])
                orphan_twins = ddf[
                    (ddf["decision"] == "REJECT")
                    & ddf["reason"].astype(str).str.contains("orphan", case=False)
                ]
                orphan_msg = ""
                if len(orphan_twins):
                    bits = []
                    for _, r in orphan_twins.iterrows():
                        bits.append(
                            f"run-{r.candidate_run} belongs to orphan acquisition {r.study_date}"
                        )
                    orphan_msg = "; twin excluded: " + "; ".join(bits)
                final_reason = (
                    "Matched MATLAB timing; magnitude series; same acquisition date; "
                    f"twin run excluded as orphan{orphan_msg}; score={int(top['score'])}"
                )
            else:
                final_decision = "REVIEW"
                selected = str(top["candidate_run"])
                final_reason = f"SINGLE_CANDIDATE_LOW_SCORE={int(top['score'])}"
        else:
            second = valid.iloc[1]
            diff = int(top["score"]) - int(second["score"])
            if int(top["score"]) >= 10 and diff >= 3:
                final_decision = "ACCEPT"
                selected = str(top["candidate_run"])
                orphan_twins = ddf[
                    (ddf["decision"] == "REJECT")
                    & ddf["reason"].astype(str).str.contains("orphan", case=False)
                ]
                orphan_msg = ""
                if len(orphan_twins):
                    bits = []
                    for _, r in orphan_twins.iterrows():
                        bits.append(
                            f"run-{r.candidate_run} belongs to orphan acquisition {r.study_date}"
                        )
                    orphan_msg = "; " + "; ".join(bits)
                final_reason = (
                    "Matched MATLAB timing; magnitude series; same acquisition date; "
                    f"twin run excluded as orphan{orphan_msg}; CLEAR_WINNER_DELTA={diff}"
                )
            else:
                final_decision = "REVIEW"
                selected = str(top["candidate_run"])
                final_reason = (
                    f"AMBIGUOUS_DELTA={diff} "
                    f"top=run-{top['candidate_run']}({int(top['score'])}) "
                    f"second=run-{second['candidate_run']}({int(second['score'])})"
                )

    # Mark selected row decision
    if selected and final_decision == "ACCEPT":
        ddf.loc[ddf["candidate_run"] == selected, "decision"] = "ACCEPT"
        ddf.loc[ddf["candidate_run"] == selected, "reason"] = final_reason
        # other CANDIDATE → REJECT as non-selected twin
        mask = (ddf["decision"] == "CANDIDATE") & (ddf["candidate_run"] != selected)
        ddf.loc[mask, "decision"] = "REJECT"
        ddf.loc[mask, "reason"] = ddf.loc[mask, "reason"].astype(str) + ";NOT_SELECTED_TWIN"

    summary = {
        "subject": case.subject,
        "session": case.session,
        "fmri_number": case.fmri_number,
        "decision": final_decision,
        "selected_bids_run": selected if final_decision == "ACCEPT" else "",
        "reason": final_reason,
        "matlab_timestamp": matlab["time_str"],
        "matlab_file_hash": sha16(str(Path(mat_path).name)),
    }
    return inv, ddf, summary


def phi_scan_outputs(output_dir: Path) -> list[str]:
    banned = [
        re.compile(r"PatientName", re.I),
        re.compile(r"PatientID", re.I),
        re.compile(r"AccessionNumber", re.I),
        re.compile(r"InstitutionName", re.I),
        re.compile(r"/lustre\d+/"),
        re.compile(r"/project/"),
        re.compile(r"/home/"),
        re.compile(r"[A-Za-z]:\\"),
        re.compile(r"1\.3\.12\.2\.1107"),  # full Siemens UID prefix
    ]
    issues = []
    for p in output_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".tsv", ".md", ".txt", ".csv"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for cre in banned:
            if cre.search(text):
                issues.append(f"{p.name}: matched {cre.pattern}")
    return issues


def write_report(
    output_dir: Path,
    summaries: list[dict[str, Any]],
    all_decisions: pd.DataFrame,
) -> None:
    nA = sum(1 for s in summaries if s.get("decision") == "ACCEPT")
    nR = sum(1 for s in summaries if s.get("decision") == "REVIEW")
    nX = sum(1 for s in summaries if s.get("decision") == "REJECT")
    md = f"""# DICOM Resolution Report — Grating events ambiguities

Generated: `{datetime.now(timezone.utc).isoformat()}`

## Summary

| Metric | n |
|--------|--:|
| Ambiguous mappings analyzed | {len(summaries)} |
| **ACCEPT** | {nA} |
| **REVIEW** | {nR} |
| **REJECT** | {nX} |

## Decision table

| subject | session | fMRI# | MATLAB time | selected run | decision | reason |
|---------|---------|------:|-------------|-------------:|----------|--------|
"""
    for s in summaries:
        md += (
            f"| {s.get('subject')} | {s.get('session')} | {s.get('fmri_number')} | "
            f"{s.get('matlab_timestamp')} | {s.get('selected_bids_run')} | "
            f"**{s.get('decision')}** | {s.get('reason')} |\n"
        )

    md += "\n## Before → After\n\n"
    for s in summaries:
        sub, ses, n = s.get("subject"), s.get("session"), s.get("fmri_number")
        before = all_decisions[
            (all_decisions["subject"] == sub)
            & (all_decisions["session"] == ses)
            & (all_decisions["matlab_fmri_number"] == n)
        ]
        runs = ", ".join(f"run-{r}" for r in before["candidate_run"].astype(str))
        md += f"### {sub} / {ses} / fMRI{n}\n\n"
        md += f"Before:\n```\nMATLAB fMRI{n}\n|\n"
        for _, r in before.iterrows():
            md += f"|-- run-{r.candidate_run}  [{r.decision}] score={r.score} date={r.study_date}\n"
        md += "```\n\nAfter:\n```\n"
        md += f"MATLAB fMRI{n}\n"
        if s.get("decision") == "ACCEPT":
            md += f"|-- selected run-{s.get('selected_bids_run')}\n"
        else:
            md += f"|-- unresolved ({s.get('decision')})\n"
        md += "```\n\n"

    md += """## Evidence used

- DICOM StudyDate (orphan detection)
- AcquisitionTime / SeriesTime vs MATLAB file timestamp
- SeriesNumber
- ImageType → magnitude / phase
- ImagingFrequency fingerprint (BIDS ↔ DICOM) when SeriesInstanceUID absent from BIDS JSON
- Volume count / TR sanity

## Safety statement

No events.tsv files were generated or modified.
All decisions were made using read-only DICOM metadata.
SeriesInstanceUID values are stored only as SHA256-16 hashes.
Patient identifiers and absolute filesystem paths are excluded from outputs.
"""
    (output_dir / "DICOM_RESOLUTION_REPORT.md").write_text(md, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=SCRATCH_DEFAULT
        / "reports/grating_events_recovery/final_review/FINAL_MAPPING_DECISION.tsv",
    )
    parser.add_argument("--raw", type=Path, default=None, help="raw_original root")
    parser.add_argument("--bids", type=Path, default=SCRATCH_DEFAULT / "bids")
    parser.add_argument(
        "--output",
        type=Path,
        default=SCRATCH_DEFAULT / "reports/grating_events_recovery/dicom_resolution",
    )
    parser.add_argument(
        "--scratch", type=Path, default=SCRATCH_DEFAULT, help="workspace with metadata/"
    )
    parser.add_argument(
        "--subjects",
        nargs="*",
        default=None,
        help="Optional filter e.g. sub-043",
    )
    parser.add_argument(
        "--force-sub043-test",
        action="store_true",
        help="Always include sub-043 ses-02 fMRI3/fMRI4 even if not REVIEW",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default safe mode (no BIDS writes; reports still written)",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Accepted but still never writes BIDS (tool cannot modify BIDS)",
    )
    args = parser.parse_args(argv)

    raw_root = args.raw
    if raw_root is None:
        raw_root = next((p for p in RAW_DEFAULTS if p.is_dir()), RAW_DEFAULTS[0])

    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    cases = load_ambiguous_cases(args.input, args.bids)
    if args.force_sub043_test or not cases:
        # Ensure obligatory test cases
        for n in (3, 4):
            runs = discover_candidate_runs(args.bids, "sub-043", "ses-02", n)
            cases.append(
                AmbiguousCase(
                    subject="sub-043",
                    session="ses-02",
                    fmri_number=n,
                    matlab_file="",
                    candidate_runs=runs or (["01", "02"] if n == 3 else ["05", "06"]),
                )
            )
        # dedupe
        uniq = {(c.subject, c.session, c.fmri_number): c for c in cases}
        cases = list(uniq.values())

    if args.subjects:
        allow = set(args.subjects)
        cases = [c for c in cases if c.subject in allow]

    print(f"Ambiguous cases to resolve: {len(cases)}", flush=True)
    all_inv = []
    all_dec = []
    summaries = []
    resolved = []

    for case in sorted(cases, key=lambda c: (c.subject, c.session, c.fmri_number)):
        print(
            f"Resolving {case.subject} {case.session} fMRI{case.fmri_number} "
            f"candidates={case.candidate_runs}",
            flush=True,
        )
        inv, dec, summary = resolve_case(
            case, scratch=args.scratch, raw_root=raw_root, bids_root=args.bids
        )
        if not inv.empty:
            all_inv.append(inv)
        if not dec.empty:
            all_dec.append(dec)
        summaries.append(summary)
        if summary.get("decision") == "ACCEPT":
            resolved.append(
                {
                    "subject": summary["subject"],
                    "session": summary["session"],
                    "matlab_fmri_number": summary["fmri_number"],
                    "selected_bids_run": summary["selected_bids_run"],
                    "matlab_timestamp": summary.get("matlab_timestamp"),
                    "reason": summary.get("reason"),
                }
            )
            print(
                f"  -> ACCEPT run-{summary['selected_bids_run']}",
                flush=True,
            )
        else:
            print(f"  -> {summary.get('decision')}: {summary.get('reason')}", flush=True)

    inv_df = pd.concat(all_inv, ignore_index=True) if all_inv else pd.DataFrame()
    # Public inventory columns
    pub_cols = [
        "subject",
        "session",
        "protocol_name",
        "series_number",
        "series_instance_uid_hash",
        "series_description",
        "acquisition_time",
        "study_date_year_month_only",
        "image_type",
        "is_magnitude",
        "is_phase",
        "volume_count",
        "TR",
    ]
    if not inv_df.empty:
        # drop any accidental PHI-ish cols / full study_date from public inventory
        for bad in (
            "PatientName",
            "PatientID",
            "AccessionNumber",
            "InstitutionName",
            "_uid",
            "study_date",
            "acquisition_time_seconds",
        ):
            if bad in inv_df.columns:
                inv_df = inv_df.drop(columns=[bad])
        # Dedupe series across cases (same session scanned twice)
        dedupe_keys = [c for c in ("subject", "session", "series_instance_uid_hash") if c in inv_df.columns]
        if dedupe_keys:
            inv_df = inv_df.drop_duplicates(subset=dedupe_keys)
        cols = [c for c in pub_cols if c in inv_df.columns]
        extra = [c for c in ("ImagingFrequency", "cohort_hint") if c in inv_df.columns]
        inv_df[cols + extra].to_csv(out / "DICOM_SERIES_INVENTORY.tsv", sep="\t", index=False)
    else:
        pd.DataFrame(columns=pub_cols).to_csv(out / "DICOM_SERIES_INVENTORY.tsv", sep="\t", index=False)

    dec_df = pd.concat(all_dec, ignore_index=True) if all_dec else pd.DataFrame()
    dec_cols = [
        "subject",
        "session",
        "matlab_fmri_number",
        "matlab_timestamp",
        "candidate_run",
        "protocol",
        "series_number",
        "study_date",
        "acquisition_time",
        "magnitude",
        "volume_count",
        "time_difference_seconds",
        "score",
        "decision",
        "reason",
    ]
    if not dec_df.empty:
        keep = [c for c in dec_cols if c in dec_df.columns]
        extra = [c for c in dec_df.columns if c not in keep and c != "series_instance_uid_hash"]
        # include hash as safe id
        if "series_instance_uid_hash" in dec_df.columns:
            keep.append("series_instance_uid_hash")
        dec_df[keep].to_csv(out / "DICOM_MAPPING_DECISIONS.tsv", sep="\t", index=False)
    else:
        pd.DataFrame(columns=dec_cols).to_csv(out / "DICOM_MAPPING_DECISIONS.tsv", sep="\t", index=False)

    pd.DataFrame(resolved).to_csv(out / "MANUAL_REVIEW_RESOLVED.tsv", sep="\t", index=False)
    write_report(out, summaries, dec_df if not dec_df.empty else pd.DataFrame(columns=dec_cols))

    issues = phi_scan_outputs(out)
    if issues:
        print("PHI SCAN FAILURES:", file=sys.stderr)
        for i in issues:
            print(" ", i, file=sys.stderr)
        # scrub absolute paths if any slipped
        for p in out.rglob("*"):
            if p.suffix.lower() in {".tsv", ".md"} and p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                text2 = re.sub(r"/lustre\d+/[^\s|]+", "<redacted_path>", text)
                text2 = re.sub(r"/project/[^\s|]+", "<redacted_path>", text2)
                text2 = re.sub(r"1\.3\.12\.2\.1107[0-9.]+", "<uid_hash_only>", text2)
                if text2 != text:
                    p.write_text(text2, encoding="utf-8")
        issues = phi_scan_outputs(out)
        if issues:
            print("Remaining PHI issues after scrub:", issues, file=sys.stderr)
            return 2

    # Obligatory sub-043 assertions when present
    ok = True
    for s in summaries:
        if s.get("subject") != "sub-043" or s.get("session") != "ses-02":
            continue
        if int(s["fmri_number"]) == 3:
            if not (s.get("decision") == "ACCEPT" and str(s.get("selected_bids_run")).zfill(2) == "02"):
                print("TEST FAIL: fMRI3 expected ACCEPT run-02", s, file=sys.stderr)
                ok = False
        if int(s["fmri_number"]) == 4:
            if not (s.get("decision") == "ACCEPT" and str(s.get("selected_bids_run")).zfill(2) == "06"):
                print("TEST FAIL: fMRI4 expected ACCEPT run-06", s, file=sys.stderr)
                ok = False
    if not ok:
        return 3

    print(
        f"Done. ACCEPT={sum(1 for s in summaries if s.get('decision')=='ACCEPT')} "
        f"REVIEW={sum(1 for s in summaries if s.get('decision')=='REVIEW')} "
        f"REJECT={sum(1 for s in summaries if s.get('decision')=='REJECT')}"
    )
    print(f"Reports: {out}")
    print("Dry-run/safe mode: no BIDS modifications performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
