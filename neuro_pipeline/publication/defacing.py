#!/usr/bin/env python3
"""Deface anatomical BIDS volumes using pydeface or fsl_deface."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.config.extensions import build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)

ANAT_SUFFIX_MARKERS: tuple[str, ...] = ("_T1w", "_T2w", "_PDw", "_FLAIR", "_MPRAGE")


def is_nifti(path: Path) -> bool:
    """Return True if *path* is a NIfTI file."""
    name = path.name.lower()
    return name.endswith(".nii.gz") or name.endswith(".nii")


def is_anatomical_nifti(path: Path, raw_bids: Path) -> bool:
    """Detect anatomical NIfTI files eligible for defacing."""
    if not is_nifti(path) or "_defaced" in path.name:
        return False

    if any(marker in path.name for marker in ANAT_SUFFIX_MARKERS):
        return True

    try:
        relative = path.relative_to(raw_bids)
    except ValueError:
        return False

    return len(relative.parts) >= 3 and relative.parts[2] == "anat"


def discover_anatomical_volumes(raw_bids: Path) -> list[Path]:
    """Collect anatomical NIfTI files from raw_bids in deterministic order."""
    return sorted(
        path
        for path in raw_bids.rglob("*")
        if path.is_file() and is_anatomical_nifti(path, raw_bids)
    )


def defaced_output_path(paths: ProjectPaths, input_nifti: Path) -> Path:
    """Compute defaced output path under derivatives/neuro_pipeline."""
    relative = input_nifti.relative_to(paths.raw_bids)
    if input_nifti.name.endswith(".nii.gz"):
        output_name = input_nifti.name.replace(".nii.gz", "_defaced.nii.gz")
    else:
        output_name = input_nifti.name.replace(".nii", "_defaced.nii")
    return paths.derivatives / relative.parent / output_name


def parse_bids_ids(nifti_path: Path, raw_bids: Path) -> tuple[str, str]:
    """Extract participant and session labels from a BIDS NIfTI path."""
    relative = nifti_path.relative_to(raw_bids)
    participant_id = relative.parts[0] if relative.parts else ""
    session_label = ""
    if len(relative.parts) >= 2 and relative.parts[1].startswith("ses-"):
        session_label = relative.parts[1]
    return participant_id, session_label


def resolve_pydeface() -> str | None:
    """Locate pydeface executable."""
    return shutil.which("pydeface")


def resolve_fsl_deface() -> str | None:
    """Locate fsl_deface executable."""
    return shutil.which("deface") or shutil.which("fsl_deface")


def run_pydeface(
    executable: str,
    input_path: Path,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run pydeface on a single anatomical volume."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [executable, str(input_path), "--outfile", str(output_path)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def run_fsl_deface(
    executable: str,
    input_path: Path,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run FSL deface on a single anatomical volume."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [executable, str(input_path), str(output_path)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def deface_volume(
    input_path: Path,
    output_path: Path,
) -> tuple[str, subprocess.CompletedProcess[str]]:
    """Deface one volume using pydeface with FSL fallback."""
    pydeface_bin = resolve_pydeface()
    if pydeface_bin:
        result = run_pydeface(pydeface_bin, input_path, output_path)
        if result.returncode == 0 and output_path.is_file():
            return "pydeface", result

    fsl_bin = resolve_fsl_deface()
    if fsl_bin:
        result = run_fsl_deface(fsl_bin, input_path, output_path)
        if result.returncode == 0 and output_path.is_file():
            return "fsl_deface", result
        return "fsl_deface", result

    if pydeface_bin:
        result = run_pydeface(pydeface_bin, input_path, output_path)
        return "pydeface", result

    raise FatalPipelineError(
        "No defacing tool found. Install pydeface or FSL deface."
    )


def write_session_defacing_log(
    paths: ProjectPaths,
    participant_id: str,
    session_label: str,
    records: list[dict[str, str]],
) -> None:
    """Write per-session defacing report JSON."""
    if not participant_id or not session_label:
        return
    log_path = paths.defacing_session_log(participant_id, session_label)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"participant_id": participant_id, "session_label": session_label, "records": records}
    log_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_defacing(paths: ProjectPaths, *, skip_defacing: bool = False) -> list[dict[str, str]]:
    """Deface all anatomical volumes and write reports."""
    paths.ensure_derivatives_dir()
    paths.validate_writable(paths.derivatives)

    anatomical_volumes = discover_anatomical_volumes(paths.raw_bids)
    if not anatomical_volumes:
        LOGGER.warning("No anatomical volumes found for defacing")
        return []

    if skip_defacing:
        LOGGER.warning("--skip-defacing enabled; defacing step skipped")
        records = [
            {
                "input_file": str(path.resolve()),
                "output_file": "",
                "tool": "skipped",
                "status": "skipped",
                "qc_flag": "skipped",
                "message": "defacing skipped via --skip-defacing",
            }
            for path in anatomical_volumes
        ]
        paths.defacing_report_json.parent.mkdir(parents=True, exist_ok=True)
        paths.defacing_report_json.write_text(
            json.dumps({"records": records, "skipped": True}, indent=2) + "\n",
            encoding="utf-8",
        )
        return records

    all_records: list[dict[str, str]] = []
    session_buckets: dict[tuple[str, str], list[dict[str, str]]] = {}

    for input_path in anatomical_volumes:
        output_path = defaced_output_path(paths, input_path)
        participant_id, session_label = parse_bids_ids(input_path, paths.raw_bids)

        if output_path.is_file():
            record = {
                "input_file": str(input_path.resolve()),
                "output_file": str(output_path.resolve()),
                "tool": "existing",
                "status": "skipped",
                "qc_flag": "pass",
                "message": "defaced output already exists",
            }
            all_records.append(record)
            session_buckets.setdefault((participant_id, session_label), []).append(record)
            continue

        try:
            tool, result = deface_volume(input_path, output_path)
            success = result.returncode == 0 and output_path.is_file()
            record = {
                "input_file": str(input_path.resolve()),
                "output_file": str(output_path.resolve()),
                "tool": tool,
                "status": "success" if success else "failed",
                "qc_flag": "pass" if success else "fail",
                "message": (result.stderr or result.stdout or "").strip(),
            }
        except FatalPipelineError as exc:
            record = {
                "input_file": str(input_path.resolve()),
                "output_file": str(output_path.resolve()),
                "tool": "none",
                "status": "failed",
                "qc_flag": "fail",
                "message": exc.message,
            }

        all_records.append(record)
        session_buckets.setdefault((participant_id, session_label), []).append(record)

        if record["status"] == "failed":
            LOGGER.error(
                "Defacing failed for %s: %s",
                input_path,
                record["message"],
            )

    for (participant_id, session_label), records in sorted(session_buckets.items()):
        write_session_defacing_log(paths, participant_id, session_label, records)

    paths.defacing_report_json.parent.mkdir(parents=True, exist_ok=True)
    paths.defacing_report_json.write_text(
        json.dumps({"records": all_records, "skipped": False}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    failed = sum(1 for record in all_records if record["status"] == "failed")
    if failed > 0:
        raise FatalPipelineError(
            f"Defacing failed for {failed} anatomical volume(s); "
            f"see {paths.defacing_report_json}"
        )

    manifest = build_manifest(
        paths.root,
        steps_completed=[
            "inventory",
            "generate_mapping",
            "deidentify_dicom",
            "convert_to_bids",
            "defacing",
        ],
        extra={
            "defacing_volumes": len(all_records),
            "defacing_skipped": skip_defacing,
        },
    )
    write_manifest(paths.pipeline_manifest_json, manifest)

    return all_records


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(description="Deface anatomical BIDS volumes.")
    parser.add_argument(
        "--skip-defacing",
        action="store_true",
        help="Skip defacing (debug only; publication gate will fail).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for anatomical defacing."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.metadata / "defacing.log",
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting defacing for %s", paths.root)
    try:
        run_defacing(paths, skip_defacing=args.skip_defacing)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("Defacing completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
