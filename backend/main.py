"""FastAPI application for MootOS."""

from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.auth import (
    auth_enabled,
    clear_session_cookie,
    password_matches,
    request_is_authenticated,
    set_session_cookie,
    validate_auth_configuration,
)
from backend.chat_memory import (
    ConversationNotFoundError,
    ProjectMismatchError,
    ProjectNotFoundError,
    save_explicit_memory_chat,
)
from backend.conversation import (
    add_message as store_message,
    create_conversation as store_conversation,
    get_conversation as load_conversation,
    list_conversations as load_conversations,
    list_messages as load_messages,
)
from backend.memory import (
    MemoryArchiveConflictError,
    MemoryCorrectionConflictError,
    MemoryHistoryProtectedError,
    MemoryNotActiveError,
    MemoryNotFoundError,
    MemoryRestoreConflictError,
    archive_memory as archive_saved_memory,
    correct_memory as replace_memory,
    create_project as store_project,
    create_memory as store_memory,
    delete_memory as remove_memory,
    get_memory as load_memory,
    get_memory_history as load_memory_history,
    init_db,
    list_projects as load_projects,
    restore_memory as restore_saved_memory,
)
from backend.memory_commands import parse_memory_save_command
from backend.memory_retrieval import retrieve_context_memories, search_memories
from backend.model_router import (
    ModelConfigurationError,
    ModelProviderError,
    get_model_router,
)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
PUBLIC_PATHS = {
    "/auth/login",
    "/auth/logout",
    "/health",
    "/login",
    "/manifest.webmanifest",
}
HTML_PATHS = {"/", "/chat", "/memory", "/docs", "/redoc"}
MAX_MEMORY_CONTENT_LENGTH = 10_000
MAX_MEMORY_SEARCH_LENGTH = 500

validate_auth_configuration()

app = FastAPI(
    title="MootOS",
    description="The backend foundation for MootOS.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
init_db()

BASE_INSTRUCTIONS = """You are MootOS Version 0.1, Moot's personal AI operating system.
Your job is to hold one continuous, useful conversation; organize projects; and use
relevant saved memories without pretending to know facts that are not provided.
Speak clearly and naturally. Ask a question only when it is actually necessary.
When Moot corrects old information, treat the correction as more reliable than the
older memory. Never claim that you completed an outside action unless it truly ran.
Never claim that long-term memory was saved unless MootOS actually completed a
memory write. Explicit commands beginning with "remember" or "save this" are
handled by MootOS storage before a confirmation is returned.
"""


class LoginRequest(BaseModel):
    """Password submitted by the private deployment login page."""

    password: str = Field(min_length=1, max_length=1_000)


class MemoryCreate(BaseModel):
    """Input accepted when creating a memory."""

    content: str = Field(min_length=1, max_length=MAX_MEMORY_CONTENT_LENGTH)
    project: Optional[str] = None
    memory_type: Optional[str] = None


class MemoryCorrection(BaseModel):
    """Input accepted when replacing one active memory version."""

    content: str = Field(min_length=1, max_length=MAX_MEMORY_CONTENT_LENGTH)


class MemorySearchRequest(BaseModel):
    """Private read-only keyword search submitted in the request body."""

    query: str = Field(min_length=1, max_length=MAX_MEMORY_SEARCH_LENGTH)
    project: Optional[str] = None
    status: str = "active"


class ProjectCreate(BaseModel):
    """Input accepted when creating a project."""

    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)


class ConversationCreate(BaseModel):
    """Input accepted when creating a conversation."""

    project: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=100)


class ChatRequest(BaseModel):
    """Input accepted by the MootOS conversation loop."""

    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: Optional[str] = None
    project: Optional[str] = None


@app.middleware("http")
async def require_private_session(request: Request, call_next):
    """Protect the interface and APIs when production auth is configured."""
    path = request.url.path
    if (
        not auth_enabled()
        or path in PUBLIC_PATHS
        or path.startswith("/static/")
        or request_is_authenticated(request)
    ):
        return await call_next(request)

    accepts_html = "text/html" in request.headers.get("accept", "")
    if request.method == "GET" and (path in HTML_PATHS or accepts_html):
        destination = quote(path if path.startswith("/") else "/chat", safe="/")
        return RedirectResponse(url=f"/login?next={destination}", status_code=303)

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Authentication required"},
    )


