"""The four V0.2A reference tools: projects.list, memory.search, tasks.list,
tasks.create.

Every executor here is a thin adapter over an existing, already-tested
domain helper (``backend.memory``, ``backend.memory_retrieval``,
``backend.tasks``). None of them re-implements storage, ranking, or
validation that already exists; none of them calls MootOS's own HTTP API
from inside the backend process.
"""

from typing import Any

from backend.memory import MEMORY_STATUS_ACTIVE
from backend.memory import list_projects as _load_projects
from backend.memory_retrieval import search_memories as _search_memories
from backend.runs import DATA_EXPOSURE_LOCAL
from backend.tasks import TASK_STATUSES, create_task as _create_task, list_tasks as _list_tasks
from backend.tool_registry import ToolRegistry
from backend.tool_types import (
    RISK_INTERNAL_WRITE,
    RISK_READ_ONLY,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionError,
)


TOOL_VERSION = "1"

MEMORY_SEARCH_DEFAULT_LIMIT = 10
MEMORY_SEARCH_MAX_LIMIT = 50
TASKS_LIST_DEFAULT_LIMIT = 20
TASKS_LIST_MAX_LIMIT = 100


# --- projects.list -----------------------------------------------------------


def _projects_list(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    projects = _load_projects()
    return {"projects": projects, "count": len(projects)}


PROJECTS_LIST = ToolDefinition(
    name="projects.list",
    version=TOOL_VERSION,
    description="List every currently stored MootOS project.",
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    risk=RISK_READ_ONLY,
    data_exposure=DATA_EXPOSURE_LOCAL,
    executor=_projects_list,
)


# --- memory.search -------------------------------------------------------------


def _memory_search(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    query = arguments["query"]
    project = arguments.get("project")
    limit = arguments.get("limit", MEMORY_SEARCH_DEFAULT_LIMIT)

    try:
        results = _search_memories(
            query=query,
            project=project,
            memory_status=MEMORY_STATUS_ACTIVE,
        )
    except ValueError as error:
        raise ToolExecutionError(str(error)) from error

    bounded = results[:limit]
    return {"memories": bounded, "count": len(bounded), "query": query}


MEMORY_SEARCH = ToolDefinition(
    name="memory.search",
    version=TOOL_VERSION,
    description="Search MootOS active long-term memory by keyword.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 500},
            "project": {"type": "string", "minLength": 1, "maxLength": 100},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MEMORY_SEARCH_MAX_LIMIT,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    risk=RISK_READ_ONLY,
    data_exposure=DATA_EXPOSURE_LOCAL,
    executor=_memory_search,
)


# --- tasks.list ------------------------------------------------------------------


def _tasks_list(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    status = arguments.get("status")
    project = arguments.get("project")
    limit = arguments.get("limit", TASKS_LIST_DEFAULT_LIMIT)

    try:
        tasks = _list_tasks(status=status, project=project, limit=limit)
    except ValueError as error:
        raise ToolExecutionError(str(error)) from error

    return {"tasks": tasks, "count": len(tasks)}


TASKS_LIST = ToolDefinition(
    name="tasks.list",
    version=TOOL_VERSION,
    description="List MootOS Tasks, optionally filtered by status and project.",
    input_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": sorted(TASK_STATUSES)},
            "project": {"type": "string", "minLength": 1, "maxLength": 100},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": TASKS_LIST_MAX_LIMIT,
            },
        },
        "required": [],
        "additionalProperties": False,
    },
    risk=RISK_READ_ONLY,
    data_exposure=DATA_EXPOSURE_LOCAL,
    executor=_tasks_list,
)


# --- tasks.create (INTERNAL_WRITE -- requires approval) ------------------------


def _tasks_create(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    try:
        task = _create_task(
            title=arguments["title"],
            project=arguments.get("project"),
            due_at=arguments.get("due_at"),
        )
    except ValueError as error:
        raise ToolExecutionError(str(error)) from error

    return {"task": task, "id": task["id"]}


TASKS_CREATE = ToolDefinition(
    name="tasks.create",
    version=TOOL_VERSION,
    description=(
        "Prepare one open MootOS Task for creation. Call this tool as soon as the user "
        "clearly asks to create/add a Task and you already know the title -- do not ask "
        "a separate chat question to confirm first. Calling this tool never creates the "
        "Task by itself: MootOS freezes the exact call and shows the user a real "
        "Approve/Reject control; the Task is only created if they approve it there. "
        "Only set project or due_at if the user explicitly stated one in this "
        "conversation -- never invent, guess, or default a due date or a project. "
        "If no due time was requested, omit due_at entirely from the call -- do not send "
        "\"none\", \"null\", \"unknown\", \"N/A\", an empty string, or any other "
        "placeholder in its place; omitting the field is the only correct way to leave it "
        "unset. When due_at is provided, it must be a real timezone-aware ISO 8601 "
        "datetime such as \"2026-08-10T15:00:00-04:00\" or \"2026-08-10T19:00:00Z\" -- a "
        "date or time without a timezone, or anything that is not an actual datetime, is "
        "rejected. No other fields exist (no description, priority, or tags)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 500},
            "project": {"type": "string", "minLength": 1, "maxLength": 100},
            "due_at": {"type": "string", "minLength": 1, "maxLength": 64, "format": "utc-datetime"},
        },
        "required": ["title"],
        "additionalProperties": False,
    },
    risk=RISK_INTERNAL_WRITE,
    data_exposure=DATA_EXPOSURE_LOCAL,
    executor=_tasks_create,
)


REFERENCE_TOOLS = (PROJECTS_LIST, MEMORY_SEARCH, TASKS_LIST, TASKS_CREATE)


def register_reference_tools(registry: ToolRegistry) -> None:
    """Register the four V0.2A reference tools on ``registry``, in order."""
    for definition in REFERENCE_TOOLS:
        registry.register(definition)
