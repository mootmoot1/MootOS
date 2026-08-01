"""SQLite-backed project and memory storage for MootOS."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db import DATABASE_PATH, database_connection, resolve_database_path
from backend.migrations import initialize_database


MEMORY_STATUS_ACTIVE = "active"
MEMORY_STATUS_SUPERSEDED = "superseded"
MEMORY_STATUS_ARCHIVED = "archived"
MEMORY_COLUMNS = """
    id,
    content,
    project,
    memory_type,
    created_at,
    status,
    updated_at,
    replaces_memory_id,
    superseded_by_id
"""


class MemoryNotFoundError(ValueError):
    """Raised when a requested memory does not exist."""


class MemoryNotActiveError(ValueError):
    """Raised when a correction targets a non-active memory version."""


class MemoryCorrectionConflictError(ValueError):
    """Raised when a correction would not change the stored memory."""


class MemoryHistoryProtectedError(ValueError):
    """Raised when hard deletion would break correction history."""


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


def _get_memory(
    connection: sqlite3.Connection,
    memory_id: str,
) -> Optional[dict[str, Any]]:
    row = connection.execute(
        f"""
        SELECT {MEMORY_COLUMNS}
        FROM memories
        WHERE id = ?
        """,
        (memory_id,),
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
    """Store and return a new active memory."""
    with database_connection() as connection:
        if project is not None:
            saved_project = _get_project(connection, project)
            if saved_project is None:
                raise ValueError("Project does not exist")
            project = saved_project["name"]

        now = datetime.now(timezone.utc).isoformat()
        memory = {
            "id": str(uuid.uuid4()),
            "content": content,
            "project": project,
            "memory_type": memory_type,
            "created_at": now,
            "status": MEMORY_STATUS_ACTIVE,
            "updated_at": now,
            "replaces_memory_id": None,
            "superseded_by_id": None,
        }
        connection.execute(
            """
            INSERT INTO memories (
                id,
                content,
                project,
                memory_type,
                created_at,
                status,
                updated_at,
                replaces_memory_id,
                superseded_by_id
            )
            VALUES (
                :id,
                :content,
                :project,
                :memory_type,
                :created_at,
                :status,
                :updated_at,
                :replaces_memory_id,
                :superseded_by_id
            )
            """,
            memory,
        )
    return memory


def list_memories(project: Optional[str] = None) -> list[dict[str, Any]]:
    """Return active memories newest first, optionally filtered by project."""
    with database_connection() as connection:
        if project is None:
            rows = connection.execute(
                f"""
                SELECT {MEMORY_COLUMNS}
                FROM memories
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (MEMORY_STATUS_ACTIVE,),
            ).fetchall()
        else:
            saved_project = _get_project(connection, project)
            if saved_project is None:
                raise ValueError("Project does not exist")
            rows = connection.execute(
                f"""
                SELECT {MEMORY_COLUMNS}
                FROM memories
                WHERE status = ? AND project = ? COLLATE NOCASE
                ORDER BY created_at DESC
                """,
                (MEMORY_STATUS_ACTIVE, saved_project["name"]),
            ).fetchall()
    return [dict(row) for row in rows]


