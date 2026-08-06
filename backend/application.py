"""MootOS application composition root.

This module extends the verified Version 0.1 app with the curated private-profile
workflow while keeping the existing chat and memory implementation unchanged.
"""

from fastapi.responses import FileResponse

from backend.main import FRONTEND_DIR, app
from backend.profile_routes import router as profile_router


app.include_router(profile_router)


@app.get("/profile", include_in_schema=False)
def profile_interface() -> FileResponse:
    """Serve the authenticated bootstrap-profile review and import page."""
    return FileResponse(FRONTEND_DIR / "profile.html")
