"""Generic DICOM sequence type classification (informational only).

Provides:
- Coarse ``SequenceType`` (anat/func/dwi/fmap/unknown) for display / BIDS hints
- Fine-grained ``SequenceClassification`` with confidence scores

Never replaces BIDS planning or blocks conversion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import yaml

from neuro_pipeline.config.paths import project_root, resource_root
from neuro_pipeline.utils.resources import resolve_config

if TYPE_CHECKING:
    from neuro_pipeline.dicom.metadata import DicomSeriesMetadata
    from neuro_pipeline.scanner.scanner_profiles import ScannerProfile

LOGGER = logging.getLogger(__name__)


class SequenceType(str, Enum):
    """Coarse imaging category used only for display / reporting."""

    ANAT = "anat"
    FUNC = "func"
    DWI = "dwi"
    FMAP = "fmap"
    UNKNOWN = "unknown"


class FineSequenceType(str, Enum):
    """Fine-grained informative labels (do not drive BIDS layout alone)."""

    ANAT_T1 = "ANAT_T1"
    ANAT_T2 = "ANAT_T2"
    FLAIR = "FLAIR"
    DWI = "DWI"
    DTI = "DTI"
    FMRI_REST = "FMRI_REST"
    FMRI_TASK = "FMRI_TASK"
    FMAP = "FMAP"
    PERFUSION = "PERFUSION"
    ASL = "ASL"
    SWI = "SWI"
    LOCALIZER = "LOCALIZER"
    UNKNOWN = "UNKNOWN"


_FINE_TO_COARSE = {
    FineSequenceType.ANAT_T1: SequenceType.ANAT,
    FineSequenceType.ANAT_T2: SequenceType.ANAT,
    FineSequenceType.FLAIR: SequenceType.ANAT,
    FineSequenceType.SWI: SequenceType.ANAT,
    FineSequenceType.LOCALIZER: SequenceType.UNKNOWN,
    FineSequenceType.DWI: SequenceType.DWI,
    FineSequenceType.DTI: SequenceType.DWI,
    FineSequenceType.FMRI_REST: SequenceType.FUNC,
    FineSequenceType.FMRI_TASK: SequenceType.FUNC,
    FineSequenceType.FMAP: SequenceType.FMAP,
    FineSequenceType.PERFUSION: SequenceType.UNKNOWN,
    FineSequenceType.ASL: SequenceType.UNKNOWN,
    FineSequenceType.UNKNOWN: SequenceType.UNKNOWN,
}

_PROFILE_TO_TYPE = {
    "T1": SequenceType.ANAT,
    "T2": SequenceType.ANAT,
    "ANAT": SequenceType.ANAT,
    "DWI": SequenceType.DWI,
    "FUNC": SequenceType.FUNC,
    "FMAP": SequenceType.FMAP,
}

# Specificity order for YAML fine matching
_FINE_MATCH_ORDER = (
    FineSequenceType.LOCALIZER,
    FineSequenceType.FLAIR,
    FineSequenceType.DTI,
    FineSequenceType.DWI,
    FineSequenceType.ASL,
    FineSequenceType.PERFUSION,
    FineSequenceType.SWI,
    FineSequenceType.FMAP,
    FineSequenceType.FMRI_REST,
    FineSequenceType.FMRI_TASK,
    FineSequenceType.ANAT_T1,
    FineSequenceType.ANAT_T2,
)


@dataclass(slots=True)
class SequenceClassification:
    """Detailed advisory classification result."""

    type: FineSequenceType
    confidence: float
    reason: list[str] = field(default_factory=list)
    coarse: SequenceType = SequenceType.UNKNOWN

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type.value,
            "confidence": round(float(self.confidence), 4),
            "reason": list(self.reason),
            "coarse": self.coarse.value,
        }


@dataclass(slots=True)
class DetectionHint:
    """Compatibility hint consumed by the DICOM parser / provenance."""

    suffix: str = ""
    confidence: float = 0.0
    display_label: str = ""
    plugin: str = "sequence_rules"
    requires_manual_mapping: bool = False


class SequenceClassifier:
    """Infer a likely sequence class from generic DICOM tags.

    Never blocks conversion — results are advisory.
    Optional ``scanner_profile`` enhances matching using vendor YAML rules
    without changing the legacy fallback behaviour.
    """

    _ANAT = re.compile(
        r"t1|t2|mprage|flair|space|mp2rage|t1w|t2w|anat|gre(?!_field)|flash|spgr",
        re.I,
    )
    _FUNC = re.compile(
        r"bold|rest|task|fmri|epi(?!2d_diff)|movie|func|mbep2d|cmrr",
        re.I,
    )
    _DWI = re.compile(
        r"dwi|dti|diff|ep2d_diff|trace|tensor",
        re.I,
    )
    _FMAP = re.compile(
        r"field.?map|fmap|gre_field|phasediff|magnitude|topup|se_epi_pa|b0map",
        re.I,
    )

    def __init__(self, rules_path: Path | str | None = None) -> None:
        self.rules_path = Path(rules_path) if rules_path else self._default_rules_path()
        self._rules = self._load_rules(self.rules_path)
        self.last_detection: DetectionHint | None = None

    @staticmethod
    def _default_rules_path() -> Path:
        return resolve_config("sequence_rules.yaml")

    def _load_rules(self, path: Path) -> dict[str, list[str]]:
        if not path.exists():
            LOGGER.warning("sequence_rules.yaml missing: %s", path)
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = yaml.safe_load(handle) or {}
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to load sequence rules: %s", exc)
            return {}
        out: dict[str, list[str]] = {}
        if not isinstance(raw, dict):
            return out
        for key, block in raw.items():
            if not isinstance(block, dict):
                continue
            patterns = block.get("patterns") or []
            if isinstance(patterns, list):
                out[str(key).upper()] = [str(p) for p in patterns]
        return out

    def classify(
        self,
        *,
        series_description: str = "",
        protocol_name: str = "",
        image_type: Sequence[str] | str | None = None,
        diffusion_present: bool | None = None,
        modality: str = "",
        scanner_profile: "ScannerProfile | None" = None,
    ) -> SequenceType:
        """Return the most likely coarse sequence type from available metadata."""
        detailed = self.classify_detailed(
            series_description=series_description,
            protocol_name=protocol_name,
            image_type=image_type,
            diffusion_present=diffusion_present,
            modality=modality,
            scanner_profile=scanner_profile,
        )
        # Preserve prior coarse behaviour using legacy regex + profile first
        coarse = self._classify_coarse(
            series_description=series_description,
            protocol_name=protocol_name,
            image_type=image_type,
            diffusion_present=diffusion_present,
            modality=modality,
            scanner_profile=scanner_profile,
        )
        self.last_detection = DetectionHint(
            suffix=detailed.type.value,
            confidence=detailed.confidence,
            display_label=detailed.type.value,
            plugin="sequence_rules",
            requires_manual_mapping=detailed.type == FineSequenceType.UNKNOWN,
        )
        # Prefer coarse when detailed maps to unknown but coarse found something
        if detailed.type == FineSequenceType.UNKNOWN:
            return coarse
        return detailed.coarse if detailed.coarse != SequenceType.UNKNOWN else coarse

    def _matches_ignore(self, blob: str) -> bool:
        for pattern in self._rules.get("IGNORE", []):
            if not pattern:
                continue
            try:
                if re.search(pattern, blob, flags=re.IGNORECASE):
                    return True
            except re.error:
                if pattern.lower() in blob.lower():
                    return True
        return False

    def _classify_coarse(
        self,
        *,
        series_description: str = "",
        protocol_name: str = "",
        image_type: Sequence[str] | str | None = None,
        diffusion_present: bool | None = None,
        modality: str = "",
        scanner_profile: "ScannerProfile | None" = None,
    ) -> SequenceType:
        blob = " ".join(
            [
                series_description or "",
                protocol_name or "",
                _image_type_text(image_type),
                modality or "",
            ]
        )

        if self._matches_ignore(blob):
            return SequenceType.UNKNOWN

        if scanner_profile is not None:
            matched = scanner_profile.match_sequence(blob)
            if matched:
                mapped = _PROFILE_TO_TYPE.get(matched.upper())
                if mapped is not None:
                    return mapped

        if diffusion_present is True or self._DWI.search(blob):
            if self._FMAP.search(blob) and not self._DWI.search(blob):
                return SequenceType.FMAP
            return SequenceType.DWI
        if self._FMAP.search(blob):
            return SequenceType.FMAP
        if self._FUNC.search(blob):
            return SequenceType.FUNC
        if self._ANAT.search(blob):
            return SequenceType.ANAT
        return SequenceType.UNKNOWN

    def classify_detailed(
        self,
        metadata: "DicomSeriesMetadata | None" = None,
        *,
        series_description: str = "",
        protocol_name: str = "",
        image_type: Sequence[str] | str | None = None,
        diffusion_present: bool | None = None,
        modality: str = "",
        scanner_profile: "ScannerProfile | None" = None,
        b_values: Sequence[float] | None = None,
    ) -> SequenceClassification:
        """Fine-grained classification with confidence and reasons."""
        if metadata is not None:
            series_description = metadata.series_description or series_description
            protocol_name = metadata.protocol_name or protocol_name
            image_type = metadata.image_type or image_type
            modality = metadata.modality or modality
            diffusion_present = metadata.diffusion_present if diffusion_present is None else diffusion_present
            b_values = metadata.b_values or b_values

        blob = " ".join(
            [
                series_description or "",
                protocol_name or "",
                _image_type_text(image_type),
                modality or "",
            ]
        ).lower()
        reasons: list[str] = []
        fine: FineSequenceType | None = None
        confidence = 0.0

        if self._matches_ignore(blob):
            return SequenceClassification(
                type=FineSequenceType.UNKNOWN,
                confidence=1.0,
                reason=["Matched IGNORE pattern (e.g. ADC map)"],
                coarse=SequenceType.UNKNOWN,
            )

        # YAML pattern pass (ordered)
        for candidate in _FINE_MATCH_ORDER:
            patterns = self._rules.get(candidate.value, [])
            for pattern in patterns:
                if not pattern:
                    continue
                try:
                    if re.search(pattern, blob, flags=re.IGNORECASE):
                        fine = candidate
                        confidence = 0.82
                        reasons.append(
                            f"Matched pattern '{pattern}' → {candidate.value}"
                        )
                        break
                except re.error:
                    if pattern.lower() in blob:
                        fine = candidate
                        confidence = 0.8
                        reasons.append(
                            f"Series/Protocol contains '{pattern}' → {candidate.value}"
                        )
                        break
            if fine is not None:
                break

        # Diffusion evidence boost / override toward DWI/DTI
        bv = list(b_values or [])
        if diffusion_present or bv:
            dti_tokens = ("dti", "tensor", "dir64", "dir30", "64dir", "30dir")
            if fine in {
                None,
                FineSequenceType.UNKNOWN,
                FineSequenceType.FMRI_TASK,
                FineSequenceType.FMRI_REST,
            }:
                if any(tok in blob for tok in dti_tokens):
                    fine = FineSequenceType.DTI
                    reasons.append("Diffusion tags / DTI tokens detected")
                else:
                    fine = FineSequenceType.DWI
                    reasons.append("b-values or diffusion tags detected")
                confidence = max(confidence, 0.9)
            elif fine in {FineSequenceType.DWI, FineSequenceType.DTI}:
                confidence = max(confidence, 0.96)
                if bv:
                    reasons.append("b-values detected")
            if series_description and "ep2d_diff" in series_description.lower():
                reasons.append("SeriesDescription contains ep2d_diff")
                confidence = max(confidence, 0.96)

        # ImageType LOCALIZER
        img = _image_type_text(image_type).upper()
        if "LOCALIZER" in img or "SCOUT" in img:
            fine = FineSequenceType.LOCALIZER
            confidence = max(confidence, 0.88)
            reasons.append("ImageType indicates LOCALIZER")

        if fine is None:
            # Fall back to coarse mapping
            coarse = self._classify_coarse(
                series_description=series_description,
                protocol_name=protocol_name,
                image_type=image_type,
                diffusion_present=diffusion_present,
                modality=modality,
                scanner_profile=scanner_profile,
            )
            fine = {
                SequenceType.ANAT: FineSequenceType.ANAT_T1,
                SequenceType.FUNC: FineSequenceType.FMRI_REST,
                SequenceType.DWI: FineSequenceType.DWI,
                SequenceType.FMAP: FineSequenceType.FMAP,
                SequenceType.UNKNOWN: FineSequenceType.UNKNOWN,
            }[coarse]
            confidence = 0.55 if fine != FineSequenceType.UNKNOWN else 0.2
            reasons.append(f"Fallback coarse mapping → {fine.value}")

        coarse_out = _FINE_TO_COARSE.get(fine, SequenceType.UNKNOWN)
        confidence = max(0.0, min(1.0, float(confidence)))
        return SequenceClassification(
            type=fine,
            confidence=confidence,
            reason=reasons or ["No strong evidence"],
            coarse=coarse_out,
        )

    def classify_from_mapping(
        self,
        tags: Mapping[str, Any],
        *,
        scanner_profile: "ScannerProfile | None" = None,
    ) -> SequenceType:
        """Convenience wrapper for dict-like DICOM tag bags."""
        image_type = tags.get("ImageType")
        diffusion = None
        for key in ("DiffusionBValue", "B_value", "DiffusionGradientDirectionSequence"):
            if key in tags and tags[key] not in (None, "", []):
                diffusion = True
                break
        return self.classify(
            series_description=str(tags.get("SeriesDescription", "") or ""),
            protocol_name=str(tags.get("ProtocolName", "") or ""),
            image_type=image_type,  # type: ignore[arg-type]
            diffusion_present=diffusion,
            modality=str(tags.get("Modality", "") or ""),
            scanner_profile=scanner_profile,
        )


def _image_type_text(image_type: Sequence[str] | str | None) -> str:
    if image_type is None:
        return ""
    if isinstance(image_type, str):
        return image_type
    return " ".join(str(x) for x in image_type)
