"""Tests for V0.3B Structured Gap Reasoning (backend/gap_reasoning.py).

Two layers are tested deliberately separately:

- Unit tests against ``_parse_and_validate_proposal`` / ``resolve_requirements``
  / classification, which never touch a model at all.
- Integration tests against ``analyze_goal`` using a scripted fake router,
  proving the full goal -> proposal -> deterministic resolution -> GapReport
  pipeline, and that every call is audited via the existing Run spine.

All registries used here are small, isolated ``ToolRegistry`` instances
(never the real production registry) so "installed" vs "missing" can be
proven directly rather than assumed.
"""

import json

import pytest

from backend.db import DATABASE_PATH
from backend.gap_reasoning import (
    CLASSIFICATION_ALREADY_POSSIBLE,
    CLASSIFICATION_CAPABILITY_GAP,
    CLASSIFICATION_COMPOSABLE,
    CLASSIFICATION_EXTERNALLY_BLOCKED,
    GapAnalysisError,
    _build_report,
    _parse_and_validate_proposal,
    analyze_goal,
    resolve_requirements,
)
from backend.memory import init_db
from backend.model_router import ModelProviderError, ModelResponse
from backend.runs import RUN_TYPE_MODEL, list_runs
from backend.tool_executor import execute_tool
from backend.tool_registry import ToolRegistry
from backend.tool_types import ToolDefinition, ToolExecutionContext, ToolNotFoundError


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _tool(name: str, *, capabilities: tuple[str, ...] = ()) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1",
        description="A test tool.",
        input_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        risk="read_only",
        data_exposure="local",
        executor=lambda arguments, context: {"ok": True},
        capabilities=capabilities,
        side_effects="None -- read-only.",
        idempotent=True,
        limitations="Test tool; no real limitation.",
    )


def _registry(*definitions: ToolDefinition) -> ToolRegistry:
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(definition)
    return registry


class FakeRouter:
    """A router double whose generate_standalone() returns fixed text."""

    def __init__(self, text: str = "", *, error: Exception = None):
        self.text = text
        self.error = error
        self.calls: list[tuple[list, str]] = []

    def generate_standalone(self, messages, instructions):
        self.calls.append((messages, instructions))
        if self.error is not None:
            raise self.error
        return ModelResponse(text=self.text, provider="fake", model="fake-model")


def _proposal(*requirements: dict) -> str:
    return json.dumps({"requirements": list(requirements)})


def _req(capability: str, reason: str = "because", externally_blocked: bool = False) -> dict:
    return {"capability": capability, "reason": reason, "externally_blocked": externally_blocked}


# --- 1. one installed capability -> already_possible ------------------------


