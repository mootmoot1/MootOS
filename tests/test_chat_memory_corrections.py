"""Integration tests for explicit chat-driven long-term-memory corrections."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.memory import DATABASE_PATH, init_db
from backend.model_router import ModelResponse


class FakeRouter:
    def __init__(self, text: str = "Corrected memory recalled.") -> None:
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


def test_explicit_correction_supersedes_old_memory(clean_db, client, monkeypatch):
    def unexpected_router():
        raise AssertionError("Explicit memory correction must not call the model")

    monkeypatch.setattr("backend.main.get_model_router", unexpected_router)

    saved = client.post(
        "/chat",
        json={"message": "Remember that my test phrase is purple engine 47."},
    )
    assert saved.status_code == 200

    corrected = client.post(
        "/chat",
        json={
            "message": "Actually, my test phrase is blue turbo 92. Remember that instead."
        },
    )
    assert corrected.status_code == 200
    data = corrected.json()["data"]
    assert "Updated Global long-term memory" in data["assistant_message"]["content"]

    active = client.get("/memories").json()["data"]
    assert len(active) == 1
    assert active[0]["content"] == "my test phrase is blue turbo 92"
    assert active[0]["replaces_memory_id"] is not None

    history = client.get(f"/memories/{active[0]['id']}/history")
    assert history.status_code == 200
    versions = history.json()["data"]
    assert [version["content"] for version in versions] == [
        "my test phrase is purple engine 47.",
        "my test phrase is blue turbo 92",
    ]
    assert versions[0]["status"] == "superseded"
    assert versions[1]["status"] == "active"


def test_new_chat_context_uses_replacement_not_superseded_memory(
    clean_db,
    client,
    monkeypatch,
):
    client.post(
        "/chat",
        json={"message": "Remember that my test phrase is purple engine 47."},
    )
    client.post(
        "/chat",
        json={
            "message": "Actually, my test phrase is blue turbo 92. Remember that instead."
        },
    )

    fake_router = FakeRouter()
    monkeypatch.setattr("backend.main.get_model_router", lambda: fake_router)

    recalled = client.post(
        "/chat",
        json={"message": "What is my test phrase?"},
    )

    assert recalled.status_code == 200
    assert "my test phrase is blue turbo 92" in fake_router.instructions
    assert "purple engine 47" not in fake_router.instructions


def test_correction_without_target_does_not_create_new_memory(
    clean_db,
    client,
    monkeypatch,
):
    def unexpected_router():
        raise AssertionError("Explicit memory correction must not call the model")

    monkeypatch.setattr("backend.main.get_model_router", unexpected_router)

    response = client.post(
        "/chat",
        json={
            "message": "Actually, my test phrase is blue turbo 92. Remember that instead."
        },
    )

    assert response.status_code == 200
    assert "could not identify an existing memory" in response.json()["data"]["assistant_message"]["content"]
    assert client.get("/memories").json()["data"] == []
