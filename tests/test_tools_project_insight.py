"""Tests for V0.3E proof #2: the projects.overview tool and its backing
cross-resource rollup, backend.project_insight.summarize_projects.

Mirrors tests/test_tools_task_summary.py's style -- exercised through the
real centralized executor, against a real temporary database. See
docs/CAPABILITY_BUILD_PIPELINE.md §12.
"""

import pytest

from backend.conversation import create_conversation
from backend.db import DATABASE_PATH
from backend.memory import archive_memory, create_memory, create_project, init_db
from backend.project_insight import summarize_projects
from backend.runs import DATA_EXPOSURE_LOCAL
from backend.tasks import cancel_task, complete_task, create_task
from backend.tool_executor import execute_tool
from backend.tool_registry import ToolRegistry, get_tool_registry
from backend.tool_types import (
    RISK_READ_ONLY,
    ToolExecutionContext,
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from backend.tools_project_insight import PROJECTS_OVERVIEW, register_v03e_proof2_tools
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


def _by_name(result):
    return {entry["name"]: entry for entry in result["projects"]}


# --- summarize_projects: the cross-resource rollup ---------------------------


def test_every_existing_project_appears_even_with_no_activity(clean_db):
    """An empty project must be visibly empty, not mysteriously absent."""
    create_project(name="Empty")

    result = summarize_projects()
    entry = _by_name(result)["Empty"]

    assert entry["active_memories"] == 0
    assert entry["open_tasks"] == 0
    assert entry["total_tasks"] == 0
    assert entry["conversations"] == 0
    assert entry["last_activity_at"] is None


def test_counts_span_memories_tasks_and_conversations(clean_db):
    create_project(name="Alpha")
    create_memory(content="alpha note one", project="Alpha")
    create_memory(content="alpha note two", project="Alpha")
    create_task(title="alpha task", project="Alpha")
    create_conversation(project="Alpha", title="alpha chat")

    entry = _by_name(summarize_projects())["Alpha"]

    assert entry["active_memories"] == 2
    assert entry["open_tasks"] == 1
    assert entry["total_tasks"] == 1
    assert entry["conversations"] == 1
    assert entry["last_activity_at"] is not None


def test_open_and_total_task_counts_are_distinct(clean_db):
    create_project(name="Alpha")
    create_task(title="stays open", project="Alpha")
    done = create_task(title="finished", project="Alpha")
    cancelled = create_task(title="dropped", project="Alpha")
    complete_task(done["id"])
    cancel_task(cancelled["id"])

    entry = _by_name(summarize_projects())["Alpha"]

    assert entry["open_tasks"] == 1
    assert entry["total_tasks"] == 3


def test_archived_memories_are_excluded_from_active_counts(clean_db):
    create_project(name="Alpha")
    kept = create_memory(content="kept note", project="Alpha")
    dropped = create_memory(content="dropped note", project="Alpha")
    archive_memory(dropped["id"])

    entry = _by_name(summarize_projects())["Alpha"]

    assert entry["active_memories"] == 1
    assert kept["id"] != dropped["id"]


def test_projects_do_not_leak_counts_into_each_other(clean_db):
    create_project(name="Alpha")
    create_project(name="Beta")
    create_memory(content="alpha only", project="Alpha")
    create_task(title="beta only", project="Beta")

    entries = _by_name(summarize_projects())

    assert entries["Alpha"]["active_memories"] == 1
    assert entries["Alpha"]["total_tasks"] == 0
    assert entries["Beta"]["active_memories"] == 0
    assert entries["Beta"]["total_tasks"] == 1


def test_unassigned_items_are_reported_separately_not_silently_dropped(clean_db):
    """Without an 'unassigned' bucket the per-project rows would be
    quietly misleading -- a caller summing them would undercount."""
    create_project(name="Alpha")
    create_memory(content="belongs to no project")
    create_task(title="no project task")

    result = summarize_projects()

    assert result["unassigned"]["active_memories"] == 1
    assert result["unassigned"]["total_tasks"] == 1
    assert _by_name(result)["Alpha"]["active_memories"] == 0


def test_projects_are_returned_in_stable_name_order(clean_db):
    for name in ("Zeta", "alpha", "Mid"):
        create_project(name=name)

    names = [entry["name"] for entry in summarize_projects()["projects"]]

    assert names == sorted(names, key=str.casefold)


def test_scoping_to_one_project_returns_only_that_project(clean_db):
    create_project(name="Alpha")
    create_project(name="Beta")
    create_memory(content="alpha note", project="Alpha")

    result = summarize_projects(project="Alpha")

    assert result["count"] == 1
    assert result["projects"][0]["name"] == "Alpha"
    assert result["projects"][0]["active_memories"] == 1


def test_scoped_call_omits_the_unassigned_bucket(clean_db):
    """An unassigned bucket is meaningless when scoped to one project."""
    create_project(name="Alpha")
    create_memory(content="no project")

    assert "unassigned" not in summarize_projects(project="Alpha")
    assert "unassigned" in summarize_projects()


def test_project_scoping_is_case_insensitive_and_returns_the_canonical_name(clean_db):
    """projects.name is UNIQUE COLLATE NOCASE, so a differently-cased
    request must resolve to the same project and echo its stored spelling."""
    create_project(name="Woodshop")
    create_memory(content="woodshop note", project="Woodshop")

    result = summarize_projects(project="wOoDsHoP")

    assert result["projects"][0]["name"] == "Woodshop"
    assert result["projects"][0]["active_memories"] == 1


def test_last_activity_takes_the_newest_across_all_three_resources(clean_db):
    create_project(name="Alpha")
    create_memory(content="oldest", project="Alpha")
    create_task(title="newer", project="Alpha")
    conversation = create_conversation(project="Alpha", title="newest")

    entry = _by_name(summarize_projects())["Alpha"]

    assert entry["last_activity_at"] == conversation["updated_at"]


def test_nonexistent_project_fails_closed(clean_db):
    with pytest.raises(ValueError):
        summarize_projects(project="Does Not Exist")


# --- projects.overview through the real executor -----------------------------


def test_tool_returns_the_rollup(clean_db):
    create_project(name="Alpha")
    create_memory(content="alpha note", project="Alpha")

    result = _run("projects.overview", {})

    assert _by_name(result.data)["Alpha"]["active_memories"] == 1
    assert result.data["count"] >= 1


def test_tool_scopes_to_project(clean_db):
    create_project(name="Alpha")
    create_project(name="Beta")

    result = _run("projects.overview", {"project": "Beta"})

    assert result.data["count"] == 1
    assert result.data["projects"][0]["name"] == "Beta"


def test_tool_executes_without_approval_being_read_only(clean_db):
    """RISK_READ_ONLY auto-executes; unlike tasks.create no approval is
    required or consulted."""
    result = _run("projects.overview", {}, approved=False)
    assert "projects" in result.data


# --- 8. Adversarial input surface --------------------------------------------


def test_unexpected_argument_is_rejected_by_schema_validation(clean_db):
    with pytest.raises(ToolValidationError):
        _run("projects.overview", {"unexpected": True})


def test_nonexistent_project_is_a_sanitized_execution_error(clean_db):
    with pytest.raises(ToolExecutionError):
        _run("projects.overview", {"project": "Does Not Exist"})


@pytest.mark.parametrize(
    "hostile",
    [
        "'; DROP TABLE projects; --",
        "Alpha' OR '1'='1",
        "%",
        "_",
        "../../etc/passwd",
    ],
)
def test_hostile_project_strings_fail_closed_without_side_effects(clean_db, hostile):
    """The project argument reaches a parameterized query only. A SQL
    metacharacter or LIKE wildcard must be treated as a literal name that
    simply does not exist -- never as syntax, never as a match-all."""
    create_project(name="Alpha")

    with pytest.raises(ToolExecutionError):
        _run("projects.overview", {"project": hostile})

    # The table is still there and untouched.
    assert _by_name(_run("projects.overview", {}).data)["Alpha"] is not None


def test_empty_project_string_is_rejected_by_schema_not_treated_as_unscoped(clean_db):
    """minLength=1 must stop "" before it reaches the executor, where it
    would otherwise be a falsy value that could be mistaken for 'no
    project supplied'."""
    with pytest.raises(ToolValidationError):
        _run("projects.overview", {"project": ""})


def test_overlong_project_string_is_rejected_by_schema(clean_db):
    with pytest.raises(ToolValidationError):
        _run("projects.overview", {"project": "x" * 101})


def test_non_string_project_argument_is_rejected(clean_db):
    with pytest.raises(ToolValidationError):
        _run("projects.overview", {"project": 5})


# --- 6/7. Metadata correctness and no hidden write path ----------------------


def test_declared_metadata_matches_the_registered_definition():
    assert PROJECTS_OVERVIEW.risk == RISK_READ_ONLY
    assert PROJECTS_OVERVIEW.data_exposure == DATA_EXPOSURE_LOCAL
    assert PROJECTS_OVERVIEW.idempotent is True
    assert PROJECTS_OVERVIEW.capabilities == ("projects.insight",)
    assert PROJECTS_OVERVIEW.limitations


def test_repeated_calls_are_idempotent_and_change_no_state(clean_db):
    """Declared idempotent=True must be true in practice, not just in
    metadata: calling repeatedly returns identical data and mutates
    nothing."""
    create_project(name="Alpha")
    create_memory(content="alpha note", project="Alpha")
    create_task(title="alpha task", project="Alpha")

    first = _run("projects.overview", {}).data
    second = _run("projects.overview", {}).data
    third = _run("projects.overview", {}).data

    assert first == second == third


def test_the_module_contains_no_write_statement_at_all():
    """Declared read_only, so no SQL write verb may appear anywhere in
    either the tool adapter or its backing rollup module."""
    from pathlib import Path

    repository_root = Path(__file__).resolve().parent.parent
    for relative in ("backend/project_insight.py", "backend/tools_project_insight.py"):
        source = (repository_root / relative).read_text(encoding="utf-8").upper()
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE TABLE"):
            assert verb not in source, f"{relative} contains a write verb: {verb.strip()}"


def test_output_never_contains_memory_task_or_conversation_content(clean_db):
    """The capability promises counts and timestamps only. Distinctive
    content is planted in every readable text column, then the entire
    serialized output is searched for it."""
    import json

    create_project(name="Alpha")
    create_memory(content="SUPERSECRETMEMORYCONTENT", project="Alpha")
    create_task(title="SUPERSECRETTASKTITLE", project="Alpha")
    create_conversation(project="Alpha", title="SUPERSECRETCHATTITLE")

    serialized = json.dumps(_run("projects.overview", {}).data)

    assert "SUPERSECRETMEMORYCONTENT" not in serialized
    assert "SUPERSECRETTASKTITLE" not in serialized
    assert "SUPERSECRETCHATTITLE" not in serialized


# --- 1/2. Absence before explicit registration -------------------------------


def test_a_registry_without_the_explicit_call_does_not_have_the_tool():
    """Importing backend.tools_project_insight (already done at module
    load, above) must not register anything anywhere."""
    without = ToolRegistry()
    register_reference_tools(without)

    assert "projects.overview" not in {d.name for d in without.list_definitions()}
    with pytest.raises(ToolNotFoundError):
        without.get("projects.overview")


def test_the_tool_appears_only_after_the_explicit_registration_call():
    after = ToolRegistry()
    register_reference_tools(after)
    register_v03e_proof2_tools(after)

    assert "projects.overview" in {d.name for d in after.list_definitions()}
