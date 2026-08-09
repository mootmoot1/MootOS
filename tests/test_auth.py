"""Tests for the private password and signed-session boundary."""

import pytest
from fastapi.testclient import TestClient

from backend.auth import (
    LOGIN_COOLDOWN_SECONDS,
    LOGIN_FAILURE_LIMIT,
    MIN_SESSION_SECRET_LENGTH,
    login_retry_after,
    record_failed_login,
    reset_login_throttle,
    validate_auth_configuration,
)
from backend.main import app
from backend.memory import init_db


TEST_SESSION_SECRET = "test-session-secret-with-at-least-32-characters"


@pytest.fixture(autouse=True)
def isolated_login_throttle():
    reset_login_throttle()
    yield
    reset_login_throttle()


@pytest.fixture(autouse=True)
def ensure_database_ready():
    """Guarantee the schema exists regardless of test collection order.

    This file previously relied on ``backend.main``'s module-import-time
    ``init_db()`` call and on always being the first test file pytest
    collects alphabetically. Any other test module that deletes the database
    file in its own teardown (an established, repeated pattern across this
    suite) and happens to sort before this file breaks that assumption.
    ``init_db()``/``run_migrations()`` is idempotent, so calling it here is
    always safe and makes this file self-sufficient.
    """
    init_db()


