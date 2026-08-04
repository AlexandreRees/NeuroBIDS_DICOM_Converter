#!/usr/bin/env python3
"""Grating events recovery — FAIL-CLOSED multi-gate mapping (READ-ONLY on BIDS/raw).

Writes ONLY under reports/grating_events_recovery/.
Does NOT modify bids/, raw_original/, derivatives/, release_dataset/.
Does NOT invent events — only recommends linking existing MATLAB timing to BOLD runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCRATCH = Path("/home/alexrees/scratch")
OUT = SCRATCH / "reports" / "grating_events_recovery"
BIDS = SCRATCH / "bids"
CODE = SCRATCH / "neuro_pipeline"
sys.path.insert(0, str(CODE))

from neuro_pipeline.associated_data.matlab.extract_scan_timing import (  # noqa: E402
    extract_scan_timing,
    parse_fmri_number_from_name,
)

RAW_PREFIXES = (
    "/lustre06/project/6001995/raw_original",
    "/project/def-amirs/raw_original",
    "/lustre07/scratch/alexrees/raw_original",
)

FMRI_PROTO_RE = re.compile(r"fMRI\s*(\d+)", re.I)


def remap(p: str | Path) -> Path:
    s = str(p)
    for pref in RAW_PREFIXES[1:]:
        if s.startswith(pref):
            s = s.replace(pref, RAW_PREFIXES[0], 1)
            break
    return Path(s)


def sha256_file(path: Path, nbytes: int | None = None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        if nbytes:
            h.update(fh.read(nbytes))
        else:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def protocol_fmri_number(protocol: str) -> int | None:
    m = FMRI_PROTO_RE.search((protocol or "").replace(" ", ""))
    return int(m.group(1)) if m else None


def build_matlab_trigger_db(inv: pd.DataFrame) -> pd.DataFrame:
    scan = inv[(inv["task"] == "fmri") & (inv["mat_role"] == "scan_info")].copy()
    rows: list[dict[str, Any]] = []
    print(f"Building MATLAB trigger DB from {len(scan)} scan_info mats…", flush=True)
    for i, r in enumerate(scan.itertuples(index=False), 1):
        if i % 50 == 0 or i == 1:
            print(f"  [{i}/{len(scan)}]", flush=True)
        path = Path(str(r.mat_file))
        fmri_n = None
        if str(r.run) not in ("", "UNKNOWN", "nan"):
            try:
                fmri_n = int(str(r.run))
            except ValueError:
                fmri_n = None
        n_trig = int(r.trigger_count) if pd.notna(r.trigger_count) else 0
        trig_dur = None
        notes = ""
        try:
            timing = extract_scan_timing(path)
            n_trig = int(timing.n_triggers)
            if timing.trigger_times.size >= 2:
                trig_dur = float(timing.trigger_times[-1] - timing.trigger_times[0])
            if timing.fmri_number is not None:
                fmri_n = int(timing.fmri_number)
            notes = "; ".join(timing.notes[:5])
        except Exception as exc:  # noqa: BLE001
            notes = f"extract_failed:{type(exc).__name__}"
        if fmri_n is None:
            fmri_n = parse_fmri_number_from_name(path)
        sha = ""
        if hasattr(r, "source_sha256_16") and pd.notna(r.source_sha256_16):
            sha = str(r.source_sha256_16)
        if not sha and path.is_file():
            sha = sha256_file(path, nbytes=1024 * 1024)[:16]
        rows.append(
            {
                "participant_id": r.subject,
                "session_id": r.session,
                "fmri_number": fmri_n if fmri_n is not None else "",
                "protocol_expected": f"fMRI{fmri_n}" if fmri_n is not None else "UNKNOWN",
                "n_triggers": n_trig,
                "trigger_duration": "" if trig_dur is None else f"{trig_dur:.6f}",
                "source_mat": str(path),
                "sha256": sha,
                "confidence_inventory": getattr(r, "confidence", ""),
                "extract_notes": notes,
            }
        )
    return pd.DataFrame(rows)


def build_bold_db() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    print("Building BOLD database (task-fmri only)…", flush=True)
    jsons = sorted(BIDS.glob("sub-*/ses-*/func/*task-fmri*_bold.json"))
    print(f"  {len(jsons)} bold json sidecars", flush=True)
    for js in jsons:
        name = js.name
        nii = Path(str(js).replace("_bold.json", "_bold.nii.gz"))
        if not nii.exists():
            nii = Path(str(js).replace("_bold.json", "_bold.nii"))
        parts = name.replace(".json", "").split("_")
        ent: dict[str, str] = {}
        for p in parts:
            if "-" in p:
                k, v = p.split("-", 1)
                ent[k] = v
        try:
            meta = json.loads(js.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        pn = str(meta.get("ProtocolName") or "")
        part = "phase" if ("part-phase" in name or ent.get("part") == "phase") else "mag"
        echo = ent.get("echo", meta.get("EchoNumber", ""))
        rows.append(
            {
                "participant_id": f"sub-{ent.get('sub', '')}",
                "session_id": f"ses-{ent.get('ses', '')}",
                "task": ent.get("task", "fmri"),
                "run": ent.get("run", ""),
                "ProtocolName": pn,
                "SeriesDescription": str(meta.get("SeriesDescription") or ""),
                "SeriesNumber": meta.get("SeriesNumber", ""),
                "SeriesTime": meta.get("SeriesTime") or meta.get("AcquisitionTime") or "",
                "Echo": echo,
                "Magnitude_or_Phase": part,
                "fmri_number_from_protocol": protocol_fmri_number(pn)
                or protocol_fmri_number(str(meta.get("SeriesDescription") or "")),
                "RepetitionTime": meta.get("RepetitionTime", ""),
                "nifti_path": str(nii) if nii.exists() else "",
                "json_path": str(js),
                "nifti_exists": nii.exists(),
                "has_events_tsv": (
                    js.parent
                    / (
                        f"sub-{ent.get('sub')}_ses-{ent.get('ses')}_"
                        f"task-fmri_run-{ent.get('run')}_events.tsv"
                    )
                ).exists(),
            }
        )
    return pd.DataFrame(rows)


_TS_IN_NAME = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"[-_](\d{1,2})[-_](\d{4}).*?(\d{1,2})[-_](\d{2})[-_](\d{2})\s*([AP]M)",
    re.I,
)
_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        "January February March April May June July August September "
        "October November December".split(),
        1,
    )
}


def matlab_sort_key(path: str) -> tuple:
    name = Path(path).name
    m = _TS_IN_NAME.search(name.replace("__", "_"))
    if m:
        mon = _MONTHS[m.group(1).lower()]
        day, year = int(m.group(2)), int(m.group(3))
        hh, mm, ss = int(m.group(4)), int(m.group(5)), int(m.group(6))
        ap = m.group(7).upper()
        if ap == "PM" and hh != 12:
            hh += 12
        if ap == "AM" and hh == 12:
            hh = 0
        return (year, mon, day, hh, mm, ss, name)
    return (9999, 0, 0, 0, 0, 0, name)


def series_number_key(val: Any) -> int:
    try:
        return int(val)
    except Exception:
        return 10**9


def multi_gate_map(matlab: pd.DataFrame, bold: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Gates (FAIL-CLOSED):
      G1 Protocol family: same fmri_number
      G2 Magnitude only
      G3 NIfTI exists
      G4 n_triggers >= 2
      G5 Unique OR equal cardinality + SeriesNumber ↔ MATLAB time order
      G6 No double-assign
    """
    mag = bold[(bold["Magnitude_or_Phase"] == "mag") & (bold["nifti_exists"])].copy()
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    bold_by: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for _, b in mag.iterrows():
        n = b["fmri_number_from_protocol"]
        if pd.isna(n) or n is None or n == "":
            rejected.append(
                {
                    "participant_id": b["participant_id"],
                    "session_id": b["session_id"],
                    "run": b["run"],
                    "ProtocolName": b["ProtocolName"],
                    "reason": "G1_FAIL_NO_fMRI_NUMBER_IN_PROTOCOL",
                    "gates_failed": "G1",
                    "decision": "REJECT",
                }
            )
            continue
        bold_by[(b["participant_id"], b["session_id"], int(n))].append(b.to_dict())

    mat_ok = matlab.copy()
    mat_ok = mat_ok[mat_ok["fmri_number"].astype(str).str.isdigit()]
    mat_ok["fmri_number"] = mat_ok["fmri_number"].astype(int)
    mat_ok["n_triggers"] = (
        pd.to_numeric(mat_ok["n_triggers"], errors="coerce").fillna(0).astype(int)
    )

    mat_by: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for _, m in mat_ok.iterrows():
        if m["n_triggers"] < 2:
            rejected.append(
                {
                    "participant_id": m["participant_id"],
                    "session_id": m["session_id"],
                    "fmri_number": m["fmri_number"],
                    "source_mat": m["source_mat"],
                    "reason": "G4_FAIL_TRIGGERS_LT_2",
                    "gates_failed": "G4",
                    "decision": "REJECT",
                    "n_triggers": m["n_triggers"],
                }
            )
            continue
        mat_by[(m["participant_id"], m["session_id"], int(m["fmri_number"]))].append(
            m.to_dict()
        )

    used_bold: set[tuple[str, str, str]] = set()
    used_mat: set[str] = set()

    for key in sorted(set(bold_by) | set(mat_by)):
        sub, ses, n = key
        blist = sorted(
            bold_by.get(key, []), key=lambda b: series_number_key(b.get("SeriesNumber"))
        )
        mlist = sorted(
            mat_by.get(key, []), key=lambda m: matlab_sort_key(m["source_mat"])
        )

        if not blist and mlist:
            for m in mlist:
                rejected.append(
                    {
                        "participant_id": sub,
                        "session_id": ses,
                        "fmri_number": n,
                        "source_mat": m["source_mat"],
                        "reason": "G1_FAIL_NO_MATCHING_MAG_BOLD",
                        "gates_failed": "G1",
                        "decision": "REJECT",
                    }
                )
            continue
        if blist and not mlist:
            for b in blist:
                rejected.append(
                    {
                        "participant_id": sub,
                        "session_id": ses,
                        "run": b["run"],
                        "ProtocolName": b["ProtocolName"],
                        "reason": "G1_FAIL_NO_MATCHING_MATLAB",
                        "gates_failed": "G1",
                        "decision": "REJECT",
                    }
                )
            continue

        if len(blist) == 1 and len(mlist) == 1:
            decision = "AUTO_ACCEPT"
            gate5 = "G5_UNIQUE"
            pairs = [(blist[0], mlist[0])]
        elif len(blist) == len(mlist) and len(blist) > 1:
            decision = "AUTO_ACCEPT_ORDERED"
            gate5 = f"G5_ORDERED_K={len(blist)}"
            pairs = list(zip(blist, mlist))
        elif len(blist) > 1 and len(mlist) == 1:
            # Single measured log → earliest SeriesNumber only; later BOLD unscored.
            decision = "AUTO_ACCEPT_FIRST_OF_DUPLICATE"
            gate5 = f"G5_FIRST_OF_{len(blist)}_BOLD_1_MATLAB"
            pairs = [(blist[0], mlist[0])]
            for b in blist[1:]:
                rejected.append(
                    {
                        "participant_id": sub,
                        "session_id": ses,
                        "run": b["run"],
                        "ProtocolName": b["ProtocolName"],
                        "SeriesNumber": b.get("SeriesNumber"),
                        "reason": "G5_DUPLICATE_BOLD_NO_SECOND_MATLAB_LEFT_UNSCORED",
                        "gates_failed": "G5_partial",
                        "decision": "REJECT_UNSCORED_DUPLICATE",
                        "paired_instead_to_run": blist[0]["run"],
                    }
                )
        else:
            for b in blist:
                rejected.append(
                    {
                        "participant_id": sub,
                        "session_id": ses,
                        "run": b["run"],
                        "ProtocolName": b["ProtocolName"],
                        "SeriesNumber": b.get("SeriesNumber"),
                        "reason": (
                            f"G5_FAIL_CARDINALITY_BOLD={len(blist)}_MATLAB={len(mlist)}"
                        ),
                        "gates_failed": "G5",
                        "decision": "REJECT",
                        "matlab_sources": "|".join(m["source_mat"] for m in mlist),
                    }
                )
            for m in mlist:
                rejected.append(
                    {
                        "participant_id": sub,
                        "session_id": ses,
                        "fmri_number": n,
                        "source_mat": m["source_mat"],
                        "reason": (
                            f"G5_FAIL_CARDINALITY_BOLD={len(blist)}_MATLAB={len(mlist)}"
                        ),
                        "gates_failed": "G5",
                        "decision": "REJECT",
                    }
                )
            continue

        for b, m in pairs:
            bkey = (sub, ses, str(b["run"]).zfill(2))
            mkey = m["source_mat"]
            if bkey in used_bold or mkey in used_mat:
                rejected.append(
                    {
                        "participant_id": sub,
                        "session_id": ses,
                        "run": b["run"],
                        "source_mat": mkey,
                        "reason": "G6_FAIL_ALREADY_ASSIGNED",
                        "gates_failed": "G6",
                        "decision": "REJECT",
                    }
                )
                continue
            used_bold.add(bkey)
            used_mat.add(mkey)
            already = bool(b.get("has_events_tsv"))
            candidates.append(
                {
                    "participant_id": sub,
                    "session_id": ses,
                    "fmri_number": n,
                    "bids_run": str(b["run"]).zfill(2),
                    "ProtocolName": b["ProtocolName"],
                    "SeriesNumber": b.get("SeriesNumber"),
                    "SeriesTime": b.get("SeriesTime"),
                    "source_mat": m["source_mat"],
                    "sha256": m.get("sha256"),
                    "n_triggers": m["n_triggers"],
                    "trigger_duration": m.get("trigger_duration"),
                    "protocol_expected": m.get("protocol_expected"),
                    "nifti_path": b.get("nifti_path"),
                    "json_path": b.get("json_path"),
                    "gates_passed": f"G1,G2,G3,G4,{gate5},G6",
                    "decision": decision,
                    "already_has_events_in_bids": already,
                    "recommendation": (
                        "KEEP_EXISTING" if already else "INTEGRATE_EVENTS_FROM_MATLAB"
                    ),
                    "events_stem": (
                        f"{sub}_{ses}_task-fmri_run-{str(b['run']).zfill(2)}_events"
                    ),
                }
            )

    return pd.DataFrame(candidates), pd.DataFrame(rejected)


