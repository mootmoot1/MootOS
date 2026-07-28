"""Tests for the memory system."""

import sqlite3
from pathlib import Path

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
    """Test creating a new memory."""
    response = client.post(
        "/memories",
        json={"content": "Test memory", "project": "TestProject", "memory_type": "task"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["content"] == "Test memory"
    assert data["data"]["project"] == "TestProject"
    assert data["data"]["memory_type"] == "task"
    assert data["data"]["id"]
    assert data["data"]["created_at"]


def test_list_memories(clean_db, client):
    """Test listing all memories."""
    # Create two memories
    client.post("/memories", json={"content": "Memory 1", "project": "A"})
    client.post("/memories", json={"content": "Memory 2", "project": "B"})

    response = client.get("/memories")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) == 2


def test_get_memory(clean_db, client):
    """Test retrieving a single memory by ID."""
    # Create a memory
    create_response = client.post("/memories", json={"content": "Test memory"})
    memory_id = create_response.json()["data"]["id"]

    # Retrieve it
    response = client.get(f"/memories/{memory_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["id"] == memory_id
    assert data["data"]["content"] == "Test memory"


def test_delete_memory(clean_db, client):
    """Test deleting a memory."""
    # Create a memory
    create_response = client.post("/memories", json={"content": "Delete me"})
    memory_id = create_response.json()["data"]["id"]

    # Delete it
    response = client.delete(f"/memories/{memory_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["status"] == "deleted"

    # Try to retrieve it (should fail)
    get_response = client.get(f"/memories/{memory_id}")
    assert get_response.status_code == 404


def test_validation_empty_content(clean_db, client):
    """Test that empty content is rejected."""
    response = client.post("/memories", json={"content": ""})
    assert response.status_code == 422


def test_validation_content_too_long(clean_db, client):
    """Test that content exceeding 10000 chars is rejected."""
    response = client.post("/memories", json={"content": "x" * 10001})
    assert response.status_code == 422


def test_get_nonexistent_memory(clean_db, client):
    """Test retrieving a non-existent memory."""
    response = client.get("/memories/nonexistent")
    assert response.status_code == 404


def test_delete_nonexistent_memory(clean_db, client):
    """Test deleting a non-existent memory."""
    response = client.delete("/memories/nonexistent")
    assert response.status_code == 404


def test_memory_persists_after_database_reconnect(clean_db, client):
    """Test that a memory persists after closing and reopening the database connection."""
    # Create a memory
    create_response = client.post("/memories", json={"content": "Persistent memory"})
    memory_id = create_response.json()["data"]["id"]

    # Close and reopen the database connection
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM memories WHERE id = ?", (memory_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "Persistent memory"

    # Reconnect and verify again
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM memories WHERE id = ?", (memory_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "Persistent memory"
