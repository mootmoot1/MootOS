"""Tests for the V0.3D migration-safety gate
(scripts/gates/migration_safety.py).

Uses `evaluate_migration_diff` (a pure function over two source-text
strings) for nearly everything -- fast, and tests the actual
classification logic (historical vs. machinery vs. additive) directly
without needing real commits. A small number of tests exercise the
git-backed `evaluate()` against this repository's real history.
"""

from scripts.gates.migration_safety import evaluate_migration_diff


BASE_SOURCE = '''
"""Migrations module."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable


def _ensure_migration_table(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER)")


def _migration_001_initial_schema(connection):
    connection.execute("CREATE TABLE projects (id TEXT)")


def _migration_002_memory_lifecycle(connection):
    connection.execute("ALTER TABLE memories ADD COLUMN status TEXT")


MIGRATIONS = (
    Migration(1, "initial_schema", _migration_001_initial_schema),
    Migration(2, "memory_lifecycle", _migration_002_memory_lifecycle),
)
'''


# --- 7. Historical migration modification fails ------------------------------


def test_modifying_a_historical_migration_function_body_fails():
    head = BASE_SOURCE.replace(
        'connection.execute("CREATE TABLE projects (id TEXT)")',
        'connection.execute("CREATE TABLE projects (id TEXT, sneaky_column TEXT)")',
    )
    result = evaluate_migration_diff(BASE_SOURCE, head)

    assert result.passed is False
    assert any("_migration_001_initial_schema" in v and "modified" in v for v in result.violations)
    assert "FAIL" in result.summary()


def test_removing_a_historical_migration_function_fails():
    head = BASE_SOURCE.replace(
        'def _migration_002_memory_lifecycle(connection):\n'
        '    connection.execute("ALTER TABLE memories ADD COLUMN status TEXT")\n\n\n',
        "",
    ).replace('Migration(2, "memory_lifecycle", _migration_002_memory_lifecycle),\n', "")
    result = evaluate_migration_diff(BASE_SOURCE, head)

    assert result.passed is False
    assert any("_migration_002_memory_lifecycle" in v for v in result.violations)


def test_modifying_migration_machinery_fails():
    head = BASE_SOURCE.replace(
        'connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER)")',
        'connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER, note TEXT)")',
    )
    result = evaluate_migration_diff(BASE_SOURCE, head)

    assert result.passed is False
    assert any("_ensure_migration_table" in v and "modified" in v for v in result.violations)


def test_renaming_a_historical_entry_in_the_migrations_tuple_without_touching_the_function_fails():
    """A sneaky remap: swap which function a historical version number
    points to, or rename its label, without editing either function body
    -- the tuple-entry check catches what the function-body diff alone
    would miss."""
    head = BASE_SOURCE.replace(
        'Migration(1, "initial_schema", _migration_001_initial_schema),',
        'Migration(1, "renamed_somehow", _migration_001_initial_schema),',
    )
    result = evaluate_migration_diff(BASE_SOURCE, head)

    assert result.passed is False
    assert any("historical version 1" in v for v in result.violations)


def test_reordering_or_removing_a_historical_tuple_entry_fails():
    head = BASE_SOURCE.replace(
        'MIGRATIONS = (\n    Migration(1, "initial_schema", _migration_001_initial_schema),\n'
        '    Migration(2, "memory_lifecycle", _migration_002_memory_lifecycle),\n)',
        'MIGRATIONS = (\n    Migration(1, "initial_schema", _migration_001_initial_schema),\n)',
    )
    result = evaluate_migration_diff(BASE_SOURCE, head)

    assert result.passed is False
    assert any("historical version 2" in v for v in result.violations)


# --- 8. A new additive migration is distinguished from history modification -


