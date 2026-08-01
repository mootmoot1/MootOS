"""Tests for the memory system."""

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


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


def test_create_memory(clean_db, client):
    response = client.post(
        "/memories",
        json={"content": "Test memory", "project": "MootOS", "memory_type": "task"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["content"] == "Test memory"
    assert data["data"]["project"] == "MootOS"
    assert data["data"]["memory_type"] == "task"
    assert data["data"]["id"]
    assert data["data"]["created_at"]
    assert data["data"]["status"] == "active"
    assert data["data"]["updated_at"] == data["data"]["created_at"]
    assert data["data"]["replaces_memory_id"] is None
    assert data["data"]["superseded_by_id"] is None


def test_list_memories(clean_db, client):
    client.post("/memories", json={"content": "Memory 1", "project": "Studio"})
    client.post("/memories", json={"content": "Memory 2", "project": "Cars"})
    response = client.get("/memories")
    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


def test_get_memory(clean_db, client):
    created = client.post("/memories", json={"content": "Test memory"}).json()["data"]
    response = client.get(f"/memories/{created['id']}")
    assert response.status_code == 200
    assert response.json()["data"]["content"] == "Test memory"


def test_delete_memory(clean_db, client):
    created = client.post("/memories", json={"content": "Delete me"}).json()["data"]
    response = client.delete(f"/memories/{created['id']}")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "deleted"
    assert client.get(f"/memories/{created['id']}").status_code == 404


def test_validation_empty_content(clean_db, client):
    assert client.post("/memories", json={"content": ""}).status_code == 422


def test_validation_content_too_long(clean_db, client):
    assert client.post("/memories", json={"content": "x" * 10001}).status_code == 422


def test_get_nonexistent_memory(clean_db, client):
    assert client.get("/memories/nonexistent").status_code == 404


def test_delete_nonexistent_memory(clean_db, client):
    assert client.delete("/memories/nonexistent").status_code == 404


def test_memory_persists_after_database_reconnect(clean_db, client):
    created = client.post("/memories", json={"content": "Persistent memory"}).json()["data"]
    for _ in range(2):
        with sqlite3.connect(DATABASE_PATH) as connection:
            row = connection.execute(
                "SELECT content FROM memories WHERE id = ?",
                (created["id"],),
            ).fetchone()
        assert row is not None
        assert row[0] == "Persistent memory"


def test_default_projects_exist(clean_db, client):
    """Test that the five initial projects are created automatically."""
    response = client.get("/projects")
    assert response.status_code == 200
    names = {project["name"] for project in response.json()["data"]}
    assert names == {"MootOS", "Studio", "Social Media", "Cars", "Personal"}


def test_create_project(clean_db, client):
    """Test creating a future project."""
    response = client.post(
        "/projects",
        json={"name": "Home", "description": "Home repairs and maintenance."},
    )
    assert response.status_code == 201
    assert response.json()["data"]["name"] == "Home"


def test_duplicate_project_is_rejected(clean_db, client):
    """Test that project names are unique regardless of capitalization."""
    response = client.post("/projects", json={"name": "studio"})
    assert response.status_code == 409


def test_memory_requires_existing_project(clean_db, client):
    """Test that a memory cannot reference an unknown project."""
    response = client.post(
        "/memories",
        json={"content": "Unknown project memory", "project": "Does Not Exist"},
    )
    assert response.status_code == 422


def test_filter_memories_by_project(clean_db, client):
    """Test retrieving only memories assigned to one project."""
    client.post("/memories", json={"content": "Fix API", "project": "MootOS"})
    client.post("/memories", json={"content": "Brake check", "project": "Cars"})

    response = client.get("/memories", params={"project": "MootOS"})
    assert response.status_code == 200
    memories = response.json()["data"]
    assert len(memories) == 1
    assert memories[0]["content"] == "Fix API"
    assert memories[0]["project"] == "MootOS"


def test_filter_unknown_project_returns_404(clean_db, client):
    """Test filtering by an unknown project."""
    response = client.get("/memories", params={"project": "Does Not Exist"})
    assert response.status_code == 404


def test_correct_memory_preserves_history_and_replaces_active_version(clean_db, client):
    created = client.post(
        "/memories",
        json={
            "content": "My car is silver",
            "project": "Cars",
            "memory_type": "explicit_chat",
        },
    ).json()["data"]

    response = client.post(
        f"/memories/{created['id']}/corrections",
        json={"content": "My car is black"},
    )

    assert response.status_code == 201
    result = response.json()["data"]
    superseded = result["superseded"]
    replacement = result["replacement"]

    assert superseded["id"] == created["id"]
    assert superseded["status"] == "superseded"
    assert superseded["superseded_by_id"] == replacement["id"]
    assert replacement["status"] == "active"
    assert replacement["replaces_memory_id"] == created["id"]
    assert replacement["content"] == "My car is black"
    assert replacement["project"] == "Cars"
    assert replacement["memory_type"] == "explicit_chat"

    active = client.get("/memories", params={"project": "Cars"}).json()["data"]
    assert [memory["id"] for memory in active] == [replacement["id"]]

    old_version = client.get(f"/memories/{created['id']}").json()["data"]
    assert old_version["content"] == "My car is silver"
    assert old_version["status"] == "superseded"

    history = client.get(f"/memories/{replacement['id']}/history")
    assert history.status_code == 200
    assert [version["id"] for version in history.json()["data"]] == [
        created["id"],
        replacement["id"],
    ]


def test_second_correction_extends_one_ordered_history_chain(clean_db, client):
    original = client.post(
        "/memories",
        json={"content": "Version one"},
    ).json()["data"]
    second = client.post(
        f"/memories/{original['id']}/corrections",
        json={"content": "Version two"},
    ).json()["data"]["replacement"]
    third = client.post(
        f"/memories/{second['id']}/corrections",
        json={"content": "Version three"},
    ).json()["data"]["replacement"]

    history = client.get(f"/memories/{second['id']}/history").json()["data"]

    assert [version["content"] for version in history] == [
        "Version one",
        "Version two",
        "Version three",
    ]
    assert history[0]["status"] == "superseded"
    assert history[1]["status"] == "superseded"
    assert history[2]["status"] == "active"
    assert history[2]["id"] == third["id"]


def test_superseded_memory_is_excluded_from_model_context(clean_db, client):
    from backend.memory import list_context_memories

    original = client.post(
        "/memories",
        json={"content": "Old address", "project": "Personal"},
    ).json()["data"]
    replacement = client.post(
        f"/memories/{original['id']}/corrections",
        json={"content": "New address"},
    ).json()["data"]["replacement"]

    context = list_context_memories(project="Personal")

    assert [memory["id"] for memory in context] == [replacement["id"]]
    assert context[0]["content"] == "New address"


def test_correction_rejects_missing_inactive_and_unchanged_memory(clean_db, client):
    missing = client.post(
        "/memories/missing/corrections",
        json={"content": "Replacement"},
    )
    assert missing.status_code == 404

    original = client.post(
        "/memories",
        json={"content": "Current value"},
    ).json()["data"]
    unchanged = client.post(
        f"/memories/{original['id']}/corrections",
        json={"content": "Current value"},
    )
    assert unchanged.status_code == 409

    replacement = client.post(
        f"/memories/{original['id']}/corrections",
        json={"content": "New value"},
    )
    assert replacement.status_code == 201

    inactive = client.post(
        f"/memories/{original['id']}/corrections",
        json={"content": "Another value"},
    )
    assert inactive.status_code == 409


def test_correction_validates_content_boundaries(clean_db, client):
    created = client.post(
        "/memories",
        json={"content": "Current value"},
    ).json()["data"]

    assert client.post(
        f"/memories/{created['id']}/corrections",
        json={"content": "   "},
    ).status_code == 422
    assert client.post(
        f"/memories/{created['id']}/corrections",
        json={"content": "x" * 10001},
    ).status_code == 422


def test_failed_correction_rolls_back_new_version(clean_db, client):
    created = client.post(
        "/memories",
        json={"content": "Keep active"},
    ).json()["data"]

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_supersede
            BEFORE UPDATE OF status ON memories
            WHEN NEW.status = 'superseded'
            BEGIN
                SELECT RAISE(ABORT, 'forced supersede failure');
            END
            """
        )

    failing_client = TestClient(app, raise_server_exceptions=False)
    response = failing_client.post(
        f"/memories/{created['id']}/corrections",
        json={"content": "Must roll back"},
    )

    assert response.status_code == 500
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            "SELECT id, content, status FROM memories ORDER BY created_at"
        ).fetchall()
    assert rows == [(created["id"], "Keep active", "active")]


def test_hard_delete_cannot_break_correction_history(clean_db, client):
    original = client.post(
        "/memories",
        json={"content": "Original value"},
    ).json()["data"]
    replacement = client.post(
        f"/memories/{original['id']}/corrections",
        json={"content": "Corrected value"},
    ).json()["data"]["replacement"]

    old_delete = client.delete(f"/memories/{original['id']}")
    new_delete = client.delete(f"/memories/{replacement['id']}")

    assert old_delete.status_code == 409
    assert new_delete.status_code == 409
    history = client.get(f"/memories/{replacement['id']}/history").json()["data"]
    assert [item["content"] for item in history] == [
        "Original value",
        "Corrected value",
    ]


def test_competing_corrections_leave_one_active_replacement(clean_db, client):
    from concurrent.futures import ThreadPoolExecutor

    from backend.memory import MemoryNotActiveError, correct_memory

    original = client.post(
        "/memories",
        json={"content": "Original concurrent value"},
    ).json()["data"]

    def attempt(content):
        try:
            return correct_memory(original["id"], content)
        except MemoryNotActiveError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                attempt,
                ["First competing correction", "Second competing correction"],
            )
        )

    successful = [result for result in results if result is not None]
    assert len(successful) == 1

    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) FROM memories GROUP BY status"
        ).fetchall()
    assert dict(rows) == {"active": 1, "superseded": 1}
