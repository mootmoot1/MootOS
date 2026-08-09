"""Durable approval operations for model-selected MootOS write tools.

A "tool operation" freezes exactly what a model asked to run -- tool name,
version, and already-schema-validated arguments -- before any human review
happens. Approving an operation can only ever execute that frozen call; there
is no path from here back into fresh model-supplied arguments.

State machine
-------------

::

    pending --> executing --> succeeded
       |            |
       |            `-------> failed
       |
       |--> rejected   (nothing executes)
       `--> expired     (nothing executes)

``executing`` is a short-lived claimed state written by ``approve_operation``
before it calls the tool executor, and cleared to a terminal state right
after. It exists specifically so a double-click/retry on approve cannot
execute the same operation twice: the claim step is an atomic
``UPDATE ... WHERE status = 'pending'``, so only the first request can ever
win it. A process crash between the claim and the terminal update leaves an
operation stuck in ``executing`` rather than duplicating the write -- the
same accepted tradeoff already used for a "started" Run row elsewhere in
this codebase (see ``backend/runs.py``): safe to detect and repair
operationally, and never silently duplicated.

``rejected``, ``failed``, and ``expired`` are terminal and executed nothing.
``succeeded`` is terminal and executed exactly once.

Approval also re-checks the frozen ``tool_version`` against the currently
registered tool immediately after the claim and before any execution --- if
the registered tool was removed or its version has since changed, approval
finalizes as ``failed`` (a ``ToolVersionMismatchError``/``ToolNotFoundError``
error class) and executes nothing. See ``approve_operation``.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.db import database_connection
from backend.tool_executor import execute_tool, record_rejected_tool_attempt
from backend.tool_registry import get_tool_registry
from backend.tool_types import ToolExecutionContext, ToolNotFoundError, ToolVersionMismatchError


OPERATION_STATUS_PENDING = "pending"
OPERATION_STATUS_EXECUTING = "executing"
OPERATION_STATUS_SUCCEEDED = "succeeded"
OPERATION_STATUS_REJECTED = "rejected"
OPERATION_STATUS_FAILED = "failed"
OPERATION_STATUS_EXPIRED = "expired"
OPERATION_STATUSES = {
    OPERATION_STATUS_PENDING,
    OPERATION_STATUS_EXECUTING,
    OPERATION_STATUS_SUCCEEDED,
    OPERATION_STATUS_REJECTED,
    OPERATION_STATUS_FAILED,
    OPERATION_STATUS_EXPIRED,
}
TERMINAL_OPERATION_STATUSES = {
    OPERATION_STATUS_SUCCEEDED,
    OPERATION_STATUS_REJECTED,
    OPERATION_STATUS_FAILED,
    OPERATION_STATUS_EXPIRED,
}

# How long a pending approval remains actionable before it fails closed.
DEFAULT_OPERATION_TTL_SECONDS = 24 * 60 * 60

OPERATION_COLUMNS = """
    id,
    tool_name,
    tool_version,
    status,
    arguments_json,
    conversation_id,
    project,
    created_at,
    updated_at,
    expires_at,
    decided_at,
    result_run_id,
    result_reference,
    error_class
"""


class OperationNotFoundError(ValueError):
    """Raised when an operation ID does not exist."""


class OperationNotPendingError(ValueError):
    """Raised when approve/reject targets a non-pending (already-decided) operation."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"Operation is already {status}")


