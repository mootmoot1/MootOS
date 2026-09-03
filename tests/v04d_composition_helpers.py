"""Shared test builders for the fixed ADR-040 baseline mission."""

from dataclasses import replace

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
from backend.tool_registry import ToolRegistry, build_default_registry


GOAL = (
    "Review project activity and task status, consult stored context, "
    "then prepare one follow-up task for human approval."
)


def _select(argument):
    return ResultBinding(
        argument,
        "project_overview",
        ("projects",),
        TRANSFORM_SELECT_PROJECT,
    )


def build_proposal(mission_id="mission-receipt"):
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
    return propose_composition_mission(mission_id, GOAL, steps)


def build_fake_registry(*, summary_count=2, listed_count=2):
    outputs = {
        "projects.overview": {
            "projects": [{"name": "MootOS", "open_tasks": 2}],
            "truncated": False,
        },
        "tasks.status_summary": {
            "counts": {
                "open": summary_count,
                "completed": 0,
                "cancelled": 0,
            },
            "total": summary_count,
            "project": "MootOS",
        },
        "tasks.list": {
            "tasks": [
                {
                    "id": f"task-{index}",
                    "title": "Existing",
                    "project": "MootOS",
                    "status": "open",
                }
                for index in range(listed_count)
            ],
            "count": listed_count,
        },
        "memory.search": {
            "memories": [],
            "count": 0,
            "query": "MootOS",
        },
    }
    registry = ToolRegistry()
    for definition in build_default_registry().list_definitions():
        if definition.name in outputs:
            value = outputs[definition.name]

            def executor(arguments, context, result=value):
                return result

            definition = replace(definition, executor=executor)
        registry.register(definition)
    return registry


def build_plan(registry, mission_id="mission-receipt"):
    return bind_composition_feasibility(
        build_proposal(mission_id), registry
    )
