"""Atomic storage for explicit long-term-memory chat commands."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db import database_connection


class ConversationNotFoundError(ValueError):
    """Raised when an explicit memory command targets a missing conversation."""


class ProjectMismatchError(ValueError):
    """Raised when a request project conflicts with an existing conversation."""


class ProjectNotFoundError(ValueError):
    """Raised when a new memory conversation names an unknown project."""


def _canonical_project_name(
    connection: sqlite3.Connection,
    project: str,
) -> Optional[str]:
    row = connection.execute(
        "SELECT name FROM projects WHERE name = ? COLLATE NOCASE",
        (project,),
    ).fetchone()
    return str(row["name"]) if row else None


def _load_conversation(
    connection: sqlite3.Connection,
    conversation_id: str,
) -> Optional[dict[str, Any]]:
    row = connection.execute(
        """
        SELECT id, title, project, created_at, updated_at
        FROM conversations
        WHERE id = ?
        """,
        (conversation_id,),
    ).fetchone()
    return dict(row) if row else None


def _insert_conversation(
    connection: sqlite3.Connection,
    project: Optional[str],
    title: str,
) -> dict[str, Any]:
    if project is not None:
        canonical_name = _canonical_project_name(connection, project)
        if canonical_name is None:
            raise ProjectNotFoundError("Project does not exist")
        project = canonical_name

    now = datetime.now(timezone.utc).isoformat()
    conversation = {
        "id": str(uuid.uuid4()),
        "title": title or "New conversation",
        "project": project,
        "created_at": now,
        "updated_at": now,
    }
    connection.execute(
        """
        INSERT INTO conversations (id, title, project, created_at, updated_at)
        VALUES (:id, :title, :project, :created_at, :updated_at)
        """,
        conversation,
    )
    return conversation


def _insert_message(
    connection: sqlite3.Connection,
    conversation_id: str,
    role: str,
    content: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
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


def _insert_memory(
    connection: sqlite3.Connection,
    content: str,
    project: Optional[str],
) -> dict[str, Any]:
    memory = {
        "id": str(uuid.uuid4()),
        "content": content,
        "project": project,
        "memory_type": "explicit_chat",
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


def save_explicit_memory_chat(
    *,
    request_message: str,
    memory_content: str,
    conversation_id: Optional[str],
    project: Optional[str],
    title: str,
) -> dict[str, dict[str, Any]]:
    """Save the complete explicit-memory chat turn in one transaction.

    Conversation creation, the user message, the memory row, and the assistant
    confirmation either all commit or all roll back together.
    """
    with database_connection() as connection:
        if conversation_id is not None:
            conversation = _load_conversation(connection, conversation_id)
            if conversation is None:
                raise ConversationNotFoundError("Conversation not found")

            if project is not None:
                existing_project = conversation["project"] or ""
                if existing_project.casefold() != project.casefold():
                    raise ProjectMismatchError(
                        "The requested project does not match this conversation"
                    )
        else:
            conversation = _insert_conversation(connection, project, title)

        user_message = _insert_message(
            connection,
            conversation_id=conversation["id"],
            role="user",
            content=request_message,
        )
        saved_memory = _insert_memory(
            connection,
            content=memory_content,
            project=conversation["project"],
        )

        memory_scope = saved_memory["project"] or "Global"
        confirmation = (
            f"Saved to {memory_scope} long-term memory: "
            f"{saved_memory['content']}"
        )
        assistant_message = _insert_message(
            connection,
            conversation_id=conversation["id"],
            role="assistant",
            content=confirmation,
            provider="mootos",
            model="memory-command-v1",
        )

        return {
            "conversation": conversation,
            "user_message": user_message,
            "memory": saved_memory,
            "assistant_message": assistant_message,
        }
