#!/usr/bin/env python3
"""Plan and, only after approval, build the safe Level-1 release candidate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from convert_events import build_strict_events, write_events
from convert_physio import assess_physio_group
from deidentify_release import assert_phi_pass, source_phi_labels


BIDS_VERSION = "1.11.1"
PHYSIO_EXTENSIONS = {".resp", ".puls", ".ecg", ".pmu", ".ext", ".ext1", ".ext2"}
MEDIA_EXTENSIONS = {".mp4", ".avi", ".wav", ".audio"}
EYE_PATTERN = re.compile(r"(?i)(?:eye|eyelink|gaze|pupil|fixation|saccade|blink)")
FMRI_STEM = re.compile(r"(?i)^fmri_(\d+)$")
FMRI_PROTOCOL = re.compile(r"(?i)(?:^|[^A-Za-z0-9])fmri[_ -]?0*(\d+)(?!\d)")
ACTION_COLUMNS = (
    "action",
    "category",
    "participant_id",
    "session_id",
    "destination",
    "status",
    "reason",
    "source_refs",
    "source_paths",
    "source_sha256",
    "phi_before",
)


@dataclass
class Action:
    action: str
    category: str
    participant_id: str
    session_id: str
    destination: str
    status: str
    reason: str
    source_refs: str
    source_paths: str
    source_sha256: str
    phi_before: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_ref(path: Path) -> str:
    return "source-" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]


def raw_relative(path: Path) -> str:
    parts = path.parts
    if "raw_original" in parts:
        return Path(*parts[parts.index("raw_original") + 1 :]).as_posix()
    return path.as_posix()


def resolve_source(path: Path, roots: list[Path]) -> Path:
    if path.is_file():
        return path
    relative = raw_relative(path)
    for root in roots:
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_tsv_exclusive(
    path: Path, rows: Iterable[dict[str, str]], columns: Iterable[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(columns), delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def mapping_index(path: Path) -> tuple[dict[tuple[str, str], str], set[tuple[str, str]]]:
    values: dict[tuple[str, str], set[str]] = defaultdict(set)
    has_dicoms: set[tuple[str, str]] = set()
    for row in read_csv(path):
        participant = row.get("participant_id", "").strip()
        subject = (
            row.get("canonical_subject_id")
            or row.get("canonical_subject")
            or ""
        ).strip()
        if not participant.startswith("sub-") or not subject:
            continue
        if row.get("exclusion_status", "").strip().lower() == "excluded":
            continue
        sessions = {
            row.get("session_id", "").strip(),
            row.get("session_label", "").strip(),
            row.get("canonical_session", "").strip(),
        }
        for session in sessions - {""}:
            key = (subject, session)
            values[key].add(participant)
            if row.get("has_dicoms", "").strip().lower() == "true":
                has_dicoms.add(key)
    conflicts = {key: item for key, item in values.items() if len(item) != 1}
    if conflicts:
        raise ValueError(f"ambiguous subject/session mappings: {len(conflicts)}")
    return {key: next(iter(item)) for key, item in values.items()}, has_dicoms


def plan_index(path: Path) -> dict[str, dict[str, str]]:
    return {
        raw_relative(Path(row["source_path"])): row
        for row in read_tsv(path)
        if row.get("source_path")
    }


def audit_index(path: Path) -> dict[str, dict[str, str]]:
    return {row["relative_path"]: row for row in read_tsv(path)}


def source_phi(
    paths: list[Path], audit: dict[str, dict[str, str]]
) -> str:
    labels: set[str] = set()
    for path in paths:
        row = audit.get(raw_relative(path), {})
        labels.update(
            item.strip()
            for item in row.get("phi_fields", "").split(";")
            if item.strip()
        )
        labels.update(source_phi_labels(path))
    return "; ".join(sorted(labels))


def encoded_sources(
    paths: list[Path], *, include_hashes: bool = False
) -> tuple[str, str, str]:
    refs = [source_ref(path) for path in paths]
    hashes = [sha256(path) for path in paths] if include_hashes else []
    return (
        json.dumps(refs, separators=(",", ":")),
        json.dumps([str(path) for path in paths], separators=(",", ":")),
        json.dumps(hashes, separators=(",", ":")),
    )


def bids_destination(
    bids_root: Path, participant: str, session: str, number: int
) -> tuple[str, str]:
    func = bids_root / participant / session / "func"
    matches: list[Path] = []
    for sidecar in func.glob(f"{participant}_{session}_task-*_run-*_bold.json"):
        if "_part-" in sidecar.name:
            continue
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        text = " ".join(
            str(metadata.get(key, ""))
            for key in ("ProtocolName", "SeriesDescription", "TaskName")
        )
        protocol_numbers = {int(item) for item in FMRI_PROTOCOL.findall(text)}
        if number in protocol_numbers:
            matches.append(sidecar)
    if len(matches) != 1:
        return "", f"expected one matching non-phase BOLD sidecar, found {len(matches)}"
    name = matches[0].name.removesuffix("_bold.json") + "_events.tsv"
    return f"{participant}/{session}/func/{name}", "matched by recorded BOLD protocol metadata"


def create_actions(args: argparse.Namespace) -> tuple[list[Action], dict[str, int]]:
    inventory = read_tsv(args.inventory)
    publication = plan_index(args.publication_plan)
    audit = audit_index(args.audit)
    mappings, has_dicoms = mapping_index(args.session_mapping)
    roots = [args.raw_root, args.current_raw_root]
    actions: list[Action] = []
    timing: dict[tuple[str, str, str], dict[str, list[Path]]] = defaultdict(
        lambda: defaultdict(list)
    )
    physio: dict[tuple[str, str, str, str], list[Path]] = defaultdict(list)
    represented_sources: set[str] = set()

    for row in inventory:
        original = Path(row.get("path", ""))
        source = resolve_source(original, roots)
        relative = raw_relative(source)
        subject = row.get("subject", "").strip()
        session = row.get("session", "").strip()
        extension = (row.get("extension") or source.suffix).lower()
        category = row.get("category", "unknown")
        mapped = mappings.get((subject, session), "")
        planned = publication.get(relative, {})
        is_strict_timing_source = extension == ".mat" and (
            "scan_info" in source.name.lower()
            or FMRI_STEM.fullmatch(source.stem) is not None
            or source.stem.lower() == "runs_random"
        )
        eligible = bool(mapped) and (
            (subject, session) in has_dicoms or (subject, session) in mappings
        )
        excluded_reason = ""
        if not source.is_file():
            excluded_reason = "source missing"
        elif not eligible:
            excluded_reason = "no unambiguous existing subject/session mapping"
        elif extension in MEDIA_EXTENSIONS:
            excluded_reason = "copyright/media exclusion"
        elif extension in {".edf", ".asc"} or category == "eye_tracking":
            excluded_reason = "eye-tracking exclusion"
        elif EYE_PATTERN.search(relative):
            excluded_reason = "eye/gaze/pupil path exclusion"
        elif (
            planned.get("release_decision") != "KEEP_BIDS"
            and not is_strict_timing_source
        ):
            excluded_reason = (
                "publication plan decision "
                + (planned.get("release_decision") or "missing")
            )

        if excluded_reason:
            refs, paths, hashes = (
                encoded_sources([source])
                if source.is_file()
                else (
                    json.dumps([source_ref(source)]),
                    json.dumps([str(source)]),
                    "[]",
                )
            )
            actions.append(
                Action(
                    "EXCLUDE",
                    category,
                    mapped,
                    session,
                    "",
                    "excluded",
                    excluded_reason,
                    refs,
                    paths,
                    hashes,
                    "",
                )
            )
            represented_sources.add(relative)
            continue

        if extension in PHYSIO_EXTENSIONS:
            physio[(mapped, session, str(source.parent), source.stem)].append(source)
            represented_sources.add(relative)
            continue

        if extension == ".mat":
            key = (mapped, session, str(source.parent))
            lower = source.name.lower()
            if "scan_info" in lower:
                timing[key]["scan_info"].append(source)
                represented_sources.add(relative)
                continue
            if FMRI_STEM.fullmatch(source.stem):
                timing[key]["stim_order"].append(source)
                represented_sources.add(relative)
                continue
            if source.stem.lower() == "runs_random":
                timing[key]["runs_random"].append(source)
                represented_sources.add(relative)
                continue

        refs, paths, hashes = encoded_sources([source])
        actions.append(
            Action(
                "EXCLUDE",
                category,
                mapped,
                session,
                "",
                "excluded",
                "not a strict physiology or recorded task-timing source",
                refs,
                paths,
                hashes,
                "",
            )
        )
        represented_sources.add(relative)

    for (participant, session, _parent, _stem), sources in sorted(physio.items()):
        assessment = assess_physio_group(sorted(sources))
        refs, paths, hashes = encoded_sources(sorted(sources))
        actions.append(
            Action(
                "REVIEW_PHYSIO",
                "physiology",
                participant,
                session,
                "review_required/manual_review.tsv",
                "requires_manual_review",
                assessment.reason,
                refs,
                paths,
                hashes,
                source_phi(sorted(sources), audit),
            )
        )

    for (participant, session, _parent), families in sorted(timing.items()):
        scans_by_run: dict[int, list[Path]] = defaultdict(list)
        stim_by_run: dict[int, list[Path]] = defaultdict(list)
        for path in families.get("scan_info", []):
            match = re.search(r"(?i)fmri_number_is(\d+)", path.name)
            if match:
                scans_by_run[int(match.group(1))].append(path)
        for path in families.get("stim_order", []):
            match = FMRI_STEM.fullmatch(path.stem)
            if match:
                stim_by_run[int(match.group(1))].append(path)
        run_numbers = sorted(set(scans_by_run) | set(stim_by_run))
        workspaces = families.get("runs_random", [])
        for number in run_numbers:
            sources = scans_by_run[number] + stim_by_run[number] + workspaces
            if (
                len(scans_by_run[number]) != 1
                or len(stim_by_run[number]) != 1
                or len(workspaces) != 1
            ):
                status = "requires_manual_review"
                reason = (
                    f"source cardinality scan={len(scans_by_run[number])}, "
                    f"stim={len(stim_by_run[number])}, workspace={len(workspaces)}"
                )
                destination = "review_required/manual_review.tsv"
            else:
                result = build_strict_events(
                    scan_info=scans_by_run[number][0],
                    stim_order=stim_by_run[number][0],
                    runs_random=workspaces[0],
                )
                destination, match_reason = bids_destination(
                    args.bids_root, participant, session, number
                )
                if result.status == "ready" and destination:
                    status = "ready"
                    reason = f"{result.reason}; {match_reason}"
                else:
                    status = "requires_manual_review"
                    reason = (
                        result.reason
                        if result.status != "ready"
                        else match_reason
                    )
                    destination = "review_required/manual_review.tsv"
            refs, paths, hashes = encoded_sources(
                sources, include_hashes=status == "ready"
            )
            actions.append(
                Action(
                    "CONVERT_EVENTS" if status == "ready" else "REVIEW_EVENTS",
                    "task_timing",
                    participant,
                    session,
                    destination,
                    status,
                    reason,
                    refs,
                    paths,
                    hashes,
                    source_phi(sources, audit),
                )
            )

    counts = Counter(action.action for action in actions)
    counts["inventory_files"] = len(inventory)
    counts["scientific_outputs_ready"] = sum(
        action.status == "ready" for action in actions
    )
    counts["manual_review_items"] = sum(
        action.status == "requires_manual_review" for action in actions
    )
    return actions, dict(counts)


def action_digest(actions: list[Action]) -> str:
    payload = json.dumps(
        [asdict(action) for action in actions],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dry_run(args: argparse.Namespace) -> int:
    if args.target.exists():
        raise FileExistsError(f"target already exists; refusing: {args.target}")
    actions, counts = create_actions(args)
    plan_dir = args.plan_dir
    plan_dir.mkdir(parents=True, exist_ok=False)
    write_tsv_exclusive(
        plan_dir / "planned_actions.tsv",
        [asdict(action) for action in actions],
        ACTION_COLUMNS,
    )
    metadata = {
        "mode": "dry-run",
        "target_created": False,
        "source_operations": "read-only",
        "bids_version": BIDS_VERSION,
        "action_digest": action_digest(actions),
        "counts": counts,
        "input_sha256": {
            "inventory": sha256(args.inventory),
            "publication_plan": sha256(args.publication_plan),
            "session_mapping": sha256(args.session_mapping),
            "audit": sha256(args.audit),
        },
    }
    with (plan_dir / "plan_metadata.json").open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")
    lines = [
        "# Level-1 release dry run",
        "",
        "**No release directory was created and no source file was modified or copied.**",
        "",
        f"- Inventory files: {counts.get('inventory_files', 0)}",
        f"- Scientific event outputs ready: {counts.get('scientific_outputs_ready', 0)}",
        f"- Physiology review groups: {counts.get('REVIEW_PHYSIO', 0)}",
        f"- Event timing review items: {counts.get('REVIEW_EVENTS', 0)}",
        f"- Excluded inventory files: {counts.get('EXCLUDE', 0)}",
        f"- Total manual-review items: {counts.get('manual_review_items', 0)}",
        "",
        "Execution requires an explicit `--execute --approved-plan` invocation.",
        "",
    ]
    (plan_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))
    print(f"planned_actions: {plan_dir / 'planned_actions.tsv'}")
    return 0


def _load_approved_actions(path: Path) -> list[Action]:
    return [Action(**row) for row in read_tsv(path / "planned_actions.tsv")]


def _copy_code(target: Path) -> None:
    source_dir = Path(__file__).resolve().parent
    destination = target / "code"
    destination.mkdir(parents=True, exist_ok=False)
    for name in (
        "convert_physio.py",
        "convert_events.py",
        "deidentify_release.py",
        "README.md",
    ):
        with (source_dir / name).open("rb") as source:
            with (destination / name).open("xb") as output:
                shutil.copyfileobj(source, output)


def _redact_report(text: str, target: Path) -> str:
    text = text.replace(str(target), "<dataset>")
    text = re.sub(r"(?i)/(?:home|Users)/[^/\s]+", "<local-home>", text)
    text = re.sub(r"/lustre\d*/scratch/[^/\s]+", "<local-scratch>", text)
    return text


def execute(args: argparse.Namespace) -> int:
    approved = args.approved_plan
    metadata = json.loads((approved / "plan_metadata.json").read_text(encoding="utf-8"))
    actions = _load_approved_actions(approved)
    if action_digest(actions) != metadata["action_digest"]:
        raise ValueError("approved action plan digest mismatch")
    for label, path in (
        ("inventory", args.inventory),
        ("publication_plan", args.publication_plan),
        ("session_mapping", args.session_mapping),
        ("audit", args.audit),
    ):
        if sha256(path) != metadata["input_sha256"][label]:
            raise ValueError(f"input changed since dry run: {label}")
    if args.target.exists():
        raise FileExistsError(f"target already exists; refusing: {args.target}")
    args.target.mkdir(parents=True, exist_ok=False)
    _copy_code(args.target)
    (args.target / "manifests").mkdir()
    (args.target / "review_required").mkdir()
    with (args.target / "dataset_description.json").open("x", encoding="utf-8") as handle:
        json.dump(
            {
                "Name": "Multimodal MRI dataset",
                "BIDSVersion": BIDS_VERSION,
                "DatasetType": "raw",
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    (args.target / ".bidsignore").write_text(
        "manifests/\nreview_required/\nvalidation_report.txt\nvalidation_issues.md\n",
        encoding="utf-8",
    )

    # Fail-closed destination collisions: keep the first ready action per
    # destination and demote later collisions to review (never overwrite).
    seen_destinations: set[str] = set()
    demoted_collisions = 0
    for action in actions:
        if action.status != "ready" or not action.destination:
            continue
        if action.destination in seen_destinations:
            action.status = "requires_manual_review"
            action.action = "REVIEW_EVENTS"
            action.reason = (
                "duplicate_destination_collision; identical or competing "
                f"ready conversion for {action.destination}; demoted to review"
            )
            action.destination = "review_required/manual_review.tsv"
            demoted_collisions += 1
            continue
        seen_destinations.add(action.destination)

    release_rows: list[dict[str, str]] = []
    phi_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    for action in actions:
        paths = [Path(item) for item in json.loads(action.source_paths)]
        refs = json.loads(action.source_refs)
        hashes = json.loads(action.source_sha256)
        if action.status == "ready" and [sha256(path) for path in paths] != hashes:
            raise ValueError(f"source changed after dry run: {refs}")
        if action.status != "ready":
            if action.status == "requires_manual_review":
                review_rows.append(
                    {
                        "source_ref": ";".join(refs),
                        "category": action.category,
                        "participant_id": action.participant_id,
                        "session_id": action.session_id,
                        "reason": action.reason,
                    }
                )
            continue
        output = args.target / action.destination
        if output.exists():
            raise FileExistsError(f"refusing to overwrite existing release file: {output}")
        if action.action == "CONVERT_EVENTS":
            result = build_strict_events(
                scan_info=paths[0], stim_order=paths[1], runs_random=paths[2]
            )
            write_events(output, result)
        else:
            raise ValueError(f"unsupported ready action: {action.action}")
        assert_phi_pass(output)
        release_rows.append(
            {
                "source_file": ";".join(refs),
                "sha256": ";".join(hashes),
                "destination": action.destination,
                "category": action.category,
                "conversion_status": "converted_phi_pass",
            }
        )
        for ref, path in zip(refs, paths):
            phi_rows.append(
                {
                    "file": ref,
                    "original_path": f"REDACTED:path-sha256={hashlib.sha256(str(path).encode()).hexdigest()}",
                    "category": action.category,
                    "phi_detected": "yes" if action.phi_before else "no",
                    "phi_type": action.phi_before,
                    "action": "minimal derivative generated; source and MATLAB metadata not copied; output PHI scan PASS",
                    "output_path": action.destination,
                }
            )

    write_tsv_exclusive(
        args.target / "manifests" / "release_manifest.tsv",
        release_rows,
        ("source_file", "sha256", "destination", "category", "conversion_status"),
    )
    write_tsv_exclusive(
        args.target / "manifests" / "phi_audit.tsv",
        phi_rows,
        (
            "file",
            "original_path",
            "category",
            "phi_detected",
            "phi_type",
            "action",
            "output_path",
        ),
    )
    write_tsv_exclusive(
        args.target / "review_required" / "manual_review.tsv",
        review_rows,
        ("source_ref", "category", "participant_id", "session_id", "reason"),
    )

    subjects = {
        action.participant_id for action in actions if action.status == "ready"
    }
    sessions = {
        (action.participant_id, action.session_id)
        for action in actions
        if action.status == "ready"
    }
    readme = [
        "# Minimal Scientific Data Level-1 release candidate",
        "",
        f"- Subjects with included scientific data: {len(subjects)}",
        f"- Subject/session pairs with included scientific data: {len(sessions)}",
        f"- Physiology files: 0 (all unresolved groups excluded pending manual review)",
        f"- Event files: {len(release_rows)}",
        f"- Manual-review items: {len(review_rows)}",
        f"- Destination collisions demoted at execute: {demoted_collisions}",
        "- Excluded: eye tracking, EDF/ASC, gaze/pupil, movies, audio, stimulus images",
        "- PHI handling: source identifiers and MATLAB metadata were not copied; every included scientific derivative passed the output PHI scan",
        "- Copyright handling: audiovisual stimuli were excluded",
        "",
    ]
    (args.target / "README.md").write_text("\n".join(readme), encoding="utf-8")

    validator = shutil.which("bids-validator")
    command = [validator, str(args.target)] if validator else []
    if not validator and shutil.which("npx"):
        command = ["npx", "--yes", "bids-validator", str(args.target)]
    if command:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        report = _redact_report(
            f"command: bids-validator <dataset>\nexit_code: {result.returncode}\n\n"
            + result.stdout
            + "\n"
            + result.stderr,
            args.target,
        )
        status = "PASS" if result.returncode == 0 else "FAIL"
    else:
        report = "bids-validator unavailable; validation not run\n"
        status = "NOT_RUN"
    (args.target / "validation_report.txt").write_text(report, encoding="utf-8")
    if status != "PASS":
        (args.target / "validation_issues.md").write_text(
            "# Validation issues\n\n"
            f"Status: **{status}**. See `validation_report.txt`. No automatic fixes were applied.\n",
            encoding="utf-8",
        )

    checksum_rows = []
    for path in sorted(item for item in args.target.rglob("*") if item.is_file()):
        if path.name == "checksums.tsv":
            continue
        checksum_rows.append(
            {"sha256": sha256(path), "file": path.relative_to(args.target).as_posix()}
        )
    write_tsv_exclusive(
        args.target / "manifests" / "checksums.tsv",
        checksum_rows,
        ("sha256", "file"),
    )
    print(
        json.dumps(
            {
                "included_scientific_files": len(release_rows),
                "excluded_inventory_files": metadata["counts"].get("EXCLUDE", 0),
                "phi_findings_before_cleaning": sum(
                    bool(row["phi_type"]) for row in phi_rows
                ),
                "phi_findings_after_cleaning": 0,
                "bids_validation_status": status,
                "manual_review_items": len(review_rows),
                "destination_collisions_demoted": demoted_collisions,
            },
            indent=2,
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--inventory",
        type=Path,
        default=Path("/home/alexrees/scratch/reports/associated_data_inventory.tsv"),
    )
    result.add_argument(
        "--publication-plan",
        type=Path,
        default=Path("/home/alexrees/scratch/release_candidate_plan/release_manifest.tsv"),
    )
    result.add_argument(
        "--audit",
        type=Path,
        default=Path(
            "/home/alexrees/scratch/reports/associated_data_audit/file_level_audit.tsv"
        ),
    )
    result.add_argument(
        "--session-mapping",
        type=Path,
        default=Path("/home/alexrees/scratch/metadata/session_mapping.csv"),
    )
    result.add_argument(
        "--raw-root",
        type=Path,
        default=Path("/project/def-amirs/raw_original"),
        help="Canonical raw_original root (also used when remapping historical inventory paths).",
    )
    result.add_argument(
        "--current-raw-root",
        type=Path,
        default=Path("/project/def-amirs/raw_original"),
        help="Live raw_original mount (same as --raw-root after scratch migration).",
    )
    result.add_argument(
        "--bids-root",
        type=Path,
        default=Path("/home/alexrees/scratch/bids"),
    )
    result.add_argument(
        "--target",
        type=Path,
        default=Path("/lustre07/scratch/alexrees/release_candidate_level1"),
    )
    result.add_argument("--plan-dir", type=Path)
    result.add_argument("--execute", action="store_true")
    result.add_argument("--approved-plan", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.execute:
        if args.approved_plan is None:
            raise ValueError("--execute requires --approved-plan")
        return execute(args)
    if args.approved_plan is not None:
        raise ValueError("--approved-plan is valid only with --execute")
    if args.plan_dir is None:
        raise ValueError("dry run requires --plan-dir")
    return dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
