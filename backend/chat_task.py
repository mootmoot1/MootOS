"""Atomic chat-command storage for creating MootOS Tasks."""

from typing import Any, Optional

from backend.chat_memory import (
    ConversationNotFoundError,
    ProjectMismatchError,
    ProjectNotFoundError,
    _insert_message,
    _resolve_conversation,
)
from backend.db import database_connection
from backend.tasks import create_task_in_connection


def create_explicit_task_chat(
    *,
    request_message: str,
    task_title: str,
    conversation_id: Optional[str],
    project: Optional[str],
    title: str,
) -> dict[str, dict[str, Any]]:
    """Create one Task and persist its chat turn in a single transaction."""
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        conversation = _resolve_conversation(
            connection,
            conversation_id,
            project,
            title,
        )
        user_message = _insert_message(
            connection,
            conversation_id=conversation["id"],
            role="user",
            content=request_message,
        )
        task = create_task_in_connection(
            connection,
            title=task_title,
            project=conversation["project"],
        )

        task_scope = task["project"] or "Global"
        confirmation = f"Created {task_scope} task: {task['title']}"
        assistant_message = _insert_message(
            connection,
            conversation_id=conversation["id"],
            role="assistant",
            content=confirmation,
            provider="mootos",
            model="task-command-v1",
        )

        return {
            "conversation": conversation,
            "user_message": user_message,
            "task": task,
            "assistant_message": assistant_message,
        }


__all__ = [
    "ConversationNotFoundError",
    "ProjectMismatchError",
    "ProjectNotFoundError",
    "create_explicit_task_chat",
]