class OperationExpiredError(ValueError):
    """Raised when approve/reject targets an operation past its expiration."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_public(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["arguments"] = json.loads(data.pop("arguments_json"))
    return data


def _get_operation_row(connection: sqlite3.Connection, operation_id: str) -> Optional[dict[str, Any]]:
    row = connection.execute(
        f"SELECT {OPERATION_COLUMNS} FROM tool_operations WHERE id = ?",
        (operation_id,),
    ).fetchone()
    return dict(row) if row else None


def create_pending_operation(
    *,
    tool_name: str,
    tool_version: Optional[str],
    arguments: dict[str, Any],
    conversation_id: Optional[str],
    project: Optional[str],
    ttl_seconds: Optional[int] = DEFAULT_OPERATION_TTL_SECONDS,
) -> dict[str, Any]:
    """Freeze one write-tool call for human review. Never executes anything."""
    now = _utc_now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat() if ttl_seconds else None
    operation = {
        "id": str(uuid.uuid4()),
        "tool_name": tool_name,
        "tool_version": tool_version,
        "status": OPERATION_STATUS_PENDING,
        "arguments_json": json.dumps(arguments, sort_keys=True, default=str),
        "conversation_id": conversation_id,
        "project": project,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "expires_at": expires_at,
        "decided_at": None,
        "result_run_id": None,
        "result_reference": None,
        "error_class": None,
    }
    with database_connection() as connection:
        connection.execute(
            """
            INSERT INTO tool_operations (
                id, tool_name, tool_version, status, arguments_json,
                conversation_id, project, created_at, updated_at, expires_at,
                decided_at, result_run_id, result_reference, error_class
            ) VALUES (
                :id, :tool_name, :tool_version, :status, :arguments_json,
                :conversation_id, :project, :created_at, :updated_at, :expires_at,
                :decided_at, :result_run_id, :result_reference, :error_class
            )
            """,
            operation,
        )
    return _row_to_public(operation)


def get_operation(operation_id: str) -> Optional[dict[str, Any]]:
    """Return one operation by ID, or None."""
    with database_connection() as connection:
        row = _get_operation_row(connection, operation_id)
    return _row_to_public(row) if row else None


def list_pending_operations(
    *,
    conversation_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return pending operations, newest first, optionally scoped to one conversation."""
    safe_limit = max(1, min(int(limit), 200))
    with database_connection() as connection:
        if conversation_id is None:
            rows = connection.execute(
                f"""
                SELECT {OPERATION_COLUMNS} FROM tool_operations
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (OPERATION_STATUS_PENDING, safe_limit),
            ).fetchall()
        else:
            rows = connection.execute(
                f"""
                SELECT {OPERATION_COLUMNS} FROM tool_operations
                WHERE status = ? AND conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (OPERATION_STATUS_PENDING, conversation_id, safe_limit),
            ).fetchall()
    return [_row_to_public(row) for row in rows]


def _expire_stale_pending_operation(operation_id: str) -> bool:
    """Transition a stale pending operation to expired, in its own committed
    transaction. Returns True when it just expired the operation.

    This must commit independently of whatever the caller does next: if it
    ran inside the same transaction a caller then rolls back (e.g. by
    raising ``OperationExpiredError`` from within a ``with
    database_connection()`` block), the expiry write would be undone along
    with it, and the operation would incorrectly look "pending" forever.
    """
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, expires_at FROM tool_operations WHERE id = ?",
            (operation_id,),
        ).fetchone()
        if row is None or row["status"] != OPERATION_STATUS_PENDING or not row["expires_at"]:
            return False
        if datetime.fromisoformat(row["expires_at"]) >= _utc_now():
            return False

        now = _utc_now().isoformat()
        connection.execute(
            "UPDATE tool_operations SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
            (OPERATION_STATUS_EXPIRED, now, operation_id, OPERATION_STATUS_PENDING),
        )
        return True


def _claim_pending_operation(operation_id: str) -> dict[str, Any]:
    """Atomically move pending -> executing. Fails closed on any other state."""
    if _expire_stale_pending_operation(operation_id):
        raise OperationExpiredError("Operation has expired")

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        operation = _get_operation_row(connection, operation_id)
        if operation is None:
            raise OperationNotFoundError("Operation not found")

        if operation["status"] != OPERATION_STATUS_PENDING:
            raise OperationNotPendingError(operation["status"])

        now = _utc_now().isoformat()
        claimed = connection.execute(
            "UPDATE tool_operations SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
            (OPERATION_STATUS_EXECUTING, now, operation_id, OPERATION_STATUS_PENDING),
        )
        if claimed.rowcount != 1:
            # Another request won the claim between the read above and here.
            raise OperationNotPendingError(OPERATION_STATUS_EXECUTING)
        return operation


