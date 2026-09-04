"""Migration/readiness and privacy tests for the V0.2A Tool System schema."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.db import DatabaseReadinessError, check_database_readiness, database_connection
from backend.memory import DATABASE_PATH, init_db
from backend.migrations import LATEST_SCHEMA_VERSION, get_schema_version, run_migrations
from backend.tool_operations import create_pending_operation
from backend.tool_types import ToolExecutionContext
from backend.tool_executor import execute_tool


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def test_schema_five_adds_tool_identity_and_operations_table(clean_db):
    assert get_schema_version() == LATEST_SCHEMA_VERSION == 7
    with database_connection() as connection:
        run_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"tool_name", "tool_version"} <= run_columns
    assert "tool_operations" in tables


def test_upgraded_v01_database_reaches_new_schema_without_losing_data(tmp_path: Path):
    """Simulate a real V0.1 (schema 4) database and confirm the V0.2A migration
    upgrades it cleanly while preserving existing rows."""
    database_path = tmp_path / "v01-upgrade.db"
    assert run_migrations(database_path) == 7

    with sqlite3.connect(database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version >= 5")
        connection.execute("DROP TABLE tool_operations")
        connection.execute(
            """
            INSERT INTO tasks (id, title, project, status, due_at, created_at, updated_at, completed_at, cancelled_at)
            VALUES ('existing-task', 'Pre-existing V0.1 task', NULL, 'open', NULL, ?, ?, NULL, NULL)
            """,
            (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()

    assert run_migrations(database_path) == 7

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        task = connection.execute(
            "SELECT title FROM tasks WHERE id = 'existing-task'"
        ).fetchone()
        tool_operations_exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_operations'"
        ).fetchone()
    assert task["title"] == "Pre-existing V0.1 task"
    assert tool_operations_exists is not None


def test_repeated_initialization_is_safe(tmp_path: Path):
    database_path = tmp_path / "repeat-init.db"
    assert run_migrations(database_path) == LATEST_SCHEMA_VERSION
    assert run_migrations(database_path) == LATEST_SCHEMA_VERSION
    assert run_migrations(database_path) == LATEST_SCHEMA_VERSION


def test_ready_endpoint_validates_new_schema_version(clean_db):
    check_database_readiness(LATEST_SCHEMA_VERSION)  # does not raise

    with pytest.raises(DatabaseReadinessError):
        check_database_readiness(LATEST_SCHEMA_VERSION - 1)

    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_tool_operations_table_rejects_unsupported_status(clean_db):
    with pytest.raises(sqlite3.IntegrityError):
        with database_connection() as connection:
            connection.execute(
                """
                INSERT INTO tool_operations (
                    id, tool_name, tool_version, status, arguments_json,
                    conversation_id, project, created_at, updated_at
                ) VALUES ('bad', 'tasks.create', '1', 'not-a-real-status', '{}',
                    NULL, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )


# --- Privacy: Tool Runs and Approval Operations never leak sensitive content ----


def test_tool_run_rows_never_store_arguments_or_secrets(clean_db):
    from backend.memory import create_memory

    create_memory(content="secret detail: the vault code is 4821")
    execute_tool(
        tool_name="memory.search",
        arguments={"query": "vault"},
        context=ToolExecutionContext(),
    )

    with database_connection() as connection:
        row = connection.execute("SELECT * FROM runs WHERE run_type = 'tool'").fetchone()
    serialized = str(dict(row))
    assert "vault" not in serialized
    assert "4821" not in serialized
    assert "arguments" not in serialized.lower().replace("data_exposure", "")


def test_tool_operation_never_echoes_api_credential_style_values(clean_db):
    operation = create_pending_operation(
        tool_name="tasks.create",
        tool_version="1",
        arguments={"title": "Call Mike"},
        conversation_id=None,
        project=None,
    )
    response = TestClient(app).get(f"/tool-operations/{operation['id']}")
    body = response.text
    assert "OPENAI_API_KEY" not in body
    assert "sk-" not in body


def test_activity_runs_endpoint_never_leaks_tool_arguments(clean_db):
    from backend.memory import create_memory

    create_memory(content="Client SSN is not actually stored here, just a test string")
    execute_tool(
        tool_name="memory.search",
        arguments={"query": "Client"},
        context=ToolExecutionContext(),
    )

    client = TestClient(app)
    response = client.get("/activity/runs")
    body = response.text
    assert "SSN" not in body
    assert "Client SSN" not in body
