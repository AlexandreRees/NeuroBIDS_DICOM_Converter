#!/usr/bin/env python3
"""Deprecated alias for publication_gate — use neuro_pipeline.publication_gate."""

from __future__ import annotations

import sys

from neuro_pipeline.publication_gate import main

if __name__ == "__main__":
    sys.exit(main())
