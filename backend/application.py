"""MootOS application composition root.

This module composes the verified Version 0.1 app with focused feature routers
without changing the existing chat and memory implementation boundaries.
"""

from fastapi.responses import FileResponse

from backend.main import FRONTEND_DIR, app
from backend.profile_routes import router as profile_router
from backend.task_routes import router as task_router


app.include_router(profile_router)
app.include_router(task_router)


@app.get("/profile", include_in_schema=False)
def profile_interface() -> FileResponse:
    """Serve the authenticated bootstrap-profile review and import page."""
    return FileResponse(FRONTEND_DIR / "profile.html")
