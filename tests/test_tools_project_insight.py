"""Tests for V0.3E proof #2: the projects.overview tool and its backing
cross-resource rollup, backend.project_insight.summarize_projects.

Mirrors tests/test_tools_task_summary.py's style -- exercised through the
real centralized executor, against a real temporary database. See
docs/CAPABILITY_BUILD_PIPELINE.md §12.
"""

import pytest

from backend.conversation import add_message, create_conversation
from backend.db import DATABASE_PATH, database_connection
from backend.memory import archive_memory, correct_memory, create_memory, create_project, init_db
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
    create_memory(content="kept note", project="Alpha")
    dropped = create_memory(content="dropped note", project="Alpha")

    assert _by_name(summarize_projects())["Alpha"]["active_memories"] == 2
    archive_memory(dropped["id"])
    assert _by_name(summarize_projects())["Alpha"]["active_memories"] == 1


def test_superseded_memories_are_excluded_from_active_counts(clean_db):
    """Memory correction produces `superseded` rows. Only `archived` was
    covered before, leaving half the non-active lifecycle unverified."""
    create_project(name="Alpha")
    original = create_memory(content="the old fact", project="Alpha")

    assert _by_name(summarize_projects())["Alpha"]["active_memories"] == 1
    correct_memory(original["id"], "the corrected fact")
    # Correction supersedes the original and creates a replacement, so the
    # active count stays 1 rather than becoming 0 or 2.
    assert _by_name(summarize_projects())["Alpha"]["active_memories"] == 1


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
    create_conversation(title="no project chat")

    result = summarize_projects()

    assert result["unassigned"]["active_memories"] == 1
    assert result["unassigned"]["total_tasks"] == 1
    assert result["unassigned"]["conversations"] == 1
    assert result["unassigned"]["last_activity_at"] is not None
    assert _by_name(result)["Alpha"]["active_memories"] == 0