@pytest.fixture
def private_client(monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("MOOTOS_ALLOW_PUBLIC", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    return TestClient(app)


def test_private_deployment_redirects_browser_and_blocks_api(private_client):
    chat_browser = private_client.get("/chat", follow_redirects=False)
    memory_browser = private_client.get("/memory", follow_redirects=False)
    api = private_client.get("/projects")
    correction = private_client.post(
        "/memories/missing/corrections",
        json={"content": "Replacement"},
    )
    history = private_client.get("/memories/missing/history")
    health = private_client.get("/health")

    assert chat_browser.status_code == 303
    assert chat_browser.headers["location"] == "/login?next=/chat"
    assert memory_browser.status_code == 303
    assert memory_browser.headers["location"] == "/login?next=/memory"
    assert api.status_code == 401
    assert api.json()["detail"] == "Authentication required"
    assert correction.status_code == 401
    assert correction.json()["detail"] == "Authentication required"
    assert history.status_code == 401
    assert history.json()["detail"] == "Authentication required"
    assert health.status_code == 200


def test_wrong_password_is_rejected(private_client):
    response = private_client.post(
        "/auth/login",
        json={"password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect password"
    assert "mootos_session" not in private_client.cookies


def test_login_throttle_is_process_global_and_ignores_forwarded_ip(private_client):
    for attempt in range(LOGIN_FAILURE_LIMIT):
        response = private_client.post(
            "/auth/login",
            json={"password": "wrong-password"},
            headers={"X-Forwarded-For": f"198.51.100.{attempt + 1}"},
        )
        expected = 401 if attempt < LOGIN_FAILURE_LIMIT - 1 else 429
        assert response.status_code == expected

    assert response.json()["detail"] == "Too many login attempts. Try again shortly."
    assert response.headers["Retry-After"] == str(LOGIN_COOLDOWN_SECONDS)

    blocked_correct_password = private_client.post(
        "/auth/login",
        json={"password": "correct-horse"},
        headers={"X-Forwarded-For": "203.0.113.50"},
    )
    assert blocked_correct_password.status_code == 429
    assert "mootos_session" not in private_client.cookies


def test_login_throttle_expires_without_permanent_lockout():
    for _ in range(LOGIN_FAILURE_LIMIT):
        retry_after = record_failed_login(now=100.0)

    assert retry_after == LOGIN_COOLDOWN_SECONDS
    assert login_retry_after(now=159.1) == 1
    assert login_retry_after(now=160.0) == 0


def test_successful_login_resets_failure_budget(private_client):
    for _ in range(LOGIN_FAILURE_LIMIT - 1):
        assert private_client.post(
            "/auth/login",
            json={"password": "wrong-password"},
        ).status_code == 401

    assert private_client.post(
        "/auth/login",
        json={"password": "correct-horse"},
    ).status_code == 200

    for _ in range(LOGIN_FAILURE_LIMIT - 1):
        assert private_client.post(
            "/auth/login",
            json={"password": "wrong-password"},
        ).status_code == 401

    assert private_client.post(
        "/auth/login",
        json={"password": "wrong-password"},
    ).status_code == 429


def test_correct_password_unlocks_interface_and_api(private_client):
    login = private_client.post(
        "/auth/login",
        json={"password": "correct-horse"},
    )

    assert login.status_code == 200
    assert "mootos_session" in private_client.cookies
    assert private_client.get("/chat").status_code == 200
    assert private_client.get("/memory").status_code == 200
    assert private_client.get("/projects").status_code == 200
    assert private_client.get("/memories").status_code == 200
    assert private_client.post(
        "/memories/missing/corrections",
        json={"content": "Replacement"},
    ).status_code == 404
    assert private_client.get("/memories/missing/history").status_code == 404


def test_private_html_json_and_redirects_are_no_store(private_client):
    login_page = private_client.get("/login")
    chat_redirect = private_client.get("/chat", follow_redirects=False)
    unauthenticated_api = private_client.get("/projects")

    assert login_page.status_code == 200
    assert login_page.headers["Cache-Control"] == "no-store"
    assert chat_redirect.status_code == 303
    assert chat_redirect.headers["Cache-Control"] == "no-store"
    assert unauthenticated_api.status_code == 401
    assert unauthenticated_api.headers["Cache-Control"] == "no-store"

    private_client.post(
        "/auth/login",
        json={"password": "correct-horse"},
    )
    authenticated_api = private_client.get("/projects")
    assert authenticated_api.status_code == 200
    assert authenticated_api.headers["Cache-Control"] == "no-store"


def test_core_security_headers_cover_public_and_private_responses(private_client):
    responses = [
        private_client.get("/health"),
        private_client.get("/login"),
        private_client.get("/chat", follow_redirects=False),
        private_client.get("/projects"),
    ]

    for response in responses:
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "same-origin"

    assert "Cache-Control" not in responses[0].headers


def test_logout_clears_private_session(private_client):
    private_client.post("/auth/login", json={"password": "correct-horse"})

    logout = private_client.post("/auth/logout", follow_redirects=False)

    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
    assert private_client.get("/projects").status_code == 401


def test_auth_can_remain_disabled_for_local_development(monkeypatch):
    monkeypatch.delenv("MOOTOS_PASSWORD", raising=False)
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("MOOTOS_ALLOW_PUBLIC", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    validate_auth_configuration()
    client = TestClient(app)

    assert client.get("/chat").status_code == 200
    assert client.get("/memory").status_code == 200
    assert client.get("/projects").status_code == 200


def test_partial_auth_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "configured")
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("MOOTOS_ALLOW_PUBLIC", raising=False)

    with pytest.raises(RuntimeError, match="must be configured together"):
        validate_auth_configuration()


def test_short_session_secret_fails_closed(monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "configured")
    monkeypatch.setenv(
        "MOOTOS_SESSION_SECRET",
        "x" * (MIN_SESSION_SECRET_LENGTH - 1),
    )
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    with pytest.raises(RuntimeError, match="must be at least 32 characters"):
        validate_auth_configuration()

    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "x" * MIN_SESSION_SECRET_LENGTH)
    validate_auth_configuration()


def test_railway_without_auth_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("MOOTOS_PASSWORD", raising=False)
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("MOOTOS_ALLOW_PUBLIC", raising=False)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="Railway deployments require"):
        validate_auth_configuration()


def test_railway_public_override_must_be_explicit(monkeypatch):
    monkeypatch.delenv("MOOTOS_PASSWORD", raising=False)
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
    monkeypatch.setenv("MOOTOS_ALLOW_PUBLIC", "true")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    validate_auth_configuration()