def list_context_memories(project: Optional[str] = None) -> list[dict[str, Any]]:
    """Return active memories relevant to model context.

    A no-project conversation can load all active memory. Project conversations
    currently load global memory plus the matching project; later retrieval work
    will rank relevant cross-project memory without changing lifecycle behavior.
    """
    with database_connection() as connection:
        if project is None:
            rows = connection.execute(
                f"""
                SELECT {MEMORY_COLUMNS}
                FROM memories
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (MEMORY_STATUS_ACTIVE,),
            ).fetchall()
        else:
            saved_project = _get_project(connection, project)
            if saved_project is None:
                raise ValueError("Project does not exist")
            rows = connection.execute(
                f"""
                SELECT {MEMORY_COLUMNS}
                FROM memories
                WHERE status = ?
                  AND (project IS NULL OR project = ? COLLATE NOCASE)
                ORDER BY created_at DESC
                """,
                (MEMORY_STATUS_ACTIVE, saved_project["name"]),
            ).fetchall()
    return [dict(row) for row in rows]


def get_memory(memory_id: str) -> Optional[dict[str, Any]]:
    """Return one memory version or None when it does not exist."""
    with database_connection() as connection:
        return _get_memory(connection, memory_id)


def correct_memory(memory_id: str, content: str) -> dict[str, dict[str, Any]]:
    """Replace one active memory atomically while preserving the old version."""
    corrected_content = content.strip()
    if not corrected_content:
        raise ValueError("Corrected memory content cannot be empty")

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        original = _get_memory(connection, memory_id)
        if original is None:
            raise MemoryNotFoundError("Memory not found")
        if original["status"] != MEMORY_STATUS_ACTIVE:
            raise MemoryNotActiveError("Only an active memory can be corrected")
        if corrected_content == original["content"]:
            raise MemoryCorrectionConflictError(
                "Corrected memory must be different from the current version"
            )

        now = datetime.now(timezone.utc).isoformat()
        replacement = {
            "id": str(uuid.uuid4()),
            "content": corrected_content,
            "project": original["project"],
            "memory_type": original["memory_type"],
            "created_at": now,
            "status": MEMORY_STATUS_ACTIVE,
            "updated_at": now,
            "replaces_memory_id": original["id"],
            "superseded_by_id": None,
        }
        connection.execute(
            """
            INSERT INTO memories (
                id,
                content,
                project,
                memory_type,
                created_at,
                status,
                updated_at,
                replaces_memory_id,
                superseded_by_id
            )
            VALUES (
                :id,
                :content,
                :project,
                :memory_type,
                :created_at,
                :status,
                :updated_at,
                :replaces_memory_id,
                :superseded_by_id
            )
            """,
            replacement,
        )
        updated = connection.execute(
            """
            UPDATE memories
            SET status = ?, updated_at = ?, superseded_by_id = ?
            WHERE id = ? AND status = ?
            """,
            (
                MEMORY_STATUS_SUPERSEDED,
                now,
                replacement["id"],
                original["id"],
                MEMORY_STATUS_ACTIVE,
            ),
        )
        if updated.rowcount != 1:
            raise MemoryNotActiveError("Only an active memory can be corrected")

        superseded = _get_memory(connection, original["id"])
        saved_replacement = _get_memory(connection, replacement["id"])
        if superseded is None or saved_replacement is None:
            raise RuntimeError("Memory correction did not persist completely")

        return {
            "superseded": superseded,
            "replacement": saved_replacement,
        }


def get_memory_history(memory_id: str) -> Optional[list[dict[str, Any]]]:
    """Return one correction chain from oldest to newest."""
    with database_connection() as connection:
        current = _get_memory(connection, memory_id)
        if current is None:
            return None

        seen: set[str] = set()
        while current["replaces_memory_id"]:
            if current["id"] in seen:
                raise RuntimeError("Memory correction history contains a cycle")
            seen.add(current["id"])
            previous = _get_memory(connection, current["replaces_memory_id"])
            if previous is None:
                raise RuntimeError("Memory correction history is incomplete")
            current = previous

        history: list[dict[str, Any]] = []
        seen.clear()
        while current is not None:
            if current["id"] in seen:
                raise RuntimeError("Memory correction history contains a cycle")
            seen.add(current["id"])
            history.append(current)
            next_id = current["superseded_by_id"]
            current = _get_memory(connection, next_id) if next_id else None

    return history


def delete_memory(memory_id: str) -> bool:
    """Delete one standalone memory while protecting correction history.

    This legacy administrative endpoint is not exposed in the browser. Any row
    that participates in a correction chain is protected from hard deletion so
    preserved history cannot be broken before recoverable archive is added.
    """
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        memory = _get_memory(connection, memory_id)
        if memory is None:
            return False
        if (
            memory["replaces_memory_id"] is not None
            or memory["superseded_by_id"] is not None
            or memory["status"] == MEMORY_STATUS_SUPERSEDED
        ):
            raise MemoryHistoryProtectedError(
                "Memory correction history cannot be permanently deleted"
            )
        cursor = connection.execute(
            "DELETE FROM memories WHERE id = ?",
            (memory_id,),
        )
    return cursor.rowcount > 0