def _build_model_instructions(project: Optional[str], query: str = "") -> str:
    """Build identity plus keyword-ranked active memory context."""
    memories = retrieve_context_memories(project=project, query=query, limit=20)
    if not memories:
        return BASE_INSTRUCTIONS

    memory_lines = []
    for memory in memories:
        memory_type = memory["memory_type"] or "memory"
        memory_project = memory["project"] or "Global"
        memory_lines.append(
            f"- [{memory_project} / {memory_type}] {memory['content']}"
        )

    return (
        BASE_INSTRUCTIONS
        + "\nRelevant long-term memory context:\n"
        + "\n".join(memory_lines)
        + "\nUse this context only when it helps answer the current request."
    )


def _get_conversation_or_404(conversation_id: str) -> dict[str, Any]:
    conversation = load_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _chat_response(
    conversation: dict[str, Any],
    user_message: dict[str, Any],
    assistant_message: dict[str, Any],
    provider: Optional[str],
    model: Optional[str],
) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "conversation_id": conversation["id"],
            "project": conversation["project"],
            "user_message": user_message,
            "assistant_message": assistant_message,
            "provider": provider,
            "model": model,
        },
    }


@app.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    """Open the normal MootOS experience instead of a raw status payload."""
    return RedirectResponse(url="/chat", status_code=307)


@app.get("/login", include_in_schema=False)
def login_page(request: Request):
    """Serve the password screen for private cloud deployments."""
    if not auth_enabled() or request_is_authenticated(request):
        return RedirectResponse(url="/chat", status_code=303)
    return FileResponse(FRONTEND_DIR / "login.html")


@app.post("/auth/login", include_in_schema=False)
def login(credentials: LoginRequest):
    """Create a signed browser session after a valid password."""
    if auth_enabled() and not password_matches(credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
        )

    response = JSONResponse({"success": True})
    if auth_enabled():
        set_session_cookie(response)
    return response


@app.post("/auth/logout", include_in_schema=False)
def logout() -> RedirectResponse:
    """Clear the private session and return to the login page."""
    response = RedirectResponse(url="/login", status_code=303)
    clear_session_cookie(response)
    return response


