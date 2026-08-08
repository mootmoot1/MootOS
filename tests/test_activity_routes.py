"""Tests for the read-only activity/log route and page."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.db import DATABASE_PATH
from backend.memory import init_db
from backend.runs import start_model_run, finish_model_run_success


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


def test_activity_runs_never_include_prompt_or_response_fields(clean_db, client):
    run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
    finish_model_run_success(run["id"])

    response = client.get("/activity/runs")

    body = response.text
    for forbidden in ("prompt", "response", "content", "message_body"):
        assert forbidden not in body.lower()


def test_activity_runs_respects_limit(clean_db, client):
    for _ in range(3):
        run = start_model_run(conversation_id=None, provider="openai", model="gpt-test")
        finish_model_run_success(run["id"])

    response = client.get("/activity/runs?limit=2")

    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


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
    response = client.get("/activity/runs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
