"""Tests for the dependency-free JSON-Schema-lite tool argument validator."""

import pytest

from backend.tool_types import ToolValidationError
from backend.tool_validation import validate_arguments


SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 20},
        "limit": {"type": "integer", "minimum": 1, "maximum": 5},
        "status": {"type": "string", "enum": ["open", "closed"]},
        "active": {"type": "boolean"},
    },
    "required": ["query"],
    "additionalProperties": False,
}


def test_valid_arguments_pass_through_normalized():
    result = validate_arguments(SCHEMA, {"query": "  hello  ", "limit": 3})
    assert result == {"query": "hello", "limit": 3}


def test_missing_required_argument_is_rejected():
    with pytest.raises(ToolValidationError, match="'query' is required"):
        validate_arguments(SCHEMA, {})


def test_unknown_argument_is_rejected_when_additional_properties_disallowed():
    with pytest.raises(ToolValidationError, match="Unsupported argument"):
        validate_arguments(SCHEMA, {"query": "hi", "unexpected": "value"})


def test_additional_properties_allowed_when_schema_opts_in():
    permissive_schema = {**SCHEMA, "additionalProperties": True}
    result = validate_arguments(permissive_schema, {"query": "hi", "extra": "ok"})
    assert result["query"] == "hi"


def test_string_length_bounds_enforced():
    with pytest.raises(ToolValidationError, match="at least 1 character"):
        validate_arguments(SCHEMA, {"query": ""})
    with pytest.raises(ToolValidationError, match="20 character"):
        validate_arguments(SCHEMA, {"query": "x" * 21})


def test_integer_bounds_enforced():
    with pytest.raises(ToolValidationError, match="at least 1"):
        validate_arguments(SCHEMA, {"query": "hi", "limit": 0})
    with pytest.raises(ToolValidationError, match="at most 5"):
        validate_arguments(SCHEMA, {"query": "hi", "limit": 6})


def test_wrong_type_is_rejected():
    with pytest.raises(ToolValidationError, match="must be an integer"):
        validate_arguments(SCHEMA, {"query": "hi", "limit": "3"})
    with pytest.raises(ToolValidationError, match="must be a string"):
        validate_arguments(SCHEMA, {"query": 5})
    with pytest.raises(ToolValidationError, match="must be a boolean"):
        validate_arguments(SCHEMA, {"query": "hi", "active": "yes"})


def test_boolean_true_is_not_mistaken_for_an_integer():
    # bool is a subclass of int in Python; the validator must not accept True/False
    # for an "integer" field.
    with pytest.raises(ToolValidationError, match="must be an integer"):
        validate_arguments(SCHEMA, {"query": "hi", "limit": True})


def test_enum_is_enforced():
    with pytest.raises(ToolValidationError, match="must be one of"):
        validate_arguments(SCHEMA, {"query": "hi", "status": "unknown"})
    assert validate_arguments(SCHEMA, {"query": "hi", "status": "open"})["status"] == "open"


def test_optional_fields_are_omitted_rather_than_defaulted_to_none():
    result = validate_arguments(SCHEMA, {"query": "hi"})
    assert "limit" not in result
    assert "status" not in result


def test_explicit_none_is_treated_as_not_provided():
    result = validate_arguments(SCHEMA, {"query": "hi", "limit": None})
    assert "limit" not in result


def test_non_object_arguments_are_rejected():
    with pytest.raises(ToolValidationError, match="must be an object"):
        validate_arguments(SCHEMA, ["not", "a", "dict"])  # type: ignore[arg-type]


def test_unsupported_schema_type_fails_closed():
    with pytest.raises(ToolValidationError, match="Unsupported schema type"):
        validate_arguments(
            {
                "type": "object",
                "properties": {"nested": {"type": "object"}},
                "required": ["nested"],
                "additionalProperties": False,
            },
            {"nested": {"a": 1}},
        )
