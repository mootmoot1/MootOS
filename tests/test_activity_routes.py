"""Tests for the read-only activity/log route and page."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.db import DATABASE_PATH
from backend.memory import init_db
from backend.runs import RUN_COLUMNS, start_model_run, finish_model_run_success


EXPECTED_RUN_KEYS = {
    column.strip() for column in RUN_COLUMNS.split(",") if column.strip()
}


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


def test_activity_runs_lists_recorded_runs_newest_first(clean_db, client):
    first = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    finish_model_run_success(first["id"])
    second = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    finish_model_run_success(second["id"])

    response = client.get("/activity/runs")

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 2
    assert data[0]["id"] == second["id"]
    assert data[1]["id"] == first["id"]


def test_activity_runs_expose_exactly_the_known_run_columns(clean_db, client):
    """Allowlist the exact Run field set rather than banning substrings.

    A substring ban (e.g. "content" not in body) is fragile: it can miss a
    genuinely new leaky field whose name doesn't happen to match the banned
    words, and it can false-fail on an unrelated, harmless field name. An
    exact key-set comparison against ``backend.runs.RUN_COLUMNS`` (the single
    source of truth the storage layer itself uses) is the precise version of
    the same guarantee: the HTTP response can never contain a field that
    RUN_COLUMNS does not already know about, including any future field.
    """
    run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    finish_model_run_success(run["id"])

    response = client.get("/activity/runs")

    data = response.json()["data"]
    assert len(data) == 1
    assert set(data[0].keys()) == EXPECTED_RUN_KEYS
    # Explicitly confirm the fields a leak would most plausibly appear under
    # are simply not part of the allowed set at all.
    assert "prompt" not in EXPECTED_RUN_KEYS
    assert "response" not in EXPECTED_RUN_KEYS
    assert "content" not in EXPECTED_RUN_KEYS


def test_activity_runs_respects_limit(clean_db, client):
    for _ in range(3):
        run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
        finish_model_run_success(run["id"])

    response = client.get("/activity/runs?limit=2")

    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


def test_activity_tasks_orders_by_creation_recency_not_due_date(clean_db, client):
    """/tasks orders due tasks first; /activity/tasks must not inherit that.

    Task A is created first but given a near-term due date. Task B is
    created second with no due date at all. Under the existing /tasks
    ordering (due-not-null before due-null), A would rank ahead of B even
    though B is the more recently *created* task. Activity's dedicated
    endpoint must rank by creation recency instead, so "recent" is accurate.
    """
    from backend.tasks import create_task

    older_task_due_soon = create_task("Older task, due soon", due_at="2030-01-01T00:00:00+00:00")
    newer_task_no_due = create_task("Newer task, no due date")

    activity_response = client.get("/activity/tasks")
    tasks_response = client.get("/tasks")

    activity_ids = [task["id"] for task in activity_response.json()["data"]]
    tasks_ids = [task["id"] for task in tasks_response.json()["data"]]

    assert activity_ids[:2] == [newer_task_no_due["id"], older_task_due_soon["id"]]
    # The existing /tasks endpoint is unchanged and still puts the due task
    # first; this is the exact ordering difference Activity had to avoid.
    assert tasks_ids[:2] == [older_task_due_soon["id"], newer_task_no_due["id"]]


def test_activity_tasks_includes_every_status_and_respects_limit(clean_db, client):
    from backend.tasks import cancel_task, complete_task, create_task

    open_task = create_task("Still open")
    completed_task = create_task("Will complete")
    complete_task(completed_task["id"])
    cancelled_task = create_task("Will cancel")
    cancel_task(cancelled_task["id"])

    response = client.get("/activity/tasks?limit=2")

    data = response.json()["data"]
    assert len(data) == 2
    returned_ids = {task["id"] for task in data}
    assert returned_ids == {cancelled_task["id"], completed_task["id"]}
    assert open_task["id"] not in returned_ids


def test_activity_memories_orders_by_recency_and_limits_server_side(clean_db, client):
    from backend.memory import create_memory

    older = create_memory("Older memory")
    newer = create_memory("Newer memory")

    response = client.get("/activity/memories?limit=1")

    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == newer["id"]
    assert data[0]["id"] != older["id"]


def test_activity_memories_excludes_archived_and_superseded(clean_db, client):
    from backend.memory import archive_memory, correct_memory, create_memory

    archived = create_memory("Will be archived")
    archive_memory(archived["id"])

    corrected_original = create_memory("Will be corrected")
    correction = correct_memory(corrected_original["id"], "The corrected version")

    response = client.get("/activity/memories")

    returned_ids = {memory["id"] for memory in response.json()["data"]}
    assert archived["id"] not in returned_ids
    assert corrected_original["id"] not in returned_ids
    assert correction["replacement"]["id"] in returned_ids


def test_activity_page_is_served(clean_db, client):
    response = client.get("/activity")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Activity" in response.text
    assert "/static/activity.js" in response.text


def test_activity_routes_require_auth_when_password_is_enabled(monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "a" * 40)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    client = TestClient(app)
    for path in ("/activity/runs", "/activity/tasks", "/activity/memories"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json() == {"detail": "Authentication required"}


def test_activity_page_requires_auth_and_redirects_to_login(monkeypatch):
    """/activity is in HTML_PATHS, so an unauthenticated GET always redirects.

    Unlike the JSON API sub-routes (/activity/runs etc.), the page route
    itself should behave exactly like the other browser pages (/chat,
    /memory): a 303 to /login regardless of the request's Accept header,
    not only when the caller happens to send "text/html".
    """
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "a" * 40)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    client = TestClient(app)

    default_accept = client.get("/activity", follow_redirects=False)
    assert default_accept.status_code == 303
    assert default_accept.headers["location"] == "/login?next=/activity"

    explicit_html_accept = client.get(
        "/activity", follow_redirects=False, headers={"accept": "text/html"}
    )
    assert explicit_html_accept.status_code == 303
    assert explicit_html_accept.headers["location"] == "/login?next=/activity"
