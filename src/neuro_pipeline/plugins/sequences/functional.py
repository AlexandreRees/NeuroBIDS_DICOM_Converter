"""Built-in functional sequence plugin (generic patterns only)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from neuro_pipeline.plugins.base import SequenceDetection, SequencePlugin


class FunctionalPlugin(SequencePlugin):
    name = "functional"
    priority = 30

    _FUNC = re.compile(r"bold|rest|task|fmri|mbep2d|cmrr|feepi", re.I)

    def detect(self, metadata: Mapping[str, Any]) -> SequenceDetection | None:
        blob = self._blob(metadata)
        if self._FUNC.search(blob):
            return SequenceDetection(
                datatype="func",
                suffix="bold",
                confidence=0.9,
                label="Functional BOLD MRI",
                plugin=self.name,
                pattern_name="BOLD",
            )
        return None
