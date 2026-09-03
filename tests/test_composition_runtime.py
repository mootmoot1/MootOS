"""Tests for the controlled V0.4D composition runtime."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.composition_feasibility import bind_composition_feasibility
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
from backend.composition_runtime import (
    STATUS_APPROVAL_PENDING,
    STATUS_BLOCKED,
    STATUS_FAILED,
    CompositionRuntimeError,
    run_composition_mission,
)
from backend.db import DATABASE_PATH
from backend.memory import init_db
from backend.tool_operations import get_operation
from backend.tool_registry import ToolRegistry, build_default_registry


GOAL = (
    "Review project activity and task status, consult stored context, "
    "then prepare one follow-up task for human approval."
)


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _select(argument):
    return ResultBinding(
        argument,
        "project_overview",
        ("projects",),
        TRANSFORM_SELECT_PROJECT,
    )


def _proposal():
    steps = (
        CompositionStepProposal(
            "project_overview",
            "projects.insight",
            "projects.overview",
            RISK_READ_ONLY,
            declared_outputs=(
                DeclaredOutput(("projects",), "array"),
                DeclaredOutput(("truncated",), "boolean"),
            ),
        ),
        CompositionStepProposal(
            "task_summary",
            "tasks.status_insight",
            "tasks.status_summary",
            RISK_READ_ONLY,
            bindings=(_select("project"),),
            prerequisite_step_ids=("project_overview",),
            declared_outputs=(
                DeclaredOutput(("counts", "open"), "integer"),
                DeclaredOutput(("project",), "string"),
            ),
        ),
        CompositionStepProposal(
            "task_list",
            "tasks.manage",
            "tasks.list",
            RISK_READ_ONLY,
            bindings=(
                _select("project"),
                LiteralBinding(
                    "status", LITERAL_APPROVED_CONTRACT, "open"
                ),
                LiteralBinding(
                    "limit", LITERAL_APPROVED_CONTRACT, 100
                ),
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
                _select("query"),
                _select("project"),
                LiteralBinding(
                    "limit", LITERAL_APPROVED_CONTRACT, 10
                ),
            ),
            prerequisite_step_ids=(
                "project_overview", "task_summary", "task_list",
            ),
            declared_outputs=(
                DeclaredOutput(("memories",), "array"),
                DeclaredOutput(("count",), "integer"),
                DeclaredOutput(("query",), "string"),
            ),
        ),
        CompositionStepProposal(
            "task_create",
            "tasks.manage",
            "tasks.create",
            RISK_INTERNAL_WRITE,
            bindings=(
                _select("project"),
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
    return propose_composition_mission("mission-runtime", GOAL, steps)


def _registry(*, summary_count=2, listed_count=2, malformed=None):
    outputs = {
        "projects.overview": {
            "projects": [
                {"name": "Zulu", "open_tasks": 2},
                {"name": "alpha", "open_tasks": 2},
            ],
            "truncated": False,
        },
        "tasks.status_summary": {
            "counts": {
                "open": summary_count,
                "completed": 0,
                "cancelled": 0,
            },
            "total": summary_count,
            "project": "alpha",
        },
        "tasks.list": {
            "tasks": [
                {
                    "id": f"task-{index}",
                    "title": "Existing",
                    "project": "alpha",
                    "status": "open",
                }
                for index in range(listed_count)
            ],
            "count": listed_count,
        },
        "memory.search": {
            "memories": [{"id": "memory-1", "content": "Context"}],
            "count": 1,
            "query": "alpha",
        },
    }
    if malformed:
        outputs[malformed] = {"unexpected": True}
    registry = ToolRegistry()
    for definition in build_default_registry().list_definitions():
        if definition.name in outputs:
            value = outputs[definition.name]

            def executor(arguments, context, result=value):
                return result

            definition = replace(definition, executor=executor)
        elif definition.name == "tasks.create":

            def forbidden_executor(arguments, context):
                raise AssertionError("write executor must not run")

            definition = replace(definition, executor=forbidden_executor)
        registry.register(definition)
    return registry


def _plan(registry):
    return bind_composition_feasibility(_proposal(), registry)


def test_valid_runtime_executes_reads_and_freezes_exact_write(clean_db):
    registry = _registry()
    result = run_composition_mission(_plan(registry), registry)

    assert result.status == STATUS_APPROVAL_PENDING
    assert result.selected_project == "alpha"
    assert result.open_task_count == 2
    assert result.listed_open_task_count == 2
    assert result.memory_match_count == 1
    assert result.processed_requests == 5
    assert result.executed_requests == 4
    assert result.write_executed is False
    assert result.approval_performed is False
    assert len(result.request_signatures) == 5
    operation = get_operation(result.pending_operation_id)
    assert operation["status"] == "pending"
    assert operation["arguments"] == {
        "project": "alpha",
        "title": "Follow up on alpha: review 2 open tasks",
    }
    assert result.pending_arguments_sha256


def test_project_selection_uses_count_then_normalized_name(clean_db):
    registry = _registry()
    result = run_composition_mission(_plan(registry), registry)
    assert result.selected_project == "alpha"


@pytest.mark.parametrize("summary_count,listed_count", [(3, 2), (1, 2)])
def test_task_summary_and_list_disagreement_fails_closed(
    clean_db, summary_count, listed_count
):
    registry = _registry(
        summary_count=summary_count, listed_count=listed_count
    )
    result = run_composition_mission(_plan(registry), registry)

    assert result.status == STATUS_FAILED
    assert result.pending_operation_id == ""
    assert result.processed_requests == 3
    assert result.executed_requests == 3


def test_malformed_declared_result_blocks_dependents(clean_db):
    registry = _registry(malformed="tasks.status_summary")
    result = run_composition_mission(_plan(registry), registry)

    assert result.status == STATUS_FAILED
    assert result.step_runs[1].status == "failed"
    assert all(
        step.status == "not_attempted" for step in result.step_runs[2:]
    )
    assert result.pending_operation_id == ""


def test_registry_change_before_execution_blocks_every_step(clean_db):
    registry = _registry()
    plan = _plan(registry)
    definition = registry.get("memory.search")
    registry._tools["memory.search"] = replace(definition, version="2")

    result = run_composition_mission(plan, registry)

    assert result.status == STATUS_BLOCKED
    assert result.processed_requests == 0
    assert result.executed_requests == 0
    assert all(step.status == "not_attempted" for step in result.step_runs)


def test_registry_is_revalidated_immediately_before_each_step(clean_db):
    registry = _registry()
    original = registry.get("projects.overview")

    def mutate_registry(arguments, context):
        memory = registry.get("memory.search")
        registry._tools["memory.search"] = replace(memory, version="2")
        return {
            "projects": [{"name": "alpha", "open_tasks": 0}],
            "truncated": False,
        }

    registry._tools["projects.overview"] = replace(
        original, executor=mutate_registry
    )
    plan = _plan(registry)
    result = run_composition_mission(plan, registry)

    assert result.status == STATUS_BLOCKED
    assert result.executed_requests == 1
    assert result.step_runs[0].status == "succeeded"
    assert result.step_runs[1].status == "not_attempted"


def test_read_executor_failure_records_safe_class_and_stops(clean_db):
    registry = _registry()
    definition = registry.get("tasks.list")

    def fail(arguments, context):
        raise RuntimeError("private details")

    registry._tools["tasks.list"] = replace(definition, executor=fail)
    plan = _plan(registry)
    result = run_composition_mission(plan, registry)

    assert result.status == STATUS_FAILED
    assert result.failure_class == "ToolExecutionError"
    assert "private details" not in result.summary()
    assert result.pending_operation_id == ""


def test_runtime_result_is_immutable_bounded_and_sanitized(clean_db):
    registry = _registry()
    result = run_composition_mission(_plan(registry), registry)
    serialized = result.summary()

    assert len(serialized.encode("utf-8")) <= 128 * 1024
    assert "Context" not in serialized
    assert "Existing" not in serialized
    assert "password" not in serialized.lower()
    with pytest.raises(FrozenInstanceError):
        result.status = STATUS_FAILED
    with pytest.raises(CompositionRuntimeError, match="binding"):
        replace(
            result,
            step_runs=(replace(result.step_runs[0], tool_version="2"),)
            + result.step_runs[1:],
        )


def test_invalid_or_non_feasible_plan_is_rejected(clean_db):
    registry = _registry()
    with pytest.raises(CompositionRuntimeError):
        run_composition_mission(None, registry)
    changed = ToolRegistry()
    for definition in registry.list_definitions():
        if definition.name != "memory.search":
            changed.register(definition)
    non_feasible = bind_composition_feasibility(_proposal(), changed)
    with pytest.raises(CompositionRuntimeError):
        run_composition_mission(non_feasible, changed)


def test_runtime_has_no_approval_resume_or_second_execution_system():
    path = Path(__file__).parents[1] / "backend/composition_runtime.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "approve_operation" not in source
    assert "reject_operation" not in source
    assert "subprocess" not in imported
    assert "requests" not in imported
    assert "httpx" not in imported
    assert "socket" not in imported
    assert "ToolRegistry" in source
    assert "execute_tool" in source
    assert "create_pending_operation" in source
