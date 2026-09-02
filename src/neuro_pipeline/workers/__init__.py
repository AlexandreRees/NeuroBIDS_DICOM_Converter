"""Background workers package.

Qt-backed worker classes live in ``qt_workers`` and are imported lazily so that
non-GUI modules (e.g. ``conversion_queue``) can load without PySide6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "BatchWorker",
    "ConversionWorker",
    "CopilotWorker",
    "FolderConvertWorker",
    "InventoryWorker",
    "ScanWorker",
    "start_worker",
]

if TYPE_CHECKING:
    from neuro_pipeline.workers.qt_workers import (  # noqa: F401
        BatchWorker,
        ConversionWorker,
        CopilotWorker,
        FolderConvertWorker,
        InventoryWorker,
        ScanWorker,
        start_worker,
    )


def __getattr__(name: str) -> Any:
    if name in __all__:
        from neuro_pipeline.workers import qt_workers

        return getattr(qt_workers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
