"""Tests for cloud deployment and persistent storage configuration."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.memory import resolve_database_path


ROOT = Path(__file__).resolve().parent.parent


def test_railway_volume_becomes_sqlite_home(monkeypatch):
    monkeypatch.delenv("MOOTOS_DATABASE_PATH", raising=False)
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")

    assert resolve_database_path() == Path("/data/mootos.db")


def test_explicit_database_path_has_priority(monkeypatch):
    monkeypatch.setenv("MOOTOS_DATABASE_PATH", "/private/mootos/custom.db")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")

    assert resolve_database_path() == Path("/private/mootos/custom.db")


def test_railway_config_uses_port_and_healthcheck():
    config = (ROOT / "railway.toml").read_text(encoding="utf-8")

    assert "--port $PORT" in config
    assert 'healthcheckPath = "/health"' in config
    assert 'restartPolicyType = "ON_FAILURE"' in config


def test_manifest_is_served_for_phone_installation():
    client = TestClient(app)
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    assert response.json()["start_url"] == "/chat"
    assert response.json()["display"] == "standalone"
