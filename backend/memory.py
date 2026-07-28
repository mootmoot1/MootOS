"""SQLite-backed persistent memory storage for MootOS."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "mootos.db"


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Create the memory database and table when they do not exist."""
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                project TEXT,
                memory_type TEXT,
                created_at TEXT NOT NULL
            )
            """
        )


def create_memory(
    content: str,
    project: Optional[str] = None,
    memory_type: Optional[str] = None,
) -> dict[str, Any]:
    """Store and return a new memory."""
    memory = {
        "id": str(uuid.uuid4()),
        "content": content,
        "project": project,
        "memory_type": memory_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO memories (id, content, project, memory_type, created_at)
            VALUES (:id, :content, :project, :memory_type, :created_at)
            """,
            memory,
        )
    return memory


def list_memories() -> list[dict[str, Any]]:
    """Return every memory, newest first."""
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, content, project, memory_type, created_at
            FROM memories
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_memory(memory_id: str) -> Optional[dict[str, Any]]:
    """Return one memory or None when it does not exist."""
    with _connect() as connection:
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
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM memories WHERE id = ?",
            (memory_id,),
        )
    return cursor.rowcount > 0
