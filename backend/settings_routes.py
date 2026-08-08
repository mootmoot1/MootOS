"""Read-only settings/status routes for the MootOS interface.

MootOS keeps model-provider configuration in environment variables, per the
replaceable-provider architecture in ``backend/model_router.py``. This module
does not add a mutable settings store or a settings table. It exposes the
already-configured, non-secret parts of that configuration (provider name,
model name, supported schema version) so the browser can show Moot what is
currently active without ever reading or echoing back a secret value.

Deliberately out of scope here: persisting settings, switching providers at
runtime, or storing any credential in SQLite. See the final PR report for the
reasoning.
"""

from typing import Any

from fastapi import APIRouter

from backend.main import _router_run_metadata
from backend.migrations import LATEST_SCHEMA_VERSION
from backend.model_router import get_model_router


router = APIRouter(prefix="/settings", tags=["settings"])

APP_VERSION = "0.1.0"


@router.get("/status")
def get_settings_status() -> dict[str, Any]:
    """Return the current non-secret model-provider and schema configuration."""
    router_instance = get_model_router()
    provider, model = _router_run_metadata(router_instance)

    return {
        "success": True,
        "data": {
            "app_version": APP_VERSION,
            "provider": provider,
            "model": model,
            "schema_version": LATEST_SCHEMA_VERSION,
        },
    }
