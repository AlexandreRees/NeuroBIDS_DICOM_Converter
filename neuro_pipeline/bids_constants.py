"""BIDS specification constants used across the pipeline."""

from __future__ import annotations

# Target BIDS specification version (https://bids-specification.readthedocs.io/)
BIDS_SPEC_VERSION: str = "1.9.0"

# Pin bids-validator npm package version for reproducible validation in Docker.
BIDS_VALIDATOR_NPM_VERSION: str = "1.14.7"
