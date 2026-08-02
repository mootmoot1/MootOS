"""Provider-backed chat preparation, serialization, and atomic persistence."""

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from backend.db import connect, database_connection


class ChatConversationNotFoundError(ValueError):
    """Raised when a normal chat targets a missing conversation."""


class ChatProjectMismatchError(ValueError):
    """Raised when a request project conflicts with an existing conversation."""


class ChatProjectNotFoundError(ValueError):
    """Raised when a new normal chat names an unknown project."""


class ChatStorageError(RuntimeError):
    """Raised when a provider-backed turn cannot be prepared or committed."""


_lock_registry_guard = threading.Lock()
_conversation_locks: dict[str, threading.Lock] = {}


@contextmanager
def conversation_turn_lock(conversation_id: Optional[str]) -> Iterator[None]:
    """Serialize provider turns for one existing conversation in this process.

    MootOS Version 0.1 runs one process and one Railway replica. Holding this lock
    across history loading, provider generation, and the short final write prevents
    two simultaneous requests from generating against the same stale history.
    New conversations have no shared identifier yet and do not need a common lock.
    """
    if conversation_id is None:
        yield
        return

    with _lock_registry_guard:
        lock = _conversation_locks.setdefault(conversation_id, threading.Lock())

    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _canonical_project_name(
    connection: sqlite3.Connection,
    project: str,
) -> Optional[str]:
    row = connection.execute(
        "SELECT name FROM projects WHERE name = ? COLLATE NOCASE",
        (project,),
    ).fetchone()
    return str(row["name"]) if row else None


def _load_recent_messages(
    connection: sqlite3.Connection,
    conversation_id: str,
    limit: int,
) -> list[dict[str, Any]]:
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


def prepare_chat_turn(
    *,
    conversation_id: Optional[str],
    project: Optional[str],
    title: str,
    history_limit: int = 20,
) -> dict[str, Any]:
    """Load existing history or prepare a new conversation without writing.

    The returned new-conversation record exists only in memory until the provider
    succeeds and ``commit_chat_turn`` atomically stores the complete pair.
    """
    try:
        with database_connection() as connection:
            if conversation_id is not None:
                row = connection.execute(
                    """
                    SELECT id, title, project, created_at, updated_at
                    FROM conversations
                    WHERE id = ?
                    """,
                    (conversation_id,),
                ).fetchone()
                if row is None:
                    raise ChatConversationNotFoundError("Conversation not found")

                conversation = dict(row)
                if project is not None:
                    existing_project = conversation["project"] or ""
                    if existing_project.casefold() != project.casefold():
                        raise ChatProjectMismatchError(
                            "The requested project does not match this conversation"
                        )

                history = _load_recent_messages(
                    connection,
                    conversation_id=conversation_id,
                    limit=history_limit,
                )
                return {
                    "conversation": conversation,
                    "history": history,
                    "is_new": False,
                }

            canonical_project = project
            if project is not None:
                canonical_project = _canonical_project_name(connection, project)
                if canonical_project is None:
                    raise ChatProjectNotFoundError("Project does not exist")
    except (
        ChatConversationNotFoundError,
        ChatProjectMismatchError,
        ChatProjectNotFoundError,
    ):
        raise
    except Exception as error:
        raise ChatStorageError("Conversation turn could not be prepared") from error

    now = datetime.now(timezone.utc).isoformat()
    conversation = {
        "id": str(uuid.uuid4()),
        "title": title or "New conversation",
        "project": canonical_project,
        "created_at": now,
        "updated_at": now,
    }
    return {
        "conversation": conversation,
        "history": [],
        "is_new": True,
    }


def _build_message(
    *,
    conversation_id: str,
    role: str,
    content: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "provider": provider,
        "model": model,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _insert_message(
    connection: sqlite3.Connection,
    message: dict[str, Any],
) -> None:
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


def _rollback_safely(connection: Optional[sqlite3.Connection]) -> None:
    if connection is None:
        return
    try:
        connection.rollback()
    except sqlite3.Error:
        pass


def commit_chat_turn(
    *,
    conversation: dict[str, Any],
    is_new: bool,
    user_content: str,
    assistant_content: str,
    provider: str,
    model: str,
) -> dict[str, dict[str, Any]]:
    """Commit a successful provider turn in one short immediate transaction."""
    user_message = _build_message(
        conversation_id=conversation["id"],
        role="user",
        content=user_content,
    )
    assistant_message = _build_message(
        conversation_id=conversation["id"],
        role="assistant",
        content=assistant_content,
        provider=provider,
        model=model,
    )

    connection: Optional[sqlite3.Connection] = None
    try:
        connection = connect()
        connection.execute("BEGIN IMMEDIATE")
        if is_new:
            connection.execute(
                """
                INSERT INTO conversations (id, title, project, created_at, updated_at)
                VALUES (:id, :title, :project, :created_at, :updated_at)
                """,
                conversation,
            )
        else:
            existing = connection.execute(
                "SELECT 1 FROM conversations WHERE id = ?",
                (conversation["id"],),
            ).fetchone()
            if existing is None:
                raise ChatConversationNotFoundError("Conversation not found")

        _insert_message(connection, user_message)
        _insert_message(connection, assistant_message)
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (assistant_message["created_at"], conversation["id"]),
        )
        connection.commit()
    except ChatConversationNotFoundError:
        _rollback_safely(connection)
        raise
    except Exception as error:
        _rollback_safely(connection)
        raise ChatStorageError("Conversation turn could not be saved") from error
    finally:
        if connection is not None:
            connection.close()

    saved_conversation = dict(conversation)
    saved_conversation["updated_at"] = assistant_message["created_at"]
    return {
        "conversation": saved_conversation,
        "user_message": user_message,
        "assistant_message": assistant_message,
    }
