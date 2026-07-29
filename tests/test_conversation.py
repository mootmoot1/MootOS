"""Tests for the MootOS conversation engine and model-router boundary."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.memory import DATABASE_PATH, init_db
from backend.model_router import ModelConfigurationError, ModelResponse


class FakeRouter:
    """Predictable model router used without making external API calls."""

    def __init__(self, text: str = "MootOS test response") -> None:
        self.text = text
        self.messages = []
        self.instructions = ""

    def ensure_ready(self) -> None:
        return None

    def generate(self, messages, instructions) -> ModelResponse:
        self.messages = messages
        self.instructions = instructions
        return ModelResponse(
            text=self.text,
            provider="fake",
            model="fake-model",
        )


class UnconfiguredRouter:
    """Router used to verify clear missing-configuration behavior."""

    def ensure_ready(self) -> None:
        raise ModelConfigurationError("Test provider is not configured")


@pytest.fixture
def clean_db():
    """Create a clean database before each test."""
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


def test_create_and_get_conversation(clean_db, client):
    response = client.post(
        "/conversations",
        json={"project": "MootOS", "title": "Build session"},
    )
    assert response.status_code == 201
    conversation = response.json()["data"]
    assert conversation["project"] == "MootOS"
    assert conversation["title"] == "Build session"

    fetched = client.get(f"/conversations/{conversation['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["messages"] == []


def test_list_conversations_by_project(clean_db, client):
    client.post("/conversations", json={"project": "Studio"})
    client.post("/conversations", json={"project": "Cars"})

    response = client.get("/conversations", params={"project": "Studio"})
    assert response.status_code == 200
    conversations = response.json()["data"]
    assert len(conversations) == 1
    assert conversations[0]["project"] == "Studio"


def test_chat_creates_conversation_and_persists_messages(
    clean_db,
    client,
    monkeypatch,
):
    fake_router = FakeRouter(text="We are live.")
    monkeypatch.setattr("backend.main.get_model_router", lambda: fake_router)

    response = client.post(
        "/chat",
        json={"message": "Are you working?", "project": "MootOS"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["assistant_message"]["content"] == "We are live."
    assert data["provider"] == "fake"

    conversation = client.get(
        f"/conversations/{data['conversation_id']}"
    ).json()["data"]
    assert [message["role"] for message in conversation["messages"]] == [
        "user",
        "assistant",
    ]
    assert conversation["messages"][0]["content"] == "Are you working?"


def test_chat_continues_existing_conversation(clean_db, client, monkeypatch):
    fake_router = FakeRouter()
    monkeypatch.setattr("backend.main.get_model_router", lambda: fake_router)

    first = client.post("/chat", json={"message": "First message"}).json()["data"]
    second = client.post(
        "/chat",
        json={
            "message": "Follow-up message",
            "conversation_id": first["conversation_id"],
        },
    )
    assert second.status_code == 200
    assert len(fake_router.messages) == 3
    assert fake_router.messages[-1]["content"] == "Follow-up message"

    conversation = client.get(
        f"/conversations/{first['conversation_id']}"
    ).json()["data"]
    assert len(conversation["messages"]) == 4


def test_project_memory_is_injected_into_model_context(
    clean_db,
    client,
    monkeypatch,
):
    fake_router = FakeRouter()
    monkeypatch.setattr("backend.main.get_model_router", lambda: fake_router)
    client.post(
        "/memories",
        json={
            "content": "Studio block sessions cost $50 per hour.",
            "project": "Studio",
            "memory_type": "project",
        },
    )

    response = client.post(
        "/chat",
        json={"message": "What is the rate?", "project": "Studio"},
    )
    assert response.status_code == 200
    assert "Studio block sessions cost $50 per hour." in fake_router.instructions


def test_missing_model_configuration_returns_503_without_saving_chat(
    clean_db,
    client,
    monkeypatch,
):
    monkeypatch.setattr("backend.main.get_model_router", lambda: UnconfiguredRouter())

    response = client.post("/chat", json={"message": "Hello"})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
    assert client.get("/conversations").json()["data"] == []


def test_conversation_messages_survive_database_reconnect(
    clean_db,
    client,
    monkeypatch,
):
    monkeypatch.setattr("backend.main.get_model_router", lambda: FakeRouter())
    data = client.post("/chat", json={"message": "Persist this"}).json()["data"]

    with sqlite3.connect(DATABASE_PATH) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            (data["conversation_id"],),
        ).fetchone()[0]
    assert count == 2
