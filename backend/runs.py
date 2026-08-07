"""Structured execution records for model calls and future tools."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db import database_connection


RUN_TYPE_MODEL = "model"
RUN_TYPE_TOOL = "tool"
RUN_STATUS_STARTED = "started"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_FAILED = "failed"
RUN_COLUMNS = """
    id,
    run_type,
    status,
    conversation_id,
    user_message_id,
    assistant_message_id,
    provider,
    model,
    started_at,
    finished_at,
    duration_ms,
    error_class,
    input_tokens,
    output_tokens,
    cost_usd,
    data_exposure
"""


class RunNotFoundError(ValueError):
    """Raised when a run ID does not exist."""


class RunAlreadyFinishedError(ValueError):
    """Raised when a terminal run is finalized again."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _duration_ms(started_at: str, finished_at: datetime) -> int:
    started = datetime.fromisoformat(started_at)
    return max(0, int((finished_at - started).total_seconds() * 1000))


def _get_run(connection, run_id: str) -> Optional[dict[str, Any]]:
    row = connection.execute(
        f"SELECT {RUN_COLUMNS} FROM runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    return dict(row) if row else None


def start_model_run(
    *,
    conversation_id: Optional[str],
    provider: Optional[str],
    model: Optional[str],
    data_exposure: Optional[str] = "model_provider",
) -> dict[str, Any]:
    """Persist a started model run before the provider request begins.

    Conversation and message references are intentionally not foreign keys. A new
    chat is not committed until model generation succeeds, but a failed provider
    attempt still needs an audit record.
    """
    started_at = _utc_now().isoformat()
    run = {
        "id": str(uuid.uuid4()),
        "run_type": RUN_TYPE_MODEL,
        "status": RUN_STATUS_STARTED,
        "conversation_id": conversation_id,
        "user_message_id": None,
        "assistant_message_id": None,
        "provider": provider,
        "model": model,
        "started_at": started_at,
        "finished_at": None,
        "duration_ms": None,
        "error_class": None,
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "data_exposure": data_exposure,
    }
    with database_connection() as connection:
        connection.execute(
            """
            INSERT INTO runs (
                id, run_type, status, conversation_id, user_message_id,
                assistant_message_id, provider, model, started_at, finished_at,
                duration_ms, error_class, input_tokens, output_tokens, cost_usd,
                data_exposure
            ) VALUES (
                :id, :run_type, :status, :conversation_id, :user_message_id,
                :assistant_message_id, :provider, :model, :started_at, :finished_at,
                :duration_ms, :error_class, :input_tokens, :output_tokens, :cost_usd,
                :data_exposure
            )
            """,
            run,
        )
    return run


def finish_model_run_success(
    run_id: str,
    *,
    conversation_id: Optional[str] = None,
    user_message_id: Optional[str] = None,
    assistant_message_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cost_usd: Optional[float] = None,
) -> dict[str, Any]:
    """Finalize one started model run after chat persistence succeeds."""
    finished_at = _utc_now()
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        run = _get_run(connection, run_id)
        if run is None:
            raise RunNotFoundError("Run not found")
        if run["status"] != RUN_STATUS_STARTED:
            raise RunAlreadyFinishedError("Run is already finished")

        updated = connection.execute(
            """
            UPDATE runs
            SET status = ?,
                conversation_id = COALESCE(?, conversation_id),
                user_message_id = COALESCE(?, user_message_id),
                assistant_message_id = COALESCE(?, assistant_message_id),
                provider = COALESCE(?, provider),
                model = COALESCE(?, model),
                finished_at = ?,
                duration_ms = ?,
                error_class = NULL,
                input_tokens = ?,
                output_tokens = ?,
                cost_usd = ?
            WHERE id = ? AND status = ?
            """,
            (
                RUN_STATUS_SUCCEEDED,
                conversation_id,
                user_message_id,
                assistant_message_id,
                provider,
                model,
                finished_at.isoformat(),
                _duration_ms(run["started_at"], finished_at),
                input_tokens,
                output_tokens,
                cost_usd,
                run_id,
                RUN_STATUS_STARTED,
            ),
        )
        if updated.rowcount != 1:
            raise RunAlreadyFinishedError("Run is already finished")
        saved = _get_run(connection, run_id)
        if saved is None:
            raise RuntimeError("Run completion did not persist")
        return saved


def finish_model_run_failure(run_id: str, error: BaseException) -> dict[str, Any]:
    """Finalize one started run without storing private exception messages."""
    finished_at = _utc_now()
    error_class = type(error).__name__[:200]
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        run = _get_run(connection, run_id)
        if run is None:
            raise RunNotFoundError("Run not found")
        if run["status"] != RUN_STATUS_STARTED:
            raise RunAlreadyFinishedError("Run is already finished")

        updated = connection.execute(
            """
            UPDATE runs
            SET status = ?, finished_at = ?, duration_ms = ?, error_class = ?
            WHERE id = ? AND status = ?
            """,
            (
                RUN_STATUS_FAILED,
                finished_at.isoformat(),
                _duration_ms(run["started_at"], finished_at),
                error_class,
                run_id,
                RUN_STATUS_STARTED,
            ),
        )
        if updated.rowcount != 1:
            raise RunAlreadyFinishedError("Run is already finished")
        saved = _get_run(connection, run_id)
        if saved is None:
            raise RuntimeError("Run failure did not persist")
        return saved


def get_run(run_id: str) -> Optional[dict[str, Any]]:
    """Return one run by ID."""
    with database_connection() as connection:
        return _get_run(connection, run_id)


def list_runs(
    *,
    conversation_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent runs without exposing any prompt or response content."""
    safe_limit = max(1, min(limit, 500))
    with database_connection() as connection:
        if conversation_id is None:
            rows = connection.execute(
                f"SELECT {RUN_COLUMNS} FROM runs ORDER BY started_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        else:
            rows = connection.execute(
                f"""
                SELECT {RUN_COLUMNS}
                FROM runs
                WHERE conversation_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (conversation_id, safe_limit),
            ).fetchall()
    return [dict(row) for row in rows]
