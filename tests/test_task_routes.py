"""HTTP boundary tests for Task v0.1."""

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.db import DATABASE_PATH
from backend.memory import init_db


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def test_task_create_read_complete_flow(clean_db):
    client = TestClient(app)

    created_response = client.post(
        "/tasks",
        json={
            "title": "Finish Task v0.1",
            "project": "mootos",
            "due_at": "2026-08-08T09:00:00-04:00",
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()["data"]
    assert created["project"] == "MootOS"
    assert created["status"] == "open"
    assert created["due_at"] == "2026-08-08T13:00:00+00:00"

    fetched = client.get(f"/tasks/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["id"] == created["id"]

    completed_response = client.post(f"/tasks/{created['id']}/complete")
    assert completed_response.status_code == 200
    completed = completed_response.json()["data"]
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None

    conflict = client.post(f"/tasks/{created['id']}/cancel")
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Task is already finished"


def test_task_list_filters_status_and_project(clean_db):
    client = TestClient(app)
    first = client.post("/tasks", json={"title": "MootOS task", "project": "MootOS"}).json()["data"]
    second = client.post("/tasks", json={"title": "Studio task", "project": "Studio"}).json()["data"]
    client.post(f"/tasks/{second['id']}/complete")

    response = client.get("/tasks", params={"status": "open", "project": "mootos"})
    assert response.status_code == 200
    assert [task["id"] for task in response.json()["data"]] == [first["id"]]


def test_task_create_rejects_naive_due_time(clean_db):
    client = TestClient(app)
    response = client.post(
        "/tasks",
        json={"title": "Ambiguous reminder", "due_at": "2026-08-08T09:00:00"},
    )
    assert response.status_code == 422
    assert "timezone" in response.json()["detail"]


def test_task_create_rejects_unknown_project(clean_db):
    client = TestClient(app)
    response = client.post(
        "/tasks",
        json={"title": "Unknown scope", "project": "Does Not Exist"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Project does not exist"


def test_task_missing_and_invalid_status_are_sanitized(clean_db):
    client = TestClient(app)
    missing = client.get("/tasks/missing")
    invalid = client.get("/tasks", params={"status": "running"})
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Task not found"
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Unsupported task status"


def test_task_routes_require_auth_when_password_is_enabled(clean_db, monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "test-password")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "x" * 32)

    # Auth helpers read environment at request time; no task route is public.
    client = TestClient(app)
    response = client.get("/tasks")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"

    monkeypatch.delenv("MOOTOS_PASSWORD", raising=False)
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
