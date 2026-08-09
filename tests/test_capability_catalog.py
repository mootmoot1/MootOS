"""Tests for the V0.3A generated capability catalog/manifest
(backend/capability_catalog.py).

These tests deliberately build small, isolated ``ToolRegistry`` instances
rather than relying only on the production default registry, so that
"a tool appears/disappears from the generated description" can be proven
directly instead of assumed. See docs/CAPABILITY_ARCHITECTURE.md and
ADR-028/ADR-029.
"""

import json

import pytest

from backend.capability_catalog import (
    build_capability_index,
    build_tool_catalog,
    describe_installed_abilities,
    render_capability_manifest,
)
from backend.db import DATABASE_PATH
from backend.memory import init_db
from backend.model_router import OpenAIProvider
from backend.tool_executor import execute_tool
from backend.tool_registry import ToolRegistry, get_tool_registry
from backend.tool_types import (
    RISK_HIGH_RISK,
    RISK_INTERNAL_WRITE,
    RISK_READ_ONLY,
    ToolDefinition,
    ToolExecutionContext,
    ToolNotFoundError,
)


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _tool(
    name: str,
    *,
    risk: str = RISK_READ_ONLY,
    capabilities: tuple[str, ...] = (),
    description: str = "A test tool.",
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1",
        description=description,
        input_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        risk=risk,
        data_exposure="local",
        executor=lambda arguments, context: {"ok": True},
        capabilities=capabilities,
        side_effects="None -- read-only." if risk == RISK_READ_ONLY else "Test side effect.",
        idempotent=True if risk == RISK_READ_ONLY else False,
        limitations="Test tool; no real limitation.",
    )


def _registry(*definitions: ToolDefinition) -> ToolRegistry:
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(definition)
    return registry


# --- 1. Generated descriptions are derived from registered tools -----------


def test_manifest_only_names_tools_actually_registered():
    registry = _registry(_tool("alpha.read"), _tool("beta.write", risk=RISK_INTERNAL_WRITE))

    manifest = render_capability_manifest(registry)

    assert "alpha.read" in manifest
    assert "beta.write" in manifest
    assert "gamma.ghost" not in manifest


def test_catalog_only_contains_registered_tools():
    registry = _registry(_tool("alpha.read"))

    catalog = build_tool_catalog(registry)

    assert [entry["name"] for entry in catalog] == ["alpha.read"]


# --- 2. Adding a tool makes it appear automatically -------------------------


def test_registering_a_new_tool_makes_it_appear_in_manifest_and_catalog():
    registry = _registry(_tool("alpha.read"))

    before_manifest = render_capability_manifest(registry)
    before_catalog = build_tool_catalog(registry)
    assert "beta.write" not in before_manifest
    assert "beta.write" not in [entry["name"] for entry in before_catalog]

    registry.register(_tool("beta.write", risk=RISK_INTERNAL_WRITE))

    after_manifest = render_capability_manifest(registry)
    after_catalog = build_tool_catalog(registry)
    assert "beta.write is registered as a write-capable tool" in after_manifest
    assert "beta.write" in [entry["name"] for entry in after_catalog]


def test_registering_a_new_tool_with_a_capability_extends_the_capability_index():
    registry = _registry(_tool("alpha.read", capabilities=("alpha.view",)))
    assert [entry["id"] for entry in build_capability_index(registry)] == ["alpha.view"]

    registry.register(_tool("alpha.write", risk=RISK_INTERNAL_WRITE, capabilities=("alpha.view",)))

    index = build_capability_index(registry)
    assert len(index) == 1
    assert index[0]["id"] == "alpha.view"
    assert index[0]["tools"] == ["alpha.read", "alpha.write"]


# --- 3. A tool that isn't registered cannot remain advertised --------------


def test_a_never_registered_tool_is_absent_from_every_generated_view():
    registry = _registry(_tool("alpha.read"))

    manifest = render_capability_manifest(registry)
    catalog = build_tool_catalog(registry)
    description = describe_installed_abilities(registry)

    for surface in (manifest, json.dumps(catalog), json.dumps(description)):
        assert "ghost.tool" not in surface


def test_two_independently_built_registries_never_leak_into_each_other():
    """Proves there is no hidden module-level cache: rendering the manifest
    for a registry that has a tool, then rendering it again for a
    *different* registry that does not, must never show the first
    registry's tool -- otherwise a genuinely removed tool (one simply never
    registered again) could remain advertised by stale generated text."""
    registry_with = _registry(_tool("only.here"))
    registry_without = _registry(_tool("something.else"))

    manifest_with = render_capability_manifest(registry_with)
    manifest_without = render_capability_manifest(registry_without)

    assert "only.here" in manifest_with
    assert "only.here" not in manifest_without


def test_empty_registry_produces_a_valid_manifest_with_no_tools_claimed():
    registry = ToolRegistry()

    manifest = render_capability_manifest(registry)

    assert "No internal tools are currently registered." in manifest
    assert build_tool_catalog(registry) == []
    assert build_capability_index(registry) == []


# --- 4. Capability/group metadata cannot execute anything ------------------


def test_capability_index_entries_are_plain_non_executable_data():
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))

    index = build_capability_index(registry)

    assert index == [{"id": "tasks.manage", "label": "View and create MootOS Tasks", "tools": ["tasks.list"]}]
    # Round-trips through JSON with no special handling -- proves there is
    # no callable, executor reference, or other non-data object hiding
    # inside a capability entry.
    json.dumps(index)


def test_a_capability_id_can_never_be_executed(clean_db):
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))

    with pytest.raises(ToolNotFoundError):
        execute_tool(
            tool_name="tasks.manage",
            arguments={},
            context=ToolExecutionContext(),
            registry=registry,
        )


