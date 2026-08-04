#!/usr/bin/env python3
"""Read-only audit: recover PhysioLog → BOLD mappings for MAPPING_AMBIGUOUS cases.

Uses existing forensic inventories + BIDS JSON sidecars (SeriesNumber / ProtocolName).
Never modifies bids/, derivatives/, release_dataset/, or raw_original/.
Never writes *_physio.tsv.gz.
Never overwrites an existing non-ambiguous mapping.

Default mode is --dry-run (audit outputs only under reports/physiology_audit/mapping_recovery/).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("physio_mapping_recovery")
NA = "NA"

DEFAULT_ROOT = Path("/home/alexrees/scratch")
DEFAULT_AUDIT = DEFAULT_ROOT / "reports" / "physiology_audit"
DEFAULT_OUT = DEFAULT_AUDIT / "mapping_recovery"
DEFAULT_BIDS = Path("/lustre07/scratch/alexrees/bids")
# Fallbacks if lustre path is unavailable
BIDS_FALLBACKS = [
    DEFAULT_ROOT / "bids",
    Path("/lustre07/scratch/alexrees/bids"),
]

_RE_RUN = re.compile(r"_run-(\d+)")
_RE_TASK = re.compile(r"_task-([a-zA-Z0-9]+)")


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


def _parse_float(x: Any) -> float | None:
    if x is None:
        return None
    s = str(x).strip()
    if s in ("", NA, "nan", "None", "NaN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _siemens_time_to_seconds(t: float | None) -> float | None:
    """Convert Siemens HHMMSS.fraction (e.g. 145504.381) to seconds-from-midnight."""
    if t is None:
        return None
    hh = int(t // 10000)
    mm = int((t % 10000) // 100)
    ss = t % 100.0
    if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss < 60:
        return hh * 3600.0 + mm * 60.0 + ss
    if 0 <= t < 86400:
        return float(t)
    return None


def resolve_bids_root(explicit: Path | None) -> Path:
    if explicit is not None and explicit.is_dir():
        return explicit
    for p in BIDS_FALLBACKS:
        if p.is_dir():
            return p
    raise FileNotFoundError(
        "BIDS root not found. Tried: "
        + ", ".join(str(p) for p in ([explicit] if explicit else []) + BIDS_FALLBACKS)
    )


def _series_uid_from_dicom(path_str: str) -> tuple[str, str]:
    """Read SeriesInstanceUID from a PhysioLog DICOM (stop_before_pixels)."""
    try:
        import pydicom

        ds = pydicom.dcmread(path_str, stop_before_pixels=True, force=True)
        uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
        return path_str, uid or NA
    except Exception as exc:  # noqa: BLE001
        return path_str, f"NA:{type(exc).__name__}"


def build_uid_index(
    deep_rows: list[dict[str, str]],
    inv_by_fp: dict[str, dict[str, str]],
    needed_subjects: set[str],
    workers: int,
) -> dict[str, dict[str, str]]:
    """Map SeriesInstanceUID → merged deep+inventory row for needed subjects."""
    dir_to_fp: dict[str, str] = {}
    for r in deep_rows:
        fp = r.get("filepath", "")
        inv = inv_by_fp.get(fp, {})
        sub = inv.get("subject", "")
        if needed_subjects and sub not in needed_subjects:
            continue
        d = str(Path(fp).parent)
        dir_to_fp.setdefault(d, fp)

    LOGGER.info(
        "Resolving SeriesInstanceUID for %d PhysioLog series (subject-filtered)",
        len(dir_to_fp),
    )
    uid_by_fp: dict[str, str] = {}
    fps = list(dir_to_fp.values())
    if not fps:
        return {}

    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(_series_uid_from_dicom, fp) for fp in fps]
        done = 0
        for fut in as_completed(futs):
            fp, uid = fut.result()
            uid_by_fp[fp] = uid
            done += 1
            if done % 50 == 0:
                LOGGER.info("UID resolve %d / %d", done, len(fps))

    uid_to_row: dict[str, dict[str, str]] = {}
    for r in deep_rows:
        fp = r.get("filepath", "")
        inv = inv_by_fp.get(fp, {})
        d = str(Path(fp).parent)
        if d not in dir_to_fp:
            continue
        rep = dir_to_fp[d]
        uid = uid_by_fp.get(rep, NA)
        if not uid or uid.startswith("NA"):
            continue
        merged = {
            **r,
            "subject": inv.get("subject", NA),
            "session": inv.get("session", NA),
            "physio_series_uid": uid,
        }
        # Prefer exact filepath match for the representative
        if uid not in uid_to_row or fp == rep:
            uid_to_row[uid] = merged
    LOGGER.info("UID index size: %d", len(uid_to_row))
    return uid_to_row


def load_bold_index(bids_root: Path, subjects_sessions: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """Index magnitude BOLD runs from BIDS JSON sidecars (read-only)."""
    rows: list[dict[str, Any]] = []
    for sub, ses in sorted(subjects_sessions):
        func = bids_root / sub / ses / "func"
        if not func.is_dir():
            LOGGER.warning("Missing func dir: %s", func)
            continue
        for jp in sorted(func.glob("*_bold.json")):
            name = jp.name
            if "part-phase" in name:
                continue  # magnitude only
            stem = name[: -len("_bold.json")]
            try:
                meta = json.loads(jp.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Cannot read %s: %s", jp, exc)
                continue
            proto = str(meta.get("ProtocolName") or meta.get("SeriesDescription") or "")
            sn = _parse_float(meta.get("SeriesNumber"))
            st = _parse_float(meta.get("SeriesTime"))
            at = _parse_float(meta.get("AcquisitionTime"))
            adt = meta.get("AcquisitionDateTime")
            m_run = _RE_RUN.search(stem)
            m_task = _RE_TASK.search(stem)
            rows.append(
                {
                    "subject": sub,
                    "session": ses,
                    "bold_stem": stem,
                    "bold_filename": f"{stem}_bold.nii.gz",
                    "bold_json": str(jp),
                    "bold_run": m_run.group(1) if m_run else NA,
                    "bold_task": m_task.group(1) if m_task else NA,
                    "protocol_name": proto,
                    "series_number": sn,
                    "series_time": st,
                    "acquisition_time": at,
                    "acquisition_datetime": adt,
                }
            )
    LOGGER.info("Indexed %d magnitude BOLD sidecars", len(rows))
    return rows


def parse_ambiguous_bolds(matched_bold: str) -> list[str]:
    s = (matched_bold or "").strip()
    if not s.startswith("AMBIGUOUS:"):
        return []
    return [x.strip() for x in s.split(":", 1)[1].split(",") if x.strip()]


def score_candidate(
    physio_sn: float | None,
    physio_time_s: float | None,
    bold: dict[str, Any],
) -> dict[str, Any]:
    bold_sn = bold.get("series_number")
    sn_dist: float | None = None
    if physio_sn is not None and bold_sn is not None:
        sn_dist = abs(float(bold_sn) - float(physio_sn))

    # Temporal proximity (seconds); BIDS JSON usually lacks SeriesTime → NA
    bold_time_raw = bold.get("series_time")
    if bold_time_raw is None:
        bold_time_raw = bold.get("acquisition_time")
    bold_time_s = _siemens_time_to_seconds(_parse_float(bold_time_raw))
    time_dist: float | None = None
    if physio_time_s is not None and bold_time_s is not None:
        time_dist = abs(bold_time_s - physio_time_s)

    immediately_after = False
    after_gap: float | None = None
    if physio_sn is not None and bold_sn is not None and float(bold_sn) > float(physio_sn):
        after_gap = float(bold_sn) - float(physio_sn)
        immediately_after = after_gap <= 4.0  # typical PhysioLog then mag(+phase)

    # Rank score: lower is better. Never ProtocolName-only (caller filters by protocol).
    if sn_dist is None:
        rank = 1e6
    else:
        rank = float(sn_dist)
        if immediately_after:
            rank -= 0.35  # prefer BOLD just after PhysioLog when SN-coherent
        if after_gap is not None and after_gap <= 2.0:
            rank -= 0.15
        if time_dist is not None:
            # soft temporal tie-break (minutes)
            rank += min(time_dist, 3600.0) / 600.0

    return {
        "seriesnumber_distance": sn_dist,
        "seriestime_distance_sec": time_dist,
        "bold_immediately_after_physio": immediately_after,
        "seriesnumber_after_gap": after_gap,
        "rank_score": rank,
    }


def assign_confidence(
    scored: list[dict[str, Any]],
) -> tuple[str, str]:
    """Return (confidence, reason) for the best-ranked candidate list (sorted)."""
    if not scored:
        return "LOW", "no_candidates"
    best = scored[0]
    sn_d = best.get("_sn_dist")
    time_d = best.get("_time_dist")
    after = bool(best.get("_after"))
    best_rank = float(best.get("_rank", 1e6))

    # Tie detection among top ranks
    top = [r for r in scored if abs(float(r["_rank"]) - best_rank) < 1e-9]
    near = [
        r
        for r in scored
        if sn_d is not None
        and r.get("_sn_dist") is not None
        and abs(float(r["_sn_dist"]) - float(sn_d)) < 1e-9
    ]

    if len(top) > 1 or (len(near) > 1 and not after and time_d is None):
        return "LOW", "tie_equivalent_candidates"

    if sn_d is None:
        return "LOW", "missing_seriesnumber"

    if sn_d <= 2 and (after or (time_d is not None and time_d <= 120) or sn_d <= 1):
        return "HIGH", "protocol+seriesnumber_close" + (
            "+after" if after else ""
        ) + ("+time" if time_d is not None else "")

    if sn_d <= 2:
        return "HIGH", "protocol+seriesnumber_leq2"

    if sn_d <= 5:
        return "MEDIUM", "protocol+seriesnumber_leq5_no_strong_time"

    return "LOW", f"seriesnumber_distance_{sn_d:g}_too_large"


def select_targets(excluded_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Deduplicate MAPPING_AMBIGUOUS rows by physio_series_uid."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for r in excluded_rows:
        if r.get("exclusion_class") != "MAPPING_AMBIGUOUS":
            continue
        uid = r.get("physio_series_uid") or ""
        if not uid or uid in seen:
            continue
        seen.add(uid)
        # Skip if matched_bold is already a concrete unique stem (should not happen)
        mb = r.get("matched_bold") or ""
        if mb and not mb.startswith("AMBIGUOUS") and mb not in ("", NA):
            LOGGER.info("Skip UID with existing non-ambiguous mapping: %s → %s", uid, mb)
            continue
        out.append(r)
    return out


def run_audit(
    audit_dir: Path,
    bids_root: Path,
    out_dir: Path,
    workers: int,
    dry_run: bool,
) -> dict[str, Any]:
    excluded_path = audit_dir / "final_bids_physio_readiness" / "EXCLUDED_324_physio_reasons.tsv"
    deep_path = audit_dir / "physiolog_dicom_deep.tsv"
    inv_path = audit_dir / "physiolog_inventory.tsv"
    status_path = audit_dir / "physio_conversion_status.tsv"

    for p in (excluded_path, deep_path, inv_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    LOGGER.info("dry_run=%s  bids_root=%s  out_dir=%s", dry_run, bids_root, out_dir)
    LOGGER.info("Loading inventories…")
    excluded = _load_tsv(excluded_path)
    deep_rows = _load_tsv(deep_path)
    inv_rows = _load_tsv(inv_path)
    status_rows = _load_tsv(status_path) if status_path.is_file() else []
    status_by_uid = {r["physio_series_uid"]: r for r in status_rows if r.get("physio_series_uid")}

    targets = select_targets(excluded)
    LOGGER.info(
        "MAPPING_AMBIGUOUS unique PhysioLog UIDs to recover: %d (from %d exclusion rows)",
        len(targets),
        sum(1 for r in excluded if r.get("exclusion_class") == "MAPPING_AMBIGUOUS"),
    )

    inv_by_fp = {r["filepath"]: r for r in inv_rows if r.get("filepath")}
    needed_subjects = {r["subject"] for r in targets}
    subjects_sessions = {(r["subject"], r["session"]) for r in targets}

    # Reuse UID cache from a previous run when complete (speeds dry-run re-runs)
    uid_cache_path = out_dir / "physio_uid_series_index.tsv"
    uid_index: dict[str, dict[str, str]] = {}
    if uid_cache_path.is_file():
        cached = _load_tsv(uid_cache_path)
        for row in cached:
            uid = row.get("physio_series_uid", "")
            if uid and not uid.startswith("NA"):
                uid_index[uid] = row
        # Ensure all target UIDs are present; otherwise rebuild
        missing_targets = [t["physio_series_uid"] for t in targets if t["physio_series_uid"] not in uid_index]
        if missing_targets:
            LOGGER.info(
                "UID cache incomplete (%d target UIDs missing) → rebuilding",
                len(missing_targets),
            )
            uid_index = build_uid_index(deep_rows, inv_by_fp, needed_subjects, workers=workers)
        else:
            LOGGER.info("Reusing UID cache with %d entries from %s", len(uid_index), uid_cache_path)
    else:
        uid_index = build_uid_index(deep_rows, inv_by_fp, needed_subjects, workers=workers)

    # Cache UID index for reproducibility / inspection
    cache_rows = []
    for uid, row in sorted(uid_index.items()):
        cache_rows.append(
            {
                "physio_series_uid": uid,
                "subject": row.get("subject", NA),
                "session": row.get("session", NA),
                "protocol_name": row.get("protocol_name", NA),
                "series_number": row.get("series_number", NA),
                "series_time": row.get("series_time", NA),
                "filepath": row.get("filepath", NA),
            }
        )
    _write_tsv(
        uid_cache_path,
        [
            "physio_series_uid",
            "subject",
            "session",
            "protocol_name",
            "series_number",
            "series_time",
            "filepath",
        ],
        cache_rows,
    )

    bold_rows = load_bold_index(bids_root, subjects_sessions)
    bold_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    bold_by_stem: dict[str, dict[str, Any]] = {}
    for b in bold_rows:
        bold_by_key[(b["subject"], b["session"])].append(b)
        bold_by_stem[b["bold_stem"]] = b

    all_candidate_rows: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []

    n_no_candidate = 0
    conf_counts: Counter[str] = Counter()
    multi_ambig_subjects: Counter[str] = Counter()

    for t in targets:
        uid = t["physio_series_uid"]
        sub, ses = t["subject"], t["session"]
        multi_ambig_subjects[sub] += 1

        # Never overwrite existing confirmed mapping in conversion status
        st = status_by_uid.get(uid, {})
        mb_status = st.get("matched_bold") or t.get("matched_bold") or ""
        if mb_status and not mb_status.startswith("AMBIGUOUS") and mb_status not in ("", NA):
            LOGGER.info("Preserving existing mapping for %s → %s", uid, mb_status)
            continue

        deep = uid_index.get(uid)
        physio_proto = (deep or {}).get("protocol_name") or NA
        physio_sn = _parse_float((deep or {}).get("series_number"))
        physio_st_raw = _parse_float((deep or {}).get("series_time"))
        physio_time_s = _siemens_time_to_seconds(physio_st_raw)
        physio_sd = (deep or {}).get("series_description") or NA
        physio_fp = (deep or {}).get("filepath") or NA

        # Candidate stems from prior ambiguous list when present; else same ProtocolName
        listed = parse_ambiguous_bolds(t.get("matched_bold", ""))
        session_bolds = bold_by_key.get((sub, ses), [])

        if listed:
            cands = []
            for stem in listed:
                b = bold_by_stem.get(stem)
                if b is None:
                    LOGGER.warning("Listed ambiguous BOLD missing in BIDS index: %s", stem)
                    continue
                cands.append(b)
            # If protocol known, keep only matching ProtocolName (safety)
            if physio_proto not in (NA, ""):
                matched_proto = [c for c in cands if c.get("protocol_name") == physio_proto]
                if matched_proto:
                    cands = matched_proto
        else:
            if physio_proto in (NA, ""):
                cands = []
            else:
                cands = [b for b in session_bolds if b.get("protocol_name") == physio_proto]

        if not cands:
            n_no_candidate += 1
            conf_counts["LOW"] += 1
            row = {
                "physio_series_uid": uid,
                "subject": sub,
                "session": ses,
                "physio_protocol_name": physio_proto,
                "physio_series_description": physio_sd,
                "physio_series_number": physio_sn if physio_sn is not None else NA,
                "physio_series_time": physio_st_raw if physio_st_raw is not None else NA,
                "physio_filepath": physio_fp,
                "channels_available": t.get("channels_available", NA),
                "start_time_available": t.get("start_time_available", NA),
                "n_candidates": 0,
                "recommended_bold_filename": NA,
                "recommended_bold_stem": NA,
                "recommended_bold_run": NA,
                "recommended_bold_series_number": NA,
                "seriesnumber_distance": NA,
                "seriestime_distance_sec": NA,
                "bold_immediately_after_physio": NA,
                "confidence": "LOW",
                "confidence_reason": "no_candidates",
                "needs_manual_review": "yes",
            }
            recommendations.append(row)
            manual_review.append(row)
            continue

        scored: list[dict[str, Any]] = []
        for b in cands:
            sc = score_candidate(physio_sn, physio_time_s, b)
            rec = {
                "physio_series_uid": uid,
                "subject": sub,
                "session": ses,
                "physio_protocol_name": physio_proto,
                "physio_series_description": physio_sd,
                "physio_series_number": physio_sn if physio_sn is not None else NA,
                "physio_series_time": physio_st_raw if physio_st_raw is not None else NA,
                "physio_filepath": physio_fp,
                "channels_available": t.get("channels_available", NA),
                "start_time_available": t.get("start_time_available", NA),
                "bold_filename": b["bold_filename"],
                "bold_stem": b["bold_stem"],
                "bold_run": b["bold_run"],
                "bold_task": b["bold_task"],
                "bold_protocol_name": b["protocol_name"],
                "bold_series_number": b["series_number"] if b["series_number"] is not None else NA,
                "bold_series_time": b["series_time"] if b["series_time"] is not None else NA,
                "seriesnumber_distance": (
                    f"{sc['seriesnumber_distance']:.6g}"
                    if sc["seriesnumber_distance"] is not None
                    else NA
                ),
                "seriestime_distance_sec": (
                    f"{sc['seriestime_distance_sec']:.6g}"
                    if sc["seriestime_distance_sec"] is not None
                    else NA
                ),
                "bold_immediately_after_physio": (
                    "yes" if sc["bold_immediately_after_physio"] else "no"
                ),
                "rank_score": f"{sc['rank_score']:.6g}",
            }
            # attach numeric helpers for ranking
            rec["_rank"] = sc["rank_score"]
            rec["_sn_dist"] = sc["seriesnumber_distance"]
            rec["_time_dist"] = sc["seriestime_distance_sec"]
            rec["_after"] = sc["bold_immediately_after_physio"]
            scored.append(rec)

        scored.sort(key=lambda r: (r["_rank"], r["_sn_dist"] if r["_sn_dist"] is not None else 1e9))
        # Confidence uses numeric helpers (_rank / _sn_dist / _after / _time_dist)
        conf, conf_reason = assign_confidence(scored)
        conf_counts[conf] += 1

        # Write all candidates with shared confidence of the recommendation context
        for i, rec in enumerate(scored):
            out = {k: v for k, v in rec.items() if not k.startswith("_")}
            out["candidate_rank"] = i + 1
            out["is_recommended"] = "yes" if i == 0 else "no"
            out["confidence"] = conf if i == 0 else NA
            out["confidence_reason"] = conf_reason if i == 0 else NA
            all_candidate_rows.append(out)

        best = scored[0]
        rec_row = {
            "physio_series_uid": uid,
            "subject": sub,
            "session": ses,
            "physio_protocol_name": physio_proto,
            "physio_series_description": physio_sd,
            "physio_series_number": best["physio_series_number"],
            "physio_series_time": best["physio_series_time"],
            "physio_filepath": physio_fp,
            "channels_available": t.get("channels_available", NA),
            "start_time_available": t.get("start_time_available", NA),
            "n_candidates": len(scored),
            "recommended_bold_filename": best["bold_filename"],
            "recommended_bold_stem": best["bold_stem"],
            "recommended_bold_run": best["bold_run"],
            "recommended_bold_series_number": best["bold_series_number"],
            "seriesnumber_distance": best["seriesnumber_distance"],
            "seriestime_distance_sec": best["seriestime_distance_sec"],
            "bold_immediately_after_physio": best["bold_immediately_after_physio"],
            "confidence": conf,
            "confidence_reason": conf_reason,
            "needs_manual_review": "yes" if conf == "LOW" else "no",
        }
        recommendations.append(rec_row)
        if conf == "LOW":
            manual_review.append(rec_row)

    # Demote one-to-many collisions: multiple PhysioLogs recommending the same BOLD
    # cannot all be auto-accepted (fail-closed for the colliding set).
    bold_owners: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for i, r in enumerate(recommendations):
        stem = r.get("recommended_bold_stem") or NA
        if stem in (NA, ""):
            continue
        bold_owners[(r["subject"], r["session"], stem)].append(i)

    n_collision_demoted = 0
    for key, idxs in bold_owners.items():
        if len(idxs) < 2:
            continue
        for i in idxs:
            r = recommendations[i]
            if r["confidence"] == "LOW" and "collision" in r.get("confidence_reason", ""):
                continue
            prev = r["confidence"]
            r["confidence"] = "LOW"
            r["confidence_reason"] = (
                f"collision_multiple_physio_to_same_bold(prev={prev})"
            )
            r["needs_manual_review"] = "yes"
            n_collision_demoted += 1
            # Keep candidate table in sync for recommended rows
            for c in all_candidate_rows:
                if (
                    c.get("physio_series_uid") == r["physio_series_uid"]
                    and c.get("is_recommended") == "yes"
                ):
                    c["confidence"] = "LOW"
                    c["confidence_reason"] = r["confidence_reason"]
    if n_collision_demoted:
        LOGGER.warning(
            "Demoted %d recommendations to LOW due to PhysioLog→BOLD collisions",
            n_collision_demoted,
        )

    # Rebuild manual review + confidence counts after collision demotion
    manual_review = [r for r in recommendations if r.get("confidence") == "LOW"]
    conf_counts = Counter(r["confidence"] for r in recommendations)
    out_dir.mkdir(parents=True, exist_ok=True)
    cand_fields = [
        "physio_series_uid",
        "subject",
        "session",
        "physio_protocol_name",
        "physio_series_description",
        "physio_series_number",
        "physio_series_time",
        "physio_filepath",
        "channels_available",
        "start_time_available",
        "bold_filename",
        "bold_stem",
        "bold_run",
        "bold_task",
        "bold_protocol_name",
        "bold_series_number",
        "bold_series_time",
        "seriesnumber_distance",
        "seriestime_distance_sec",
        "bold_immediately_after_physio",
        "rank_score",
        "candidate_rank",
        "is_recommended",
        "confidence",
        "confidence_reason",
    ]
    rec_fields = [
        "physio_series_uid",
        "subject",
        "session",
        "physio_protocol_name",
        "physio_series_description",
        "physio_series_number",
        "physio_series_time",
        "physio_filepath",
        "channels_available",
        "start_time_available",
        "n_candidates",
        "recommended_bold_filename",
        "recommended_bold_stem",
        "recommended_bold_run",
        "recommended_bold_series_number",
        "seriesnumber_distance",
        "seriestime_distance_sec",
        "bold_immediately_after_physio",
        "confidence",
        "confidence_reason",
        "needs_manual_review",
    ]

    _write_tsv(out_dir / "all_physio_bold_candidates.tsv", cand_fields, all_candidate_rows)
    _write_tsv(out_dir / "physio_bold_mapping_recommendations.tsv", rec_fields, recommendations)
    _write_tsv(out_dir / "manual_review_required.tsv", rec_fields, manual_review)

    multi_subjects = sorted(
        [s for s, n in multi_ambig_subjects.items() if n >= 2],
        key=lambda s: (-multi_ambig_subjects[s], s),
    )
    multi_lines = "\n".join(
        f"- `{s}`: {multi_ambig_subjects[s]} ambiguous PhysioLog UIDs"
        for s in multi_subjects
    ) or "- (none)"

    n = len(recommendations)
    report = f"""# PhysioLog → BOLD mapping recovery audit

