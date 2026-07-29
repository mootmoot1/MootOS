"""SQLite-backed conversation and message storage for MootOS."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.memory import DATABASE_PATH, get_project


VALID_MESSAGE_ROLES = {"user", "assistant"}


def _connect() -> sqlite3.Connection:
    """Open the shared MootOS SQLite database."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def create_conversation(
    project: Optional[str] = None,
    title: Optional[str] = None,
) -> dict[str, Any]:
    """Create and return a conversation."""
    if project is not None:
        saved_project = get_project(project)
        if saved_project is None:
            raise ValueError("Project does not exist")
        project = saved_project["name"]

    now = datetime.now(timezone.utc).isoformat()
    conversation = {
        "id": str(uuid.uuid4()),
        "title": title or "New conversation",
        "project": project,
        "created_at": now,
        "updated_at": now,
    }
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO conversations (id, title, project, created_at, updated_at)
            VALUES (:id, :title, :project, :created_at, :updated_at)
            """,
            conversation,
        )
    return conversation


def list_conversations(project: Optional[str] = None) -> list[dict[str, Any]]:
    """Return conversations newest first, optionally filtered by project."""
    with _connect() as connection:
        if project is None:
            rows = connection.execute(
                """
                SELECT id, title, project, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC
                """
            ).fetchall()
        else:
            saved_project = get_project(project)
            if saved_project is None:
                raise ValueError("Project does not exist")
            rows = connection.execute(
                """
                SELECT id, title, project, created_at, updated_at
                FROM conversations
                WHERE project = ? COLLATE NOCASE
                ORDER BY updated_at DESC
                """,
                (saved_project["name"],),
            ).fetchall()
    return [dict(row) for row in rows]


def get_conversation(conversation_id: str) -> Optional[dict[str, Any]]:
    """Return one conversation with its complete message history."""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, title, project, created_at, updated_at
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        ).fetchone()
    if row is None:
        return None

    conversation = dict(row)
    conversation["messages"] = list_messages(conversation_id)
    return conversation


def list_messages(
    conversation_id: str,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return conversation messages oldest first."""
    with _connect() as connection:
        if limit is None:
            rows = connection.execute(
                """
                SELECT id, conversation_id, role, content, provider, model, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, conversation_id, role, content, provider, model, created_at
                FROM (
                    SELECT id, conversation_id, role, content, provider, model, created_at
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC
                """,
                (conversation_id, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Persist one user or assistant message."""
    if role not in VALID_MESSAGE_ROLES:
        raise ValueError("Message role must be user or assistant")
    if get_conversation(conversation_id) is None:
        raise ValueError("Conversation does not exist")

    created_at = datetime.now(timezone.utc).isoformat()
    message = {
        "id": str(uuid.uuid4()),
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "provider": provider,
        "model": model,
        "created_at": created_at,
    }
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO messages (
                id, conversation_id, role, content, provider, model, created_at
            )
            VALUES (
                :id, :conversation_id, :role, :content, :provider, :model, :created_at
            )
            """,
            message,
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (created_at, conversation_id),
        )
    return message