# --- 5. Unknown tools still fail closed -------------------------------------


def test_unregistered_tool_name_is_not_looked_up_by_the_catalog_layer():
    registry = _registry(_tool("alpha.read"))
    assert "beta.write" not in [entry["name"] for entry in build_tool_catalog(registry)]
    with pytest.raises(ToolNotFoundError):
        registry.get("beta.write")


# --- 6. Risk classifications remain registry-controlled ---------------------


def test_catalog_entry_risk_always_matches_the_registered_definition():
    registry = _registry(
        _tool("alpha.read", risk=RISK_READ_ONLY),
        _tool("beta.write", risk=RISK_INTERNAL_WRITE),
    )
    by_name = {entry["name"]: entry for entry in build_tool_catalog(registry)}
    assert by_name["alpha.read"]["risk"] == RISK_READ_ONLY
    assert by_name["beta.write"]["risk"] == RISK_INTERNAL_WRITE


def test_high_risk_tools_are_never_described_as_available_or_callable():
    """Adversarial/hallucination-prevention: even if a high-risk tool is
    registered, the generated manifest must never describe it as something
    the model may call -- matching backend.tool_executor's unconditional
    block on RISK_HIGH_RISK (docs/TOOL_SYSTEM.md Sec5)."""
    registry = _registry(
        _tool("alpha.read", risk=RISK_READ_ONLY),
        _tool("danger.launch", risk=RISK_HIGH_RISK),
    )

    manifest = render_capability_manifest(registry)

    assert "alpha.read" in manifest
    assert "danger.launch" not in manifest


def test_high_risk_only_registry_claims_no_available_tools():
    registry = _registry(_tool("danger.launch", risk=RISK_HIGH_RISK))

    manifest = render_capability_manifest(registry)

    assert "No internal tools are currently registered." in manifest
    assert "danger.launch" not in manifest


# --- 7. tasks.create (and any internal_write tool) still requires approval -


def test_new_metadata_fields_never_bypass_write_tool_approval_enforcement(clean_db):
    """A write tool carrying rich V0.3A metadata (capabilities, idempotent,
    limitations) must still be blocked without approval -- proves the new
    descriptive fields are inert with respect to enforcement, which lives
    entirely in backend/tool_executor.py and never reads them."""
    from backend.tool_types import ToolPermissionError

    registry = _registry(
        _tool("things.create", risk=RISK_INTERNAL_WRITE, capabilities=("things.manage",))
    )

    with pytest.raises(ToolPermissionError):
        execute_tool(
            tool_name="things.create",
            arguments={},
            context=ToolExecutionContext(approved=False),
            registry=registry,
        )


def test_tasks_create_still_requires_frozen_approval_in_the_real_registry(clean_db):
    from backend.tool_types import ToolPermissionError

    with pytest.raises(ToolPermissionError):
        execute_tool(
            tool_name="tasks.create",
            arguments={"title": "Call Mike"},
            context=ToolExecutionContext(approved=False),
            registry=get_tool_registry(),
        )


# --- 8. Internal dotted names / provider encoding remain intact ------------


def test_enriched_catalog_entries_still_encode_cleanly_for_the_openai_provider():
    """The new V0.3A metadata keys on a catalog entry must never leak into
    what is sent to the provider -- _build_function_tools already
    whitelists name/description/input_schema (backend/model_router.py);
    this proves that still holds against an enriched entry."""
    registry = _registry(_tool("dotted.name", capabilities=("dotted.view",)))
    catalog = build_tool_catalog(registry)
    assert "capabilities" in catalog[0]  # enriched entry, not the old shape

    provider = OpenAIProvider()  # pure method under test needs no API key/network
    function_tools = provider._build_function_tools(catalog)

    assert len(function_tools) == 1
    assert set(function_tools[0]) == {"type", "name", "description", "parameters"}
    assert "." not in function_tools[0]["name"]
    assert provider._decode_tool_name(function_tools[0]["name"]) == "dotted.name"


# --- 9. No arguments, prompts, responses, secrets, or private data ---------


_DISALLOWED_KEYS = {"arguments", "prompt", "response", "secret", "api_key", "password", "token", "content"}


def _walk_keys(value, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            found.add(str(key).lower())
            _walk_keys(inner, found)
    elif isinstance(value, list):
        for inner in value:
            _walk_keys(inner, found)


def test_describe_installed_abilities_contains_no_disallowed_keys():
    description = describe_installed_abilities(get_tool_registry())

    found_keys: set[str] = set()
    _walk_keys(description, found_keys)

    assert found_keys & _DISALLOWED_KEYS == set()


def test_describe_installed_abilities_has_only_the_expected_top_level_shape():
    description = describe_installed_abilities(get_tool_registry())

    assert set(description) == {"tools", "capabilities"}
    for tool_entry in description["tools"]:
        assert set(tool_entry) == {
            "name",
            "version",
            "description",
            "input_schema",
            "risk",
            "capabilities",
            "side_effects",
            "idempotent",
            "limitations",
            "depends_on",
        }
    for capability_entry in description["capabilities"]:
        assert set(capability_entry) == {"id", "label", "tools"}


# --- Real default registry: the smoke test tying it all together -----------


def test_real_default_registry_produces_the_known_v02a_tools_and_capabilities():
    description = describe_installed_abilities(get_tool_registry())

    tool_names = {entry["name"] for entry in description["tools"]}
    assert tool_names == {"projects.list", "memory.search", "tasks.list", "tasks.create"}

    capability_ids = {entry["id"] for entry in description["capabilities"]}
    assert capability_ids == {"projects.view", "memory.recall", "tasks.manage"}

    by_id = {entry["id"]: entry for entry in description["capabilities"]}
    assert by_id["tasks.manage"]["tools"] == ["tasks.create", "tasks.list"]
