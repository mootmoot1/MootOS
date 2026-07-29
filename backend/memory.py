"""SQLite-backed persistent memory storage for MootOS."""

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def resolve_database_path() -> Path:
    """Choose an explicit path, Railway volume, or local development database."""
    explicit_path = os.getenv("MOOTOS_DATABASE_PATH", "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser()

    railway_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_mount:
        return Path(railway_mount) / "mootos.db"

    return Path(__file__).resolve().parent.parent / "data" / "mootos.db"


DATABASE_PATH = resolve_database_path()

DEFAULT_PROJECTS = (
    ("MootOS", "Development and planning for the MootOS personal AI system."),
    ("Studio", "Studio sessions, clients, engineering work, and business operations."),
    ("Social Media", "Content ideas, publishing plans, and audience growth."),
    ("Cars", "Vehicle maintenance, repairs, and automotive projects."),
    ("Personal", "Personal information that does not belong to another project."),
)


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Create the database schema and seed the default projects."""
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                description TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                project TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
            ON messages (conversation_id)
            """
        )
        created_at = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            """
            INSERT OR IGNORE INTO projects (id, name, description, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                (str(uuid.uuid4()), name, description, created_at)
                for name, description in DEFAULT_PROJECTS
            ),
        )


def create_project(name: str, description: Optional[str] = None) -> dict[str, Any]:
    """Create and return a project."""
    project = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with _connect() as connection:
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
    with _connect() as connection:
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
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, name, description, created_at
            FROM projects
            WHERE name = ? COLLATE NOCASE
            """,
            (name,),
        ).fetchone()
    return dict(row) if row else None


def create_memory(
    content: str,
    project: Optional[str] = None,
    memory_type: Optional[str] = None,
) -> dict[str, Any]:
    """Store and return a new memory."""
    if project is not None:
        saved_project = get_project(project)
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
    with _connect() as connection:
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
    with _connect() as connection:
        if project is None:
            rows = connection.execute(
                """
                SELECT id, content, project, memory_type, created_at
                FROM memories
                ORDER BY created_at DESC
                """
            ).fetchall()
        else:
            saved_project = get_project(project)
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