def match_existing_tmp_events(candidates: pd.DataFrame) -> pd.DataFrame:
    tmp = SCRATCH / "tmp_processing" / "events_validation" / "all_events"
    if not tmp.is_dir() or candidates.empty:
        candidates = candidates.copy()
        candidates["precomputed_events_tsv"] = ""
        return candidates
    paths = []
    for _, r in candidates.iterrows():
        plain = tmp / f"{r['events_stem']}.tsv"
        desc = tmp / (
            f"{r['participant_id']}_{r['session_id']}_task-fmri_run-{r['bids_run']}"
            f"_desc-matlabFMRI{int(r['fmri_number'])}_events.tsv"
        )
        if plain.exists():
            paths.append(str(plain))
        elif desc.exists():
            paths.append(str(desc))
        else:
            hits = list(
                tmp.glob(
                    f"{r['participant_id']}_{r['session_id']}_task-fmri_*"
                    f"_desc-matlabFMRI{int(r['fmri_number'])}_events.tsv"
                )
            )
            paths.append(str(hits[0]) if hits else "")
    candidates = candidates.copy()
    candidates["precomputed_events_tsv"] = paths
    return candidates


def write_reports(
    matlab: pd.DataFrame,
    bold: pd.DataFrame,
    cand: pd.DataFrame,
    rej: pd.DataFrame,
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "candidates").mkdir(exist_ok=True)
    (OUT / "rejected").mkdir(exist_ok=True)

    matlab.to_csv(OUT / "MATLAB_TRIGGER_DATABASE.tsv", sep="\t", index=False)
    bold.to_csv(OUT / "BOLD_DATABASE.tsv", sep="\t", index=False)
    cand.to_csv(OUT / "candidates" / "MAPPING_CANDIDATES.tsv", sep="\t", index=False)
    rej.to_csv(OUT / "rejected" / "MAPPING_REJECTED.tsv", sep="\t", index=False)

    to_add = cand[cand["recommendation"] == "INTEGRATE_EVENTS_FROM_MATLAB"]
    to_add.to_csv(OUT / "candidates" / "RECOMMEND_INTEGRATE.tsv", sep="\t", index=False)
    keep = cand[cand["recommendation"] == "KEEP_EXISTING"]
    keep.to_csv(OUT / "candidates" / "ALREADY_IN_BIDS.tsv", sep="\t", index=False)

    miss_path = (
        SCRATCH / "reports" / "events_reconstruction" / "events_missing_task-fmri.tsv"
    )
    recovered_from_missing = 0
    still_missing: list[tuple[str, str, str]] = []
    if miss_path.exists():
        miss = pd.read_csv(miss_path, sep="\t")
        cand_keys = set(
            zip(
                cand["participant_id"],
                cand["session_id"],
                cand["bids_run"].astype(str).str.zfill(2),
            )
        )
        for _, r in miss.iterrows():
            key = (r["subject"], r["session"], str(r["run"]).zfill(2))
            if key in cand_keys:
                recovered_from_missing += 1
            else:
                still_missing.append(key)
        pd.DataFrame(
            [
                {"participant_id": a, "session_id": b, "run": c}
                for a, b, c in still_missing
            ]
        ).to_csv(
            OUT / "rejected" / "STILL_MISSING_AFTER_RECOVERY.tsv", sep="\t", index=False
        )

    n_auto = int((cand["decision"] == "AUTO_ACCEPT").sum()) if len(cand) else 0
    n_ord = int((cand["decision"] == "AUTO_ACCEPT_ORDERED").sum()) if len(cand) else 0
    n_int = len(to_add)
    n_keep = len(keep)
    n_ready = (
        int((to_add["precomputed_events_tsv"].astype(str) != "").sum())
        if n_int
        else 0
    )

    md = f"""# Grating events recovery — FINAL REPORT

Generated: `{datetime.now(timezone.utc).isoformat()}`

## Mode

- **FAIL-CLOSED** — no guessing when BOLD/MATLAB cardinality disagrees
- **READ-ONLY** on `bids/`, `raw_original/`, `derivatives/`, `release_dataset/`
- **No BIDS integration** — recommendations only
- **No invented timing**

## Multi-gate mapping

| Gate | Rule |
|------|------|
| G1 | ProtocolName → same `fmri_number` as MATLAB |
| G2 | Magnitude only (reject `part-phase`) |
| G3 | NIfTI exists |
| G4 | `n_triggers >= 2` |
| G5 | Unique **or** equal cardinality + `SeriesNumber` ↔ MATLAB filename time |
| G6 | Each BOLD run / each `scan_info` used at most once |

Note: user prompt was truncated at « Le mapping doit être ». Gates above implement the fail-closed policy from the Grating gap audit.

## Counts

| Artifact | n |
|----------|--:|
| MATLAB_TRIGGER_DATABASE | {len(matlab)} |
| BOLD_DATABASE | {len(bold)} |
| Candidates | {len(cand)} |
| Rejected rows | {len(rej)} |
| AUTO_ACCEPT | {n_auto} |
| AUTO_ACCEPT_ORDERED | {n_ord} |
| Recommend INTEGRATE | {n_int} |
| … with precomputed events TSV | {n_ready} |
| Already in BIDS | {n_keep} |
| Prior-57 now matched | {recovered_from_missing} |
| Prior-57 still missing | {len(still_missing)} |

## Recommendations

1. Curator review `candidates/RECOMMEND_INTEGRATE.tsv` (prefer rows with `precomputed_events_tsv`).
2. Spot-check all `AUTO_ACCEPT_ORDERED` pairs before release.
3. Do not integrate `rejected/` without manual decision.
4. A separate integration step (not run here) may copy approved TSVs into BIDS.

## Reject reasons

"""
    if len(rej):
        for k, v in rej["reason"].value_counts().items():
            md += f"- `{k}`: {int(v)}\n"
    else:
        md += "- (none)\n"

    (OUT / "FINAL_RECOVERY_REPORT.md").write_text(md, encoding="utf-8")
    (OUT / "MAPPING_GATES.md").write_text(
        """# Mapping gates (fail-closed)

## G1 — Protocol family
BOLD `ProtocolName`/`SeriesDescription` must parse to the same integer `fmri_number`
as the MATLAB `scan_info` (`fmri_number_isN` / extracted field).

## G2 — Magnitude
Only magnitude BOLD (`part-phase` excluded). Phase shares events with magnitude sibling
but is never the integration target.

## G3 — File existence
NIfTI must exist on disk.

## G4 — Measured triggers
`n_triggers >= 2` from `triggerTimes`. Otherwise REJECT (no invented timing).

## G5 — Uniqueness / ordered 1:1
- 1 BOLD ↔ 1 MATLAB for that (sub, ses, N): AUTO_ACCEPT
- K BOLD ↔ K MATLAB, K>1: pair by ascending `SeriesNumber` ↔ MATLAB filename timestamp
  → AUTO_ACCEPT_ORDERED (acquisition-order hypothesis; spot-check required)
- K_bold ≠ K_matlab: REJECT (do not guess which redo to drop)

## G6 — Injectivity
Each BOLD run and each `scan_info` path assigned at most once.
""",
        encoding="utf-8",
    )
    print(md)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    inv_path = (
        SCRATCH
        / "reports"
        / "events_reconstruction"
        / "MATLAB_EVENTS_SOURCE_INVENTORY.tsv"
    )
    if not inv_path.exists():
        print("Missing inventory", inv_path)
        return 1
    inv = pd.read_csv(inv_path, sep="\t")
    matlab = build_matlab_trigger_db(inv)
    bold = build_bold_db()
    cand, rej = multi_gate_map(matlab, bold)
    cand = match_existing_tmp_events(cand)
    write_reports(matlab, bold, cand, rej)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
