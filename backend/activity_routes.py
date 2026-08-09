"""Read-only activity/log routes for the MootOS interface.

This module adds no new durable storage. It exposes existing,
already-tested storage helpers over HTTP, each behind the same
authenticated boundary as every other private route:

- ``backend.runs.list_runs`` (unchanged) for recent model-run execution
  metadata. Run rows already exclude prompt/response content and raw
  provider errors (see ``docs/MODEL_RUN_LOGGING.md`` and
  ``tests/test_runs.py``); this route does not change that contract, only
  reads it.
- ``backend.tasks.list_recent_tasks`` (new, additive) for recent Tasks
  ordered by creation recency. The existing ``GET /tasks`` orders due
  tasks before unscheduled ones for the Task viewer, which is not
  creation recency; this route intentionally uses a separate query so
  Activity's "recent" label is accurate without changing ``/tasks`` for
  its existing consumers.
- ``backend.memory.list_recent_active_memories`` (new, additive) for
  recent active memories, server-side limited. ``GET /memories`` is
  unchanged and still returns the full unlimited listing for its
  existing consumers (the Memory review page).
"""

import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.memory import list_recent_active_memories
from backend.runs import list_runs
from backend.tasks import list_recent_tasks


router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/runs")
def list_recent_runs(
    conversation_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return recent model-run execution metadata, newest first."""
    try:
        runs = list_runs(conversation_id=conversation_id, limit=limit)
    except sqlite3.Error as error:
        raise HTTPException(
            status_code=503,
            detail="MootOS could not load recent activity.",
        ) from error
    return {"success": True, "data": runs}


@router.get("/tasks")
def list_recent_tasks_route(
    limit: int = Query(default=15, ge=1, le=200),
) -> dict[str, Any]:
    """Return recently created Tasks, newest first, for the Activity feed."""
    try:
        tasks = list_recent_tasks(limit=limit)
    except sqlite3.Error as error:
        raise HTTPException(
            status_code=503,
            detail="MootOS could not load recent activity.",
        ) from error
    return {"success": True, "data": tasks}


@router.get("/memories")
def list_recent_memories_route(
    limit: int = Query(default=15, ge=1, le=200),
) -> dict[str, Any]:
    """Return recently created active memories, newest first, bounded."""
    try:
        memories = list_recent_active_memories(limit=limit)
    except sqlite3.Error as error:
        raise HTTPException(
            status_code=503,
            detail="MootOS could not load recent activity.",
        ) from error
    return {"success": True, "data": memories}
