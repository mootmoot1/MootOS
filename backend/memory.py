"""SQLite-backed project and memory storage for MootOS."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db import DATABASE_PATH, database_connection, resolve_database_path
from backend.migrations import initialize_database


def init_db() -> None:
    """Initialize the database through the versioned migration runner."""
    initialize_database()


def _get_project(
    connection: sqlite3.Connection,
    name: str,
) -> Optional[dict[str, Any]]:
    row = connection.execute(
        """
        SELECT id, name, description, created_at
        FROM projects
        WHERE name = ? COLLATE NOCASE
        """,
        (name,),
    ).fetchone()
    return dict(row) if row else None


def create_project(name: str, description: Optional[str] = None) -> dict[str, Any]:
    """Create and return a project."""
    project = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with database_connection() as connection:
            connection.execute(
                """
                INSERT INTO projects (id, name, description, created_at)
                VALUES (:id, :name, :description, :created_at)
                """,
                project,
            )
    except sqlite3.IntegrityError as error:
        raise ValueError("Project already exists") from error
    return project


def list_projects() -> list[dict[str, Any]]:
    """Return every project alphabetically."""
    with database_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, name, description, created_at
            FROM projects
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_project(name: str) -> Optional[dict[str, Any]]:
    """Return a project by name, ignoring capitalization."""
    with database_connection() as connection:
        return _get_project(connection, name)


def create_memory(
    content: str,
    project: Optional[str] = None,
    memory_type: Optional[str] = None,
) -> dict[str, Any]:
    """Store and return a new memory."""
    with database_connection() as connection:
        if project is not None:
            saved_project = _get_project(connection, project)
            if saved_project is None:
                raise ValueError("Project does not exist")
            project = saved_project["name"]

        memory = {
            "id": str(uuid.uuid4()),
            "content": content,
            "project": project,
            "memory_type": memory_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        connection.execute(
            """
            INSERT INTO memories (id, content, project, memory_type, created_at)
            VALUES (:id, :content, :project, :memory_type, :created_at)
            """,
            memory,
        )
    return memory


def list_memories(project: Optional[str] = None) -> list[dict[str, Any]]:
    """Return memories newest first, optionally filtered by project."""
    with database_connection() as connection:
        if project is None:
            rows = connection.execute(
                """
                SELECT id, content, project, memory_type, created_at
                FROM memories
                ORDER BY created_at DESC
                """
            ).fetchall()
        else:
            saved_project = _get_project(connection, project)
            if saved_project is None:
                raise ValueError("Project does not exist")
            rows = connection.execute(
                """
                SELECT id, content, project, memory_type, created_at
                FROM memories
                WHERE project = ? COLLATE NOCASE
                ORDER BY created_at DESC
                """,
                (saved_project["name"],),
            ).fetchall()
    return [dict(row) for row in rows]


def list_context_memories(project: Optional[str] = None) -> list[dict[str, Any]]:
    """Return memories relevant to model context.

    Unassigned memories are global and available in every project conversation.
    Project-assigned memories remain limited to their matching project.
    """
    with database_connection() as connection:
        if project is None:
            rows = connection.execute(
                """
                SELECT id, content, project, memory_type, created_at
                FROM memories
                ORDER BY created_at DESC
                """
            ).fetchall()
        else:
            saved_project = _get_project(connection, project)
            if saved_project is None:
                raise ValueError("Project does not exist")
            rows = connection.execute(
                """
                SELECT id, content, project, memory_type, created_at
                FROM memories
                WHERE project IS NULL OR project = ? COLLATE NOCASE
                ORDER BY created_at DESC
                """,
                (saved_project["name"],),
            ).fetchall()
    return [dict(row) for row in rows]


def get_memory(memory_id: str) -> Optional[dict[str, Any]]:
    """Return one memory or None when it does not exist."""
    with database_connection() as connection:
        row = connection.execute(
            """
            SELECT id, content, project, memory_type, created_at
            FROM memories
            WHERE id = ?
            """,
            (memory_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_memory(memory_id: str) -> bool:
    """Delete one memory and report whether it existed."""
    with database_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM memories WHERE id = ?",
            (memory_id,),
        )
    return cursor.rowcount > 0
