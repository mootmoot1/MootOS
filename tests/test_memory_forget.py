"""Tests for recoverable memory forget and restore."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.memory import (
    DATABASE_PATH,
    MemoryArchiveConflictError,
    MemoryNotActiveError,
    MemoryRestoreConflictError,
    archive_memory,
    correct_memory,
    init_db,
    list_context_memories,
    restore_memory,
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


def test_archive_hides_memory_and_restore_returns_it(clean_db, client):
    created = client.post(
        "/memories",
        json={"content": "Temporary test fact", "project": "Personal"},
    ).json()["data"]

    archived = client.post(f"/memories/{created['id']}/archive")

    assert archived.status_code == 200
    assert archived.json()["data"]["status"] == "archived"
    assert client.get("/memories").json()["data"] == []
    archived_rows = client.get(
        "/memories", params={"status": "archived", "project": "Personal"}
    ).json()["data"]
    assert [item["id"] for item in archived_rows] == [created["id"]]
    assert list_context_memories(project="Personal") == []

    restored = client.post(f"/memories/{created['id']}/restore")

    assert restored.status_code == 200
    assert restored.json()["data"]["status"] == "active"
    assert client.get("/memories").json()["data"][0]["id"] == created["id"]
    assert client.get(
        "/memories", params={"status": "archived"}
    ).json()["data"] == []
    assert list_context_memories(project="Personal")[0]["id"] == created["id"]


def test_archive_and_restore_preserve_correction_history(clean_db, client):
    original = client.post(
        "/memories",
        json={"content": "Old value", "project": "Cars"},
    ).json()["data"]
    replacement = client.post(
        f"/memories/{original['id']}/corrections",
        json={"content": "Corrected value"},
    ).json()["data"]["replacement"]

    assert client.post(f"/memories/{replacement['id']}/archive").status_code == 200
    history = client.get(f"/memories/{original['id']}/history").json()["data"]
    assert [item["status"] for item in history] == ["superseded", "archived"]
    assert [item["content"] for item in history] == ["Old value", "Corrected value"]

    assert client.post(f"/memories/{replacement['id']}/restore").status_code == 200
    restored_history = client.get(
        f"/memories/{replacement['id']}/history"
    ).json()["data"]
    assert [item["status"] for item in restored_history] == [
        "superseded",
        "active",
    ]


def test_archive_and_restore_reject_missing_or_wrong_status(clean_db, client):
    assert client.post("/memories/missing/archive").status_code == 404
    assert client.post("/memories/missing/restore").status_code == 404

    created = client.post(
        "/memories",
        json={"content": "Lifecycle value"},
    ).json()["data"]

    assert client.post(f"/memories/{created['id']}/restore").status_code == 409
    assert client.post(f"/memories/{created['id']}/archive").status_code == 200
    assert client.post(f"/memories/{created['id']}/archive").status_code == 409
    assert client.post(
        f"/memories/{created['id']}/corrections",
        json={"content": "Cannot correct archived"},
    ).status_code == 409
    assert client.post(f"/memories/{created['id']}/restore").status_code == 200
    assert client.post(f"/memories/{created['id']}/restore").status_code == 409


def test_archived_memory_is_protected_from_hard_delete(clean_db, client):
    created = client.post(
        "/memories",
        json={"content": "Recoverable memory"},
    ).json()["data"]
    client.post(f"/memories/{created['id']}/archive")

    response = client.delete(f"/memories/{created['id']}")

    assert response.status_code == 409
    assert client.get(f"/memories/{created['id']}").json()["data"]["status"] == "archived"


def test_memory_status_filter_rejects_superseded_and_unknown_values(clean_db, client):
    assert client.get("/memories", params={"status": "superseded"}).status_code == 422
    assert client.get("/memories", params={"status": "unknown"}).status_code == 422


def test_failed_archive_rolls_back_to_active(clean_db, client):
    created = client.post(
        "/memories",
        json={"content": "Must stay active"},
    ).json()["data"]

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_archive
            BEFORE UPDATE OF status ON memories
            WHEN NEW.status = 'archived'
            BEGIN
                SELECT RAISE(ABORT, 'forced archive failure');
            END
            """
        )

    failing_client = TestClient(app, raise_server_exceptions=False)
    response = failing_client.post(f"/memories/{created['id']}/archive")

    assert response.status_code == 500
    saved = client.get(f"/memories/{created['id']}").json()["data"]
    assert saved["status"] == "active"


