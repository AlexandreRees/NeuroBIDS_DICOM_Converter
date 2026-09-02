"""NeuroBIDS UI Preview / Demo Mode package."""

from __future__ import annotations

from typing import Any

__all__ = [
    "apply_preview_scenario",
    "build_preview_plan",
    "build_preview_series",
    "build_preview_window",
]


def __getattr__(name: str) -> Any:
    if name in {"apply_preview_scenario", "build_preview_window"}:
        from neuro_pipeline.gui.preview.bootstrap import apply_preview_scenario, build_preview_window

        mapping = {
            "apply_preview_scenario": apply_preview_scenario,
            "build_preview_window": build_preview_window,
        }
        return mapping[name]
    if name in {"build_preview_plan", "build_preview_series"}:
        from neuro_pipeline.gui.preview.dataset import build_preview_plan, build_preview_series

        mapping = {
            "build_preview_plan": build_preview_plan,
            "build_preview_series": build_preview_series,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