Generated: `{_now()}`

**READ-ONLY.** No modifications to `raw_original/`, `bids/`, `derivatives/`, or `release_dataset/`.
No `*_physio.tsv.gz` created. Existing confirmed mappings were not overwritten.
Mode: `dry_run={dry_run}`.

## Inputs

- `{excluded_path}` — `MAPPING_AMBIGUOUS` exclusion class
- `{deep_path}` — PhysioLog SeriesNumber / SeriesTime / ProtocolName
- `{inv_path}` — subject / session join via filepath
- `{status_path}` — prior conversion status (skip non-ambiguous mappings)
- BIDS root `{bids_root}` — magnitude `*_bold.json` sidecars (ProtocolName, SeriesNumber, run)

## Method (summary)

1. Restrict BOLD candidates to same subject, session, and Siemens `ProtocolName`.
2. Score by SeriesNumber distance, optional SeriesTime distance, and prefer BOLD immediately after PhysioLog when SeriesNumber-coherent.
3. Assign confidence HIGH / MEDIUM / LOW; ties → manual review.
4. Never choose on ProtocolName alone.

## Results

| Metric | Count |
| --- | ---: |
| PhysioLog UIDs analysed | {n} |
| No BOLD candidate | {n_no_candidate} |
| HIGH confidence | {conf_counts.get('HIGH', 0)} |
| MEDIUM confidence | {conf_counts.get('MEDIUM', 0)} |
| LOW confidence | {conf_counts.get('LOW', 0)} |
| Manual review rows | {len(manual_review)} |
| Candidate pairs written | {len(all_candidate_rows)} |
| Demoted for BOLD collision | {n_collision_demoted} |

