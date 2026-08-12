"""Built-in fieldmap sequence plugin (generic patterns only)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from neuro_pipeline.plugins.base import SequenceDetection, SequencePlugin


class FieldmapPlugin(SequencePlugin):
    name = "fieldmaps"
    priority = 15

    _FMAP = re.compile(
        r"field.?map|fmap|gre_field|phasediff|magnitude|b0map|topup",
        re.I,
    )

    def detect(self, metadata: Mapping[str, Any]) -> SequenceDetection | None:
        blob = self._blob(metadata)
        if self._FMAP.search(blob):
            return SequenceDetection(
                datatype="fmap",
                suffix="fmap",
                confidence=0.9,
                label="Fieldmap MRI",
                plugin=self.name,
                pattern_name="FMAP",
            )
        return None
