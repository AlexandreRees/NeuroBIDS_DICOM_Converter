"""Built-in diffusion sequence plugin (generic patterns only)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from neuro_pipeline.plugins.base import SequenceDetection, SequencePlugin


class DiffusionPlugin(SequencePlugin):
    name = "diffusion"
    priority = 10

    _DWI = re.compile(r"\bdwi\b|dti|diff(?:usion)?|ep2d_diff|epi[_-]?diff", re.I)
    _ADC = re.compile(r"\badc\b", re.I)

    def detect(self, metadata: Mapping[str, Any]) -> SequenceDetection | None:
        blob = self._blob(metadata)
        if metadata.get("diffusion_present") is True or self._DWI.search(blob):
            if self._ADC.search(blob) and not self._DWI.search(blob.replace("ADC", "")):
                return SequenceDetection(
                    datatype="dwi",
                    suffix="ADC",
                    confidence=0.85,
                    label="Apparent diffusion coefficient",
                    plugin=self.name,
                    pattern_name="ADC",
                )
            return SequenceDetection(
                datatype="dwi",
                suffix="dwi",
                confidence=0.93,
                label="Diffusion weighted MRI",
                plugin=self.name,
                pattern_name="DWI",
            )
        return None
