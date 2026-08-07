"""Authenticated HTTP API for the MootOS Task primitive."""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.tasks import (
    TASK_STATUSES,
    TaskAlreadyFinishedError,
    TaskNotFoundError,
    cancel_task,
    complete_task,
    create_task,
    get_task,
    list_tasks,
)


router = APIRouter()


class TaskCreate(BaseModel):
    """Input accepted when creating a Task."""

    title: str = Field(min_length=1, max_length=500)
    project: Optional[str] = Field(default=None, max_length=100)
    due_at: Optional[datetime] = None


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task_route(request: TaskCreate) -> dict[str, Any]:
    """Create one open Task."""
    try:
        task = create_task(
            title=request.title,
            project=request.project,
            due_at=request.due_at.isoformat() if request.due_at is not None else None,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"success": True, "data": task}


@router.get("/tasks")
def list_tasks_route(
    task_status: Optional[str] = Query(default=None, alias="status"),
    project: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """List Tasks, optionally filtered by lifecycle state and project."""
    if task_status is not None and task_status not in TASK_STATUSES:
        raise HTTPException(status_code=422, detail="Unsupported task status")
    try:
        tasks = list_tasks(status=task_status, project=project, limit=limit)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"success": True, "data": tasks}


@router.get("/tasks/{task_id}")
def get_task_route(task_id: str) -> dict[str, Any]:
    """Retrieve one Task by ID."""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "data": task}


@router.post("/tasks/{task_id}/complete")
def complete_task_route(task_id: str) -> dict[str, Any]:
    """Complete one open Task."""
    try:
        task = complete_task(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="Task not found") from error
    except TaskAlreadyFinishedError as error:
        raise HTTPException(status_code=409, detail="Task is already finished") from error
    return {"success": True, "data": task}


@router.post("/tasks/{task_id}/cancel")
def cancel_task_route(task_id: str) -> dict[str, Any]:
    """Cancel one open Task."""
    try:
        task = cancel_task(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="Task not found") from error
    except TaskAlreadyFinishedError as error:
        raise HTTPException(status_code=409, detail="Task is already finished") from error
    return {"success": True, "data": task}
