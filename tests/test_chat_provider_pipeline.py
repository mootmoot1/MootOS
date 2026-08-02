"""Tests for provider-backed chat atomicity, errors, and retry safety."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.memory import DATABASE_PATH, init_db
from backend.model_router import (
    ModelProviderError,
    ModelResponse,
    OpenAIProvider,
    PROVIDER_MAX_RETRIES,
    PROVIDER_TIMEOUT_SECONDS,
)


class SuccessfulRouter:
    """Predictable provider that can inspect the pre-commit database state."""

    def __init__(self, text: str = "Atomic response") -> None:
        self.text = text
        self.messages = []
        self.message_count_during_generate = None

    def ensure_ready(self) -> None:
        return None

    def generate(self, messages, instructions) -> ModelResponse:
        self.messages = messages
        with sqlite3.connect(DATABASE_PATH) as connection:
            self.message_count_during_generate = connection.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0]
        return ModelResponse(
            text=self.text,
            provider="fake",
            model="fake-model",
        )


class FailingRouter:
    """Provider that fails with text that must never reach the browser."""

    def ensure_ready(self) -> None:
        return None

    def generate(self, messages, instructions) -> ModelResponse:
        raise ModelProviderError(
            "raw provider failure containing private upstream details"
        )


@pytest.fixture
def clean_db():
    """Create a clean database before each test."""
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _table_count(table: str) -> int:
    with sqlite3.connect(DATABASE_PATH) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_new_chat_provider_failure_writes_nothing_and_hides_raw_error(
    clean_db,
    monkeypatch,
):
    monkeypatch.setattr("backend.main.get_model_router", lambda: FailingRouter())
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Do not orphan me"})

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "MootOS could not get a model response. Your message was not saved."
    )
    assert "private upstream" not in response.text
    assert _table_count("conversations") == 0
    assert _table_count("messages") == 0


def test_existing_chat_provider_failure_leaves_history_unchanged(
    clean_db,
    monkeypatch,
):
    client = TestClient(app)
    conversation = client.post(
        "/conversations",
        json={"project": "MootOS", "title": "Existing"},
    ).json()["data"]
    monkeypatch.setattr("backend.main.get_model_router", lambda: FailingRouter())

    response = client.post(
        "/chat",
        json={
            "message": "This should not be stored",
            "conversation_id": conversation["id"],
        },
    )

    assert response.status_code == 502
    stored = client.get(f"/conversations/{conversation['id']}").json()["data"]
    assert stored["messages"] == []
    assert _table_count("conversations") == 1
    assert _table_count("messages") == 0


def test_successful_chat_calls_provider_before_atomic_pair_commit(
    clean_db,
    monkeypatch,
):
    router = SuccessfulRouter(text="Both messages commit together")
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={"message": "Commit this pair", "project": "MootOS"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert router.message_count_during_generate == 0
    assert router.messages[-1] == {"role": "user", "content": "Commit this pair"}
    assert _table_count("conversations") == 1
    assert _table_count("messages") == 2

    stored = client.get(f"/conversations/{data['conversation_id']}").json()["data"]
    assert [message["role"] for message in stored["messages"]] == [
        "user",
        "assistant",
    ]
    assert stored["messages"][1]["content"] == "Both messages commit together"


def test_new_chat_assistant_storage_failure_rolls_back_entire_pair(
    clean_db,
    monkeypatch,
):
    from backend import chat_pipeline

    router = SuccessfulRouter()
    original_insert_message = chat_pipeline._insert_message

    def fail_assistant(connection, message):
        if message["role"] == "assistant":
            raise RuntimeError("forced assistant storage failure")
        return original_insert_message(connection, message)

    monkeypatch.setattr("backend.main.get_model_router", lambda: router)
    monkeypatch.setattr("backend.chat_pipeline._insert_message", fail_assistant)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Rollback this pair"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "MootOS could not save the conversation turn. Please retry."
    )
    assert "forced assistant" not in response.text
    assert _table_count("conversations") == 0
    assert _table_count("messages") == 0


def test_existing_chat_assistant_storage_failure_keeps_old_history_only(
    clean_db,
    monkeypatch,
):
    from backend import chat_pipeline

    client = TestClient(app)
    conversation = client.post(
        "/conversations",
        json={"project": "MootOS", "title": "Existing"},
    ).json()["data"]
    router = SuccessfulRouter()
    original_insert_message = chat_pipeline._insert_message

    def fail_assistant(connection, message):
        if message["role"] == "assistant":
            raise RuntimeError("forced assistant storage failure")
        return original_insert_message(connection, message)

    monkeypatch.setattr("backend.main.get_model_router", lambda: router)
    monkeypatch.setattr("backend.chat_pipeline._insert_message", fail_assistant)

    response = client.post(
        "/chat",
        json={
            "message": "Do not leave half a turn",
            "conversation_id": conversation["id"],
        },
    )

    assert response.status_code == 503
    stored = client.get(f"/conversations/{conversation['id']}").json()["data"]
    assert stored["messages"] == []
    assert _table_count("conversations") == 1
    assert _table_count("messages") == 0


def test_chat_preparation_storage_failure_is_sanitized_and_writes_nothing(
    clean_db,
    monkeypatch,
):
    def fail_database_connection(*args, **kwargs):
        raise RuntimeError("raw database path and preparation details")

    monkeypatch.setattr("backend.main.get_model_router", lambda: SuccessfulRouter())
    monkeypatch.setattr(
        "backend.chat_pipeline.database_connection",
        fail_database_connection,
    )
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Preparation must fail cleanly"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "MootOS could not save the conversation turn. Please retry."
    )
    assert "raw database" not in response.text
    assert _table_count("conversations") == 0
    assert _table_count("messages") == 0


def test_chat_connection_failure_after_provider_is_sanitized_and_writes_nothing(
    clean_db,
    monkeypatch,
):
    def fail_connect(*args, **kwargs):
        raise RuntimeError("raw database connection details")

    monkeypatch.setattr("backend.main.get_model_router", lambda: SuccessfulRouter())
    monkeypatch.setattr("backend.chat_pipeline.connect", fail_connect)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Commit must fail cleanly"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "MootOS could not save the conversation turn. Please retry."
    )
    assert "raw database" not in response.text
    assert _table_count("conversations") == 0
    assert _table_count("messages") == 0


def test_openai_provider_uses_bounded_timeout_and_zero_automatic_retries(
    monkeypatch,
):
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            return type("Response", (), {"output_text": "bounded response"})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("backend.model_router.OpenAI", FakeOpenAI)

    response = OpenAIProvider().generate(
        messages=[{"role": "user", "content": "Hello"}],
        instructions="Test",
    )

    assert response.text == "bounded response"
    assert captured["timeout"] == PROVIDER_TIMEOUT_SECONDS == 45.0
    assert captured["max_retries"] == PROVIDER_MAX_RETRIES == 0


def test_frontend_distinguishes_failed_send_from_saved_turn_refresh_error():
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    send_source = source.split("async function sendMessage(message) {", 1)[1].split(
        "async function checkHealth()",
        1,
    )[0]

    request_failure = send_source.split("  } catch (error) {", 1)[1].split(
        "  }\n\n  try {",
        1,
    )[0]
    assert "typingRow.remove();\n    userRow.remove();" in request_failure
    assert "elements.messageInput.value = cleanMessage;" in request_failure
    assert "localStorage.setItem" not in request_failure
    assert "return;" in request_failure

    refresh_failure = send_source.rsplit("    } catch (error) {", 1)[1].split(
        "    }\n  } finally",
        1,
    )[0]
    assert "Message was saved" in refresh_failure
    assert "userRow.remove();" not in refresh_failure
    assert "elements.messageInput.value = cleanMessage;" not in refresh_failure
