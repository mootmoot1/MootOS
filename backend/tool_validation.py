"""Small, dependency-free JSON-Schema-lite validator for Tool System inputs.

MootOS does not add a third-party JSON Schema library for this. Every tool
input schema in this codebase is a plain object with a handful of scalar
properties, so a small explicit validator is easier to review, cannot import
arbitrary code, and cannot silently pass through an unsupported schema
shape -- unsupported shapes fail closed instead of being accepted unchecked.

Supported subset:

- top-level ``type: "object"`` with ``properties``, ``required``, and
  ``additionalProperties`` (defaults to ``False`` -- unknown keys rejected)
- property ``type``: ``string``, ``integer``, ``boolean``
- string: ``minLength``, ``maxLength``, ``enum``
- integer: ``minimum``, ``maximum``

This intentionally does not support nested objects/arrays, ``oneOf``, or
other advanced JSON Schema features. Every current MootOS tool fits this
subset; extend it deliberately, not by broadening the fallback.
"""

from typing import Any, Mapping, Sequence

from backend.tool_types import ToolValidationError


def validate_arguments(
    schema: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and normalize ``arguments`` against a tool's input schema.

    Returns a new dict containing only recognized, validated properties
    (unset optional properties are omitted, never defaulted to ``None``).
    Raises ``ToolValidationError`` for any violation, including an unknown
    argument name when the schema does not explicitly allow extras.
    """
    if not isinstance(arguments, Mapping):
        raise ToolValidationError("Tool arguments must be an object")

    properties: Mapping[str, Any] = schema.get("properties", {}) or {}
    required: Sequence[str] = schema.get("required", ()) or ()
    additional_allowed = bool(schema.get("additionalProperties", False))

    unknown = set(arguments) - set(properties)
    if unknown and not additional_allowed:
        raise ToolValidationError(
            f"Unsupported argument(s): {', '.join(sorted(unknown))}"
        )

    validated: dict[str, Any] = {}
    for name, spec in properties.items():
        provided = name in arguments and arguments[name] is not None
        if not provided:
            if name in required:
                raise ToolValidationError(f"'{name}' is required")
            continue
        validated[name] = _validate_value(name, arguments[name], spec)
    return validated


def _validate_value(name: str, value: Any, spec: Mapping[str, Any]) -> Any:
    expected_type = spec.get("type")

    if expected_type == "string":
        if not isinstance(value, str):
            raise ToolValidationError(f"'{name}' must be a string")
        text = value.strip()
        min_length = spec.get("minLength")
        if min_length is not None and len(text) < min_length:
            raise ToolValidationError(
                f"'{name}' must be at least {min_length} character(s)"
            )
        max_length = spec.get("maxLength")
        if max_length is not None and len(text) > max_length:
            raise ToolValidationError(
                f"'{name}' must be {max_length} character(s) or fewer"
            )
        enum = spec.get("enum")
        if enum is not None and text not in enum:
            raise ToolValidationError(
                f"'{name}' must be one of: {', '.join(str(item) for item in enum)}"
            )
        return text

    if expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolValidationError(f"'{name}' must be an integer")
        minimum = spec.get("minimum")
        if minimum is not None and value < minimum:
            raise ToolValidationError(f"'{name}' must be at least {minimum}")
        maximum = spec.get("maximum")
        if maximum is not None and value > maximum:
            raise ToolValidationError(f"'{name}' must be at most {maximum}")
        return value

    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise ToolValidationError(f"'{name}' must be a boolean")
        return value

    # An unrecognized/unsupported schema type is a MootOS registration bug,
    # not something to pass through unchecked -- fail closed.
    raise ToolValidationError(f"Unsupported schema type for '{name}'")
