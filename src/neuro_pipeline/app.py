"""Application bootstrap for the NeuroPipeline DICOM Converter."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path
from typing import Sequence

from neuro_pipeline import __version__
from neuro_pipeline.config.loader import load_app_config
from neuro_pipeline.config.paths import project_root, resource_root
from neuro_pipeline.logging.setup import configure_logging, get_conversion_log_path

LOGGER = logging.getLogger(__name__)


def _find_app_icon() -> Path | None:
    """Locate the application icon for window / taskbar use."""
    candidates = [
        project_root() / "installer" / "NeuroPipeline.ico",
        project_root() / "assets" / "NeuroPipeline.ico",
        resource_root() / "installer" / "NeuroPipeline.ico",
        resource_root() / "assets" / "NeuroPipeline.ico",
        resource_root() / "NeuroPipeline.ico",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def run_app(argv: Sequence[str] | None = None) -> int:
    """Create the Qt application, load config, and show the main window."""
    # Import Qt only when launching the GUI so non-GUI tests stay lightweight.
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from neuro_pipeline.gui.main_window import MainWindow
    from neuro_pipeline.gui.styles import APP_STYLESHEET

    args = list(argv if argv is not None else sys.argv)
    log_file: Path | None = None

    try:
        config = load_app_config()
        if getattr(config, "logging_enabled", True):
            log_file = configure_logging(config.log_dir)
        else:
            logging.basicConfig(level=logging.WARNING)

        app = QApplication(args)
        app.setApplicationName("NeuroPipeline DICOM Converter")
        app.setApplicationVersion(__version__)
        app.setOrganizationName("Alexandre Rees")
        app.setOrganizationDomain("neuropipeline.local")
        app.setStyle("Fusion")
        app.setStyleSheet(APP_STYLESHEET)

        def _hook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            details = "".join(traceback.format_exception(exc_type, exc, tb))
            LOGGER.error("Unhandled exception:\n%s", details)
            hint = str(log_file or get_conversion_log_path(config.log_dir or None))
            try:
                QMessageBox.critical(
                    None,
                    "Unexpected error",
                    (
                        "NeuroPipeline DICOM Converter encountered an unexpected error.\n\n"
                        f"{exc_type.__name__}: {exc}\n\n"
                        f"Please check the NeuroPipeline log file at:\n{hint}"
                    ),
                )
            except Exception:  # noqa: BLE001
                pass

        sys.excepthook = _hook

        icon_path = _find_app_icon()
        if icon_path is not None:
            app.setWindowIcon(QIcon(str(icon_path)))

        window = MainWindow(config=config)
        if icon_path is not None:
            window.setWindowIcon(QIcon(str(icon_path)))
        window.show()
        return app.exec()
    except Exception as exc:  # noqa: BLE001 - last-resort GUI-safe exit
        LOGGER.exception("Failed to start application")
        hint = ""
        try:
            hint = str(log_file or get_conversion_log_path())
        except Exception:  # noqa: BLE001
            hint = ""
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            _ = QApplication.instance() or QApplication(list(argv or sys.argv))
            QMessageBox.critical(
                None,
                "Startup failed",
                (
                    "NeuroPipeline DICOM Converter could not start.\n\n"
                    f"{exc}\n\n"
                    + (
                        f"Please check the NeuroPipeline log file at:\n{hint}"
                        if hint
                        else "Please check the configuration and logs."
                    )
                ),
            )
        except Exception:  # noqa: BLE001
            print(f"Startup failed: {exc}", file=sys.stderr)
        return 1
