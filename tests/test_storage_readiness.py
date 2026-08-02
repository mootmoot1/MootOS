"""Tests for Railway database fail-closed behavior and readiness."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.db import (
    DatabaseConfigurationError,
    DatabaseReadinessError,
    check_database_readiness,
    resolve_database_path,
    validate_database_configuration,
)
from backend.main import app
from backend.migrations import LATEST_SCHEMA_VERSION, initialize_database


RAILWAY_VARIABLES = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_PUBLIC_DOMAIN",
    "RAILWAY_VOLUME_MOUNT_PATH",
    "MOOTOS_DATABASE_PATH",
    "MOOTOS_ALLOW_UNSAFE_DATABASE_PATH",
)


def _clear_storage_environment(monkeypatch) -> None:
    for name in RAILWAY_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_local_database_override_remains_available(monkeypatch, tmp_path):
    _clear_storage_environment(monkeypatch)
    database_path = tmp_path / "local.db"
    monkeypatch.setenv("MOOTOS_DATABASE_PATH", str(database_path))

    assert resolve_database_path() == database_path
    assert validate_database_configuration() == database_path


def test_railway_requires_persistent_volume(monkeypatch):
    _clear_storage_environment(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    with pytest.raises(DatabaseConfigurationError, match="persistent volume"):
        validate_database_configuration()


def test_railway_uses_existing_volume_mount(monkeypatch, tmp_path):
    _clear_storage_environment(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))

    assert validate_database_configuration() == tmp_path / "mootos.db"


def test_railway_rejects_unavailable_volume_mount(monkeypatch, tmp_path):
    _clear_storage_environment(monkeypatch)
    missing_mount = tmp_path / "missing-volume"
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(missing_mount))

    with pytest.raises(DatabaseConfigurationError, match="mount is unavailable"):
        validate_database_configuration()


def test_railway_rejects_database_override_without_explicit_approval(
    monkeypatch,
):
    _clear_storage_environment(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
    monkeypatch.setenv("MOOTOS_DATABASE_PATH", "/data/custom.db")

    with pytest.raises(DatabaseConfigurationError, match="reject MOOTOS_DATABASE_PATH"):
        validate_database_configuration()


def test_railway_unsafe_override_must_be_absolute(monkeypatch):
    _clear_storage_environment(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("MOOTOS_DATABASE_PATH", "relative.db")
    monkeypatch.setenv("MOOTOS_ALLOW_UNSAFE_DATABASE_PATH", "true")

    with pytest.raises(DatabaseConfigurationError, match="absolute path"):
        validate_database_configuration()


def test_railway_allows_deliberate_high_risk_override(monkeypatch):
    _clear_storage_environment(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("MOOTOS_DATABASE_PATH", "/private/mootos/custom.db")
    monkeypatch.setenv("MOOTOS_ALLOW_UNSAFE_DATABASE_PATH", "true")

    assert validate_database_configuration() == Path("/private/mootos/custom.db")


def test_readiness_accepts_existing_latest_schema(tmp_path):
    database_path = tmp_path / "ready.db"
    initialize_database(database_path)

    check_database_readiness(LATEST_SCHEMA_VERSION, database_path)


def test_readiness_rejects_missing_database_without_creating_it(tmp_path):
    database_path = tmp_path / "missing.db"

    with pytest.raises(DatabaseReadinessError, match="unavailable"):
        check_database_readiness(LATEST_SCHEMA_VERSION, database_path)

    assert not database_path.exists()


def test_readiness_rejects_unsupported_schema(tmp_path):
    database_path = tmp_path / "old-schema.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, applied_at)
            VALUES (1, 'initial_schema', '2026-08-02T00:00:00+00:00')
            """
        )

    with pytest.raises(DatabaseReadinessError, match="schema"):
        check_database_readiness(LATEST_SCHEMA_VERSION, database_path)


def test_readiness_route_is_public_when_auth_is_enabled(monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "correct-horse")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "test-secret-that-is-long-enough")
    monkeypatch.setattr("backend.main.check_database_readiness", lambda version: None)
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_route_returns_generic_service_unavailable(monkeypatch):
    def fail_readiness(version):
        raise DatabaseReadinessError("private internal reason")

    monkeypatch.setattr("backend.main.check_database_readiness", fail_readiness)
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not ready"}
    assert "private internal reason" not in response.text
