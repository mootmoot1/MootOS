"""Tests for Railway hard-delete policy and private HTTP safeguards."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.memory import DATABASE_PATH, init_db


@pytest.fixture
def clean_db(monkeypatch):
    monkeypatch.delenv("MOOTOS_PASSWORD", raising=False)
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("MOOTOS_ALLOW_PUBLIC", raising=False)
    monkeypatch.delenv("MOOTOS_ALLOW_HARD_DELETE", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def test_railway_hard_delete_is_disabled_but_archive_restore_stay_available(
    clean_db,
    monkeypatch,
):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    client = TestClient(app)
    created = client.post(
        "/memories",
        json={"content": "Keep this recoverable"},
    ).json()["data"]

    blocked = client.delete(f"/memories/{created['id']}")

    assert blocked.status_code == 403
    assert blocked.json()["detail"] == (
        "Permanent memory deletion is disabled on Railway. "
        "Archive the memory instead."
    )
    assert client.get(f"/memories/{created['id']}").json()["data"]["status"] == "active"

    archived = client.post(f"/memories/{created['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["data"]["status"] == "archived"

    restored = client.post(f"/memories/{created['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["data"]["status"] == "active"


def test_railway_hard_delete_needs_explicit_truthy_override(clean_db, monkeypatch):
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "mootos.example")
    monkeypatch.setenv("MOOTOS_ALLOW_HARD_DELETE", "false")
    client = TestClient(app)
    created = client.post(
        "/memories",
        json={"content": "Delete only with deliberate override"},
    ).json()["data"]

    assert client.delete(f"/memories/{created['id']}").status_code == 403

    monkeypatch.setenv("MOOTOS_ALLOW_HARD_DELETE", "true")
    deleted = client.delete(f"/memories/{created['id']}")

    assert deleted.status_code == 200
    assert deleted.json()["data"] == {
        "id": created["id"],
        "status": "deleted",
    }
    assert client.get(f"/memories/{created['id']}").status_code == 404


def test_local_hard_delete_remains_available_by_default(clean_db):
    client = TestClient(app)
    created = client.post(
        "/memories",
        json={"content": "Disposable local test memory"},
    ).json()["data"]

    deleted = client.delete(f"/memories/{created['id']}")

    assert deleted.status_code == 200
    assert client.get(f"/memories/{created['id']}").status_code == 404
