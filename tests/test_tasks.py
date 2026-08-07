"""Tests for the MootOS task primitive."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.db import DATABASE_PATH, database_connection
from backend.memory import init_db
from backend.migrations import LATEST_SCHEMA_VERSION, get_schema_version, run_migrations
from backend.tasks import (
    TaskAlreadyFinishedError,
    TaskNotFoundError,
    cancel_task,
    complete_task,
    create_task,
    get_task,
    list_tasks,
)


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def test_schema_migrates_to_tasks(clean_db):
    assert get_schema_version() == LATEST_SCHEMA_VERSION == 4
    with database_connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
    assert {
        "id",
        "title",
        "project",
        "status",
        "due_at",
        "created_at",
        "updated_at",
        "completed_at",
        "cancelled_at",
    } <= columns


def test_schema_three_file_upgrades_to_tasks_without_losing_runs(tmp_path: Path):
    database_path = tmp_path / "schema-three.db"
    assert run_migrations(database_path) == 4
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DELETE FROM schema_migrations WHERE version = 4")
        connection.execute("DROP TABLE tasks")
        connection.execute(
            """
            INSERT INTO runs (
                id, run_type, status, provider, model, started_at, data_exposure
            ) VALUES (?, 'model', 'succeeded', 'openai', 'gpt-test', ?, 'model_provider')
            """,
            ("existing-run", "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()
    finally:
        connection.close()

    assert run_migrations(database_path) == 4
    connection = sqlite3.connect(database_path)
    try:
        run = connection.execute(
            "SELECT id FROM runs WHERE id = 'existing-run'"
        ).fetchone()
        tasks_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
    finally:
        connection.close()

    assert run[0] == "existing-run"
    assert tasks_table[0] == "tasks"


def test_create_global_task(clean_db):
    task = create_task("  Finish Task v0.1  ")
    assert task["title"] == "Finish Task v0.1"
    assert task["project"] is None
    assert task["status"] == "open"
    assert task["due_at"] is None
    assert task["completed_at"] is None
    assert task["cancelled_at"] is None
    assert get_task(task["id"])["id"] == task["id"]


def test_create_project_task_canonicalizes_project_casing(clean_db):
    task = create_task("Ship it", project="mootos")
    assert task["project"] == "MootOS"


def test_create_task_rejects_unknown_project(clean_db):
    with pytest.raises(ValueError, match="Project does not exist"):
        create_task("Nope", project="Missing")


def test_create_task_requires_nonempty_bounded_title(clean_db):
    with pytest.raises(ValueError, match="cannot be empty"):
        create_task("   ")
    with pytest.raises(ValueError, match="500"):
        create_task("x" * 501)


def test_due_at_requires_timezone_and_normalizes_to_utc(clean_db):
    with pytest.raises(ValueError, match="timezone"):
        create_task("Naive", due_at="2026-08-08T09:00:00")

    task = create_task("Aware", due_at="2026-08-08T09:00:00-04:00")
    assert task["due_at"] == "2026-08-08T13:00:00+00:00"


def test_due_at_accepts_z_suffix(clean_db):
    task = create_task("UTC", due_at="2026-08-08T13:00:00Z")
    assert task["due_at"] == "2026-08-08T13:00:00+00:00"


def test_complete_task_sets_terminal_metadata(clean_db):
    task = create_task("Complete me")
    completed = complete_task(task["id"])
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None
    assert completed["cancelled_at"] is None
    assert completed["updated_at"] >= task["updated_at"]


def test_cancel_task_sets_terminal_metadata(clean_db):
    task = create_task("Cancel me")
    cancelled = cancel_task(task["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_at"] is not None
    assert cancelled["completed_at"] is None


def test_terminal_task_cannot_transition_again(clean_db):
    task = create_task("One terminal state")
    complete_task(task["id"])
    with pytest.raises(TaskAlreadyFinishedError):
        cancel_task(task["id"])
    with pytest.raises(TaskAlreadyFinishedError):
        complete_task(task["id"])


def test_missing_task_transition_raises_not_found(clean_db):
    with pytest.raises(TaskNotFoundError):
        complete_task("missing-task")


def test_list_tasks_filters_status_and_project(clean_db):
    first = create_task("First", project="MootOS")
    second = create_task("Second", project="Studio")
    complete_task(second["id"])

    open_mootos = list_tasks(status="open", project="mootos")
    completed = list_tasks(status="completed")

    assert [item["id"] for item in open_mootos] == [first["id"]]
    assert [item["id"] for item in completed] == [second["id"]]


def test_list_tasks_orders_due_tasks_before_unscheduled(clean_db):
    unscheduled = create_task("No due")
    later = create_task("Later", due_at="2026-08-10T12:00:00+00:00")
    sooner = create_task("Sooner", due_at="2026-08-09T12:00:00+00:00")

    ids = [item["id"] for item in list_tasks(status="open")]
    assert ids.index(sooner["id"]) < ids.index(later["id"])
    assert ids.index(later["id"]) < ids.index(unscheduled["id"])


def test_list_tasks_clamps_limit(clean_db):
    for index in range(3):
        create_task(f"Task {index}")
    assert len(list_tasks(limit=1)) == 1
    assert len(list_tasks(limit=0)) == 1
    assert len(list_tasks(limit=9999)) == 3


def test_schema_rejects_invalid_task_status(clean_db):
    now = datetime.now(timezone.utc).isoformat()
    with pytest.raises(sqlite3.IntegrityError):
        with database_connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id, title, status, created_at, updated_at
                ) VALUES ('bad-status', 'Bad', 'running', ?, ?)
                """,
                (now, now),
            )


def test_schema_rejects_blank_task_title(clean_db):
    now = datetime.now(timezone.utc).isoformat()
    with pytest.raises(sqlite3.IntegrityError):
        with database_connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id, title, status, created_at, updated_at
                ) VALUES ('blank-title', '   ', 'open', ?, ?)
                """,
                (now, now),
            )
