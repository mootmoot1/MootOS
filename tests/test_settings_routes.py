"""Tests for the read-only settings/status route and page."""

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.migrations import LATEST_SCHEMA_VERSION


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("MOOTOS_PASSWORD", raising=False)
    monkeypatch.delenv("MOOTOS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def test_settings_status_reports_current_provider_model_and_schema(clean_env, client, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-model")

    response = client.get("/settings/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-test-model"
    assert data["schema_version"] == LATEST_SCHEMA_VERSION
    assert data["app_version"] == "0.1.0"


def test_settings_status_never_exposes_the_api_key(clean_env, client, monkeypatch):
    secret_key = "sk-super-secret-value-do-not-leak"
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", secret_key)

    response = client.get("/settings/status")

    assert response.status_code == 200
    assert secret_key not in response.text


def test_settings_status_handles_unknown_provider_without_crashing(clean_env, client, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "not-a-real-provider")

    response = client.get("/settings/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "not-a-real-provider"
    assert data["model"] is None


def test_settings_page_is_served(clean_env, client):
    response = client.get("/settings")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Settings" in response.text
    assert "/static/settings.js" in response.text


def test_settings_routes_require_auth_when_password_is_enabled(monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "a" * 40)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    client = TestClient(app)
    response = client.get("/settings/status")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
