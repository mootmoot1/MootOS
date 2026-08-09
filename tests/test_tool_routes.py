"""HTTP boundary tests for the Tool operation approval/rejection API."""

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.db import DATABASE_PATH
from backend.memory import init_db
from backend.tool_operations import create_pending_operation


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _pending_task_operation(**overrides):
    defaults = {
        "tool_name": "tasks.create",
        "tool_version": "1",
        "arguments": {"title": "Call Mike"},
        "conversation_id": None,
        "project": None,
    }
    defaults.update(overrides)
    return create_pending_operation(**defaults)


def test_approve_endpoint_executes_and_returns_success(clean_db):
    client = TestClient(app)
    operation = _pending_task_operation()

    response = client.post(f"/tool-operations/{operation['id']}/approve")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["result_reference"]

    tasks = client.get("/tasks").json()["data"]
    assert [task["title"] for task in tasks] == ["Call Mike"]


def test_duplicate_approve_returns_conflict_without_duplicating(clean_db):
    client = TestClient(app)
    operation = _pending_task_operation()
    client.post(f"/tool-operations/{operation['id']}/approve")

    second = client.post(f"/tool-operations/{operation['id']}/approve")

    assert second.status_code == 409
    tasks = client.get("/tasks").json()["data"]
    assert len(tasks) == 1


def test_reject_endpoint_executes_nothing(clean_db):
    client = TestClient(app)
    operation = _pending_task_operation()

    response = client.post(f"/tool-operations/{operation['id']}/reject")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "rejected"
    assert client.get("/tasks").json()["data"] == []


def test_reject_after_approve_is_conflict(clean_db):
    client = TestClient(app)
    operation = _pending_task_operation()
    client.post(f"/tool-operations/{operation['id']}/approve")

    response = client.post(f"/tool-operations/{operation['id']}/reject")

    assert response.status_code == 409


def test_unknown_operation_id_returns_404(clean_db):
    client = TestClient(app)

    assert client.post("/tool-operations/does-not-exist/approve").status_code == 404
    assert client.post("/tool-operations/does-not-exist/reject").status_code == 404
    assert client.get("/tool-operations/does-not-exist").status_code == 404


def test_get_operation_returns_frozen_arguments(clean_db):
    client = TestClient(app)
    operation = _pending_task_operation(arguments={"title": "Call Mike", "project": None})

    response = client.get(f"/tool-operations/{operation['id']}")

    assert response.status_code == 200
    assert response.json()["data"]["arguments"]["title"] == "Call Mike"


def test_list_pending_operations_endpoint(clean_db):
    client = TestClient(app)
    _pending_task_operation(arguments={"title": "First"})
    _pending_task_operation(arguments={"title": "Second"})

    response = client.get("/tool-operations")

    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


def test_approval_endpoints_require_authentication_when_configured(clean_db, monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct horse battery staple")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "s" * 40)
    operation = _pending_task_operation()

    client = TestClient(app)
    response = client.post(f"/tool-operations/{operation['id']}/approve")

    assert response.status_code == 401
    from backend.tasks import list_tasks

    assert list_tasks() == []