def test_failed_restore_rolls_back_to_archived(clean_db, client):
    created = client.post(
        "/memories",
        json={"content": "Must stay archived"},
    ).json()["data"]
    assert client.post(f"/memories/{created['id']}/archive").status_code == 200

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_restore
            BEFORE UPDATE OF status ON memories
            WHEN OLD.status = 'archived' AND NEW.status = 'active'
            BEGIN
                SELECT RAISE(ABORT, 'forced restore failure');
            END
            """
        )

    failing_client = TestClient(app, raise_server_exceptions=False)
    response = failing_client.post(f"/memories/{created['id']}/restore")

    assert response.status_code == 500
    saved = client.get(f"/memories/{created['id']}").json()["data"]
    assert saved["status"] == "archived"


def test_competing_archive_and_restore_requests_serialize(clean_db, client):
    created = client.post(
        "/memories",
        json={"content": "Concurrent lifecycle value"},
    ).json()["data"]

    def attempt_archive(_):
        try:
            return archive_memory(created["id"])
        except MemoryArchiveConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        archive_results = list(executor.map(attempt_archive, range(2)))

    assert len([item for item in archive_results if item is not None]) == 1
    assert client.get(f"/memories/{created['id']}").json()["data"]["status"] == "archived"

    def attempt_restore(_):
        try:
            return restore_memory(created["id"])
        except MemoryRestoreConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        restore_results = list(executor.map(attempt_restore, range(2)))

    assert len([item for item in restore_results if item is not None]) == 1
    assert client.get(f"/memories/{created['id']}").json()["data"]["status"] == "active"


def test_competing_correction_and_forget_leave_one_valid_outcome(clean_db, client):
    created = client.post(
        "/memories",
        json={"content": "Original concurrent value"},
    ).json()["data"]

    def attempt_correction():
        try:
            result = correct_memory(created["id"], "Corrected concurrent value")
            return ("corrected", result)
        except MemoryNotActiveError:
            return ("conflict", None)

    def attempt_archive():
        try:
            result = archive_memory(created["id"])
            return ("archived", result)
        except MemoryArchiveConflictError:
            return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        correction_future = executor.submit(attempt_correction)
        archive_future = executor.submit(attempt_archive)
        results = [correction_future.result(), archive_future.result()]

    winners = [name for name, result in results if result is not None]
    assert len(winners) == 1

    active_rows = client.get("/memories").json()["data"]
    archived_rows = client.get(
        "/memories", params={"status": "archived"}
    ).json()["data"]
    history = client.get(f"/memories/{created['id']}/history").json()["data"]

    if winners == ["corrected"]:
        assert archived_rows == []
        assert len(active_rows) == 1
        assert active_rows[0]["content"] == "Corrected concurrent value"
        assert [row["status"] for row in history] == ["superseded", "active"]
    else:
        assert active_rows == []
        assert len(archived_rows) == 1
        assert archived_rows[0]["id"] == created["id"]
        assert [row["status"] for row in history] == ["archived"]


def test_forget_and_restore_endpoints_require_authentication(monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "test-secret-that-is-long-enough")
    monkeypatch.delenv("MOOTOS_ALLOW_PUBLIC", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    private_client = TestClient(app)

    archive = private_client.post("/memories/missing/archive")
    restore = private_client.post("/memories/missing/restore")
    archived_list = private_client.get("/memories", params={"status": "archived"})

    assert archive.status_code == 401
    assert restore.status_code == 401
    assert archived_list.status_code == 401


def test_memory_interface_exposes_confirmed_forget_and_restore_controls():
    client = TestClient(app)
    page = client.get("/memory")
    script = client.get("/static/memory.js")

    assert page.status_code == 200
    assert 'id="memoryStatusFilter"' in page.text
    assert 'id="memoryLifecycleDialog"' in page.text
    assert "Forget is recoverable" in page.text
    assert "`/memories/${encodeURIComponent(memoryId)}/${action}`" in script.text
    assert 'action === "restore"' in script.text
    assert 'method: "POST"' in script.text
    assert "textContent = memory.content" in script.text
    assert 'method: "DELETE"' not in script.text
    assert 'method: "PATCH"' not in script.text
    assert 'method: "PUT"' not in script.text
