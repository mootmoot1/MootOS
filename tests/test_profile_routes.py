"""Focused HTTP contract tests for the bootstrap-profile API router."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.profile_routes as profile_routes


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(profile_routes.router)
    return TestClient(app)


def sample_manifest():
    return {
        "version": 1,
        "entries": [
            {"content": "Use plain explanations.", "project": None},
        ],
    }


def test_preview_returns_classification_without_import(monkeypatch):
    calls = []

    def fake_preview(manifest):
        calls.append(manifest)
        return {
            "version": 1,
            "ready": manifest["entries"],
            "already_active": [],
            "blocked": [],
            "counts": {
                "ready": 1,
                "already_active": 0,
                "blocked": 0,
                "total": 1,
            },
            "can_import": True,
        }

    def fail_import(_manifest):
        raise AssertionError("preview must not import")

    monkeypatch.setattr(profile_routes, "preview_bootstrap_profile", fake_preview)
    monkeypatch.setattr(profile_routes, "import_bootstrap_profile", fail_import)

    response = make_client().post("/profile/preview", json=sample_manifest())

    assert response.status_code == 200
    assert response.json()["data"]["can_import"] is True
    assert calls == [sample_manifest()]


def test_import_returns_created_result(monkeypatch):
    def fake_import(manifest):
        return {
            "version": 1,
            "imported": manifest["entries"],
            "already_active": [],
            "counts": {"imported": 1, "already_active": 0, "total": 1},
        }

    monkeypatch.setattr(profile_routes, "import_bootstrap_profile", fake_import)

    response = make_client().post("/profile/import", json=sample_manifest())

    assert response.status_code == 201
    assert response.json()["data"]["counts"]["imported"] == 1


def test_validation_error_is_422(monkeypatch):
    def fail_preview(_manifest):
        raise profile_routes.BootstrapProfileValidationError("Invalid profile")

    monkeypatch.setattr(profile_routes, "preview_bootstrap_profile", fail_preview)

    response = make_client().post("/profile/preview", json=sample_manifest())

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid profile"}


def test_lifecycle_conflict_is_409(monkeypatch):
    def fail_import(_manifest):
        raise profile_routes.BootstrapProfileConflictError("Profile is blocked")

    monkeypatch.setattr(profile_routes, "import_bootstrap_profile", fail_import)

    response = make_client().post("/profile/import", json=sample_manifest())

    assert response.status_code == 409
    assert response.json() == {"detail": "Profile is blocked"}


def test_storage_failures_are_sanitized(monkeypatch):
    def fail_preview(_manifest):
        raise profile_routes.BootstrapProfileStorageError(
            "private database path and sqlite details"
        )

    def fail_import(_manifest):
        raise profile_routes.BootstrapProfileStorageError(
            "private database path and sqlite details"
        )

    monkeypatch.setattr(profile_routes, "preview_bootstrap_profile", fail_preview)
    preview_response = make_client().post(
        "/profile/preview",
        json=sample_manifest(),
    )

    monkeypatch.setattr(profile_routes, "import_bootstrap_profile", fail_import)
    import_response = make_client().post(
        "/profile/import",
        json=sample_manifest(),
    )

    assert preview_response.status_code == 503
    assert preview_response.json() == {
        "detail": "MootOS could not preview the profile safely"
    }
    assert import_response.status_code == 503
    assert import_response.json() == {
        "detail": "MootOS could not import the profile safely"
    }
    assert "private database" not in preview_response.text
    assert "private database" not in import_response.text


def test_request_shape_requires_version_and_entries():
    response = make_client().post("/profile/preview", json={})

    assert response.status_code == 422
