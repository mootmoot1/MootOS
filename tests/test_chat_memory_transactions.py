"""Tests for atomic explicit-memory chat storage."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.memory import DATABASE_PATH, init_db


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


def test_new_chat_memory_write_failure_rolls_back_entire_turn(
    clean_db,
    monkeypatch,
):
    def fail_memory_write(*args, **kwargs):
        raise RuntimeError("forced memory write failure")

    monkeypatch.setattr("backend.chat_memory._insert_memory", fail_memory_write)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/chat",
        json={
            "message": "Remember that my favorite tea is jasmine.",
            "project": "Personal",
        },
    )

    assert response.status_code == 500
    assert _table_count("conversations") == 0
    assert _table_count("messages") == 0
    assert _table_count("memories") == 0


def test_existing_chat_memory_write_failure_leaves_no_unmatched_message(
    clean_db,
    monkeypatch,
):
    client = TestClient(app)
    conversation = client.post(
        "/conversations",
        json={"project": "Personal", "title": "Existing chat"},
    ).json()["data"]

    def fail_memory_write(*args, **kwargs):
        raise RuntimeError("forced memory write failure")

    monkeypatch.setattr("backend.chat_memory._insert_memory", fail_memory_write)
    failing_client = TestClient(app, raise_server_exceptions=False)

    response = failing_client.post(
        "/chat",
        json={
            "message": "Remember that my favorite tea is jasmine.",
            "conversation_id": conversation["id"],
        },
    )

    assert response.status_code == 500
    saved_conversation = client.get(
        f"/conversations/{conversation['id']}"
    ).json()["data"]
    assert saved_conversation["messages"] == []
    assert _table_count("memories") == 0


def test_oversized_memory_in_existing_chat_writes_nothing(clean_db):
    client = TestClient(app)
    conversation = client.post(
        "/conversations",
        json={"project": "Personal", "title": "Existing chat"},
    ).json()["data"]

    response = client.post(
        "/chat",
        json={
            "message": "Remember that " + ("x" * 10_001),
            "conversation_id": conversation["id"],
        },
    )

    assert response.status_code == 422
    saved_conversation = client.get(
        f"/conversations/{conversation['id']}"
    ).json()["data"]
    assert saved_conversation["messages"] == []
    assert _table_count("memories") == 0


def test_project_filtered_memory_list_excludes_global_memories(clean_db):
    client = TestClient(app)
    saved = client.post(
        "/chat",
        json={"message": "Remember that I prefer plain explanations."},
    )

    assert saved.status_code == 200
    assert len(client.get("/memories").json()["data"]) == 1
    assert (
        client.get("/memories", params={"project": "MootOS"}).json()["data"]
        == []
    )
