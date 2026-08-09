"""MootOS application composition root.

This module composes the verified Version 0.1 app with focused feature routers.
Deterministic chat-command dispatch belongs to the core /chat route in backend.main.
"""

from fastapi.responses import FileResponse

from backend.activity_routes import router as activity_router
from backend.main import FRONTEND_DIR, app
from backend.profile_routes import router as profile_router
from backend.settings_routes import router as settings_router
from backend.task_routes import router as task_router


app.include_router(profile_router)
app.include_router(task_router)
app.include_router(activity_router)
app.include_router(settings_router)


@app.get("/profile", include_in_schema=False)
def profile_interface() -> FileResponse:
    """Serve the authenticated bootstrap-profile review and import page."""
    return FileResponse(FRONTEND_DIR / "profile.html")


@app.get("/task", include_in_schema=False)
def task_interface() -> FileResponse:
    """Serve the authenticated Task viewer/creation page.

    Named singular to avoid colliding with the existing plural ``/tasks`` JSON
    API, matching the existing ``/memory`` (page) vs ``/memories`` (API)
    convention.
    """
    return FileResponse(FRONTEND_DIR / "task.html")


@app.get("/activity", include_in_schema=False)
def activity_interface() -> FileResponse:
    """Serve the authenticated activity/log viewer page."""
    return FileResponse(FRONTEND_DIR / "activity.html")


@app.get("/settings", include_in_schema=False)
def settings_interface() -> FileResponse:
    """Serve the authenticated read-only settings/status page."""
    return FileResponse(FRONTEND_DIR / "settings.html")
