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


def test_task_page_requires_auth_when_password_is_enabled(monkeypatch):
    # Matches the existing /profile precedent: TestClient sends no text/html
    # Accept header, so the private-session middleware returns 401 JSON here.
    # A real browser (Accept: text/html, ...) receives a 303 redirect to
    # /login instead, exactly like /profile already does.
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "a" * 40)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    client = TestClient(app)
    response = client.get("/task", follow_redirects=False)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}

    browser_response = client.get(
        "/task", follow_redirects=False, headers={"accept": "text/html"}
    )
    assert browser_response.status_code == 303
    assert browser_response.headers["location"] == "/login?next=/task"
