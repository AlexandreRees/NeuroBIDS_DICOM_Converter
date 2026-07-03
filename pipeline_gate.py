#!/usr/bin/env python3
"""Entry point for the strict BIDS publication gate."""

from __future__ import annotations

import sys

from neuro_pipeline.publication_gate import main

if __name__ == "__main__":
    sys.exit(main())
