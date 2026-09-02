"""Launch NeuroBIDS UI Preview/Demo Mode.

Usage::

    python -m neuro_pipeline.gui.preview
    python -m neuro_pipeline.gui.preview --scenario audit
    python -m neuro_pipeline.gui.preview --scenario changeset

Uses the real :class:`MainWindow` and production widgets with a tiny
synthetic dataset. No real DICOM, no patient data, no LLM API key.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m neuro_pipeline.gui.preview",
        description="NeuroBIDS UI Preview/Demo Mode (synthetic dataset, Fake LLM).",
    )
    parser.add_argument(
        "--scenario",
        choices=("normal", "audit", "changeset"),
        default="normal",
        help="Demo scenario: normal Map view, Audit focus, or pending ChangeSet",
    )
    parser.add_argument(
        "--root",
        default="",
        help="Optional synthetic dataset root label (paths only; no real DICOM required)",
    )
    args = parser.parse_args(argv)

    from PySide6.QtWidgets import QApplication

    from neuro_pipeline.config.loader import load_app_config
    from neuro_pipeline.gui.preview.bootstrap import build_preview_window
    from neuro_pipeline.gui.styles import APP_STYLESHEET

    app = QApplication(sys.argv)
    app.setApplicationName("NeuroBIDS UI Preview")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    config = load_app_config()
    root = Path(args.root) if args.root else Path("preview_demo")
    window = build_preview_window(config, scenario=args.scenario, root=root)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
