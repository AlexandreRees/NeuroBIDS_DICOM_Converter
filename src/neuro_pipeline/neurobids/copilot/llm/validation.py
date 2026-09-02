"""Lightweight JSON-schema subset validation for LLM tool arguments."""

from __future__ import annotations

from typing import Any


class ToolArgumentValidationError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_tool_arguments(schema: dict[str, Any] | None, arguments: dict[str, Any]) -> None:
    """Validate ``arguments`` against a registered tool's input_schema.

    Supports a practical subset: object type, properties, required,
    additionalProperties, enum, type string/integer/number/boolean/array/object.
    """
    schema = schema or {"type": "object"}
    if not isinstance(arguments, dict):
        raise ToolArgumentValidationError("arguments must be an object")
    _validate_value(arguments, schema, path="$")


def _validate_value(value: Any, schema: dict[str, Any], *, path: str) -> None:
    expected = schema.get("type")
    if expected == "object" or (expected is None and "properties" in schema):
        if not isinstance(value, dict):
            raise ToolArgumentValidationError(f"{path}: expected object")
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                raise ToolArgumentValidationError(f"{path}: missing required property {key!r}")
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                _validate_value(item, props[key], path=f"{path}.{key}")
            elif additional is False:
                raise ToolArgumentValidationError(f"{path}: unexpected property {key!r}")
            elif isinstance(additional, dict):
                _validate_value(item, additional, path=f"{path}.{key}")
        return

    if expected == "array":
        if not isinstance(value, list):
            raise ToolArgumentValidationError(f"{path}: expected array")
        item_schema = schema.get("items") or {}
        for idx, item in enumerate(value):
            _validate_value(item, item_schema, path=f"{path}[{idx}]")
        return

    if expected == "string":
        if not isinstance(value, str):
            raise ToolArgumentValidationError(f"{path}: expected string")
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ToolArgumentValidationError(f"{path}: expected integer")
        if "minimum" in schema and value < int(schema["minimum"]):
            raise ToolArgumentValidationError(f"{path}: below minimum")
    elif expected == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ToolArgumentValidationError(f"{path}: expected number")
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise ToolArgumentValidationError(f"{path}: expected boolean")
    elif expected is not None:
        raise ToolArgumentValidationError(f"{path}: unsupported schema type {expected!r}")

    if "enum" in schema and value not in schema["enum"]:
        raise ToolArgumentValidationError(f"{path}: value not in enum")
