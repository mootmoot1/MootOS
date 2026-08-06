"""HTTP routes for reviewed bootstrap-profile preview and import."""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.bootstrap_profile import (
    BootstrapProfileConflictError,
    BootstrapProfileStorageError,
    BootstrapProfileValidationError,
    import_bootstrap_profile,
    preview_bootstrap_profile,
)


router = APIRouter(prefix="/profile", tags=["profile"])


class BootstrapProfileManifest(BaseModel):
    """Private reviewed profile manifest submitted by the authenticated user."""

    version: int
    entries: list[dict[str, Any]]


def _manifest_dict(manifest: BootstrapProfileManifest) -> dict[str, Any]:
    """Return a normal dictionary across supported Pydantic versions."""
    if hasattr(manifest, "model_dump"):
        return manifest.model_dump()
    return manifest.dict()


@router.post("/preview")
def preview_profile(manifest: BootstrapProfileManifest) -> dict[str, Any]:
    """Validate and classify a private profile without changing storage."""
    try:
        preview = preview_bootstrap_profile(_manifest_dict(manifest))
    except BootstrapProfileValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except BootstrapProfileStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MootOS could not preview the profile safely",
        ) from error

    return {"success": True, "data": preview}


@router.post("/import", status_code=status.HTTP_201_CREATED)
def import_profile(manifest: BootstrapProfileManifest) -> dict[str, Any]:
    """Atomically import every ready entry after revalidation."""
    try:
        imported = import_bootstrap_profile(_manifest_dict(manifest))
    except BootstrapProfileValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except BootstrapProfileConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except BootstrapProfileStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MootOS could not import the profile safely",
        ) from error

    return {"success": True, "data": imported}
