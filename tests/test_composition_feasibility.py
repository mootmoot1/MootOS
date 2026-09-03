"""Tests for V0.4D Slice 3 registry-bound composition feasibility."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.composition_feasibility import (
    BASELINE_TOOL_ORDER,
    STATUS_FEASIBLE,
    STATUS_NOT_FEASIBLE,
    CompositionFeasibilityError,
    bind_composition_feasibility,
)
from backend.composition_proposal import (
    LITERAL_APPROVED_CONTRACT,
    RISK_INTERNAL_WRITE,
    RISK_READ_ONLY,
    TRANSFORM_FIXED_TITLE,
    TRANSFORM_SELECT_PROJECT,
    CompositionStepProposal,
    DeclaredOutput,
    LiteralBinding,
    ResultBinding,
    propose_composition_mission,
)
from backend.tool_registry import ToolRegistry, build_default_registry
from backend.tool_types import RISK_HIGH_RISK


GOAL = (
    "Review current project activity and task status, consult relevant stored "
    "context, then prepare one appropriate follow-up task for human approval."
)


def _steps():
    def select(argument):
        return ResultBinding(
            argument,
            "project_overview",
            ("projects",),
            TRANSFORM_SELECT_PROJECT,
        )

    return (
        CompositionStepProposal(
            "project_overview",
            "projects.insight",
            "projects.overview",
            RISK_READ_ONLY,
            declared_outputs=(DeclaredOutput(("projects",), "array"),),
        ),
        CompositionStepProposal(
            "task_summary",
            "tasks.status_insight",
            "tasks.status_summary",
            RISK_READ_ONLY,
            bindings=(select("project"),),
            prerequisite_step_ids=("project_overview",),
            declared_outputs=(
                DeclaredOutput(("counts", "open"), "integer"),
                DeclaredOutput(("project",), "string"),
            ),
        ),
        CompositionStepProposal(
            "task_list", "tasks.manage", "tasks.list", RISK_READ_ONLY,
            bindings=(
                select("project"),
                LiteralBinding("status", LITERAL_APPROVED_CONTRACT, "open"),
                LiteralBinding("limit", LITERAL_APPROVED_CONTRACT, 100),
            ),
            prerequisite_step_ids=("project_overview", "task_summary"),
            declared_outputs=(
                DeclaredOutput(("tasks",), "array"),
                DeclaredOutput(("count",), "integer"),
            ),
        ),
        CompositionStepProposal(
            "memory_search", "memory.recall", "memory.search", RISK_READ_ONLY,
            bindings=(
                select("query"), select("project"),
                LiteralBinding("limit", LITERAL_APPROVED_CONTRACT, 10),
            ),
            prerequisite_step_ids=(
                "project_overview", "task_summary", "task_list",
            ),
            declared_outputs=(DeclaredOutput(("results",), "array"),),
        ),
        CompositionStepProposal(
            "task_create", "tasks.manage", "tasks.create", RISK_INTERNAL_WRITE,
            bindings=(
                select("project"),
                ResultBinding(
                    "title",
                    "task_summary",
                    ("counts", "open"),
                    TRANSFORM_FIXED_TITLE,
                ),
            ),
            prerequisite_step_ids=(
                "project_overview",
                "task_summary",
                "task_list",
                "memory_search",
            ),
        ),
    )


def _proposal(steps=None):
    return propose_composition_mission(
        "mission-v04d-baseline", GOAL, steps or _steps()
    )


def _registry(*, replace_name=None, omit_name=None, **changes):
    registry = ToolRegistry()
    for definition in build_default_registry().list_definitions():
        if definition.name == omit_name:
            continue
        if definition.name == replace_name:
            definition = replace(definition, **changes)
        registry.register(definition)
    return registry


def test_current_live_registry_resolves_exact_baseline_facts():
    plan = bind_composition_feasibility(_proposal(), build_default_registry())
    assert plan.status == STATUS_FEASIBLE
    assert tuple(
        step.tool.name for step in plan.bound_steps
    ) == BASELINE_TOOL_ORDER
    assert {step.tool.version for step in plan.bound_steps} == {"1"}
    assert len(plan.registry_snapshot_sha256) == 64
    assert plan.registry_bound is True
    assert plan.runtime_revalidation_required is True
    assert plan.tool_requests_created is False
    assert plan.execution_performed is False
    assert plan.pending_operation_created is False


def test_schema_risk_capability_and_dependency_facts_are_bound():
    plan = bind_composition_feasibility(_proposal(), build_default_registry())
    facts = {step.tool.name: step.tool for step in plan.bound_steps}
    assert len(facts["projects.overview"].input_schema_sha256) == 64
    assert facts["projects.overview"].risk == RISK_READ_ONLY
    assert facts["projects.overview"].capabilities == ("projects.insight",)
    assert facts["projects.overview"].dependencies == ("projects.list",)
    assert facts["tasks.create"].risk == RISK_INTERNAL_WRITE


def test_missing_tool_and_unresolved_dependency_fail_closed():
    missing = bind_composition_feasibility(
        _proposal(), _registry(omit_name="memory.search")
    )
    assert missing.status == STATUS_NOT_FEASIBLE
    dependency = bind_composition_feasibility(
        _proposal(), _registry(omit_name="projects.list")
    )
    assert dependency.status == STATUS_NOT_FEASIBLE
    assert "dependency" in dependency.blocking_reasons[0]


def test_changed_version_is_bound_and_changes_snapshot_identity():
    current = bind_composition_feasibility(
        _proposal(), build_default_registry()
    )
    changed = bind_composition_feasibility(
        _proposal(), _registry(replace_name="memory.search", version="2")
    )
    assert changed.status == STATUS_FEASIBLE
    assert changed.bound_steps[3].tool.version == "2"
    assert changed.registry_snapshot_sha256 != current.registry_snapshot_sha256


def test_changed_or_incompatible_schema_fails_closed():
    definition = build_default_registry().get("memory.search")
    schema = dict(definition.input_schema)
    schema["properties"] = dict(schema["properties"])
    schema["properties"].pop("project")
    result = bind_composition_feasibility(
        _proposal(),
        _registry(replace_name="memory.search", input_schema=schema),
    )
    assert result.status == STATUS_NOT_FEASIBLE
    assert "schema" in result.blocking_reasons[0]


@pytest.mark.parametrize(
    "changes",
    [
        {"risk": RISK_HIGH_RISK},
        {"risk": RISK_INTERNAL_WRITE},
        {"capabilities": ("other.capability",)},
    ],
)
def test_changed_risk_high_risk_and_missing_capability_fail(changes):
    result = bind_composition_feasibility(
        _proposal(), _registry(replace_name="memory.search", **changes)
    )
    assert result.status == STATUS_NOT_FEASIBLE


def test_missing_result_field_and_incompatible_transform_fail_closed():
    steps = _steps()
    missing_output = replace(steps[0], declared_outputs=())
    missing = bind_composition_feasibility(
        _proposal((missing_output, *steps[1:])), build_default_registry()
    )
    assert missing.status == STATUS_NOT_FEASIBLE
    incompatible_output = replace(
        steps[0], declared_outputs=(DeclaredOutput(("projects",), "integer"),)
    )
    incompatible = bind_composition_feasibility(
        _proposal((incompatible_output, *steps[1:])), build_default_registry()
    )
    assert incompatible.status == STATUS_NOT_FEASIBLE
    assert "type-incompatible" in incompatible.blocking_reasons[0]


def test_baseline_order_budget_and_identical_policy_are_bound():
    plan = bind_composition_feasibility(_proposal(), build_default_registry())
    assert plan.proposal.max_processed_requests == 5
    assert plan.proposal.max_identical_requests == 2
    assert plan.proposal.max_consecutive_failures == 2
    assert plan.pending_write_counts_as_processed is True
    assert plan.in_memory_budget_only is True
    assert plan.cross_process_budget_continuity is False
    reordered = _steps()[1:] + _steps()[:1]
    result = bind_composition_feasibility(
        _proposal(reordered), build_default_registry()
    )
    assert result.status == STATUS_NOT_FEASIBLE


def test_forged_budget_overflow_and_repeated_tool_fail_closed():
    proposal = _proposal()
    forged_budget = object.__new__(type(proposal))
    for name in proposal.__dataclass_fields__:
        object.__setattr__(forged_budget, name, getattr(proposal, name))
    object.__setattr__(forged_budget, "max_processed_requests", 4)
    budget_result = bind_composition_feasibility(
        forged_budget, build_default_registry()
    )
    assert budget_result.status == STATUS_NOT_FEASIBLE

    steps = _steps()
    repeated = replace(steps[3], tool_name="tasks.list")
    repeated_result = bind_composition_feasibility(
        _proposal((*steps[:3], repeated, steps[4])),
        build_default_registry(),
    )
    assert repeated_result.status == STATUS_NOT_FEASIBLE


def test_result_binding_cannot_derive_executable_authority():
    steps = _steps()
    authority_binding = ResultBinding(
        "tool_name",
        "project_overview",
        ("projects",),
        TRANSFORM_SELECT_PROJECT,
    )
    forged_step = replace(
        steps[1], bindings=(*steps[1].bindings, authority_binding)
    )
    result = bind_composition_feasibility(
        _proposal((steps[0], forged_step, *steps[2:])),
        build_default_registry(),
    )
    assert result.status == STATUS_NOT_FEASIBLE


def test_forged_cycle_is_rejected_defensively():
    proposal = _proposal()
    forged_steps = (
        replace(proposal.steps[0], prerequisite_step_ids=("task_create",)),
        *proposal.steps[1:],
    )
    forged = object.__new__(type(proposal))
    for name in proposal.__dataclass_fields__:
        object.__setattr__(forged, name, getattr(proposal, name))
    object.__setattr__(forged, "steps", forged_steps)
    result = bind_composition_feasibility(forged, build_default_registry())
    assert result.status == STATUS_NOT_FEASIBLE
    assert "authoritative" in result.blocking_reasons[0]


def test_plan_is_deterministic_immutable_bounded_and_unforgeable():
    first = bind_composition_feasibility(_proposal(), build_default_registry())
    second = bind_composition_feasibility(
        _proposal(), build_default_registry()
    )
    assert first == second
    assert first.summary() == second.summary()
    assert len(first.summary().encode("utf-8")) <= 128 * 1024
    serialized = first.summary().lower()
    assert "raw_prompt" not in serialized
    assert "credentials" not in serialized
    assert "access_token" not in serialized
    with pytest.raises(FrozenInstanceError):
        first.status = STATUS_NOT_FEASIBLE
    with pytest.raises(CompositionFeasibilityError, match="snapshot"):
        replace(first, registry_snapshot_sha256="0" * 64)


def test_invalid_types_fail_and_binding_does_not_mutate_registry():
    registry = build_default_registry()
    before = registry.catalog()
    with pytest.raises(CompositionFeasibilityError):
        bind_composition_feasibility(None, registry)
    with pytest.raises(CompositionFeasibilityError):
        bind_composition_feasibility(_proposal(), None)
    bind_composition_feasibility(_proposal(), registry)
    assert registry.catalog() == before


def test_module_has_no_executor_request_operation_io_or_second_registry():
    path = Path(__file__).parents[1] / "backend/composition_feasibility.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        getattr(node.func, "id", getattr(node.func, "attr", ""))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert not calls & {
        "execute_tool",
        "create_pending_operation",
        "register",
        "open",
        "run",
        "Popen",
    }
    assert "ToolRequest" not in source
    assert "tool_executor" not in source
    assert "tool_operations" not in source
    assert "class ToolRegistry" not in source
