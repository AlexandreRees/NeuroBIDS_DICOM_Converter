"""Application entry point.

Usage:
    python -m neuro_pipeline
    python -m neuro_pipeline --debug-scan DICOM_FOLDER
    python -m neuro_pipeline convert --input DIR --output DIR [--batch]
    python -m neuro_pipeline export-profile --input DIR --output DIR --profile bids
    python -m neuro_pipeline audit identity --config configs/audit_paths.yaml
    neuro-pipeline-gui
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _debug_scan(folder: Path) -> int:
    """Print detected series without launching the GUI."""
    from neuro_pipeline.dicom import DicomParser
    from neuro_pipeline.logging.setup import configure_logging

    configure_logging()
    parser = DicomParser()
    series = parser.scan(folder)
    print(f"Detected series: {len(series)}")
    print()
    for idx, item in enumerate(series, start=1):
        print(f"{idx}. {item.series_description or item.protocol_name or item.display_name}")
        print(f"   Path: {item.source_dir}")
        print(f"   Number of DICOM files: {item.num_images}")
        print(f"   Classified modality: {item.sequence_type} ({item.modality or '—'})")
        if item.fine_sequence_type:
            print(
                f"   Fine type: {item.fine_sequence_type} "
                f"(confidence={item.sequence_confidence:.2f})"
            )
        print()
    if parser.last_scanner_info is not None:
        info = parser.last_scanner_info
        print("Scanner detected:")
        print(f"  Manufacturer: {info.manufacturer}")
        print(f"  Model: {info.model}")
        print(f"  Field: {info.field_label}")
        print(f"  Confidence: {info.confidence}")
    return 0


def _convert_cli(args: argparse.Namespace) -> int:
    """Headless conversion using existing ConversionManager / BatchManager."""
    from neuro_pipeline.batch import BatchManager
    from neuro_pipeline.converter.conversion_manager import ConversionManager
    from neuro_pipeline.dicom import DicomParser
    from neuro_pipeline.logging.setup import configure_logging
    from neuro_pipeline.models import ConversionOptions

    configure_logging()
    inp = Path(args.input)
    out = Path(args.output)
    if not inp.is_dir():
        print(f"Input not found: {inp}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    options = ConversionOptions(
        compress=not args.no_compress,
        preserve_json=not args.no_json,
        validate_output=not args.no_validate,
        export_profile=str(getattr(args, "export_profile", "") or ""),
    )

    if args.batch:
        mgr = BatchManager()
        jobs = mgr.discover_datasets(inp, output_root=out)
        print(f"Batch jobs: {len(jobs)}")
        mgr.run_all(options=options, resume=not args.no_resume)
        for job in mgr.queue.all_jobs():
            print(
                f"{job.label}: {job.status.value} "
                f"converted={job.converted_count} failed={job.failed_count}"
            )
        return 0 if all(j.status.value != "FAILED" for j in mgr.queue.all_jobs()) else 1

    parser = DicomParser()
    series = parser.scan(inp)
    print(f"Series: {len(series)}")
    pipeline = ConversionManager().run(
        series_list=series,
        input_folder=inp,
        output_dir=out,
        options=options,
    )
    print(f"Converted={pipeline.converted} failed={pipeline.failed}")
    if pipeline.bids_validation_report:
        print(f"BIDS validation report: {pipeline.bids_validation_report}")
    if pipeline.report_path:
        print(f"Report: {pipeline.report_path}")
    return 0 if pipeline.failed == 0 else 1


def _export_profile_cli(args: argparse.Namespace) -> int:
    """Package an existing conversion output with a named profile."""
    from neuro_pipeline.export import ExportProfileManager
    from neuro_pipeline.logging.setup import configure_logging

    configure_logging()
    inp = Path(args.input)
    out = Path(args.output)
    if not inp.is_dir():
        print(f"Input not found: {inp}", file=sys.stderr)
        return 2
    try:
        result = ExportProfileManager().apply(
            input_dir=inp,
            output_dir=out,
            profile=args.profile,
            dataset_name=args.dataset_name or "NeuroPipeline Dataset",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1
    print(f"Profile: {result.profile}")
    print(f"Output: {result.output_dir}")
    print(f"Files written: {len(result.files_written)}")
    print(f"Skipped: {len(result.skipped)}")
    print(result.message)
    return 0


def _audit_identity_cli(args: argparse.Namespace) -> int:
    """Read-only DICOM ↔ BIDS ↔ defaced ↔ resync identity audit."""
    from neuro_pipeline.audit.identity_audit import IdentityAudit
    from neuro_pipeline.logging.setup import configure_logging

    configure_logging()
    config = Path(args.config)
    if not config.is_file():
        print(f"Config not found: {config}", file=sys.stderr)
        return 2
    try:
        result = IdentityAudit(config).run()
    except Exception as exc:  # noqa: BLE001
        print(f"Identity audit failed: {exc}", file=sys.stderr)
        return 1
    print("Identity audit complete (read-only; no imaging data modified).")
    print(f"Mapping rows: {len(result.subject_mapping)}")
    for path in result.output_files:
        print(f"  wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Launch the GUI, or run diagnostic / conversion modes."""
    args = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(prog="neuro_pipeline")
    parser.add_argument(
        "--debug-scan",
        metavar="DICOM_FOLDER",
        help="Scan a DICOM folder and print detected series, then exit",
    )
    sub = parser.add_subparsers(dest="command")

    convert = sub.add_parser("convert", help="Headless DICOM → NIfTI conversion")
    convert.add_argument("--input", required=True, help="DICOM folder (or dataset root in --batch)")
    convert.add_argument("--output", required=True, help="Output folder")
    convert.add_argument("--batch", action="store_true", help="Treat input children as subjects")
    convert.add_argument("--no-resume", action="store_true", help="Do not resume from state.json")
    convert.add_argument("--no-compress", action="store_true")
    convert.add_argument("--no-json", action="store_true")
    convert.add_argument("--no-validate", action="store_true")
    convert.add_argument(
        "--export-profile",
        default="",
        help="Optional packaging profile after conversion: bids|clinical|archive",
    )

    export_p = sub.add_parser(
        "export-profile",
        help="Package an existing conversion output (bids|clinical|archive)",
    )
    export_p.add_argument("--input", required=True, help="Existing conversion output folder")
    export_p.add_argument("--output", required=True, help="Destination package folder")
    export_p.add_argument(
        "--profile",
        required=True,
        choices=["bids", "clinical", "archive"],
        help="Export profile",
    )
    export_p.add_argument("--dataset-name", default="NeuroPipeline Dataset")

    audit = sub.add_parser("audit", help="Read-only dataset audits")
    audit_sub = audit.add_subparsers(dest="audit_command")
    identity = audit_sub.add_parser(
        "identity",
        help="DICOM ↔ BIDS ↔ defaced ↔ resync subject identity audit",
    )
    identity.add_argument(
        "--config",
        required=True,
        help="Path to audit_paths.yaml (no hardcoded dataset roots)",
    )

    known, remaining = parser.parse_known_args(args)

    if known.debug_scan:
        folder = Path(known.debug_scan)
        if not folder.exists():
            print(f"Folder not found: {folder}", file=sys.stderr)
            return 2
        return _debug_scan(folder)

    if known.command == "convert":
        return _convert_cli(known)
    if known.command == "export-profile":
        return _export_profile_cli(known)
    if known.command == "audit":
        if getattr(known, "audit_command", None) == "identity":
            return _audit_identity_cli(known)
        audit.print_help()
        return 2

    from neuro_pipeline.app import run_app

    return run_app([sys.argv[0], *remaining] if remaining else [sys.argv[0], *args])


if __name__ == "__main__":
    raise SystemExit(main())
