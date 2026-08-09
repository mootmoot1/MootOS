"""Integration tests for the private bootstrap-profile interface."""

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
    monkeypatch.delenv("MOOTOS_ALLOW_PUBLIC", raising=False)
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


def reviewed_manifest():
    return {
        "version": 1,
        "entries": [
            {"content": "Use direct explanations.", "project": None},
            {"content": "Studio work uses Pro Tools.", "project": "Studio"},
        ],
    }


def test_profile_page_and_assets_are_served(clean_db):
    client = TestClient(app)

    page = client.get("/profile")
    script = client.get("/static/profile.js")
    stylesheet = client.get("/static/profile.css")

    assert page.status_code == 200
    assert "Bootstrap profile" in page.text
    assert 'id="profileJsonInput"' in page.text
    assert 'id="previewProfileButton"' in page.text
    assert 'id="importProfileButton"' in page.text
    assert script.status_code == 200
    assert stylesheet.status_code == 200


def test_profile_page_and_endpoints_require_private_session(clean_db, monkeypatch):
    monkeypatch.setenv("MOOTOS_PASSWORD", "private-password")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "s" * 32)
    client = TestClient(app)

    page = client.get(
        "/profile",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    preview = client.post("/profile/preview", json=reviewed_manifest())
    imported = client.post("/profile/import", json=reviewed_manifest())

    assert page.status_code == 303
    assert page.headers["location"] == "/login?next=/profile"
    assert preview.status_code == 401
    assert imported.status_code == 401

    login = client.post("/auth/login", json={"password": "private-password"})
    assert login.status_code == 200
    assert client.get("/profile").status_code == 200
    assert client.post("/profile/preview", json=reviewed_manifest()).status_code == 200


def test_profile_page_redirects_to_login_regardless_of_accept_header(clean_db, monkeypatch):
    """/profile is in HTML_PATHS, so an unauthenticated GET always redirects.

    This must hold even without an explicit text/html Accept header,
    matching /chat and /memory's existing behavior. /profile/preview and
    /profile/import (JSON APIs) are unaffected and still return 401.
    """
    monkeypatch.setenv("MOOTOS_PASSWORD", "private-password")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "s" * 32)
    client = TestClient(app)

    default_accept = client.get("/profile", follow_redirects=False)
    assert default_accept.status_code == 303
    assert default_accept.headers["location"] == "/login?next=/profile"

    preview = client.post("/profile/preview", json=reviewed_manifest())
    assert preview.status_code == 401


def test_profile_preview_and_import_have_private_response_headers(clean_db):
    client = TestClient(app)

    preview = client.post("/profile/preview", json=reviewed_manifest())
    imported = client.post("/profile/import", json=reviewed_manifest())

    for response in (preview, imported):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "same-origin"

    assert preview.json()["data"]["counts"]["ready"] == 2
    assert imported.json()["data"]["counts"]["imported"] == 2


def test_profile_browser_uses_safe_text_rendering_and_no_provider_endpoint(clean_db):
    source = Path("frontend/profile.js").read_text(encoding="utf-8")

    assert 'textContent = entry.content' in source
    assert "innerHTML" not in source
    assert 'fetch("/profile/preview"' not in source
    assert 'requestJson("/profile/preview"' in source
    assert 'requestJson("/profile/import"' in source
    assert "/chat" not in source
    assert "OPENAI" not in source.upper()


def test_railway_uses_composed_application_entrypoint(clean_db):
    config = Path("railway.toml").read_text(encoding="utf-8")

    assert "backend.application:app" in config
    assert "backend.main:app" not in config
    assert 'healthcheckPath = "/ready"' in config
