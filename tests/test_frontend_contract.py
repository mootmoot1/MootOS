"""Contract tests mirroring the exact payloads the frontend JS sends.

These tests exist to catch a divergence between what task.js/memory.js/
activity.js/settings.js actually send/read (as of this file's writing) and
what the backend accepts/returns, without introducing a JS test framework.
Each test constructs the literal request shape from the corresponding
frontend/*.js call site and asserts the response contains the fields that
call site subsequently reads. If a frontend file's payload or read shape
changes, this file should be updated to match it.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.db import DATABASE_PATH
from backend.memory import init_db


@pytest.fixture
def clean_db(monkeypatch):
    monkeypatch.delenv("MOOTOS_PASSWORD", raising=False)
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    paths = [
        Path(DATABASE_PATH),
        Path(f"{DATABASE_PATH}-wal"),
        Path(f"{DATABASE_PATH}-shm"),
    ]
    for path in paths:
        if path.exists():
            path.unlink()
    init_db()
    yield
    for path in paths:
        if path.exists():
            path.unlink()


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# task.js -> POST /tasks
# ---------------------------------------------------------------------------
# elements.createForm submit handler builds:
#   const body = { title };
#   if (elements.projectSelect.value) body.project = elements.projectSelect.value;
#   const dueAt = dueInputToUtcIso(elements.dueInput.value);
#   if (dueAt) body.due_at = dueAt;
#   apiRequest("/tasks", { method: "POST", body: JSON.stringify(body) });


def test_task_creation_matches_task_js_minimal_payload(clean_db, client):
    """Title only: the exact body sent when no project/due date is chosen."""
    response = client.post("/tasks", json={"title": "Export final mix"})

    assert response.status_code == 201
    data = response.json()["data"]
    # Every field task.js's taskCard() reads from a created/listed task.
    assert data["title"] == "Export final mix"
    assert data["project"] is None
    assert data["status"] == "open"
    assert data["due_at"] is None
    assert "created_at" in data
    assert "id" in data


def test_task_creation_matches_task_js_payload_with_project(clean_db, client):
    response = client.post("/tasks", json={"title": "Book studio time", "project": "Studio"})

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["project"] == "Studio"


def test_task_creation_matches_task_js_datetime_local_derived_due_at(clean_db, client):
    """The exact string shape produced by task.js's dueInputToUtcIso().

    dueInputToUtcIso() does ``new Date(datetimeLocalValue).toISOString()``,
    which always emits three-digit milliseconds and a literal "Z" suffix,
    e.g. "2026-08-09T19:00:00.000Z" -- never a numeric UTC offset and never
    a value without milliseconds. This is the one piece of new client-side
    date logic in this PR set; this test proves the backend's Z-suffix and
    fractional-second handling actually accepts exactly what the browser
    will actually send, not just a hand-picked ISO string.
    """
    response = client.post(
        "/tasks",
        json={"title": "Call Mike", "due_at": "2030-06-15T19:00:00.000Z"},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    # Normalized to UTC; the stored/returned form uses a numeric +00:00
    # offset (see backend/time_utils.py), which the frontend never has to
    # parse itself -- it only ever renders due_at through `new Date(value)`.
    assert data["due_at"] == "2030-06-15T19:00:00+00:00"


def test_task_creation_rejects_naive_datetime_local_value_without_z_or_offset(clean_db, client):
    """Guard against a future dueInputToUtcIso() regression that skips .toISOString().

    If that helper were ever changed to send the raw <input type="datetime-local">
    value directly (no timezone information at all), the existing due_at
    timezone requirement must still reject it rather than silently guessing.
    """
    response = client.post(
        "/tasks",
        json={"title": "Call Mike", "due_at": "2030-06-15T19:00:00"},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# task.js -> POST /tasks/{id}/complete and /tasks/{id}/cancel
# ---------------------------------------------------------------------------
# finishTask(taskId, action) sends:
#   apiRequest(`/tasks/${encodeURIComponent(taskId)}/${action}`, { method: "POST" })
# with action being the literal string "complete" or "cancel", no body.


def test_task_complete_matches_task_js_finish_task_call(clean_db, client):
    created = client.post("/tasks", json={"title": "Mix reference track"}).json()["data"]

    response = client.post(f"/tasks/{created['id']}/complete")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["completed_at"] is not None
    assert data["cancelled_at"] is None


def test_task_cancel_matches_task_js_finish_task_call(clean_db, client):
    created = client.post("/tasks", json={"title": "Reshoot cover art"}).json()["data"]

    response = client.post(f"/tasks/{created['id']}/cancel")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "cancelled"
    assert data["cancelled_at"] is not None
    assert data["completed_at"] is None


# ---------------------------------------------------------------------------
# memory.js -> POST /memories (create-memory form)
# ---------------------------------------------------------------------------
# submitCreateMemory() builds:
#   const body = { content };
#   if (elements.createProject.value) body.project = elements.createProject.value;
#   const memoryType = elements.createType.value.trim();
#   if (memoryType) body.memory_type = memoryType;
#   apiRequest("/memories", { method: "POST", body: JSON.stringify(body) });


def test_direct_memory_creation_matches_memory_js_minimal_payload(clean_db, client):
    response = client.post("/memories", json={"content": "Prefers concise explanations."})

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["content"] == "Prefers concise explanations."
    assert data["project"] is None
    assert data["memory_type"] is None
    assert data["status"] == "active"


def test_direct_memory_creation_matches_memory_js_full_payload(clean_db, client):
    """Project selected and a type chosen/typed from the <datalist> suggestions."""
    response = client.post(
        "/memories",
        json={
            "content": "Client prefers morning sessions.",
            "project": "Studio",
            "memory_type": "people",
        },
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["project"] == "Studio"
    assert data["memory_type"] == "people"


# ---------------------------------------------------------------------------
# activity.js -> read shapes
# ---------------------------------------------------------------------------
# renderRuns() reads: run.provider, run.model, run.status, run.duration_ms,
#   run.started_at, run.error_class
# renderTasks() reads: task.title, task.status, task.project, task.created_at
# renderMemories() reads: memory.content, memory.memory_type, memory.project,
#   memory.created_at


def test_activity_runs_response_has_every_field_activity_js_reads(clean_db, client):
    from backend.runs import finish_model_run_success, start_model_run

    run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    finish_model_run_success(run["id"])

    response = client.get("/activity/runs")

    row = response.json()["data"][0]
    for field in ("provider", "model", "status", "duration_ms", "started_at", "error_class"):
        assert field in row


def test_activity_tasks_response_has_every_field_activity_js_reads(clean_db, client):
    client.post("/tasks", json={"title": "Export final mix"})

    response = client.get("/activity/tasks")

    row = response.json()["data"][0]
    for field in ("title", "status", "project", "created_at"):
        assert field in row


def test_activity_memories_response_has_every_field_activity_js_reads(clean_db, client):
    client.post("/memories", json={"content": "Prefers concise explanations."})

    response = client.get("/activity/memories")

    row = response.json()["data"][0]
    for field in ("content", "memory_type", "project", "created_at"):
        assert field in row


# ---------------------------------------------------------------------------
# settings.js -> read shape
# ---------------------------------------------------------------------------
# initialize() reads: status.provider, status.model, status.schema_version,
#   status.app_version


def test_settings_status_response_has_every_field_settings_js_reads(clean_db, client):
    response = client.get("/settings/status")

    row = response.json()["data"]
    for field in ("provider", "model", "schema_version", "app_version"):
        assert field in row
