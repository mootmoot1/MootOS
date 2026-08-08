"""Atomic storage for explicit long-term-memory chat commands."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db import database_connection
from backend.memory_commands import parse_memory_correction_command
from backend.memory_retrieval import rank_memories, tokenize_keywords


class ConversationNotFoundError(ValueError):
    """Raised when an explicit memory command targets a missing conversation."""


class ProjectMismatchError(ValueError):
    """Raised when a request project conflicts with an existing conversation."""


class ProjectNotFoundError(ValueError):
    """Raised when a new memory conversation names an unknown project."""


class MemoryCorrectionTargetNotFoundError(ValueError):
    """Raised when a correction cannot identify an existing active memory."""


class MemoryCorrectionAmbiguousError(ValueError):
    """Raised when a correction matches more than one active memory."""


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
    now = datetime.now(timezone.utc).isoformat()
    memory = {
        "id": str(uuid.uuid4()),
        "content": content,
        "project": project,
        "memory_type": "explicit_chat",
        "created_at": now,
        "status": "active",
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


def _active_memories_in_scope(
    connection: sqlite3.Connection,
    project: Optional[str],
) -> list[dict[str, Any]]:
    if project is None:
        rows = connection.execute(
            """
            SELECT id, content, project, memory_type, created_at, status,
                   updated_at, replaces_memory_id, superseded_by_id
            FROM memories
            WHERE status = 'active' AND project IS NULL
            ORDER BY created_at DESC
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT id, content, project, memory_type, created_at, status,
                   updated_at, replaces_memory_id, superseded_by_id
            FROM memories
            WHERE status = 'active' AND project = ? COLLATE NOCASE
            ORDER BY created_at DESC
            """,
            (project,),
        ).fetchall()
    return [dict(row) for row in rows]


def _strong_correction_match(candidate: dict[str, Any], content: str) -> bool:
    query_tokens = set(tokenize_keywords(content))
    candidate_tokens = set(tokenize_keywords(candidate.get("content")))
    shared = query_tokens & candidate_tokens
    if len(shared) >= 2:
        return True
    return len(shared) == 1 and len(query_tokens) <= 2


def _select_correction_target(
    connection: sqlite3.Connection,
    content: str,
    project: Optional[str],
) -> dict[str, Any]:
    candidates = rank_memories(
        _active_memories_in_scope(connection, project),
        content,
        project,
        include_fallback=False,
    )
    candidates = [
        candidate for candidate in candidates if _strong_correction_match(candidate, content)
    ]
    if not candidates:
        raise MemoryCorrectionTargetNotFoundError(
            "I could not identify an existing memory to replace. Save it as a new memory or make the correction more specific."
        )
    if len(candidates) > 1:
        raise MemoryCorrectionAmbiguousError(
            "More than one saved memory could match that correction. Make the correction more specific before I replace anything."
        )
    return candidates[0]


def _replace_memory(
    connection: sqlite3.Connection,
    original: dict[str, Any],
    content: str,
) -> dict[str, Any]:
    corrected_content = content.strip()
    now = datetime.now(timezone.utc).isoformat()
    replacement = {
        "id": str(uuid.uuid4()),
        "content": corrected_content,
        "project": original["project"],
        "memory_type": original["memory_type"],
        "created_at": now,
        "status": "active",
        "updated_at": now,
        "replaces_memory_id": original["id"],
        "superseded_by_id": None,
    }
    connection.execute(
        """
        INSERT INTO memories (
            id, content, project, memory_type, created_at, status, updated_at,
            replaces_memory_id, superseded_by_id
        )
        VALUES (
            :id, :content, :project, :memory_type, :created_at, :status, :updated_at,
            :replaces_memory_id, :superseded_by_id
        )
        """,
        replacement,
    )
    updated = connection.execute(
        """
        UPDATE memories
        SET status = 'superseded', updated_at = ?, superseded_by_id = ?
        WHERE id = ? AND status = 'active'
        """,
        (now, replacement["id"], original["id"]),
    )
    if updated.rowcount != 1:
        raise MemoryCorrectionTargetNotFoundError(
            "The memory changed before the correction could be saved. Please retry."
        )
    return replacement


def _resolve_conversation(
    connection: sqlite3.Connection,
    conversation_id: Optional[str],
    project: Optional[str],
    title: str,
) -> dict[str, Any]:
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
        return conversation

    return _insert_conversation(connection, project, title)


def _correction_clarification_turn(
    connection: sqlite3.Connection,
    conversation: dict[str, Any],
    request_message: str,
    detail: str,
) -> dict[str, dict[str, Any]]:
    user_message = _insert_message(
        connection,
        conversation_id=conversation["id"],
        role="user",
        content=request_message,
    )
    assistant_message = _insert_message(
        connection,
        conversation_id=conversation["id"],
        role="assistant",
        content=detail,
        provider="mootos",
        model="memory-command-v1",
    )
    return {
        "conversation": conversation,
        "user_message": user_message,
        "assistant_message": assistant_message,
    }


def correct_explicit_memory_chat(
    *,
    request_message: str,
    memory_content: str,
    conversation_id: Optional[str],
    project: Optional[str],
    title: str,
) -> dict[str, dict[str, Any]]:
    """Replace one unambiguous active memory and preserve its prior version."""
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        conversation = _resolve_conversation(
            connection,
            conversation_id,
            project,
            title,
        )
        try:
            target = _select_correction_target(
                connection,
                memory_content,
                conversation["project"],
            )
        except (MemoryCorrectionTargetNotFoundError, MemoryCorrectionAmbiguousError) as error:
            return _correction_clarification_turn(
                connection,
                conversation,
                request_message,
                str(error),
            )

        corrected_content = memory_content.strip()
        if corrected_content == target["content"]:
            return _correction_clarification_turn(
                connection,
                conversation,
                request_message,
                "The corrected memory is the same as the current memory.",
            )

        user_message = _insert_message(
            connection,
            conversation_id=conversation["id"],
            role="user",
            content=request_message,
        )
        replacement = _replace_memory(connection, target, corrected_content)

        memory_scope = replacement["project"] or "Global"
        confirmation = (
            f"Updated {memory_scope} long-term memory: "
            f"{replacement['content']}"
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
            "memory": replacement,
            "superseded_memory": target,
            "assistant_message": assistant_message,
        }


def save_explicit_memory_chat(
    *,
    request_message: str,
    memory_content: str,
    conversation_id: Optional[str],
    project: Optional[str],
    title: str,
) -> dict[str, dict[str, Any]]:
    """Save or explicitly correct long-term memory in one complete chat turn."""
    correction = parse_memory_correction_command(request_message)
    if correction is not None:
        return correct_explicit_memory_chat(
            request_message=request_message,
            memory_content=correction.content,
            conversation_id=conversation_id,
            project=project,
            title=title,
        )

    with database_connection() as connection:
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