def test_single_installed_capability_is_already_possible(clean_db):
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    router = FakeRouter(_proposal(_req("tasks.manage")))

    report = analyze_goal("Show me my tasks", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_ALREADY_POSSIBLE
    assert report.available_capabilities == ("tasks.manage",)
    assert report.missing_capabilities == ()
    assert report.composable_capabilities == ()


# --- 2. several installed capabilities -> composable -------------------------


def test_multiple_installed_capabilities_are_composable(clean_db):
    registry = _registry(
        _tool("tasks.list", capabilities=("tasks.manage",)),
        _tool("memory.search", capabilities=("memory.recall",)),
    )
    router = FakeRouter(_proposal(_req("tasks.manage"), _req("memory.recall")))

    report = analyze_goal("Find my notes and check my tasks", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_COMPOSABLE
    assert report.composable_capabilities == ("memory.recall", "tasks.manage")
    assert report.available_capabilities == ("memory.recall", "tasks.manage")
    assert "Achievable by combining" in report.notes


# --- 3. mixed installed + missing -> capability_gap --------------------------


def test_mixed_installed_and_missing_is_capability_gap(clean_db):
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    router = FakeRouter(_proposal(_req("tasks.manage"), _req("cloud.archive_dropbox")))

    report = analyze_goal("Track tasks and archive files to Dropbox", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_CAPABILITY_GAP
    assert report.available_capabilities == ("tasks.manage",)
    assert report.missing_capabilities == ("cloud.archive_dropbox",)
    assert report.composable_capabilities == ()


# --- 4. only missing requirements -> capability_gap ---------------------------


def test_only_missing_requirements_is_capability_gap(clean_db):
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    router = FakeRouter(_proposal(_req("filesystem.inspect"), _req("cloud.archive_dropbox")))

    report = analyze_goal("Organize my computer", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_CAPABILITY_GAP
    assert report.available_capabilities == ()
    assert set(report.missing_capabilities) == {"filesystem.inspect", "cloud.archive_dropbox"}


# --- 5. externally_blocked classification -------------------------------------


def test_externally_blocked_requirement_drives_overall_classification(clean_db):
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    router = FakeRouter(
        _proposal(
            _req("tasks.manage"),
            _req("other.private_account_access", "read someone else's private messages", externally_blocked=True),
        )
    )

    report = analyze_goal("Read my coworker's private messages", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_EXTERNALLY_BLOCKED
    assert report.externally_blocked_capabilities == ("other.private_account_access",)
    assert "tasks.manage" in report.available_capabilities


def test_missing_capability_alone_is_not_externally_blocked(clean_db):
    """A capability being merely missing must never itself produce
    externally_blocked -- only an explicit model flag does."""
    registry = ToolRegistry()
    router = FakeRouter(_proposal(_req("cloud.archive_dropbox")))

    report = analyze_goal("Archive my files to Dropbox", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_CAPABILITY_GAP
    assert report.externally_blocked_capabilities == ()


# --- 6/7. hallucinated/stale capability names never become installed ---------


def test_model_proposed_nonexistent_capability_remains_missing(clean_db):
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    router = FakeRouter(_proposal(_req("instagram.manage_messages")))

    report = analyze_goal("Manage my Instagram DMs", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_CAPABILITY_GAP
    assert report.missing_capabilities == ("instagram.manage_messages",)
    assert report.requirements[0].installed is False
    assert report.requirements[0].tools == ()


def test_near_miss_capability_id_does_not_fuzzy_match_the_real_one(clean_db):
    """A typo/near-miss ("tasks.managed") must not deterministically match
    the real "tasks.manage" -- no fuzzy matching exists in the resolver."""
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    router = FakeRouter(_proposal(_req("tasks.managed")))

    report = analyze_goal("Track my tasks", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_CAPABILITY_GAP
    assert report.missing_capabilities == ("tasks.managed",)


def test_capability_id_is_case_and_whitespace_normalized_but_not_fuzzy_matched(clean_db):
    """Deterministic normalization (case/whitespace) is allowed; semantic
    fuzzy matching is not."""
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    router = FakeRouter(_proposal(_req("  Tasks.Manage  ")))

    report = analyze_goal("Track my tasks", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_ALREADY_POSSIBLE
    assert report.available_capabilities == ("tasks.manage",)


# --- 8. empty registry produces an honest gap report --------------------------


def test_empty_registry_produces_an_honest_capability_gap_report(clean_db):
    registry = ToolRegistry()
    router = FakeRouter(_proposal(_req("tasks.manage")))

    report = analyze_goal("Track my tasks", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_CAPABILITY_GAP
    assert report.available_capabilities == ()
    assert report.missing_capabilities == ("tasks.manage",)


def test_empty_registry_and_no_requirements_is_already_possible(clean_db):
    """A goal needing nothing beyond ordinary conversation is honestly
    already_possible even against an empty registry -- it never claims a
    capability gap that doesn't exist."""
    registry = ToolRegistry()
    router = FakeRouter(_proposal())

    report = analyze_goal("Tell me a joke", router=router, registry=registry)

    assert report.classification == CLASSIFICATION_ALREADY_POSSIBLE
    assert report.requirements == ()
    assert "No new capability is required" in report.notes


# --- 9. two isolated registries never leak capability state ------------------


def test_two_independent_registries_do_not_leak_installed_state(clean_db):
    registry_with = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    registry_without = ToolRegistry()

    report_with = analyze_goal(
        "Track tasks", router=FakeRouter(_proposal(_req("tasks.manage"))), registry=registry_with
    )
    report_without = analyze_goal(
        "Track tasks", router=FakeRouter(_proposal(_req("tasks.manage"))), registry=registry_without
    )

    assert report_with.classification == CLASSIFICATION_ALREADY_POSSIBLE
    assert report_without.classification == CLASSIFICATION_CAPABILITY_GAP


# --- 10. Gap Reports cannot execute tools -------------------------------------


def test_a_proposed_capability_can_never_be_executed(clean_db):
    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    router = FakeRouter(_proposal(_req("tasks.manage")))

    report = analyze_goal("Track my tasks", router=router, registry=registry)

    # The report names a capability, never a callable -- attempting to
    # execute it by name (the only thing a capability id could be used
    # for) fails closed exactly like any other unregistered/non-tool name.
    with pytest.raises(ToolNotFoundError):
        execute_tool(
            tool_name=report.available_capabilities[0],
            arguments={},
            context=ToolExecutionContext(),
            registry=registry,
        )


def test_gap_report_and_resolution_objects_carry_no_executor():
    resolutions = resolve_requirements([{"capability": "tasks.manage", "reason": "x", "externally_blocked": False}])
    report = _build_report("goal", resolutions)

    # Round-trips through JSON with no special handling -- proves nothing
    # inside is a callable or other non-plain-data object.
    json.dumps(report.to_dict())
    assert not hasattr(report, "execute")
    assert not hasattr(resolutions[0], "execute")


# --- 11. Gap Reports cannot create/register capabilities ---------------------


def test_analyzing_a_goal_never_mutates_the_registry_or_catalog(clean_db):
    from backend.capability_catalog import build_capability_index

    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    before = build_capability_index(registry)

    router = FakeRouter(
        _proposal(
            _req("tasks.manage"),
            _req("instagram.manage_messages"),
            _req("cloud.archive_dropbox"),
        )
    )
    analyze_goal("Do a lot of things", router=router, registry=registry)

    after = build_capability_index(registry)
    assert before == after
    assert len(registry) == 1  # still only the one real registered tool


# --- 12. malformed model output fails closed ----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        "",
        "   ",
        '{"requirements": "not-a-list"}',
        '{"requirements": [], "extra_key": true}',
        '{"totally_wrong_key": []}',
        "[]",
        '{"requirements": [{"capability": 123}]}',
        '{"requirements": [{"capability": "tasks.manage", "unexpected_key": true}]}',
        '{"requirements": [{"reason": "no capability field"}]}',
        '{"requirements": [{"capability": "not a valid capability id with spaces"}]}',
        '{"requirements": [{"capability": "NoDotAtAll"}]}',
        '{"requirements": [{"capability": ""}]}',
        '{"requirements": [{"capability": "tasks.manage", "externally_blocked": "yes"}]}',
        '{"requirements": [' + ", ".join(f'{{"capability": "cap{i}.thing"}}' for i in range(11)) + "]}",
    ],
)
def test_malformed_model_output_fails_closed(clean_db, text):
    router = FakeRouter(text)
    with pytest.raises(GapAnalysisError):
        analyze_goal("Do something", router=router, registry=ToolRegistry())


def test_valid_json_wrapped_in_a_markdown_fence_still_parses():
    fenced = "```json\n" + _proposal(_req("tasks.manage")) + "\n```"
    parsed = _parse_and_validate_proposal(fenced)
    assert parsed == [{"capability": "tasks.manage", "reason": "because", "externally_blocked": False}]


def test_model_provider_failure_fails_closed_and_is_audited(clean_db):
    router = FakeRouter(error=ModelProviderError("provider unreachable"))

    with pytest.raises(GapAnalysisError):
        analyze_goal("Do something", router=router, registry=ToolRegistry())

    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"


def test_empty_goal_fails_closed_without_ever_calling_the_model(clean_db):
    router = FakeRouter("irrelevant")

    with pytest.raises(GapAnalysisError, match="empty"):
        analyze_goal("   ", router=router, registry=ToolRegistry())

    assert router.calls == []  # never reached the model
    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"  # still audited, per module docstring


# --- Adversarial: model tries to claim a fake capability is installed --------


@pytest.mark.parametrize(
    "sneaky_item",
    [
        {"capability": "fake.thing", "installed": True},
        {"capability": "fake.thing", "reason": "x", "verified": True},
        {"capability": "fake.thing", "reason": "x", "tools": ["tasks.create"]},
        {"capability": "fake.thing", "status": "installed"},
    ],
)
def test_model_cannot_smuggle_an_installed_claim_into_a_requirement(clean_db, sneaky_item):
    """The proposal schema has no field the model could use to assert
    installation -- any attempt to add one is an unknown key and fails the
    whole payload closed, rather than being silently accepted or ignored."""
    text = json.dumps({"requirements": [sneaky_item]})
    router = FakeRouter(text)

    with pytest.raises(GapAnalysisError):
        analyze_goal("Do the fake thing", router=router, registry=ToolRegistry())


def test_model_asserting_installed_via_reason_text_does_not_verify_it(clean_db):
    """Even if the model's free-text reason claims a capability is
    installed, the deterministic resolver only ever trusts the registry."""
    registry = ToolRegistry()
    router = FakeRouter(
        _proposal(_req("fake.thing", reason="this is already installed and fully working"))
    )

    report = analyze_goal("Do the fake thing", router=router, registry=registry)

    assert report.requirements[0].installed is False
    assert report.classification == CLASSIFICATION_CAPABILITY_GAP


# --- 13/14. V0.2A/V0.3A behavior is unaffected --------------------------------
#
# These are lightweight, targeted checks; the authoritative proof is the
# full existing test suite (test_tool_executor.py, test_tool_conversation.py,
# test_capability_catalog.py, etc.) passing unmodified -- see the report.


def test_gap_reasoning_module_never_imports_tool_conversation_or_operations():
    """Structural guard: gap reasoning must stay reasoning-only and never
    gain a dependency on the approval/execution modules, which would be a
    sign it started doing more than analysis."""
    import backend.gap_reasoning as module

    source_modules = {getattr(value, "__module__", None) for value in vars(module).values()}
    assert "backend.tool_operations" not in source_modules
    assert "backend.tool_executor" not in source_modules
    assert "backend.tool_conversation" not in source_modules


def test_capability_catalog_still_only_reflects_registered_tools_after_gap_analysis(clean_db):
    from backend.capability_catalog import describe_installed_abilities

    registry = _registry(_tool("tasks.list", capabilities=("tasks.manage",)))
    router = FakeRouter(_proposal(_req("instagram.manage_messages")))
    analyze_goal("Manage Instagram", router=router, registry=registry)

    description = describe_installed_abilities(registry)
    tool_names = {entry["name"] for entry in description["tools"]}
    assert tool_names == {"tasks.list"}
    assert "instagram.manage_messages" not in {c["id"] for c in description["capabilities"]}


# --- 15. audit logging stores no prompts/responses/secrets/arguments ---------


def test_gap_analysis_run_stores_no_goal_or_model_text(clean_db):
    secret_goal = "PRIVATE-GOAL-TEXT-should-never-be-stored"
    router = FakeRouter(_proposal(_req("tasks.manage")))

    analyze_goal(secret_goal, router=router, registry=_registry(_tool("tasks.list", capabilities=("tasks.manage",))))

    runs = list_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run["run_type"] == RUN_TYPE_MODEL
    assert run["status"] == "succeeded"
    # The Run row's columns are a fixed, closed set (backend/runs.py) with
    # no field capable of holding prompt/response/goal text -- this proves
    # the secret text is not present anywhere in the persisted row.
    for value in run.values():
        assert secret_goal not in str(value)


def test_failed_gap_analysis_run_stores_only_a_sanitized_error_class(clean_db):
    router = FakeRouter("PRIVATE-MALFORMED-OUTPUT-not-json")

    with pytest.raises(GapAnalysisError):
        analyze_goal("goal text", router=router, registry=ToolRegistry())

    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["error_class"] == "GapAnalysisError"
    for value in runs[0].values():
        assert "PRIVATE-MALFORMED-OUTPUT" not in str(value)


# --- Resolver unit tests (no model involved) ----------------------------------


def test_resolve_requirements_marks_backing_tools_for_an_installed_capability():
    registry = _registry(
        _tool("tasks.list", capabilities=("tasks.manage",)),
        _tool("tasks.create", capabilities=("tasks.manage",)),
    )
    resolutions = resolve_requirements(
        [{"capability": "tasks.manage", "reason": "x", "externally_blocked": False}],
        registry=registry,
    )
    assert resolutions[0].installed is True
    assert resolutions[0].tools == ("tasks.create", "tasks.list")


def test_resolve_requirements_against_explicitly_empty_registry_stays_empty():
    """Regression-style check for the V0.3A registry-truthiness bug class:
    an explicitly empty ToolRegistry must never be treated as 'not given'."""
    resolutions = resolve_requirements(
        [{"capability": "tasks.manage", "reason": "x", "externally_blocked": False}],
        registry=ToolRegistry(),
    )
    assert resolutions[0].installed is False
