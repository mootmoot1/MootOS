"""SQLite-backed task lifecycle for MootOS."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db import database_connection
from backend.time_utils import normalize_optional_utc_datetime


TASK_STATUS_OPEN = "open"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_CANCELLED = "cancelled"
TASK_STATUSES = {TASK_STATUS_OPEN, TASK_STATUS_COMPLETED, TASK_STATUS_CANCELLED}
TASK_COLUMNS = """
    id,
    title,
    project,
    status,
    due_at,
    created_at,
    updated_at,
    completed_at,
    cancelled_at
"""


class TaskNotFoundError(ValueError):
    """Raised when a requested task does not exist."""


class TaskAlreadyFinishedError(ValueError):
    """Raised when a terminal task is completed or cancelled again."""


def _normalize_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise ValueError("Task title cannot be empty")
    if len(normalized) > 500:
        raise ValueError("Task title must be 500 characters or fewer")
    return normalized


def _normalize_due_at(due_at: Optional[str]) -> Optional[str]:
    return normalize_optional_utc_datetime(due_at, field_name="Task due_at")


def _get_project_name(connection: sqlite3.Connection, project: str) -> str:
    row = connection.execute(
        "SELECT name FROM projects WHERE name = ? COLLATE NOCASE",
        (project,),
    ).fetchone()
    if row is None:
        raise ValueError("Project does not exist")
    return str(row["name"])


def _get_task(connection: sqlite3.Connection, task_id: str) -> Optional[dict[str, Any]]:
    row = connection.execute(
        f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    return dict(row) if row else None


def create_task_in_connection(
    connection: sqlite3.Connection,
    title: str,
    project: Optional[str] = None,
    due_at: Optional[str] = None,
) -> dict[str, Any]:
    """Create an open task using the caller's existing transaction."""
    normalized_title = _normalize_title(title)
    normalized_due_at = _normalize_due_at(due_at)

    canonical_project = None
    if project is not None:
        canonical_project = _get_project_name(connection, project)

    now = datetime.now(timezone.utc).isoformat()
    task = {
        "id": str(uuid.uuid4()),
        "title": normalized_title,
        "project": canonical_project,
        "status": TASK_STATUS_OPEN,
        "due_at": normalized_due_at,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "cancelled_at": None,
    }
    connection.execute(
        """
        INSERT INTO tasks (
            id, title, project, status, due_at,
            created_at, updated_at, completed_at, cancelled_at
        )
        VALUES (
            :id, :title, :project, :status, :due_at,
            :created_at, :updated_at, :completed_at, :cancelled_at
        )
        """,
        task,
    )
    return task


def create_task(
    title: str,
    project: Optional[str] = None,
    due_at: Optional[str] = None,
) -> dict[str, Any]:
    """Create an open task with optional project scope and due time."""
    with database_connection() as connection:
        return create_task_in_connection(connection, title, project, due_at)


def get_task(task_id: str) -> Optional[dict[str, Any]]:
    """Return one task by ID."""
    with database_connection() as connection:
        return _get_task(connection, task_id)


def list_tasks(
    status: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List tasks by status/project with due tasks ordered first."""
    if status is not None and status not in TASK_STATUSES:
        raise ValueError("Unsupported task status")
    limit = max(1, min(int(limit), 500))

    with database_connection() as connection:
        canonical_project = None
        if project is not None:
            canonical_project = _get_project_name(connection, project)

        clauses = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if project is not None:
            clauses.append("project = ?")
            params.append(canonical_project)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = connection.execute(
            f"""
            SELECT {TASK_COLUMNS}
            FROM tasks
            {where}
            ORDER BY
                CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,
                due_at ASC,
                created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def _finish_task(task_id: str, target_status: str) -> dict[str, Any]:
    if target_status not in {TASK_STATUS_COMPLETED, TASK_STATUS_CANCELLED}:
        raise ValueError("Unsupported terminal task status")

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        task = _get_task(connection, task_id)
        if task is None:
            raise TaskNotFoundError("Task not found")
        if task["status"] != TASK_STATUS_OPEN:
            raise TaskAlreadyFinishedError("Task is already finished")

        now = datetime.now(timezone.utc).isoformat()
        completed_at = now if target_status == TASK_STATUS_COMPLETED else None
        cancelled_at = now if target_status == TASK_STATUS_CANCELLED else None
        cursor = connection.execute(
            """
            UPDATE tasks
            SET status = ?,
                updated_at = ?,
                completed_at = ?,
                cancelled_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (target_status, now, completed_at, cancelled_at, task_id),
        )
        if cursor.rowcount != 1:
            raise TaskAlreadyFinishedError("Task is already finished")
        updated = _get_task(connection, task_id)
        assert updated is not None
        return updated


def complete_task(task_id: str) -> dict[str, Any]:
    """Mark one open task completed."""
    return _finish_task(task_id, TASK_STATUS_COMPLETED)


def cancel_task(task_id: str) -> dict[str, Any]:
    """Mark one open task cancelled."""
    return _finish_task(task_id, TASK_STATUS_CANCELLED)
