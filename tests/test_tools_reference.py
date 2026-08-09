"""Tests for the four V0.2A reference tools, exercised through the executor."""

import pytest

from backend.db import DATABASE_PATH
from backend.memory import create_memory, create_project, init_db
from backend.tasks import create_task
from backend.tool_executor import execute_tool
from backend.tool_registry import get_tool_registry
from backend.tool_types import ToolExecutionContext, ToolExecutionError, ToolValidationError


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


# --- projects.list -----------------------------------------------------------


def test_projects_list_returns_stored_projects(clean_db):
    result = _run("projects.list", {})
    names = {project["name"] for project in result.data["projects"]}
    assert "MootOS" in names
    assert "Studio" in names


def test_projects_list_rejects_unexpected_arguments(clean_db):
    with pytest.raises(ToolValidationError):
        _run("projects.list", {"unexpected": True})


# --- memory.search -------------------------------------------------------------


def test_memory_search_finds_active_matching_memory(clean_db):
    create_memory(content="The car needs an oil change soon.", project="Cars")

    result = _run("memory.search", {"query": "car"})

    assert result.data["count"] == 1
    assert "oil change" in result.data["memories"][0]["content"]


def test_memory_search_requires_nonempty_query(clean_db):
    with pytest.raises(ToolValidationError):
        _run("memory.search", {"query": ""})
    with pytest.raises(ToolValidationError):
        _run("memory.search", {})


def test_memory_search_bounds_results_to_requested_limit(clean_db):
    for index in range(5):
        create_memory(content=f"studio note {index} about mixing")

    result = _run("memory.search", {"query": "studio", "limit": 2})

    assert result.data["count"] == 2


def test_memory_search_never_returns_archived_memory(clean_db):
    from backend.memory import archive_memory

    saved = create_memory(content="Old car detail that was archived")
    archive_memory(saved["id"])

    result = _run("memory.search", {"query": "car"})

    assert result.data["count"] == 0


def test_memory_search_rejects_unknown_project(clean_db):
    with pytest.raises(ToolExecutionError):
        _run("memory.search", {"query": "car", "project": "Does Not Exist"})


# --- tasks.list ------------------------------------------------------------------


def test_tasks_list_returns_open_tasks(clean_db):
    create_task(title="Export final mix")

    result = _run("tasks.list", {})

    assert result.data["count"] == 1
    assert result.data["tasks"][0]["title"] == "Export final mix"


def test_tasks_list_filters_by_status_and_project(clean_db):
    create_project("Filming")
    create_task(title="Studio task", project="Studio")
    create_task(title="Filming task", project="Filming")

    result = _run("tasks.list", {"project": "Studio"})

    assert [task["title"] for task in result.data["tasks"]] == ["Studio task"]


def test_tasks_list_rejects_unsupported_status(clean_db):
    with pytest.raises(ToolValidationError):
        _run("tasks.list", {"status": "not-a-real-status"})


def test_tasks_list_bounds_limit(clean_db):
    with pytest.raises(ToolValidationError):
        _run("tasks.list", {"limit": 0})
    with pytest.raises(ToolValidationError):
        _run("tasks.list", {"limit": 1000})


# --- tasks.create (INTERNAL_WRITE) ----------------------------------------------


def test_tasks_create_is_blocked_without_approval(clean_db):
    from backend.tool_types import ToolPermissionError

    with pytest.raises(ToolPermissionError):
        _run("tasks.create", {"title": "Call Mike"}, approved=False)

    from backend.tasks import list_tasks

    assert list_tasks() == []


def test_tasks_create_creates_exactly_one_task_when_approved(clean_db):
    result = _run("tasks.create", {"title": "Call Mike"}, approved=True)

    assert result.success is True
    assert result.data["task"]["title"] == "Call Mike"

    from backend.tasks import list_tasks

    assert len(list_tasks()) == 1


def test_tasks_create_rejects_unknown_project_even_when_approved(clean_db):
    with pytest.raises(ToolExecutionError, match="Project does not exist"):
        _run("tasks.create", {"title": "Call Mike", "project": "Nonexistent"}, approved=True)


def test_tasks_create_requires_nonempty_title(clean_db):
    with pytest.raises(ToolValidationError):
        _run("tasks.create", {"title": ""}, approved=True)
