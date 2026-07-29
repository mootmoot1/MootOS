"""Tests for the private password and signed-session boundary."""

import pytest
from fastapi.testclient import TestClient

from backend.auth import validate_auth_configuration
from backend.main import app


@pytest.fixture
def private_client(monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "test-secret-that-is-long-enough")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    return TestClient(app)


def test_private_deployment_redirects_browser_and_blocks_api(private_client):
    browser = private_client.get("/chat", follow_redirects=False)
    api = private_client.get("/projects")
    health = private_client.get("/health")

    assert browser.status_code == 303
    assert browser.headers["location"] == "/login?next=/chat"
    assert api.status_code == 401
    assert api.json()["detail"] == "Authentication required"
    assert health.status_code == 200


def test_wrong_password_is_rejected(private_client):
    response = private_client.post(
        "/auth/login",
        json={"password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect password"
    assert "mootos_session" not in private_client.cookies


def test_correct_password_unlocks_interface_and_api(private_client):
    login = private_client.post(
        "/auth/login",
        json={"password": "correct-horse"},
    )

    assert login.status_code == 200
    assert "mootos_session" in private_client.cookies
    assert private_client.get("/chat").status_code == 200
    assert private_client.get("/projects").status_code == 200


def test_logout_clears_private_session(private_client):
    private_client.post("/auth/login", json={"password": "correct-horse"})

    logout = private_client.post("/auth/logout", follow_redirects=False)

    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
    assert private_client.get("/projects").status_code == 401


def test_auth_can_remain_disabled_for_local_development(monkeypatch):
    monkeypatch.delenv("MOOTOS_PASSWORD", raising=False)
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
    client = TestClient(app)

    assert client.get("/chat").status_code == 200
    assert client.get("/projects").status_code == 200


def test_partial_auth_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "configured")
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="must be configured together"):
        validate_auth_configuration()