### Subjects with multiple ambiguous PhysioLogs

{multi_lines}

## Outputs

- `all_physio_bold_candidates.tsv` — all scored PhysioLog↔BOLD pairs
- `physio_bold_mapping_recommendations.tsv` — best candidate per PhysioLog
- `manual_review_required.tsv` — LOW / ties / no candidate
- `physio_uid_series_index.tsv` — UID → SeriesNumber/SeriesTime cache used

## Recommendations for BIDS conversion

1. **Auto-accept HIGH** recommendations into a gated converter mapping table (`physio_uid → bold_stem`) after spot-checking a few sessions (e.g. `sub-015`).
2. **Review MEDIUM** (SeriesNumber proximity without temporal confirmation in BIDS JSON). Most BIDS sidecars lack `SeriesTime`/`AcquisitionTime`; SeriesNumber adjacency is the primary recoverable signal.
3. **Do not convert LOW** until manual resolution (ties, missing SeriesNumber, or identical BOLD SeriesNumbers across redos — especially `sub-043`).
4. Keep fail-closed policy for any UID not listed as HIGH/MEDIUM with a unique recommended stem.
5. This audit does **not** authorize writing `*_physio.tsv.gz`; conversion remains a separate gated step.

## Notes

- {sum(1 for r in excluded if r.get('exclusion_class')=='MAPPING_AMBIGUOUS')} exclusion rows collapsed to {n} unique `physio_series_uid` values.
- Phase BOLD (`part-phase`) excluded from candidates.
- Temporal scores are usually `NA` because BIDS JSON sidecars in this dataset typically omit SeriesTime/AcquisitionTime.
"""
    (out_dir / "MAPPING_RECOVERY_REPORT.md").write_text(report, encoding="utf-8")
    LOGGER.info("Wrote report → %s", out_dir / "MAPPING_RECOVERY_REPORT.md")

    summary = {
        "n_analysed": n,
        "n_no_candidate": n_no_candidate,
        "HIGH": conf_counts.get("HIGH", 0),
        "MEDIUM": conf_counts.get("MEDIUM", 0),
        "LOW": conf_counts.get("LOW", 0),
        "n_manual": len(manual_review),
        "n_candidate_rows": len(all_candidate_rows),
        "out_dir": str(out_dir),
    }
    LOGGER.info("Summary: %s", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read-only PhysioLog→BOLD mapping recovery for MAPPING_AMBIGUOUS cases."
    )
    p.add_argument(
        "--audit-dir",
        type=Path,
        default=DEFAULT_AUDIT,
        help="physiology_audit directory (default: %(default)s)",
    )
    p.add_argument(
        "--bids-root",
        type=Path,
        default=None,
        help="BIDS root (auto-detected if omitted)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT,
        help="Output directory under reports (default: %(default)s)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Workers for read-only DICOM SeriesInstanceUID resolve",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Default. Audit-only writes under --out-dir; never touch BIDS (default).",
    )
    p.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Same write scope as dry-run for this audit script (still never modifies BIDS).",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        bids_root = resolve_bids_root(args.bids_root)
    except FileNotFoundError as exc:
        LOGGER.error("%s", exc)
        return 2

    LOGGER.info("Using inventories:")
    LOGGER.info("  excluded: %s", args.audit_dir / "final_bids_physio_readiness/EXCLUDED_324_physio_reasons.tsv")
    LOGGER.info("  deep:     %s", args.audit_dir / "physiolog_dicom_deep.tsv")
    LOGGER.info("  invent:   %s", args.audit_dir / "physiolog_inventory.tsv")
    LOGGER.info("  status:   %s", args.audit_dir / "physio_conversion_status.tsv")
    LOGGER.info("  bids:     %s", bids_root)

    summary = run_audit(
        audit_dir=args.audit_dir,
        bids_root=bids_root,
        out_dir=args.out_dir,
        workers=args.workers,
        dry_run=args.dry_run,
    )
    print(
        "MAPPING RECOVERY SUMMARY\n"
        f"  analysed={summary['n_analysed']}  "
        f"HIGH={summary['HIGH']}  MEDIUM={summary['MEDIUM']}  "
        f"LOW={summary['LOW']}  no_candidate={summary['n_no_candidate']}\n"
        f"  outputs → {summary['out_dir']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
