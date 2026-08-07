"""Tests for structured model execution records."""

import sqlite3

import pytest

from backend.db import DATABASE_PATH, database_connection
from backend.memory import init_db
from backend.migrations import LATEST_SCHEMA_VERSION, get_schema_version
from backend.runs import (
    RunAlreadyFinishedError,
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
    assert get_schema_version() == LATEST_SCHEMA_VERSION == 3

    with database_connection() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }

    assert {
        "id",
        "run_type",
        "status",
        "conversation_id",
        "user_message_id",
        "assistant_message_id",
        "provider",
        "model",
        "started_at",
        "finished_at",
        "duration_ms",
        "error_class",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "data_exposure",
    } <= columns


def test_successful_model_run_links_messages_without_storing_prompt_text(clean_db):
    run = start_model_run(
        conversation_id="conversation-123",
        provider="openai",
        model="gpt-test",
    )

    completed = finish_model_run_success(
        run["id"],
        conversation_id="conversation-123",
        user_message_id="user-message-123",
        assistant_message_id="assistant-message-123",
        provider="openai",
        model="gpt-test",
        input_tokens=12,
        output_tokens=8,
    )

    assert completed["status"] == "succeeded"
    assert completed["conversation_id"] == "conversation-123"
    assert completed["user_message_id"] == "user-message-123"
    assert completed["assistant_message_id"] == "assistant-message-123"
    assert completed["provider"] == "openai"
    assert completed["model"] == "gpt-test"
    assert completed["input_tokens"] == 12
    assert completed["output_tokens"] == 8
    assert completed["error_class"] is None
    assert completed["duration_ms"] >= 0

    with database_connection() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }
    assert "prompt" not in columns
    assert "response" not in columns
    assert "content" not in columns


def test_failed_model_run_records_error_class_not_private_message(clean_db):
    run = start_model_run(
        conversation_id="not-yet-persisted-conversation",
        provider="openai",
        model="gpt-test",
    )
    error = RuntimeError("private provider detail that must not be stored")

    failed = finish_model_run_failure(run["id"], error)

    assert failed["status"] == "failed"
    assert failed["error_class"] == "RuntimeError"
    assert "private provider detail" not in repr(failed)
    assert failed["finished_at"] is not None
    assert failed["duration_ms"] >= 0


def test_terminal_run_cannot_be_finalized_twice(clean_db):
    run = start_model_run(
        conversation_id=None,
        provider="openai",
        model="gpt-test",
    )
    finish_model_run_success(run["id"])

    with pytest.raises(RunAlreadyFinishedError):
        finish_model_run_failure(run["id"], RuntimeError("later failure"))


def test_run_constraints_reject_invalid_status(clean_db):
    with pytest.raises(sqlite3.IntegrityError):
        with database_connection() as connection:
            connection.execute(
                """
                INSERT INTO runs (id, run_type, status, started_at)
                VALUES ('bad-run', 'model', 'made-up-status', '2026-01-01T00:00:00+00:00')
                """
            )


def test_list_runs_can_filter_by_conversation_without_private_content(clean_db):
    first = start_model_run(
        conversation_id="conversation-a",
        provider="openai",
        model="model-a",
    )
    second = start_model_run(
        conversation_id="conversation-b",
        provider="openai",
        model="model-b",
    )

    results = list_runs(conversation_id="conversation-a")

    assert [item["id"] for item in results] == [first["id"]]
    assert second["id"] not in {item["id"] for item in results}
    assert get_run(first["id"])["data_exposure"] == "model_provider"
