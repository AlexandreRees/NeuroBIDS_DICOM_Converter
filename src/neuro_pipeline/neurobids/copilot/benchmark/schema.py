"""Benchmark case schema for NeuroBIDS Copilot evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CaseCategory(str, Enum):
    DATASET_UNDERSTANDING = "dataset_understanding"
    ACQUISITION_RETRIEVAL = "acquisition_retrieval"
    BIDS_REASONING = "bids_reasoning"
    MUTATIONS = "mutations"
    SAFETY = "safety"


class ExpectedBehavior(str, Enum):
    REJECT = "reject"
    CLARIFY = "clarify"
    READ_ONLY = "read-only response"
    MUTATION_PROPOSAL = "mutation proposal"

    @classmethod
    def parse(cls, value: str) -> ExpectedBehavior:
        raw = (value or "").strip().lower()
        aliases = {
            "reject": cls.REJECT,
            "refusal": cls.REJECT,
            "clarify": cls.CLARIFY,
            "clarification": cls.CLARIFY,
            "read-only response": cls.READ_ONLY,
            "read only": cls.READ_ONLY,
            "readonly": cls.READ_ONLY,
            "read-only": cls.READ_ONLY,
            "mutation proposal": cls.MUTATION_PROPOSAL,
            "mutation": cls.MUTATION_PROPOSAL,
        }
        if raw not in aliases:
            raise ValueError(f"Unknown expected_behavior: {value!r}")
        return aliases[raw]


class FailureCategory(str, Enum):
    WRONG_TOOL = "wrong_tool"
    WRONG_ARGUMENTS = "wrong_arguments"
    HALLUCINATION = "hallucination"
    INCOMPLETE_ANSWER = "incomplete_answer"
    WRONG_MAPPING = "wrong_mapping"
    INCORRECT_MUTATION = "incorrect_mutation"
    MISSING_CLARIFICATION = "missing_clarification"
    SAFETY_FAILURE = "safety_failure"
    UI_FAILURE = "UI_failure"
    UNEXPECTED_AUTO_APPLY = "unexpected_auto_apply"
    FACT_MISMATCH = "fact_mismatch"
    WRONG_BEHAVIOR = "wrong_behavior"
    CHANGESET_MISMATCH = "changeset_mismatch"


class BenchmarkLevel(str, Enum):
    LEVEL1 = "level1"
    LEVEL2 = "level2"
    LEVEL3 = "level3"


VALID_LEVELS = {item.value for item in BenchmarkLevel}


@dataclass(slots=True)
class BenchmarkCase:
    """One explicitly specified Copilot evaluation case."""

    id: str
    category: str
    prompt: str
    expected_behavior: str
    expected_tools: list[str] = field(default_factory=list)
    expected_tool_arguments: list[dict[str, Any]] | dict[str, Any] | None = None
    expected_answer: dict[str, Any] | str | None = None
    expected_subjects: list[str] | None = None
    expected_sessions: list[str] | None = None
    expected_acquisitions: list[str] | None = None
    expected_changes: dict[str, Any] | None = None
    expected_change_set: dict[str, Any] | None = None
    expected_auto_apply: bool = False
    expected_safety_behavior: str | None = None
    expected_answer_contains: list[str] | None = None
    expected_stopped_reason: str | None = None
    expected_session_datatypes: dict[str, list[str]] | None = None
    expected_issue_codes: list[str] | None = None
    expected_final_plan: dict[str, Any] | None = None
    levels: list[str] = field(default_factory=lambda: ["level1", "level2"])
    level1_tool: str | None = None
    level1_arguments: dict[str, Any] | None = None
    level1_check: str = "execute"
    scripted_llm_responses: list[dict[str, Any]] | None = None
    apply_changeset: bool = False
    gui_action: str = "none"
    notes: str = ""

    def has_level(self, level: str) -> bool:
        return level in self.levels

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BenchmarkCase:
        if not isinstance(payload, dict):
            raise ValueError("Benchmark case must be a JSON object")
        case_id = str(payload.get("id") or "").strip()
        if not case_id:
            raise ValueError("Benchmark case is missing id")
        category = str(payload.get("category") or "").strip()
        if not category:
            raise ValueError(f"{case_id}: category is required")
        prompt = str(payload.get("prompt") or "")
        if not str(payload.get("prompt") or "").strip() and payload.get("level1_check") == "execute":
            # Safety / tool-absence cases may still have a prompt
            pass
        behavior = str(payload.get("expected_behavior") or "").strip()
        if not behavior:
            raise ValueError(f"{case_id}: expected_behavior is required")
        ExpectedBehavior.parse(behavior)

        levels_raw = payload.get("levels") or ["level1", "level2"]
        if isinstance(levels_raw, str):
            levels = [levels_raw]
        else:
            levels = [str(x) for x in levels_raw]
        unknown = [lv for lv in levels if lv not in VALID_LEVELS]
        if unknown:
            raise ValueError(f"{case_id}: unknown levels {unknown}")

        tools = payload.get("expected_tools") or []
        if isinstance(tools, str):
            tools = [tools]
        if not isinstance(tools, list):
            raise ValueError(f"{case_id}: expected_tools must be a list")

        args = payload.get("expected_tool_arguments")
        if isinstance(args, dict):
            pass
        elif args is None:
            args = None
        elif isinstance(args, list):
            if not all(isinstance(item, dict) for item in args):
                raise ValueError(f"{case_id}: expected_tool_arguments list must contain objects")
        else:
            raise ValueError(f"{case_id}: expected_tool_arguments must be an object or list")

        check = str(payload.get("level1_check") or "execute").strip() or "execute"
        if check not in {"execute", "tool_not_registered", "skip"}:
            raise ValueError(f"{case_id}: unknown level1_check {check!r}")

        gui_action = str(payload.get("gui_action") or "none").strip() or "none"
        if gui_action not in {"none", "apply", "reject"}:
            raise ValueError(f"{case_id}: unknown gui_action {gui_action!r}")

        return cls(
            id=case_id,
            category=category,
            prompt=prompt,
            expected_behavior=behavior,
            expected_tools=[str(t) for t in tools],
            expected_tool_arguments=args,
            expected_answer=payload.get("expected_answer"),
            expected_subjects=_str_list(payload.get("expected_subjects")),
            expected_sessions=_str_list(payload.get("expected_sessions")),
            expected_acquisitions=_str_list(payload.get("expected_acquisitions")),
            expected_changes=payload.get("expected_changes"),
            expected_change_set=payload.get("expected_change_set"),
            expected_auto_apply=bool(payload.get("expected_auto_apply", False)),
            expected_safety_behavior=(
                None
                if payload.get("expected_safety_behavior") is None
                else str(payload.get("expected_safety_behavior"))
            ),
            expected_answer_contains=_str_list(payload.get("expected_answer_contains")),
            expected_stopped_reason=(
                None
                if payload.get("expected_stopped_reason") is None
                else str(payload.get("expected_stopped_reason"))
            ),
            expected_session_datatypes=_session_datatypes(payload.get("expected_session_datatypes")),
            expected_issue_codes=_str_list(payload.get("expected_issue_codes")),
            expected_final_plan=payload.get("expected_final_plan"),
            levels=levels,
            level1_tool=None if payload.get("level1_tool") is None else str(payload.get("level1_tool")),
            level1_arguments=(
                dict(payload.get("level1_arguments") or {})
                if payload.get("level1_arguments") is not None
                else None
            ),
            level1_check=check,
            scripted_llm_responses=_dict_list(payload.get("scripted_llm_responses")),
            apply_changeset=bool(payload.get("apply_changeset", False)),
            gui_action=gui_action,
            notes=str(payload.get("notes") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "prompt": self.prompt,
            "expected_behavior": self.expected_behavior,
            "expected_tools": list(self.expected_tools),
            "expected_tool_arguments": self.expected_tool_arguments,
            "expected_answer": self.expected_answer,
            "expected_subjects": self.expected_subjects,
            "expected_sessions": self.expected_sessions,
            "expected_acquisitions": self.expected_acquisitions,
            "expected_changes": self.expected_changes,
            "expected_change_set": self.expected_change_set,
            "expected_auto_apply": self.expected_auto_apply,
            "expected_safety_behavior": self.expected_safety_behavior,
            "expected_answer_contains": self.expected_answer_contains,
            "expected_stopped_reason": self.expected_stopped_reason,
            "expected_session_datatypes": self.expected_session_datatypes,
            "expected_issue_codes": self.expected_issue_codes,
            "expected_final_plan": self.expected_final_plan,
            "levels": list(self.levels),
            "level1_tool": self.level1_tool,
            "level1_arguments": self.level1_arguments,
            "level1_check": self.level1_check,
            "scripted_llm_responses": self.scripted_llm_responses,
            "apply_changeset": self.apply_changeset,
            "gui_action": self.gui_action,
            "notes": self.notes,
        }


def _str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise ValueError("expected a list of strings")


def _dict_list(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("scripted_llm_responses must be a list")
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("scripted_llm_responses items must be objects")
        out.append(dict(item))
    return out


def _session_datatypes(value: Any) -> dict[str, list[str]] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("expected_session_datatypes must be an object")
    return {str(k): [str(x) for x in (v or [])] for k, v in value.items()}


__all__ = [
    "BenchmarkCase",
    "BenchmarkLevel",
    "CaseCategory",
    "ExpectedBehavior",
    "FailureCategory",
]
