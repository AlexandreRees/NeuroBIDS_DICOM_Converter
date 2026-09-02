"""Dataset-specific Curation Rules (deterministic, inspectable, reversible)."""

from neuro_pipeline.neurobids.curation.engine import (
    CurationRuleEngine,
    RuleMatch,
    RuleValidationResult,
    acquisition_facts,
    validate_rule,
)
from neuro_pipeline.neurobids.curation.models import (
    ALLOWED_ACTION_FIELDS,
    ALLOWED_CONDITION_FIELDS,
    ALLOWED_OPERATORS,
    CurationRule,
    CurationRuleError,
    RuleAction,
    RuleCondition,
    RulePredicate,
    RuleProvenance,
)
from neuro_pipeline.neurobids.curation.store import CurationRuleStore, dataset_id_for

# proposal imports ChangeSet; keep it lazy to avoid a circular import with
# copilot.changeset → curation.engine/models (which load this package).


def __getattr__(name: str):
    if name in {"propose_rule_from_changeset", "propose_rule_from_examples"}:
        from neuro_pipeline.neurobids.curation import proposal as _proposal

        return getattr(_proposal, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ALLOWED_ACTION_FIELDS",
    "ALLOWED_CONDITION_FIELDS",
    "ALLOWED_OPERATORS",
    "CurationRule",
    "CurationRuleEngine",
    "CurationRuleError",
    "CurationRuleStore",
    "RuleAction",
    "RuleCondition",
    "RuleMatch",
    "RulePredicate",
    "RuleProvenance",
    "RuleValidationResult",
    "acquisition_facts",
    "dataset_id_for",
    "propose_rule_from_changeset",
    "propose_rule_from_examples",
    "validate_rule",
]