def _finalize_operation(
    operation_id: str,
    status: str,
    *,
    result_run_id: Optional[str] = None,
    result_reference: Optional[str] = None,
    error_class: Optional[str] = None,
) -> dict[str, Any]:
    now = _utc_now().isoformat()
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        updated = connection.execute(
            """
            UPDATE tool_operations
            SET status = ?, updated_at = ?, decided_at = ?,
                result_run_id = ?, result_reference = ?, error_class = ?
            WHERE id = ? AND status = ?
            """,
            (
                status,
                now,
                now,
                result_run_id,
                result_reference,
                error_class,
                operation_id,
                OPERATION_STATUS_EXECUTING,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Tool operation finalize did not persist")
        return _row_to_public(_get_operation_row(connection, operation_id))


def approve_operation(operation_id: str) -> dict[str, Any]:
    """Execute the exact frozen tool call the user reviewed, exactly once.

    Never accepts arguments -- the only input is the operation ID, so a
    model or client cannot alter what runs after approval.

    Also refuses to execute -- and executes nothing -- if the tool has been
    unregistered since the operation was frozen, or if the currently
    registered version no longer matches ``claimed["tool_version"]``. The
    human reviewed one specific version of this tool call; approval must
    never silently run a different one just because the registry changed
    between when the operation was created and when it was approved.
    """
    claimed = _claim_pending_operation(operation_id)
    arguments = json.loads(claimed["arguments_json"])

    try:
        live_definition = get_tool_registry().get(claimed["tool_name"])
    except ToolNotFoundError as error:
        record_rejected_tool_attempt(
            tool_name=claimed["tool_name"],
            conversation_id=claimed["conversation_id"],
            error=error,
        )
        return _finalize_operation(
            operation_id,
            OPERATION_STATUS_FAILED,
            error_class=type(error).__name__[:200],
        )

    if live_definition.version != claimed["tool_version"]:
        version_error = ToolVersionMismatchError(
            "Registered tool version no longer matches the approved operation"
        )
        record_rejected_tool_attempt(
            tool_name=claimed["tool_name"],
            conversation_id=claimed["conversation_id"],
            error=version_error,
        )
        return _finalize_operation(
            operation_id,
            OPERATION_STATUS_FAILED,
            error_class=type(version_error).__name__[:200],
        )

    context = ToolExecutionContext(
        conversation_id=claimed["conversation_id"],
        project=claimed["project"],
        approved=True,
    )

    try:
        result = execute_tool(
            tool_name=claimed["tool_name"],
            arguments=arguments,
            context=context,
        )
    except Exception as error:
        return _finalize_operation(
            operation_id,
            OPERATION_STATUS_FAILED,
            error_class=type(error).__name__[:200],
        )

    reference = None
    if isinstance(result.data, dict):
        reference = result.data.get("id")
    return _finalize_operation(
        operation_id,
        OPERATION_STATUS_SUCCEEDED,
        result_run_id=result.run_id,
        result_reference=str(reference) if reference is not None else None,
    )


def reject_operation(operation_id: str) -> dict[str, Any]:
    """Move one pending operation to rejected. Executes nothing."""
    if _expire_stale_pending_operation(operation_id):
        raise OperationExpiredError("Operation has expired")

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        operation = _get_operation_row(connection, operation_id)
        if operation is None:
            raise OperationNotFoundError("Operation not found")

        if operation["status"] != OPERATION_STATUS_PENDING:
            raise OperationNotPendingError(operation["status"])

        now = _utc_now().isoformat()
        updated = connection.execute(
            """
            UPDATE tool_operations
            SET status = ?, updated_at = ?, decided_at = ?
            WHERE id = ? AND status = ?
            """,
            (OPERATION_STATUS_REJECTED, now, now, operation_id, OPERATION_STATUS_PENDING),
        )
        if updated.rowcount != 1:
            raise OperationNotPendingError(operation["status"])
        return _row_to_public(_get_operation_row(connection, operation_id))