@app.get("/chat", include_in_schema=False)
def chat_interface() -> FileResponse:
    """Serve the mobile-friendly MootOS chat interface."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/memory", include_in_schema=False)
def memory_interface() -> FileResponse:
    """Serve the long-term-memory review and lifecycle interface."""
    return FileResponse(FRONTEND_DIR / "memory.html")


@app.get("/manifest.webmanifest", include_in_schema=False)
def web_manifest() -> FileResponse:
    """Serve install metadata for adding MootOS to a phone home screen."""
    return FileResponse(
        FRONTEND_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    """Return a public health check for Railway deployments."""
    return {"status": "healthy"}


@app.post("/memories", status_code=status.HTTP_201_CREATED)
def create_memory(memory: MemoryCreate) -> dict[str, Any]:
    """Create and persist a memory."""
    try:
        saved_memory = store_memory(
            content=memory.content,
            project=memory.project,
            memory_type=memory.memory_type,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "success": True,
        "data": saved_memory,
    }


@app.get("/memories")
def list_memories(
    project: Optional[str] = None,
    memory_status: str = Query(default="active", alias="status"),
) -> dict[str, Any]:
    """List active or archived memories, optionally filtered by project."""
    if memory_status not in {"active", "archived"}:
        raise HTTPException(
            status_code=422,
            detail="Memory status must be active or archived",
        )
    try:
        memories = search_memories(
            query=None,
            project=project,
            memory_status=memory_status,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"success": True, "data": memories}


@app.post("/memories/search")
def search_memory_list(search: MemorySearchRequest) -> dict[str, Any]:
    """Search active or archived memories without placing terms in the URL."""
    query = search.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Search query cannot be empty")
    if search.status not in {"active", "archived"}:
        raise HTTPException(
            status_code=422,
            detail="Memory status must be active or archived",
        )
    try:
        memories = search_memories(
            query=query,
            project=search.project,
            memory_status=search.status,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"success": True, "data": memories}


@app.get("/memories/{memory_id}/history")
def get_memory_history(memory_id: str) -> dict[str, Any]:
    """Return one preserved memory correction chain oldest first."""
    history = load_memory_history(memory_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"success": True, "data": history}


@app.post(
    "/memories/{memory_id}/corrections",
    status_code=status.HTTP_201_CREATED,
)
def correct_memory(
    memory_id: str,
    correction: MemoryCorrection,
) -> dict[str, Any]:
    """Create a corrected active version and supersede the selected memory."""
    corrected_content = correction.content.strip()
    if not corrected_content:
        raise HTTPException(
            status_code=422,
            detail="Corrected memory content cannot be empty",
        )

    try:
        result = replace_memory(memory_id, corrected_content)
    except MemoryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (MemoryNotActiveError, MemoryCorrectionConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "data": result}


@app.post("/memories/{memory_id}/archive")
def archive_memory(memory_id: str) -> dict[str, Any]:
    """Recoverably forget one selected active memory."""
    try:
        archived = archive_saved_memory(memory_id)
    except MemoryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except MemoryArchiveConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "data": archived}


@app.post("/memories/{memory_id}/restore")
def restore_memory(memory_id: str) -> dict[str, Any]:
    """Restore one selected archived memory to normal recall."""
    try:
        restored = restore_saved_memory(memory_id)
    except MemoryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except MemoryRestoreConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "data": restored}


@app.get("/memories/{memory_id}")
def get_memory(memory_id: str) -> dict[str, Any]:
    """Retrieve one saved memory version by ID."""
    memory = load_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"success": True, "data": memory}


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: str) -> dict[str, Any]:
    """Delete a standalone active memory without breaking lifecycle history."""
    try:
        removed = remove_memory(memory_id)
    except MemoryHistoryProtectedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not removed:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"success": True, "data": {"id": memory_id, "status": "deleted"}}


@app.get("/projects")
def list_projects() -> dict[str, Any]:
    """List all available projects."""
    return {"success": True, "data": load_projects()}


@app.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(project: ProjectCreate) -> dict[str, Any]:
    """Create a project."""
    try:
        saved_project = store_project(
            name=project.name,
            description=project.description,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "data": saved_project}


@app.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(conversation: ConversationCreate) -> dict[str, Any]:
    """Create a persistent conversation."""
    try:
        saved_conversation = store_conversation(
            project=conversation.project,
            title=conversation.title,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"success": True, "data": saved_conversation}


@app.get("/conversations")
def list_conversations(project: Optional[str] = None) -> dict[str, Any]:
    """List conversations, optionally filtered by project."""
    try:
        conversations = load_conversations(project=project)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"success": True, "data": conversations}


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    """Retrieve one conversation and all of its messages."""
    return {"success": True, "data": _get_conversation_or_404(conversation_id)}


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    """Run conversation or an explicit long-term-memory save command."""
    memory_command = parse_memory_save_command(request.message)
    if memory_command and len(memory_command.content) > MAX_MEMORY_CONTENT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail="Memory content must be 10,000 characters or fewer",
        )

    if memory_command is not None:
        try:
            saved_turn = save_explicit_memory_chat(
                request_message=request.message,
                memory_content=memory_command.content,
                conversation_id=request.conversation_id,
                project=request.project,
                title=request.message.strip()[:80],
            )
        except ConversationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ProjectMismatchError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        return _chat_response(
            conversation=saved_turn["conversation"],
            user_message=saved_turn["user_message"],
            assistant_message=saved_turn["assistant_message"],
            provider="mootos",
            model="memory-command-v1",
        )

    router = get_model_router()
    try:
        router.ensure_ready()
    except ModelConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if request.conversation_id:
        conversation = _get_conversation_or_404(request.conversation_id)
        if request.project is not None:
            existing_project = conversation["project"] or ""
            if existing_project.casefold() != request.project.casefold():
                raise HTTPException(
                    status_code=409,
                    detail="The requested project does not match this conversation",
                )
    else:
        try:
            conversation = store_conversation(
                project=request.project,
                title=request.message.strip()[:80],
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    user_message = store_message(
        conversation_id=conversation["id"],
        role="user",
        content=request.message,
    )
    history = load_messages(conversation["id"], limit=20)
    model_messages = [
        {"role": message["role"], "content": message["content"]}
        for message in history
    ]

    try:
        model_response = router.generate(
            messages=model_messages,
            instructions=_build_model_instructions(
                conversation["project"],
                request.message,
            ),
        )
    except ModelConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ModelProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    assistant_message = store_message(
        conversation_id=conversation["id"],
        role="assistant",
        content=model_response.text,
        provider=model_response.provider,
        model=model_response.model,
    )
    return _chat_response(
        conversation=conversation,
        user_message=user_message,
        assistant_message=assistant_message,
        provider=model_response.provider,
        model=model_response.model,
    )
