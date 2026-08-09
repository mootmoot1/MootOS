"""Tests for explicit, deterministic Tool System registration."""

import pytest

from backend.tool_registry import ToolRegistry, build_default_registry, get_tool_registry
from backend.tool_types import DuplicateToolError, ToolDefinition, ToolNotFoundError


def _fake_definition(name: str = "fake.tool") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1",
        description="A fake tool for tests.",
        input_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        risk="read_only",
        data_exposure="local",
        executor=lambda arguments, context: {"ok": True},
    )


def test_register_and_get_round_trips():
    registry = ToolRegistry()
    definition = _fake_definition()
    registry.register(definition)

    assert registry.get("fake.tool") is definition
    assert len(registry) == 1


def test_duplicate_registration_is_rejected():
    registry = ToolRegistry()
    registry.register(_fake_definition())

    with pytest.raises(DuplicateToolError):
        registry.register(_fake_definition())


def test_unknown_tool_lookup_fails_closed():
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError):
        registry.get("does.not.exist")


def test_catalog_is_deterministically_ordered_and_excludes_executor():
    registry = ToolRegistry()
    registry.register(_fake_definition("z.tool"))
    registry.register(_fake_definition("a.tool"))

    catalog = registry.catalog()

    assert [entry["name"] for entry in catalog] == ["a.tool", "z.tool"]
    for entry in catalog:
        assert "executor" not in entry
        assert set(entry) == {"name", "version", "description", "input_schema", "risk"}


def test_list_definitions_is_deterministically_ordered():
    registry = ToolRegistry()
    registry.register(_fake_definition("b.tool"))
    registry.register(_fake_definition("a.tool"))

    assert [d.name for d in registry.list_definitions()] == ["a.tool", "b.tool"]


def test_default_registry_registers_exactly_the_four_reference_tools():
    registry = build_default_registry()

    assert {d.name for d in registry.list_definitions()} == {
        "projects.list",
        "memory.search",
        "tasks.list",
        "tasks.create",
    }


def test_get_tool_registry_returns_a_stable_singleton():
    first = get_tool_registry()
    second = get_tool_registry()

    assert first is second
