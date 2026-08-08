"""Regression coverage for scheduler/reminder foundation preparation."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.db import DATABASE_PATH
from backend.main import app
from backend.memory import init_db
from backend.tasks import (
    TaskAlreadyFinishedError,
    cancel_task,
    complete_task,
    create_task,
    get_task,
)


TEST_SESSION_SECRET = "test-session-secret-with-at-least-32-characters"


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def test_unauthenticated_task_shaped_chat_is_blocked(monkeypatch, clean_db):
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("MOOTOS_ALLOW_PUBLIC", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={"message": "Create a task to call Mike"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_task_terminal_transition_race_has_exactly_one_winner(clean_db):
    task = create_task("Race terminal transition")

    def complete():
        try:
            return ("completed", complete_task(task["id"]))
        except TaskAlreadyFinishedError:
            return ("rejected", None)

    def cancel():
        try:
            return ("cancelled", cancel_task(task["id"]))
        except TaskAlreadyFinishedError:
            return ("rejected", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            pool.submit(complete).result(),
            pool.submit(cancel).result(),
        ]

    winners = [result for result in results if result[0] != "rejected"]
    rejected = [result for result in results if result[0] == "rejected"]

    assert len(winners) == 1
    assert len(rejected) == 1
    stored = get_task(task["id"])
    assert stored is not None
    assert stored["status"] == winners[0][0]
    if stored["status"] == "completed":
        assert stored["completed_at"] is not None
        assert stored["cancelled_at"] is None
    else:
        assert stored["cancelled_at"] is not None
        assert stored["completed_at"] is None