def test_a_brand_new_additive_migration_passes_but_is_flagged_for_review():
    head = (
        BASE_SOURCE
        + '''

def _migration_003_tasks(connection):
    connection.execute("CREATE TABLE tasks (id TEXT)")
'''
    ).replace(
        'MIGRATIONS = (\n    Migration(1, "initial_schema", _migration_001_initial_schema),\n'
        '    Migration(2, "memory_lifecycle", _migration_002_memory_lifecycle),\n)',
        'MIGRATIONS = (\n    Migration(1, "initial_schema", _migration_001_initial_schema),\n'
        '    Migration(2, "memory_lifecycle", _migration_002_memory_lifecycle),\n'
        '    Migration(3, "tasks", _migration_003_tasks),\n)',
    )

    result = evaluate_migration_diff(BASE_SOURCE, head)

    assert result.passed is True, result.summary()
    assert len(result.additive_notices) == 1
    assert "_migration_003_tasks" in result.additive_notices[0]
    assert "version 3" in result.additive_notices[0]
    assert "NOTICE" in result.summary()
    assert "requires human migration review" in result.summary()


def test_identical_source_passes_with_no_notices():
    result = evaluate_migration_diff(BASE_SOURCE, BASE_SOURCE)
    assert result.passed is True
    assert result.additive_notices == ()


def test_adding_an_unrelated_helper_function_is_not_flagged_as_additive_or_a_violation():
    head = BASE_SOURCE + '''

def _some_new_helper(connection):
    pass
'''
    result = evaluate_migration_diff(BASE_SOURCE, head)
    assert result.passed is True
    assert result.additive_notices == ()


# --- Adversarial: attempts to evade the migration-safety gate ---------------


def test_reusing_a_historical_version_number_for_a_new_function_fails():
    """A devious attempt to "add" a migration that actually collides with
    (and could shadow at runtime) a historical version number."""
    sneaky_function = (
        "def _migration_002_sneaky_replacement(connection):\n"
        '    connection.execute("DROP TABLE memories")\n\n\n'
        "MIGRATIONS = ("
    )
    head = BASE_SOURCE.replace("MIGRATIONS = (", sneaky_function)
    result = evaluate_migration_diff(BASE_SOURCE, head)

    assert result.passed is False
    assert any("reuses historical migration version 2" in v for v in result.violations)


def test_editing_a_historical_function_while_also_adding_an_additive_one_still_fails_overall():
    """A violation elsewhere in the same diff must not be masked by an
    otherwise-legitimate additive migration."""
    head = BASE_SOURCE.replace(
        'connection.execute("CREATE TABLE projects (id TEXT)")',
        'connection.execute("CREATE TABLE projects (id TEXT, sneaky TEXT)")',
    ) + '''

def _migration_003_tasks(connection):
    connection.execute("CREATE TABLE tasks (id TEXT)")
'''
    result = evaluate_migration_diff(BASE_SOURCE, head)

    assert result.passed is False
    assert any("_migration_001_initial_schema" in v for v in result.violations)


def test_malformed_migrations_tuple_in_the_proposed_version_fails_closed():
    head = BASE_SOURCE.replace(
        'MIGRATIONS = (\n    Migration(1, "initial_schema", _migration_001_initial_schema),\n'
        '    Migration(2, "memory_lifecycle", _migration_002_memory_lifecycle),\n)',
        "MIGRATIONS = compute_migrations_dynamically()",
    )
    result = evaluate_migration_diff(BASE_SOURCE, head)

    assert result.passed is False
    assert any("fails closed" in v for v in result.violations)


def test_syntactically_invalid_proposed_source_fails_closed():
    result = evaluate_migration_diff(BASE_SOURCE, "def broken(:\n    this is not python")
    assert result.passed is False
    assert any("could not be parsed" in v for v in result.violations)


# --- git-backed integration (real repository history) ------------------------


def test_evaluate_against_this_repositorys_real_migrations_file_passes_when_unchanged():
    from scripts.gates.migration_safety import evaluate

    result = evaluate("HEAD", "HEAD")
    assert result.passed is True
