"""Integration tests for model Run logging in the normal chat path."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.memory import DATABASE_PATH, init_db
from backend.model_router import ModelProviderError, ModelResponse
from backend.runs import list_runs


class CountingSuccessRouter:
    """Deterministic model router that records whether generation ran."""

    def __init__(self, text: str = "Logged response") -> None:
        self.calls = 0
        self.text = text
        self.provider_name = "fake"
        self.providers = {
            "fake": type("Provider", (), {"model": "fake-model"})(),
        }

    def ensure_ready(self) -> None:
        return None

    def generate(self, messages, instructions) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            text=self.text,
            provider="fake",
            model="fake-model",
        )


class CountingFailRouter(CountingSuccessRouter):
    """Deterministic router whose provider request fails."""

    def generate(self, messages, instructions) -> ModelResponse:
        self.calls += 1
        raise ModelProviderError("private provider details must not persist")


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _table_count(table: str) -> int:
    with sqlite3.connect(DATABASE_PATH) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_run_start_failure_prevents_provider_call_and_chat_persistence(
    clean_db,
    monkeypatch,
):
    router = CountingSuccessRouter()

    def fail_run_start(**kwargs):
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr("backend.main.get_model_router", lambda: router)
    monkeypatch.setattr("backend.main.start_model_run", fail_run_start)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Do not run unlogged"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "MootOS could not record model execution. Please retry."
    )
    assert "private database" not in response.text
    assert router.calls == 0
    assert _table_count("conversations") == 0
    assert _table_count("messages") == 0
    assert list_runs() == []


def test_provider_failure_marks_run_failed_without_saving_chat_turn(
    clean_db,
    monkeypatch,
):
    router = CountingFailRouter()
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Provider should fail"})

    assert response.status_code == 502
    assert router.calls == 1
    assert _table_count("conversations") == 0
    assert _table_count("messages") == 0

    runs = list_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "failed"
    assert run["error_class"] == "ModelProviderError"
    assert run["provider"] == "fake"
    assert run["model"] == "fake-model"
    assert run["user_message_id"] is None
    assert run["assistant_message_id"] is None
    assert "private provider" not in repr(run)


def test_successful_chat_marks_run_succeeded_and_links_saved_messages(
    clean_db,
    monkeypatch,
):
    router = CountingSuccessRouter(text="Persist and link me")
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={"message": "Create a truthful run", "project": "MootOS"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    runs = list_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "succeeded"
    assert run["conversation_id"] == data["conversation_id"]
    assert run["user_message_id"] == data["user_message"]["id"]
    assert run["assistant_message_id"] == data["assistant_message"]["id"]
    assert run["provider"] == "fake"
    assert run["model"] == "fake-model"
    assert run["error_class"] is None
    assert _table_count("messages") == 2


def test_chat_storage_failure_marks_model_run_failed(
    clean_db,
    monkeypatch,
):
    from backend import chat_pipeline

    router = CountingSuccessRouter()
    original_insert_message = chat_pipeline._insert_message

    def fail_assistant(connection, message):
        if message["role"] == "assistant":
            raise RuntimeError("private forced assistant storage failure")
        return original_insert_message(connection, message)

    monkeypatch.setattr("backend.main.get_model_router", lambda: router)
    monkeypatch.setattr("backend.chat_pipeline._insert_message", fail_assistant)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Fail after model success"})

    assert response.status_code == 503
    assert router.calls == 1
    assert _table_count("conversations") == 0
    assert _table_count("messages") == 0

    runs = list_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "failed"
    assert run["error_class"] == "ChatStorageError"
    assert run["user_message_id"] is None
    assert run["assistant_message_id"] is None
    assert "private forced" not in repr(run)


def test_run_success_finalization_failure_does_not_duplicate_saved_chat(
    clean_db,
    monkeypatch,
):
    router = CountingSuccessRouter()

    def fail_finalization(*args, **kwargs):
        raise sqlite3.OperationalError("private finalization failure")

    monkeypatch.setattr("backend.main.get_model_router", lambda: router)
    monkeypatch.setattr("backend.main.finish_model_run_success", fail_finalization)
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Save chat once"})

    assert response.status_code == 200
    assert router.calls == 1
    assert _table_count("conversations") == 1
    assert _table_count("messages") == 2

    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "started"
    assert runs[0]["finished_at"] is None
