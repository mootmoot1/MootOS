"""Tests for the Task viewer page and its coexistence with the Task JSON API."""

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


def test_task_page_is_served_at_singular_path(clean_db, client):
    response = client.get("/task")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Tasks" in response.text
    assert "/static/task.js" in response.text


def test_task_page_shows_a_visible_timezone_note_near_the_due_input(clean_db, client):
    response = client.get("/task")

    assert 'id="taskDueInput"' in response.text
    assert 'id="taskDueTimezoneNote"' in response.text
    assert "local timezone" in response.text
    assert "stored as UTC" in response.text


def test_task_script_labels_the_terminal_action_cancel_task(clean_db, client):
    response = client.get("/static/task.js")

    assert response.status_code == 200
    assert '"Cancel task"' in response.text


def test_task_page_does_not_collide_with_task_json_api(clean_db, client):
    page_response = client.get("/task")
    api_response = client.get("/tasks")

    assert page_response.headers["content-type"].startswith("text/html")
    assert api_response.headers["content-type"].startswith("application/json")
    assert api_response.json()["success"] is True


def test_task_route_methods_are_unchanged_by_this_page(clean_db):
    task_page_methods = {
        method
        for route in app.routes
        if getattr(route, "path", None) == "/task"
        for method in route.methods
    }
    task_api_methods = {
        method
        for route in app.routes
        if getattr(route, "path", None) == "/tasks"
        for method in route.methods
    }

    assert task_page_methods == {"GET"}
    assert task_api_methods == {"GET", "POST"}


def test_task_page_requires_auth_and_redirects_to_login(monkeypatch):
    """/task is in HTML_PATHS, so an unauthenticated GET always redirects.

    This must hold regardless of the request's Accept header, exactly like
    /chat and /memory already behave, not only when the caller happens to
    send "text/html".
    """
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "a" * 40)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    client = TestClient(app)

    default_accept = client.get("/task", follow_redirects=False)
    assert default_accept.status_code == 303
    assert default_accept.headers["location"] == "/login?next=/task"

    explicit_html_accept = client.get(
        "/task", follow_redirects=False, headers={"accept": "text/html"}
    )
    assert explicit_html_accept.status_code == 303
    assert explicit_html_accept.headers["location"] == "/login?next=/task"


def test_task_json_api_still_returns_401_json_not_a_redirect(monkeypatch):
    """The JSON /tasks API is unaffected by /task joining HTML_PATHS.

    /tasks (plural, the API) was never added to HTML_PATHS, and a GET
    request without a text/html Accept header must still receive a plain
    401 so API/script callers keep getting a JSON error, not an HTML
    redirect response.
    """
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "a" * 40)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    client = TestClient(app)
    response = client.get("/tasks", follow_redirects=False)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
