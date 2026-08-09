"""Tests for structured model execution records."""

import sqlite3
from pathlib import Path

import pytest

from backend.db import DATABASE_PATH, database_connection
from backend.memory import init_db
from backend.migrations import LATEST_SCHEMA_VERSION, get_schema_version, run_migrations
from backend.runs import (
    DATA_EXPOSURE_LOCAL,
    RunAlreadyFinishedError,
    RunNotFoundError,
    RunValidationError,
    finish_model_run_failure,
    finish_model_run_success,
    get_run,
    list_runs,
    start_model_run,
)


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def test_schema_migrates_to_model_runs(clean_db):
    assert get_schema_version() == LATEST_SCHEMA_VERSION == 5
    with database_connection() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }
    assert {
        "id", "run_type", "status", "conversation_id", "user_message_id",
        "assistant_message_id", "provider", "model", "started_at", "finished_at",
        "duration_ms", "error_class", "input_tokens", "output_tokens", "cost_usd",
        "data_exposure",
    } <= columns


def test_real_schema_two_file_upgrades_without_losing_existing_rows(tmp_path: Path):
    database_path = tmp_path / "schema-two.db"
    assert run_migrations(database_path) == LATEST_SCHEMA_VERSION == 5
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DELETE FROM schema_migrations WHERE version >= 3")
        connection.execute("DROP TABLE runs")
        connection.execute("DROP TABLE tasks")
        connection.execute(
            "INSERT INTO memories (id, content, project, memory_type, created_at, status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("existing-memory", "keep me", None, "test", "2026-01-01T00:00:00+00:00", "active", "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()
    finally:
        connection.close()

    assert run_migrations(database_path) == LATEST_SCHEMA_VERSION == 5
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute("SELECT content FROM memories WHERE id = 'existing-memory'").fetchone()
        assert row[0] == "keep me"
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
    finally:
        connection.close()


def test_successful_model_run_links_messages_without_storing_prompt_text(clean_db):
    run = start_model_run(conversation_id="conversation-123", provider="openai", model="gpt-test")
    completed = finish_model_run_success(
        run["id"], conversation_id="conversation-123", user_message_id="user-message-123",
        assistant_message_id="assistant-message-123", provider="openai", model="gpt-test",
        input_tokens=12, output_tokens=8, cost_usd=0.01,
    )
    assert completed["status"] == "succeeded"
    assert completed["conversation_id"] == "conversation-123"
    assert completed["user_message_id"] == "user-message-123"
    assert completed["assistant_message_id"] == "assistant-message-123"
    assert completed["input_tokens"] == 12
    assert completed["output_tokens"] == 8
    assert completed["cost_usd"] == 0.01
    assert completed["error_class"] is None
    assert completed["duration_ms"] >= 0
    assert completed["finished_at"] >= completed["started_at"]
    with database_connection() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
    for forbidden in {"prompt", "response", "content", "body", "message", "exception", "trace"}:
        assert forbidden not in columns


def test_success_finalization_preserves_existing_metrics_when_new_values_omitted(clean_db):
    run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    with database_connection() as connection:
        connection.execute("UPDATE runs SET input_tokens = 5, output_tokens = 7, cost_usd = 0.25 WHERE id = ?", (run["id"],))
    completed = finish_model_run_success(run["id"])
    assert completed["input_tokens"] == 5
    assert completed["output_tokens"] == 7
    assert completed["cost_usd"] == 0.25


def test_failed_model_run_records_error_class_not_private_message(clean_db):
    run = start_model_run(conversation_id="not-yet-persisted-conversation", provider="openai", model="gpt-test")
    error = RuntimeError("private provider detail that must not be stored")
    failed = finish_model_run_failure(run["id"], error)
    assert failed["status"] == "failed"
    assert failed["error_class"] == "RuntimeError"
    assert "private provider detail" not in repr(failed)
    assert failed["finished_at"] is not None
    assert failed["duration_ms"] >= 0


def test_terminal_run_cannot_be_finalized_failure_after_success(clean_db):
    run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    finish_model_run_success(run["id"])
    with pytest.raises(RunAlreadyFinishedError):
        finish_model_run_failure(run["id"], RuntimeError("later failure"))


def test_terminal_run_cannot_be_finalized_success_twice(clean_db):
    run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    finish_model_run_success(run["id"])
    with pytest.raises(RunAlreadyFinishedError):
        finish_model_run_success(run["id"])


def test_finishing_unknown_run_raises_not_found(clean_db):
    with pytest.raises(RunNotFoundError):
        finish_model_run_success("missing-run")
    with pytest.raises(RunNotFoundError):
        finish_model_run_failure("missing-run", RuntimeError("ignored"))


def test_run_constraints_reject_invalid_status_and_type(clean_db):
    with pytest.raises(sqlite3.IntegrityError):
        with database_connection() as connection:
            connection.execute("INSERT INTO runs (id, run_type, status, started_at) VALUES ('bad-status', 'model', 'made-up', '2026-01-01T00:00:00+00:00')")
    with pytest.raises(sqlite3.IntegrityError):
        with database_connection() as connection:
            connection.execute("INSERT INTO runs (id, run_type, status, started_at) VALUES ('bad-type', 'other', 'started', '2026-01-01T00:00:00+00:00')")


def test_invalid_data_exposure_is_rejected_before_insert(clean_db):
    with pytest.raises(RunValidationError):
        start_model_run(conversation_id=None, provider="openai", model="gpt-test", data_exposure="private prompt text")
    assert list_runs() == []


def test_data_exposure_default_and_explicit_override(clean_db):
    default_run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    local_run = start_model_run(conversation_id=None, provider="local", model="local-test", data_exposure=DATA_EXPOSURE_LOCAL)
    assert default_run["data_exposure"] == "model_provider"
    assert local_run["data_exposure"] == "local"


def test_negative_metrics_are_rejected(clean_db):
    run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    with pytest.raises(RunValidationError):
        finish_model_run_success(run["id"], input_tokens=-1)
    with pytest.raises(RunValidationError):
        finish_model_run_success(run["id"], output_tokens=-1)
    with pytest.raises(RunValidationError):
        finish_model_run_success(run["id"], cost_usd=-0.01)
    assert get_run(run["id"])["status"] == "started"


def test_list_runs_can_filter_by_conversation_without_private_content(clean_db):
    first = start_model_run(conversation_id="conversation-a", provider="openai", model="model-a")
    second = start_model_run(conversation_id="conversation-b", provider="openai", model="model-b")
    results = list_runs(conversation_id="conversation-a")
    assert [item["id"] for item in results] == [first["id"]]
    assert second["id"] not in {item["id"] for item in results}
    assert get_run(first["id"])["data_exposure"] == "model_provider"


def test_list_runs_clamps_limit_between_one_and_five_hundred(clean_db):
    first = start_model_run(conversation_id=None, provider="openai", model="one")
    start_model_run(conversation_id=None, provider="openai", model="two")
    assert len(list_runs(limit=0)) == 1
    assert len(list_runs(limit=9999)) == 2
    assert get_run(first["id"]) is not None
