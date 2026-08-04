#!/usr/bin/env python3
"""Generate design-level BIDS task-movie events.tsv (+ sidecars).

Timing basis (protocol assumption; no measured Psychtoolbox TTL logs exist):
  - Lab confirmation (fMRI lead): scanner acquisition started with the movie clips;
    TR × n_volumes should roughly equal clip length; no other timing files acquired.
  - Empirical QC: magnitude BOLD is typically 210 volumes @ TR 0.937 s → 196.770 s;
    ffprobe duration of Movie{1A,1B,2A,2B}.mp4 is 196.821333 s (Δ ≈ 51 ms ≈ 0.05 TR).
  - Therefore each run is modeled as one continuous movie event with onset = 0
    relative to the first archived BOLD volume, and duration = measured MP4 length.

Stimulus identity comes from ProtocolName MovieN_* → matlab_run_id dictionary,
enriched by code/task-movie/task-movie_run_assignments.tsv when present.

Does not invent sub-TR onsets. Documents limitations in README + sidecars.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/alexrees/scratch")
BIDS_DEFAULT = ROOT / "bids"
RELEASE_DEFAULT = ROOT / "release_dataset"
DICT_TSV = ROOT / "code" / "task-movie" / "task-movie_run_dictionary.tsv"
ASSIGN_TSV = ROOT / "code" / "task-movie" / "task-movie_run_assignments.tsv"
REPORT_DIR = ROOT / "reports" / "movie_events_generation"

# Measured with ffprobe on archived stimulus copies (Control SUBC01 + Glaucoma SUBG16).
MP4_DURATION_SEC = 196.821333
EXPECTED_VOLUMES = 210
EXPECTED_TR = 0.937
SCRIPT_NAME = "generate_movie_events.py"
SCRIPT_VERSION = "2026-07-29_protocol_sync_v1"

BOLD_RE = re.compile(
    r"^(?P<sub>sub-\d+)_(?P<ses>ses-\d+)_task-movie_(?P<run>run-\d+)_bold\.nii\.gz$"
)
MOVIE_N_RE = re.compile(r"(?i)Movie\s*([1-4])")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_dictionary(path: Path) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            rid = int(row["matlab_run_id"])
            out[rid] = row
    return out


def load_assignments(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    out: dict[tuple[str, str, str], dict[str, str]] = {}
    if not path.is_file():
        return out
    with path.open(newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            run = f"run-{int(row['bids_run']):02d}"
            key = (row["participant_id"], row["session_id"], run)
            out[key] = row
    return out


def movie_index_from_protocol(protocol: str | None) -> int | None:
    if not protocol:
        return None
    m = MOVIE_N_RE.search(protocol)
    return int(m.group(1)) if m else None


def dataset_events_json() -> dict:
    return {
        "onset": {
            "Description": (
                "Onset of continuous movie viewing relative to the start of the "
                "archived BOLD series (first volume), in seconds. Set to 0 under the "
                "documented protocol assumption that scanner acquisition and movie "
                "clip playback started together. Not derived from saved Psychtoolbox "
                "triggerTimes (none were logged for task-movie)."
            ),
            "Units": "s",
        },
        "duration": {
            "Description": (
                "Duration of the movie stimulus in seconds, from ffprobe of the "
                f"archived MP4 clips (all four clips = {MP4_DURATION_SEC} s). "
                f"Scan length is typically {EXPECTED_VOLUMES}×{EXPECTED_TR}="
                f"{EXPECTED_VOLUMES * EXPECTED_TR:.3f} s (Δ≈51 ms)."
            ),
            "Units": "s",
        },
        "trial_type": {
            "Description": "Task condition. Single continuous naturalistic movie block per run.",
            "Levels": {
                "movie": "Naturalistic monocular movie clip presentation with fixation overlay."
            },
        },
        "stim_file": {
            "Description": (
                "Basename of the movie file selected by MATLAB run_id / ProtocolName "
                "mapping (files not redistributed for copyright reasons)."
            ),
        },
        "eye": {
            "Description": "Stimulated eye for monocular presentation (from protocol dictionary / assignments).",
            "Levels": {
                "left": "Left-eye stimulation.",
                "right": "Right-eye stimulation.",
            },
        },
        "movie_label": {
            "Description": "Scanner ProtocolName family label (Movie1–Movie4).",
            "Levels": {
                "Movie1": "Protocol Movie1_* ↔ Movie1A.mp4",
                "Movie2": "Protocol Movie2_* ↔ Movie2A.mp4",
                "Movie3": "Protocol Movie3_* ↔ Movie1B.mp4",
                "Movie4": "Protocol Movie4_* ↔ Movie2B.mp4",
            },
        },
        "matlab_run_id": {
            "Description": "MATLAB main.m run_id (1–4) corresponding to clip/eye mapping.",
        },
    }


def per_run_sidecar(
    *,
    stim_file: str,
    eye: str,
    movie_label: str,
    matlab_run_id: int,
    protocol_name: str | None,
    mapping_confidence: str,
    mapping_method: str,
    n_volumes: int | None,
    tr: float | None,
) -> dict:
    scan_dur = None
    if n_volumes is not None and tr is not None:
        scan_dur = round(n_volumes * tr, 6)
    return {
        "Description": (
            "Design-level task-movie events. Onsets are protocol-synchronized to BOLD "
            "series start (lab-confirmed scan↔movie co-start), not measured TTL/VBL logs."
        ),
        "TaskName": "movie",
        "timing_basis": "protocol_sync_scan_start_equals_movie_start",
        "timing_basis_note": (
            "No triggerTimes/VBL were saved by Show_movie.m. Lab fMRI lead confirmed "
            "scanner started with movie clips; TR×volumes≈MP4 duration (Δ≈51 ms)."
        ),
        "stimulus_duration_source": "ffprobe_mp4",
        "stimulus_duration_seconds": MP4_DURATION_SEC,
        "expected_volumes": EXPECTED_VOLUMES,
        "expected_RepetitionTime": EXPECTED_TR,
        "observed_n_volumes": n_volumes,
        "observed_RepetitionTime": tr,
        "observed_scan_duration_seconds": scan_dur,
        "stim_file": stim_file,
        "eye": eye,
        "movie_label": movie_label,
        "matlab_run_id": matlab_run_id,
        "ProtocolName": protocol_name,
        "mapping_confidence": mapping_confidence,
        "mapping_method": mapping_method,
        "GeneratedBy": [
            {
                "Name": SCRIPT_NAME,
                "Version": SCRIPT_VERSION,
                "Description": (
                    "Design-level reconstruction from ProtocolName/assignments + "
                    "protocol sync assumption + measured MP4 duration."
                ),
                "Date": utc_now(),
            }
        ],
    }


def read_bold_meta(bold: Path) -> tuple[dict, int | None, float | None]:
    js = bold.with_suffix("").with_suffix(".json")  # .nii.gz → .json
    # Path.with_suffix only strips one suffix; handle .nii.gz explicitly
    if bold.name.endswith(".nii.gz"):
        js = bold.with_name(bold.name[: -len(".nii.gz")] + ".json")
    meta: dict = {}
    if js.is_file():
        meta = json.loads(js.read_text())
    tr = meta.get("RepetitionTime")
    n_volumes = None
    # Prefer nifti header when affordable; for speed use expected if header slow — try nibabel
    try:
        import nibabel as nib

        n_volumes = int(nib.load(str(bold)).shape[3])
    except Exception:
        n_volumes = None
    return meta, n_volumes, float(tr) if tr is not None else None


def write_events_tsv(path: Path, row: dict[str, object]) -> None:
    cols = ["onset", "duration", "trial_type", "stim_file", "eye", "movie_label", "matlab_run_id"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerow({c: row[c] for c in cols})


def process_tree(
    bids_root: Path,
    dictionary: dict[int, dict[str, str]],
    assignments: dict[tuple[str, str, str], dict[str, str]],
    *,
    dry_run: bool,
    skip_header_volumes: bool,
) -> list[dict[str, object]]:
    bolds = sorted(
        p
        for p in bids_root.glob("sub-*/ses-*/func/*task-movie*_bold.nii.gz")
        if "_part-phase_" not in p.name
    )
    rows: list[dict[str, object]] = []
    for bold in bolds:
        m = BOLD_RE.match(bold.name)
        if not m:
            continue
        sub, ses, run = m.group("sub"), m.group("ses"), m.group("run")
        key = (sub, ses, run)
        meta = {}
        n_volumes = None
        tr = None
        if skip_header_volumes:
            js = bold.with_name(bold.name[: -len(".nii.gz")] + ".json")
            if js.is_file():
                meta = json.loads(js.read_text())
            tr = float(meta["RepetitionTime"]) if meta.get("RepetitionTime") is not None else None
        else:
            meta, n_volumes, tr = read_bold_meta(bold)

        protocol = meta.get("ProtocolName") or meta.get("SeriesDescription")
        assign = assignments.get(key)

        if assign:
            matlab_run_id = int(assign["matlab_run_id"])
            stim_file = assign["stimulus_name"]
            eye = assign["eye"]
            movie_label = dictionary[matlab_run_id]["movie_label"]
            mapping_confidence = assign.get("mapping_confidence", "HIGH")
            mapping_method = assign.get("mapping_method", "assignment_tsv")
            protocol = assign.get("ProtocolName") or protocol
        else:
            idx = movie_index_from_protocol(protocol)
            if idx is None or idx not in dictionary:
                rows.append(
                    {
                        "bids_root": str(bids_root),
                        "participant_id": sub,
                        "session_id": ses,
                        "bids_run": run,
                        "bold_path": str(bold.relative_to(bids_root)),
                        "status": "SKIPPED_NO_PROTOCOL_MAP",
                        "ProtocolName": protocol,
                    }
                )
                continue
            matlab_run_id = idx
            d = dictionary[matlab_run_id]
            stim_file = d["stimulus_name"]
            eye = d["eye"]
            movie_label = d["movie_label"]
            mapping_confidence = "MEDIUM"
            mapping_method = "ProtocolName_MovieN_fallback_unassigned_or_ambiguous"

        events_tsv = bold.with_name(bold.name.replace("_bold.nii.gz", "_events.tsv"))
        events_json = bold.with_name(bold.name.replace("_bold.nii.gz", "_events.json"))

        duration = MP4_DURATION_SEC
        capped = False
        if n_volumes is not None and tr is not None:
            scan_s = float(n_volumes) * float(tr)
            if scan_s + 1e-9 < MP4_DURATION_SEC:
                duration = scan_s
                capped = True

        event_row = {
            "onset": f"{0.0:.6f}",
            "duration": f"{duration:.6f}",
            "trial_type": "movie",
            "stim_file": stim_file,
            "eye": eye,
            "movie_label": movie_label,
            "matlab_run_id": matlab_run_id,
        }
        sidecar = per_run_sidecar(
            stim_file=stim_file,
            eye=eye,
            movie_label=movie_label,
            matlab_run_id=matlab_run_id,
            protocol_name=protocol,
            mapping_confidence=mapping_confidence,
            mapping_method=mapping_method,
            n_volumes=n_volumes,
            tr=tr,
        )
        sidecar["events_duration_seconds"] = float(f"{duration:.6f}")
        sidecar["duration_capped_to_scan"] = capped
        if capped:
            sidecar["duration_cap_note"] = (
                "BOLD series shorter than full MP4 (likely aborted/truncated); "
                "events duration=min(mp4_duration, n_volumes*TR)."
            )

        if not dry_run:
            write_events_tsv(events_tsv, event_row)
            events_json.write_text(json.dumps(sidecar, indent=2) + "\n")

        rows.append(
            {
                "bids_root": str(bids_root),
                "participant_id": sub,
                "session_id": ses,
                "bids_run": run,
                "bold_path": str(bold.relative_to(bids_root)),
                "events_tsv": str(events_tsv.relative_to(bids_root)),
                "status": "DRY_RUN" if dry_run else "WRITTEN",
                "stim_file": stim_file,
                "eye": eye,
                "movie_label": movie_label,
                "matlab_run_id": matlab_run_id,
                "mapping_confidence": mapping_confidence,
                "mapping_method": mapping_method,
                "ProtocolName": protocol,
                "observed_n_volumes": n_volumes,
                "observed_TR": tr,
                "onset": 0.0,
                "duration": MP4_DURATION_SEC,
            }
        )
    return rows


def write_report(rows: list[dict[str, object]], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    tsv = report_dir / "movie_events_generation.tsv"
    # union of keys
    fieldnames: list[str] = []
    for r in rows:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with tsv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    status = Counter(str(r.get("status")) for r in rows)
    conf = Counter(str(r.get("mapping_confidence")) for r in rows if r.get("mapping_confidence"))
    md = report_dir / "MOVIE_EVENTS_GENERATION_REPORT.md"
    md.write_text(
        "\n".join(
            [
                "# Movie events.tsv generation report",
                "",
                f"**Generated:** `{utc_now()}`",
                f"**Script:** `code/bids_fixes/{SCRIPT_NAME}` (`{SCRIPT_VERSION}`)",
                "",
                "## Timing policy",
                "",
                "- `onset = 0` — protocol assumption: scanner start = movie start (lab fMRI lead).",
                f"- `duration = {MP4_DURATION_SEC}` s — ffprobe of archived MP4 clips.",
                f"- QC: {EXPECTED_VOLUMES} volumes × TR {EXPECTED_TR} s = "
                f"{EXPECTED_VOLUMES * EXPECTED_TR:.3f} s (Δ ≈ 51 ms vs MP4).",
                "- No Psychtoolbox `triggerTimes` / VBL logs exist for task-movie.",
                "",
                "## Counts",
                "",
                "| Status | N |",
                "|---|---:|",
                *[f"| `{k}` | {v} |" for k, v in sorted(status.items())],
                "",
                "| mapping_confidence | N |",
                "|---|---:|",
                *[f"| `{k}` | {v} |" for k, v in sorted(conf.items())],
                "",
                "## Artifacts",
                "",
                "- Per-run `*_task-movie_run-*_events.tsv` + `*_events.json`",
                "- Dataset `task-movie_events.json` (column definitions)",
                "- This report + `movie_events_generation.tsv`",
                "",
                "## Limitations",
                "",
                "- Onsets are **not** millisecond-precise TTL measurements.",
                "- Suitable for run-level / continuous-movie models; not frame-locked analyses.",
                "- `MEDIUM` confidence rows lack a unique MATLAB assignment (usually duplicate ProtocolName).",
                "",
            ]
        )
        + "\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bids-root", type=Path, action="append", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--read-nifti-volumes",
        action="store_true",
        help="Read NIfTI headers for observed_n_volumes (slower on Lustre).",
    )
    ap.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    args = ap.parse_args()

    roots = args.bids_root or [BIDS_DEFAULT, RELEASE_DEFAULT]
    dictionary = load_dictionary(DICT_TSV)
    assignments = load_assignments(ASSIGN_TSV)

    all_rows: list[dict[str, object]] = []
    for root in roots:
        if not root.is_dir():
            print(f"SKIP missing root: {root}")
            continue
        # dataset-level sidecar
        if not args.dry_run:
            (root / "task-movie_events.json").write_text(
                json.dumps(dataset_events_json(), indent=2) + "\n"
            )
        rows = process_tree(
            root,
            dictionary,
            assignments,
            dry_run=args.dry_run,
            skip_header_volumes=not args.read_nifti_volumes,
        )
        all_rows.extend(rows)
        written = sum(1 for r in rows if r.get("status") in {"WRITTEN", "DRY_RUN"})
        skipped = sum(1 for r in rows if str(r.get("status", "")).startswith("SKIPPED"))
        print(f"{root}: events={written} skipped={skipped}")

    write_report(all_rows, args.report_dir)
    print(f"report → {args.report_dir}")


if __name__ == "__main__":
    main()
