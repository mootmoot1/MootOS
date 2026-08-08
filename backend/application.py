"""MootOS application composition root.

This module composes the verified Version 0.1 app with focused feature routers
without changing the existing chat and memory implementation boundaries.
"""

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse

from backend.auth import auth_enabled, request_is_authenticated
from backend.chat_task import (
    ConversationNotFoundError,
    ProjectMismatchError,
    ProjectNotFoundError,
    create_explicit_task_chat,
)
from backend.main import FRONTEND_DIR, app
from backend.profile_routes import router as profile_router
from backend.task_commands import parse_task_create_command
from backend.task_routes import router as task_router


app.include_router(profile_router)
app.include_router(task_router)


@app.middleware("http")
async def route_explicit_task_chat_commands(request: Request, call_next):
    """Intercept only deterministic create-task chat commands.

    The main /chat handler remains authoritative for ordinary conversation and
    memory commands. Authentication is deliberately left to the existing app
    middleware unless the request already carries a valid private session.
    """
    if request.method != "POST" or request.url.path != "/chat":
        return await call_next(request)
    if auth_enabled() and not request_is_authenticated(request):
        return await call_next(request)

    try:
        payload = await request.json()
    except Exception:
        return await call_next(request)
    if not isinstance(payload, dict):
        return await call_next(request)

    message = payload.get("message")
    conversation_id = payload.get("conversation_id")
    project = payload.get("project")
    if not isinstance(message, str) or not (1 <= len(message) <= 20_000):
        return await call_next(request)
    if conversation_id is not None and not isinstance(conversation_id, str):
        return await call_next(request)
    if project is not None and not isinstance(project, str):
        return await call_next(request)

    command = parse_task_create_command(message)
    if command is None:
        return await call_next(request)

    try:
        saved_turn = create_explicit_task_chat(
            request_message=message,
            task_title=command.title,
            conversation_id=conversation_id,
            project=project,
            title=message.strip()[:80],
        )
    except ConversationNotFoundError as error:
        return JSONResponse(status_code=404, content={"detail": str(error)})
    except ProjectMismatchError as error:
        return JSONResponse(status_code=409, content={"detail": str(error)})
    except (ProjectNotFoundError, ValueError) as error:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    conversation = saved_turn["conversation"]
    return JSONResponse(
        {
            "success": True,
            "data": {
                "conversation_id": conversation["id"],
                "project": conversation["project"],
                "user_message": saved_turn["user_message"],
                "assistant_message": saved_turn["assistant_message"],
                "task": saved_turn["task"],
                "provider": "mootos",
                "model": "task-command-v1",
            },
        }
    )


@app.get("/profile", include_in_schema=False)
def profile_interface() -> FileResponse:
    """Serve the authenticated bootstrap-profile review and import page."""
    return FileResponse(FRONTEND_DIR / "profile.html")
