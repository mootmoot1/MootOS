"""Tests for the V0.3E proof-capability tool, tasks.status_summary, and
its backing helper backend.tasks.count_tasks_by_status.

Mirrors the style of tests/test_tools_reference.py -- executed through the
real centralized executor, against the real (temporary) database, exactly
like every other tool. See docs/CAPABILITY_BUILD_PIPELINE.md.
"""

import pytest

from backend.db import DATABASE_PATH
from backend.memory import create_project, init_db
from backend.tasks import TASK_STATUSES, cancel_task, complete_task, count_tasks_by_status, create_task
from backend.tool_executor import execute_tool
from backend.tool_registry import ToolRegistry, get_tool_registry
from backend.tool_types import RISK_READ_ONLY, ToolExecutionContext, ToolExecutionError, ToolValidationError
from backend.tools_task_summary import TASKS_STATUS_SUMMARY, register_v03e_tools
from backend.tools_reference import register_reference_tools


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _run(tool_name, arguments, *, approved=False):
    return execute_tool(
        tool_name=tool_name,
        arguments=arguments,
        context=ToolExecutionContext(approved=approved),
        registry=get_tool_registry(),
    )


# --- backend.tasks.count_tasks_by_status (domain helper) --------------------


def test_count_tasks_by_status_reports_every_status_including_zero(clean_db):
    counts = count_tasks_by_status()
    assert set(counts) == TASK_STATUSES
    assert all(value == 0 for value in counts.values())


def test_count_tasks_by_status_counts_real_tasks_correctly(clean_db):
    open_task = create_task(title="Open task")
    to_complete = create_task(title="Will complete")
    to_cancel = create_task(title="Will cancel")
    complete_task(to_complete["id"])
    cancel_task(to_cancel["id"])

    counts = count_tasks_by_status()

    assert counts["open"] == 1
    assert counts["completed"] == 1
    assert counts["cancelled"] == 1
    assert open_task["status"] == "open"


def test_count_tasks_by_status_scopes_to_one_project(clean_db):
    create_project(name="Alpha")
    create_project(name="Beta")
    create_task(title="Alpha task", project="Alpha")
    create_task(title="Beta task 1", project="Beta")
    create_task(title="Beta task 2", project="Beta")

    alpha_counts = count_tasks_by_status(project="Alpha")
    beta_counts = count_tasks_by_status(project="Beta")

    assert alpha_counts["open"] == 1
    assert beta_counts["open"] == 2


def test_count_tasks_by_status_rejects_a_nonexistent_project(clean_db):
    with pytest.raises(ValueError):
        count_tasks_by_status(project="Does Not Exist")


# --- tasks.status_summary (registered tool, via the real executor) ----------


def test_tasks_status_summary_returns_exact_counts(clean_db):
    create_task(title="Open one")

    result = _run("tasks.status_summary", {})

    assert result.data["counts"]["open"] == 1
    assert result.data["counts"]["completed"] == 0
    assert result.data["counts"]["cancelled"] == 0
    assert result.data["total"] == 1
    assert result.data["project"] is None


def test_tasks_status_summary_scopes_to_project(clean_db):
    create_project(name="Alpha")
    create_task(title="Alpha task", project="Alpha")
    create_task(title="Unscoped task")

    result = _run("tasks.status_summary", {"project": "Alpha"})

    assert result.data["total"] == 1
    assert result.data["project"] == "Alpha"


def test_tasks_status_summary_rejects_unexpected_arguments(clean_db):
    with pytest.raises(ToolValidationError):
        _run("tasks.status_summary", {"unexpected": True})


def test_tasks_status_summary_rejects_a_nonexistent_project(clean_db):
    with pytest.raises(ToolExecutionError):
        _run("tasks.status_summary", {"project": "Does Not Exist"})


def test_tasks_status_summary_executes_without_approval_being_read_only(clean_db):
    """RISK_READ_ONLY tools auto-execute; unlike tasks.create, no approval
    is required or consulted."""
    result = _run("tasks.status_summary", {}, approved=False)
    assert result.data["total"] == 0


# --- Tool contract / metadata -------------------------------------------------


def test_tasks_status_summary_is_registered_read_only_with_expected_metadata():
    assert TASKS_STATUS_SUMMARY.risk == RISK_READ_ONLY
    assert TASKS_STATUS_SUMMARY.idempotent is True
    assert "read-only" in TASKS_STATUS_SUMMARY.side_effects.lower()
    assert TASKS_STATUS_SUMMARY.capabilities == ("tasks.status_insight",)
    assert TASKS_STATUS_SUMMARY.limitations


# --- 8/9. Registration is explicit -- implementing code alone installs nothing


def test_the_tool_definition_existing_does_not_make_it_registered_anywhere():
    """Importing backend.tools_task_summary (module load) must not, by
    itself, register TASKS_STATUS_SUMMARY on any registry -- registration
    only ever happens inside register_v03e_tools, called explicitly."""
    fresh = ToolRegistry()
    register_reference_tools(fresh)
    # Deliberately do NOT call register_v03e_tools here.
    with pytest.raises(Exception):
        fresh.get("tasks.status_summary")


def test_registered_capability_appears_only_after_explicit_registration_call():
    before = ToolRegistry()
    register_reference_tools(before)
    assert "tasks.status_summary" not in {d.name for d in before.list_definitions()}

    after = ToolRegistry()
    register_reference_tools(after)
    register_v03e_tools(after)
    assert "tasks.status_summary" in {d.name for d in after.list_definitions()}


def test_it_is_present_in_the_real_default_registry_on_this_branch():
    """On THIS branch, the registration call has been added to
    backend/tool_registry.py, so the live default registry does contain
    it -- this is expected and correct for this branch's own code; it is
    not evidence that production (main) has it until this branch is
    actually merged and deployed. See docs/CAPABILITY_BUILD_PIPELINE.md."""
    registry = get_tool_registry()
    assert "tasks.status_summary" in {d.name for d in registry.list_definitions()}
