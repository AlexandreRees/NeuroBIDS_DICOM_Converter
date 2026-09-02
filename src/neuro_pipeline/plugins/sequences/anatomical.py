"""Built-in anatomical sequence plugin (generic patterns only)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from neuro_pipeline.plugins.base import SequenceDetection, SequencePlugin


class AnatomicalPlugin(SequencePlugin):
    name = "anatomical"
    priority = 20

    _T1 = re.compile(r"mprage|t1w|t1[_ -]?weighted|mp2rage|bravo|fspgr|t1ffe", re.I)
    _T2 = re.compile(r"t2w|t2[_ -]?weighted|t2[_ -]?space|cube|spc", re.I)
    _FLAIR = re.compile(r"flair", re.I)

    def detect(self, metadata: Mapping[str, Any]) -> SequenceDetection | None:
        blob = self._blob(metadata)
        if self._FLAIR.search(blob):
            return SequenceDetection(
                datatype="anat",
                suffix="FLAIR",
                confidence=0.92,
                label="T2-FLAIR MRI",
                plugin=self.name,
                pattern_name="FLAIR",
            )
        if self._T1.search(blob):
            return SequenceDetection(
                datatype="anat",
                suffix="T1w",
                confidence=0.9,
                label="T1 weighted MRI",
                plugin=self.name,
                pattern_name="T1w",
            )
        if self._T2.search(blob):
            return SequenceDetection(
                datatype="anat",
                suffix="T2w",
                confidence=0.88,
                label="T2 weighted MRI",
                plugin=self.name,
                pattern_name="T2w",
            )
        return None
