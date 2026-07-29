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
