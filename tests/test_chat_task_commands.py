"""Integration tests for explicit chat-driven Task creation."""

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.db import DATABASE_PATH
from backend.memory import init_db
from backend.tasks import list_tasks


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


@pytest.fixture
def client():
    return TestClient(app)


class FakeRouter:
    provider_name = "fake"
    providers = {"fake": type("Provider", (), {"model": "fake-model"})()}

    def __init__(self, text: str = "Normal model chat.") -> None:
        self.text = text

    def ensure_ready(self):
        return None

    def generate(self, messages, instructions):
        from backend.model_router import ModelResponse

        return ModelResponse(
            text=self.text,
            provider="fake",
            model="fake-model",
        )


def test_explicit_task_command_creates_task_without_model(clean_db, client, monkeypatch):
    def unexpected_router():
        raise AssertionError("Explicit task creation must not call the model")

    monkeypatch.setattr("backend.main.get_model_router", unexpected_router)

    response = client.post(
        "/chat",
        json={"message": "Create a task to call Mike"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "mootos"
    assert data["model"] == "task-command-v1"
    assert data["task"]["title"] == "call Mike"
    assert data["task"]["project"] is None
    assert data["task"]["status"] == "open"
    assert data["assistant_message"]["content"] == "Created Global task: call Mike"
    assert [task["title"] for task in list_tasks(status="open")] == ["call Mike"]


def test_project_chat_task_inherits_canonical_project(clean_db, client, monkeypatch):
    monkeypatch.setattr(
        "backend.main.get_model_router",
        lambda: (_ for _ in ()).throw(AssertionError("model should not run")),
    )

    response = client.post(
        "/chat",
        json={"message": "Add task: export stems", "project": "studio"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["project"] == "Studio"
    assert data["task"]["project"] == "Studio"
    assert data["assistant_message"]["content"] == "Created Studio task: export stems"
    assert [task["title"] for task in list_tasks(status="open", project="Studio")] == [
        "export stems"
    ]


def test_task_command_can_continue_existing_conversation(clean_db, client, monkeypatch):
    monkeypatch.setattr(
        "backend.main.get_model_router",
        lambda: (_ for _ in ()).throw(AssertionError("model should not run")),
    )

    first = client.post(
        "/chat",
        json={"message": "Create a task to inspect the O2 wiring"},
    )
    conversation_id = first.json()["data"]["conversation_id"]

    second = client.post(
        "/chat",
        json={
            "message": "Add a task to order the connector",
            "conversation_id": conversation_id,
        },
    )

    assert second.status_code == 200
    assert second.json()["data"]["conversation_id"] == conversation_id
    assert {task["title"] for task in list_tasks(status="open")} == {
        "inspect the O2 wiring",
        "order the connector",
    }


def test_task_command_rejects_project_mismatch_without_creating_task(
    clean_db,
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        "backend.main.get_model_router",
        lambda: (_ for _ in ()).throw(AssertionError("model should not run")),
    )

    first = client.post(
        "/chat",
        json={"message": "Create a task to test memory", "project": "MootOS"},
    )
    conversation_id = first.json()["data"]["conversation_id"]

    mismatch = client.post(
        "/chat",
        json={
            "message": "Add task: export vocals",
            "conversation_id": conversation_id,
            "project": "Studio",
        },
    )

    assert mismatch.status_code == 409
    assert [task["title"] for task in list_tasks(status="open")] == ["test memory"]


def test_task_title_validation_rolls_back_entire_turn(clean_db, client, monkeypatch):
    monkeypatch.setattr(
        "backend.main.get_model_router",
        lambda: (_ for _ in ()).throw(AssertionError("model should not run")),
    )

    response = client.post(
        "/chat",
        json={"message": "Create a task to " + ("x" * 501)},
    )

    assert response.status_code == 422
    assert list_tasks(status="open") == []
    assert client.get("/conversations").json()["data"] == []


def test_unknown_project_rolls_back_without_task_or_conversation(clean_db, client):
    response = client.post(
        "/chat",
        json={"message": "Create a task to ship the mix", "project": "Missing"},
    )

    assert response.status_code == 422
    assert list_tasks(status="open") == []
    assert client.get("/conversations").json()["data"] == []


def test_missing_conversation_id_does_not_create_task(clean_db, client):
    response = client.post(
        "/chat",
        json={
            "message": "Create a task to call Mike",
            "conversation_id": "missing-conversation",
        },
    )

    assert response.status_code == 404
    assert list_tasks(status="open") == []


def test_memory_command_still_uses_memory_path(clean_db, client, monkeypatch):
    def unexpected_router():
        raise AssertionError("Explicit memory save must not call the model")

    monkeypatch.setattr("backend.main.get_model_router", unexpected_router)

    response = client.post(
        "/chat",
        json={"message": "Remember that the interface is black"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["model"] == "memory-command-v1"
    memories = client.get("/memories").json()["data"]
    assert [memory["content"] for memory in memories] == ["the interface is black"]
    assert list_tasks(status="open") == []


@pytest.mark.parametrize(
    "message",
    [
        "Create a task system for tracking clients",
        "Create a task manager",
        "Add task list to the sidebar",
    ],
)
def test_taskish_ordinary_chat_reaches_model(clean_db, client, monkeypatch, message):
    monkeypatch.setattr("backend.main.get_model_router", lambda: FakeRouter())

    response = client.post("/chat", json={"message": message})

    assert response.status_code == 200
    assert response.json()["data"]["model"] == "fake-model"
    assert list_tasks(status="open") == []


def test_remind_me_is_not_silently_treated_as_task_creation(clean_db, client, monkeypatch):
    monkeypatch.setattr(
        "backend.main.get_model_router",
        lambda: FakeRouter("Reminder delivery is not enabled yet."),
    )

    response = client.post(
        "/chat",
        json={"message": "Remind me to call Mike tomorrow at 3"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["model"] == "fake-model"
    assert list_tasks(status="open") == []