def test_differently_cased_project_rows_accumulate_instead_of_overwriting(clean_db):
    """Regression (advisory review, correctness role): the merge ASSIGNED
    rather than accumulated, so two GROUP BY rows differing only in case
    collapsed to one key and the last row silently evicted the other's
    counts -- three memories were reported as one.

    Every current write path canonicalizes the project name, so mixed-case
    rows require a legacy or directly-inserted row; these are inserted
    directly precisely because the module claims to handle the case."""
    create_project(name="Woodshop")
    create_memory(content="canonical spelling", project="Woodshop")
    with database_connection() as connection:
        connection.execute(
            "INSERT INTO memories (id, content, project, created_at, status, updated_at)"
            " VALUES ('m-lower', 'lowercase spelling', 'woodshop',"
            " '2026-01-01T00:00:00+00:00', 'active', '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO tasks (id, title, project, status, created_at, updated_at)"
            " VALUES ('t-upper', 'uppercase spelling', 'WOODSHOP', 'open',"
            " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO tasks (id, title, project, status, created_at, updated_at)"
            " VALUES ('t-canon', 'canonical', 'Woodshop', 'open',"
            " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )

    entry = _by_name(summarize_projects())["Woodshop"]

    assert entry["active_memories"] == 2, "differently-cased memory rows must sum, not overwrite"
    assert entry["total_tasks"] == 2, "differently-cased task rows must sum, not overwrite"
    assert entry["open_tasks"] == 2


def test_rows_naming_a_project_that_does_not_exist_land_in_unassigned(clean_db):
    """Regression (advisory review, correctness role): a project value with
    no matching row in `projects` was dropped from BOTH the per-project
    entries and the unassigned bucket, so it vanished entirely -- exactly
    the undercount the unassigned bucket exists to prevent."""
    create_project(name="Alpha")
    with database_connection() as connection:
        connection.execute(
            "INSERT INTO tasks (id, title, project, status, created_at, updated_at)"
            " VALUES ('t-ghost', 'orphaned', 'DeletedProject', 'open',"
            " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )

    result = summarize_projects()

    assert "DeletedProject" not in _by_name(result)
    assert result["unassigned"]["total_tasks"] == 1
    assert result["unassigned"]["open_tasks"] == 1


def test_no_projects_at_all_returns_a_clean_empty_result(clean_db):
    with database_connection() as connection:
        connection.execute("DELETE FROM projects")

    result = summarize_projects()

    assert result["projects"] == []
    assert result["count"] == 0
    assert result["unassigned"]["active_memories"] == 0
    assert result["truncated"] is False


def test_count_always_equals_the_number_of_entries_returned(clean_db):
    result = summarize_projects()
    assert result["count"] == len(result["projects"])


def test_each_entry_has_exactly_the_documented_key_set(clean_db):
    """Locks the output contract so a field added to the internal entry
    shape cannot silently change what callers receive."""
    entry = summarize_projects()["projects"][0]
    assert set(entry) == {
        "name",
        "active_memories",
        "open_tasks",
        "total_tasks",
        "conversations",
        "last_activity_at",
    }


def test_results_are_capped_and_truncation_is_reported_honestly(clean_db, monkeypatch):
    """Raised in advisory review (security role): every sibling
    list-shaped tool bounds its output, and this one did not. The cap must
    never silently return a partial answer -- `truncated` says so."""
    monkeypatch.setattr("backend.project_insight.MAX_PROJECT_ENTRIES", 3)

    for index in range(5):
        create_project(name=f"Bulk{index}")

    result = summarize_projects()

    assert len(result["projects"]) == 3
    assert result["count"] == 3
    assert result["truncated"] is True


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


@pytest.mark.parametrize("winner", ["memory", "task", "conversation"])
def test_any_of_the_three_resources_can_be_the_last_activity_winner(clean_db, winner):
    """The original test always made the conversation newest, so it could
    not detect a wrong column or a reversed comparison. Here each resource
    takes a turn at being the newest, with controlled timestamps far
    enough apart that ordering is unambiguous."""
    create_project(name="Alpha")
    create_memory(content="m", project="Alpha")
    create_task(title="t", project="Alpha")
    create_conversation(project="Alpha", title="c")

    future = "2099-01-01T00:00:00+00:00"
    table = {"memory": "memories", "task": "tasks", "conversation": "conversations"}[winner]
    with database_connection() as connection:
        connection.execute(f"UPDATE {table} SET updated_at = ? WHERE project = 'Alpha'", (future,))

    assert _by_name(summarize_projects())["Alpha"]["last_activity_at"] == future


def test_completing_a_task_moves_last_activity_forward(clean_db):
    """Regression (advisory review, correctness role): last_activity_at
    previously used MAX(created_at), so finishing a Task -- a real change
    to the project -- did not move the 'last touched' timestamp at all."""
    create_project(name="Alpha")
    task = create_task(title="finish me", project="Alpha")
    before = _by_name(summarize_projects())["Alpha"]["last_activity_at"]

    complete_task(task["id"])

    assert _by_name(summarize_projects())["Alpha"]["last_activity_at"] > before


def test_archiving_the_newest_memory_never_moves_last_activity_backward(clean_db):
    """Regression (advisory review, correctness role): the timestamp was
    computed over active memories only, so archiving the newest one made
    the project look like it had been touched LESS recently than before."""
    create_project(name="Alpha")
    create_memory(content="older", project="Alpha")
    newest = create_memory(content="newest", project="Alpha")
    before = _by_name(summarize_projects())["Alpha"]["last_activity_at"]

    archive_memory(newest["id"])

    assert _by_name(summarize_projects())["Alpha"]["last_activity_at"] >= before


def test_nonexistent_project_fails_closed(clean_db):
    with pytest.raises(ValueError):
        summarize_projects(project="Does Not Exist")


# --- projects.overview through the real executor -----------------------------


def test_tool_returns_the_rollup(clean_db):
    seeded = len(summarize_projects()["projects"])
    create_project(name="Alpha")
    create_memory(content="alpha note", project="Alpha")

    result = _run("projects.overview", {})

    assert _by_name(result.data)["Alpha"]["active_memories"] == 1
    # Exact, not ">= 1": the value is knowable, and an exact assertion
    # catches a scoping bug that a lower bound cannot.
    assert result.data["count"] == seeded + 1


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
    create_memory(content="alpha note", project="Alpha")
    create_task(title="alpha task", project="Alpha")
    before = _run("projects.overview", {}).data

    with pytest.raises(ToolExecutionError):
        _run("projects.overview", {"project": hostile})

    # Compare the FULL rollup before and after: a hostile string that
    # deleted rows rather than the whole table would slip past a mere
    # "the project still exists" check.
    assert _run("projects.overview", {}).data == before


def test_empty_project_string_is_rejected_by_schema_not_treated_as_unscoped(clean_db):
    """minLength=1 must stop "" before it reaches the executor, where it
    would otherwise be a falsy value that could be mistaken for 'no
    project supplied'."""
    with pytest.raises(ToolValidationError):
        _run("projects.overview", {"project": ""})


def test_overlong_project_string_is_rejected_by_schema(clean_db):
    with pytest.raises(ToolValidationError):
        _run("projects.overview", {"project": "x" * 101})


def test_length_boundaries_are_one_off_correct(clean_db):
    """The rejection side was tested but not the acceptance side, so a
    maxLength off by one would not have been caught. Both boundary values
    must reach the executor (and there fail as a nonexistent project,
    which is a different error than schema rejection)."""
    create_project(name="A" * 100)

    assert _run("projects.overview", {"project": "A" * 100}).data["count"] == 1
    with pytest.raises(ToolExecutionError):
        _run("projects.overview", {"project": "z"})  # minLength 1 accepted, just unknown


def test_explicit_null_project_means_unscoped_and_is_documented_behavior(clean_db):
    """backend/tool_validation.py treats an explicit None as absent, so
    {"project": null} is accepted and means 'all projects'. That is the
    same falsy-value hazard the empty-string test names, so it is pinned
    here rather than left to chance."""
    create_project(name="Alpha")

    scoped = _run("projects.overview", {"project": "Alpha"}).data
    nulled = _run("projects.overview", {"project": None}).data

    assert scoped["count"] == 1
    assert nulled["count"] == len(summarize_projects()["projects"])
    assert "unassigned" in nulled


def test_non_string_project_argument_is_rejected(clean_db):
    with pytest.raises(ToolValidationError):
        _run("projects.overview", {"project": 5})


# --- 6/7. Metadata correctness and no hidden write path ----------------------


def test_declared_metadata_matches_the_definition_actually_in_the_registry():
    """Reads the definition back OUT of a real registry rather than
    trusting the module constant, and checks every declared field."""
    registry = ToolRegistry()
    register_v03e_proof2_tools(registry)
    registered = registry.get("projects.overview")

    assert registered is PROJECTS_OVERVIEW
    assert registered.name == "projects.overview"
    assert registered.version == "1"
    assert registered.risk == RISK_READ_ONLY
    assert registered.data_exposure == DATA_EXPOSURE_LOCAL
    assert registered.idempotent is True
    assert registered.capabilities == ("projects.insight",)
    assert registered.depends_on == ("projects.list",)
    assert "read-only" in registered.side_effects.lower()
    assert registered.limitations


def test_repeated_calls_are_idempotent_and_write_no_domain_row(clean_db):
    """Declared idempotent=True must hold in practice. Comparing outputs
    to each other cannot see a stray write, so this also snapshots row
    counts across the calls.

    `runs` is deliberately excluded from the unchanged-tables assertion
    and checked separately: every tool call is Run-logged for audit by
    `execute_tool` (docs/TOOL_SYSTEM.md §8), so one new Run per call is
    the correct, intended behavior -- what a read-only tool must not do
    is touch any *domain* table or create an approval operation.
    """
    create_project(name="Alpha")
    create_memory(content="alpha note", project="Alpha")
    create_task(title="alpha task", project="Alpha")

    domain_tables = ("projects", "memories", "tasks", "conversations", "messages", "tool_operations")

    def snapshot():
        with database_connection() as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                for table in domain_tables
            }
            counts["_runs"] = connection.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
            return counts

    before = snapshot()
    first = _run("projects.overview", {}).data
    second = _run("projects.overview", {}).data
    third = _run("projects.overview", {}).data
    after = snapshot()

    assert first == second == third
    for table in domain_tables:
        assert after[table] == before[table], f"read-only tool wrote to {table}"
    # Exactly one audit Run per call -- no more, no fewer.
    assert after["_runs"] == before["_runs"] + 3


def test_the_module_contains_no_write_statement_at_all():
    """Declared read_only, so no SQL write verb may appear in executable
    code in either module.

    Docstrings and comments are stripped before scanning: they legitimately
    discuss writes (the module explains why it performs none), and scanning
    them made the earlier version of this test both noisy and brittle.
    """
    import ast
    import io
    import re
    import tokenize
    from pathlib import Path

    # Word-boundary matched, so the column names `updated_at` and
    # `created_at` are not mistaken for the UPDATE and CREATE verbs.
    verbs = (
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE",
        "ATTACH", "VACUUM", "PRAGMA", "COMMIT",
    )
    repository_root = Path(__file__).resolve().parent.parent

    for relative in ("backend/project_insight.py", "backend/tools_project_insight.py"):
        source = (repository_root / relative).read_text(encoding="utf-8")

        # Drop comments via tokenize, then drop docstrings via the AST.
        without_comments = "".join(
            "" if token.type == tokenize.COMMENT else token.string
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
        )
        tree = ast.parse(source)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docstrings.add(doc)
        executable = without_comments
        for doc in docstrings:
            executable = executable.replace(doc, "")

        upper = executable.upper()
        for verb in verbs:
            assert not re.search(rf"\b{verb}\b", upper), (
                f"{relative} contains a write/DDL verb: {verb}"
            )


def test_output_never_contains_memory_task_or_conversation_content(clean_db):
    """The capability promises counts and timestamps only. Distinctive
    content is planted in every readable text column, then the entire
    serialized output is searched for it."""
    import json

    create_project(name="Alpha", description="SUPERSECRETPROJECTDESCRIPTION")
    memory = create_memory(
        content="SUPERSECRETMEMORYCONTENT", project="Alpha", memory_type="SUPERSECRETMEMORYTYPE"
    )
    create_task(title="SUPERSECRETTASKTITLE", project="Alpha")
    conversation = create_conversation(project="Alpha", title="SUPERSECRETCHATTITLE")
    add_message(conversation["id"], role="user", content="SUPERSECRETMESSAGEBODY")

    serialized = json.dumps(_run("projects.overview", {}).data)

    for secret in (
        "SUPERSECRETPROJECTDESCRIPTION",
        "SUPERSECRETMEMORYCONTENT",
        "SUPERSECRETMEMORYTYPE",
        "SUPERSECRETTASKTITLE",
        "SUPERSECRETCHATTITLE",
        "SUPERSECRETMESSAGEBODY",
    ):
        assert secret not in serialized, f"{secret} leaked into the tool output"
    assert memory["id"] not in serialized


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
