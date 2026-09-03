"""Tests for V0.4D Slice 2 inert composition proposals."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.composition_proposal import (
    LITERAL_APPROVED_CONTRACT,
    MAX_GOAL_BYTES,
    RISK_INTERNAL_WRITE,
    RISK_READ_ONLY,
    TRANSFORM_FIXED_TITLE,
    TRANSFORM_SELECT_PROJECT,
    CompositionProposalError,
    CompositionStepProposal,
    DeclaredOutput,
    LiteralBinding,
    ResultBinding,
    propose_composition_mission,
)


GOAL = (
    "Review current project activity and task status, consult relevant stored "
    "context, then prepare one appropriate follow-up task for human approval."
)


def _steps():
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
            bindings=(
                ResultBinding(
                    "project",
                    "project_overview",
                    ("projects",),
                    TRANSFORM_SELECT_PROJECT,
                ),
            ),
            prerequisite_step_ids=("project_overview",),
            declared_outputs=(
                DeclaredOutput(("counts", "open"), "integer"),
                DeclaredOutput(("project",), "string"),
            ),
        ),
        CompositionStepProposal(
            "task_list", "tasks.manage", "tasks.list", RISK_READ_ONLY,
            bindings=(
                ResultBinding(
                    "project",
                    "project_overview",
                    ("projects",),
                    TRANSFORM_SELECT_PROJECT,
                ),
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
            "memory_search",
            "memory.recall",
            "memory.search",
            RISK_READ_ONLY,
            bindings=(
                ResultBinding(
                    "query",
                    "project_overview",
                    ("projects",),
                    TRANSFORM_SELECT_PROJECT,
                ),
                ResultBinding(
                    "project",
                    "project_overview",
                    ("projects",),
                    TRANSFORM_SELECT_PROJECT,
                ),
                LiteralBinding("limit", LITERAL_APPROVED_CONTRACT, 10),
            ),
            prerequisite_step_ids=(
                "project_overview", "task_summary", "task_list",
            ),
            declared_outputs=(DeclaredOutput(("results",), "array"),),
        ),
        CompositionStepProposal(
            "task_create",
            "tasks.manage",
            "tasks.create",
            RISK_INTERNAL_WRITE,
            bindings=(
                ResultBinding(
                    "project",
                    "project_overview",
                    ("projects",),
                    TRANSFORM_SELECT_PROJECT,
                ),
                ResultBinding(
                    "title",
                    "task_summary",
                    ("counts", "open"),
                    TRANSFORM_FIXED_TITLE,
                ),
            ),
            prerequisite_step_ids=(
                "project_overview", "task_summary", "task_list",
                "memory_search",
            ),
        ),
    )


def _proposal(steps=None, goal=GOAL):
    return propose_composition_mission(
        "mission-v04d-baseline", goal, steps or _steps()
    )


def test_valid_baseline_proposal_is_inert_and_bounded():
    proposal = _proposal()
    assert len(proposal.steps) == 5
    assert proposal.max_processed_requests == 5
    assert proposal.tools_resolved is False
    assert proposal.execution_performed is False
    assert proposal.pending_operation_created is False
    assert proposal.persisted is False


def test_serialization_is_deterministic_and_result_is_immutable():
    first = _proposal()
    second = _proposal()
    assert first == second
    assert first.summary() == second.summary()
    with pytest.raises(FrozenInstanceError):
        first.steps = ()


def test_step_ids_and_argument_bindings_must_be_unique():
    steps = _steps()
    with pytest.raises(CompositionProposalError, match="step IDs"):
        duplicate = replace(steps[-1], step_id=steps[0].step_id)
        _proposal(steps=steps + (duplicate,))
    with pytest.raises(CompositionProposalError, match="argument bindings"):
        replace(steps[0], bindings=(
            LiteralBinding("project", LITERAL_APPROVED_CONTRACT, "one"),
            LiteralBinding("project", LITERAL_APPROVED_CONTRACT, "two"),
        ))


def test_missing_prerequisite_and_result_source_are_rejected():
    steps = _steps()
    with pytest.raises(CompositionProposalError, match="invalid references"):
        first = replace(steps[0], prerequisite_step_ids=("missing",))
        _proposal(steps=(first,) + steps[1:])
    with pytest.raises(
        CompositionProposalError, match="explicit prerequisite"
    ):
        second = replace(steps[1], prerequisite_step_ids=())
        _proposal(steps=(steps[0], second, *steps[2:]))


def test_cycles_are_rejected():
    steps = _steps()
    cycled = (
        replace(steps[0], prerequisite_step_ids=("task_create",)),
        *steps[1:],
    )
    with pytest.raises(CompositionProposalError, match="cycle"):
        _proposal(steps=cycled)


def test_goal_step_and_literal_bounds_are_enforced():
    valid = "é" * (MAX_GOAL_BYTES // 2)
    assert _proposal(goal=valid).goal_summary == valid
    with pytest.raises(CompositionProposalError, match="exceeds"):
        _proposal(goal=valid + "é")
    with pytest.raises(CompositionProposalError, match="step count"):
        _proposal(steps=_steps() + _steps())
    with pytest.raises(
        CompositionProposalError, match="literal value exceeds"
    ):
        LiteralBinding("title", LITERAL_APPROVED_CONTRACT, "x" * 2049)


def test_invalid_transform_and_malformed_field_path_are_rejected():
    with pytest.raises(CompositionProposalError, match="transform"):
        ResultBinding("project", "source", ("projects",), "eval")
    for path in ((), ("bad.path",), "projects"):
        with pytest.raises(CompositionProposalError, match="field_path"):
            ResultBinding("project", "source", path)


def test_result_binding_cannot_select_tool_capability_risk_or_authority():
    fields = set(ResultBinding.__dataclass_fields__)
    assert fields == {
        "argument_name", "source_step_id", "field_path", "transform",
    }
    assert not fields & {
        "tool_name", "capability_id", "risk", "executor", "approval",
        "budget",
    }


def test_summary_is_sanitized_and_contains_no_operational_state():
    proposal = _proposal()
    lowered = proposal.summary().casefold()
    assert "raw_prompt" not in lowered
    assert "provider_state" not in lowered
    assert "credentials" not in lowered
    with pytest.raises(CompositionProposalError, match="secret-like"):
        _proposal(goal="password=do-not-store")


def test_direct_forgery_is_rejected():
    proposal = _proposal()
    with pytest.raises(CompositionProposalError, match="digest"):
        replace(proposal, goal_sha256="0" * 64)
    with pytest.raises(CompositionProposalError, match="budget"):
        replace(proposal, max_processed_requests=6)


def test_module_has_no_registry_executor_operation_or_io_authority():
    path = Path(__file__).parents[1] / "backend/composition_proposal.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imports.update(
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not imports & {
        "backend", "os", "pathlib", "requests", "socket", "subprocess",
        "urllib",
    }
    assert "ToolRequest" not in source
    assert "create_pending_operation" not in source
