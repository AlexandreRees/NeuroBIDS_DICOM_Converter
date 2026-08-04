#!/usr/bin/env python3
"""Run the two independent publication reports and print separate summaries."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path("/home/alexrees/scratch")


def _load_main(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main


def main() -> int:
    demo = ROOT / "reports" / "participant_demographics" / "build_participant_demographics.py"
    proto = ROOT / "reports" / "protocol_completeness" / "build_protocol_completeness.py"

    print("=" * 60)
    print("REPORT 1 — Participant demographic characteristics")
    print("=" * 60)
    code1 = _load_main(demo)([])

    print()
    print("-" * 60)
    print()

    print("=" * 60)
    print("REPORT 2 — MRI protocol completeness")
    print("=" * 60)
    code2 = _load_main(proto)([])
    return 0 if code1 == 0 and code2 == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
