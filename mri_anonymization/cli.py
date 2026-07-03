"""Command-line interface for the MRI anonymization pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mri_anonymization.config import AnonymizationConfig
from mri_anonymization.pipeline import AnonymizationPipeline


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Anonymize MRI/BIDS datasets for public release "
            "(OpenNeuro, Scientific Data, etc.)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Input BIDS dataset directory containing sub-* folders.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Output root containing Public_Dataset/ and Private/.",
    )
    parser.add_argument(
        "--enable-defacing",
        action="store_true",
        help="Apply facial defacing to anatomical MRI volumes.",
    )
    parser.add_argument(
        "--seed",
        type=str,
        default=None,
        help="Secret key for deterministic anonymization (reproducible mode).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel worker processes.",
    )
    parser.add_argument(
        "--dataset-name",
        type=str,
        default="Anonymized Neuroimaging Dataset",
        help="Dataset name written to dataset_description.json.",
    )
    parser.add_argument(
        "--license",
        type=str,
        default="CC0",
        help="License string for dataset_description.json.",
    )
    parser.add_argument(
        "--remove-sex",
        action="store_true",
        help="Remove PatientSex from DICOM (default: preserve).",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)

    config = AnonymizationConfig(
        input_dir=args.input_dir.resolve(),
        output_root=args.output_root.resolve(),
        enable_defacing=args.enable_defacing,
        seed=args.seed,
        preserve_patient_sex=not args.remove_sex,
        num_workers=args.workers,
        dataset_name=args.dataset_name,
        license_text=args.license,
    )

    logging.getLogger("mri_anonymization").setLevel(getattr(logging, args.log_level))

    try:
        pipeline = AnonymizationPipeline(config)
        stats = pipeline.run()
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done. Public dataset: {config.output_root / 'Public_Dataset'} "
        f"({stats.n_subjects} subjects, {stats.n_files_processed} files processed)"
    )
    if stats.n_files_failed:
        print(f"WARNING: {stats.n_files_failed} files failed — see Private/logs/", file=sys.stderr)
    return 0 if stats.n_files_failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
