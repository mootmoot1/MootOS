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


def _block_model(monkeypatch):
    def unexpected_router():
        raise AssertionError("Explicit memory correction must not call the model")

    monkeypatch.setattr("backend.main.get_model_router", unexpected_router)


def test_explicit_correction_supersedes_old_memory(clean_db, client, monkeypatch):
    _block_model(monkeypatch)

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
    _block_model(monkeypatch)

    response = client.post(
        "/chat",
        json={
            "message": "Actually, my test phrase is blue turbo 92. Remember that instead."
        },
    )

    assert response.status_code == 200
    assert "could not identify one active memory" in response.json()["data"]["assistant_message"]["content"]
    assert client.get("/memories").json()["data"] == []


def test_ambiguous_correction_preserves_all_existing_memories(
    clean_db,
    client,
    monkeypatch,
):
    _block_model(monkeypatch)

    client.post(
        "/chat",
        json={"message": "Remember that my test phrase is purple engine 47."},
    )
    client.post(
        "/chat",
        json={"message": "Remember that my test phrase is purple motor 88."},
    )

    response = client.post(
        "/chat",
        json={
            "message": "Actually, my test phrase is blue turbo 92. Remember that instead."
        },
    )

    assert response.status_code == 200
    detail = response.json()["data"]["assistant_message"]["content"]
    assert "More than one saved memory could match" in detail
    active = client.get("/memories").json()["data"]
    assert len(active) == 2
    assert {memory["content"] for memory in active} == {
        "my test phrase is purple engine 47.",
        "my test phrase is purple motor 88.",
    }


def test_project_scoped_correction_stays_in_project(clean_db, client, monkeypatch):
    _block_model(monkeypatch)

    saved = client.post(
        "/chat",
        json={
            "message": "Remember that tire pressure is 32 PSI.",
            "project": "Cars",
        },
    )
    assert saved.status_code == 200

    corrected = client.post(
        "/chat",
        json={
            "message": "Actually, tire pressure is 35 PSI. Remember that instead.",
            "project": "Cars",
        },
    )
    assert corrected.status_code == 200
    assert "Updated Cars long-term memory" in corrected.json()["data"]["assistant_message"]["content"]

    active = client.get("/memories", params={"project": "Cars"}).json()["data"]
    assert len(active) == 1
    assert active[0]["content"] == "tire pressure is 35 PSI"
    assert active[0]["project"] == "Cars"

    history = client.get(f"/memories/{active[0]['id']}/history").json()["data"]
    assert [version["status"] for version in history] == ["superseded", "active"]
    assert all(version["project"] == "Cars" for version in history)


def test_project_chat_can_correct_unique_global_memory(clean_db, client, monkeypatch):
    _block_model(monkeypatch)

    client.post(
        "/chat",
        json={"message": "Remember that my test phrase is purple engine 47."},
    )

    corrected = client.post(
        "/chat",
        json={
            "message": "Actually, my test phrase is blue turbo 92. Remember that instead.",
            "project": "MootOS",
        },
    )

    assert corrected.status_code == 200
    assert "Updated Global long-term memory" in corrected.json()["data"]["assistant_message"]["content"]
    active = client.get("/memories").json()["data"]
    assert len(active) == 1
    assert active[0]["project"] is None
    assert active[0]["content"] == "my test phrase is blue turbo 92"


def test_same_content_correction_returns_clarification_without_write(
    clean_db,
    client,
    monkeypatch,
):
    _block_model(monkeypatch)

    client.post(
        "/chat",
        json={"message": "Remember that test phrase blue"},
    )
    before = client.get("/memories").json()["data"]
    assert len(before) == 1

    response = client.post(
        "/chat",
        json={"message": "Actually, test phrase blue. Remember that instead."},
    )

    assert response.status_code == 200
    assert "same as the current memory" in response.json()["data"]["assistant_message"]["content"]
    after = client.get("/memories").json()["data"]
    assert len(after) == 1
    assert after[0]["id"] == before[0]["id"]
    assert after[0]["replaces_memory_id"] is None
