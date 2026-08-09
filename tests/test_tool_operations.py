"""Tests for the frozen tool-operation approval state machine."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.db import DATABASE_PATH, database_connection
from backend.memory import init_db
from backend.tasks import list_tasks
from backend.tool_operations import (
    OPERATION_STATUS_EXPIRED,
    OPERATION_STATUS_PENDING,
    OPERATION_STATUS_REJECTED,
    OPERATION_STATUS_SUCCEEDED,
    OperationExpiredError,
    OperationNotFoundError,
    OperationNotPendingError,
    approve_operation,
    create_pending_operation,
    get_operation,
    list_pending_operations,
    reject_operation,
)


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _create_task_operation(**overrides):
    defaults = {
        "tool_name": "tasks.create",
        "tool_version": "1",
        "arguments": {"title": "Call Mike"},
        "conversation_id": "conversation-1",
        "project": None,
    }
    defaults.update(overrides)
    return create_pending_operation(**defaults)


def test_pending_operation_persists_with_frozen_arguments(clean_db):
    operation = _create_task_operation(arguments={"title": "Call Mike", "project": "Studio"})

    assert operation["status"] == OPERATION_STATUS_PENDING
    assert operation["arguments"] == {"title": "Call Mike", "project": "Studio"}

    reloaded = get_operation(operation["id"])
    assert reloaded["arguments"] == {"title": "Call Mike", "project": "Studio"}
    assert reloaded["tool_name"] == "tasks.create"


def test_creating_an_operation_never_executes_anything(clean_db):
    _create_task_operation()
    assert list_tasks() == []


def test_approve_executes_the_frozen_operation_exactly_once(clean_db):
    operation = _create_task_operation(arguments={"title": "Call Mike"})

    approved = approve_operation(operation["id"])

    assert approved["status"] == OPERATION_STATUS_SUCCEEDED
    assert approved["result_reference"] is not None
    assert approved["error_class"] is None

    tasks = list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Call Mike"
    assert tasks[0]["id"] == approved["result_reference"]


def test_approved_operation_with_omitted_due_at_creates_exactly_one_task(clean_db):
    """Live-approval-testing regression: due_at is optional, and omitting it
    (as opposed to a placeholder string like "none") must approve and
    execute cleanly, creating exactly one Task with no due date."""
    operation = _create_task_operation(arguments={"title": "Call Mike"})
    assert "due_at" not in operation["arguments"]

    approved = approve_operation(operation["id"])

    assert approved["status"] == OPERATION_STATUS_SUCCEEDED
    tasks = list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Call Mike"
    assert tasks[0]["due_at"] is None


def test_duplicate_approval_does_not_duplicate_the_task(clean_db):
    operation = _create_task_operation()

    approve_operation(operation["id"])
    with pytest.raises(OperationNotPendingError):
        approve_operation(operation["id"])

    assert len(list_tasks()) == 1


def test_reject_executes_nothing(clean_db):
    operation = _create_task_operation()

    rejected = reject_operation(operation["id"])

    assert rejected["status"] == OPERATION_STATUS_REJECTED
    assert list_tasks() == []


def test_rejected_operation_cannot_later_be_approved(clean_db):
    operation = _create_task_operation()
    reject_operation(operation["id"])

    with pytest.raises(OperationNotPendingError):
        approve_operation(operation["id"])

    assert list_tasks() == []


def test_approving_an_already_rejected_operation_is_rejected(clean_db):
    operation = _create_task_operation()
    reject_operation(operation["id"])

    with pytest.raises(OperationNotPendingError):
        approve_operation(operation["id"])


def test_terminal_operations_cannot_be_rejected_again(clean_db):
    operation = _create_task_operation()
    approve_operation(operation["id"])

    with pytest.raises(OperationNotPendingError):
        reject_operation(operation["id"])


def test_unknown_operation_id_raises_not_found(clean_db):
    with pytest.raises(OperationNotFoundError):
        approve_operation("does-not-exist")
    with pytest.raises(OperationNotFoundError):
        reject_operation("does-not-exist")
    assert get_operation("does-not-exist") is None


def test_list_pending_operations_excludes_decided_ones(clean_db):
    pending = _create_task_operation(arguments={"title": "Still pending"})
    decided = _create_task_operation(arguments={"title": "Already approved"})
    approve_operation(decided["id"])

    pending_ids = {item["id"] for item in list_pending_operations()}

    assert pending["id"] in pending_ids
    assert decided["id"] not in pending_ids


def test_list_pending_operations_can_scope_to_one_conversation(clean_db):
    _create_task_operation(conversation_id="conversation-a", arguments={"title": "A"})
    _create_task_operation(conversation_id="conversation-b", arguments={"title": "B"})

    scoped = list_pending_operations(conversation_id="conversation-a")

    assert len(scoped) == 1
    assert scoped[0]["conversation_id"] == "conversation-a"


def test_expired_pending_operation_fails_closed_on_approve(clean_db):
    operation = _create_task_operation()
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with database_connection() as connection:
        connection.execute(
            "UPDATE tool_operations SET expires_at = ? WHERE id = ?",
            (past, operation["id"]),
        )

    with pytest.raises(OperationExpiredError):
        approve_operation(operation["id"])

    reloaded = get_operation(operation["id"])
    assert reloaded["status"] == OPERATION_STATUS_EXPIRED
    assert list_tasks() == []


def test_expired_pending_operation_fails_closed_on_reject(clean_db):
    operation = _create_task_operation()
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with database_connection() as connection:
        connection.execute(
            "UPDATE tool_operations SET expires_at = ? WHERE id = ?",
            (past, operation["id"]),
        )

    with pytest.raises(OperationExpiredError):
        reject_operation(operation["id"])

    assert get_operation(operation["id"])["status"] == OPERATION_STATUS_EXPIRED


def test_operation_with_no_ttl_never_expires(clean_db):
    operation = create_pending_operation(
        tool_name="tasks.create",
        tool_version="1",
        arguments={"title": "No expiry"},
        conversation_id=None,
        project=None,
        ttl_seconds=None,
    )
    assert operation["expires_at"] is None

    approved = approve_operation(operation["id"])
    assert approved["status"] == OPERATION_STATUS_SUCCEEDED


def test_approval_failure_is_recorded_without_leaking_details(clean_db):
    operation = create_pending_operation(
        tool_name="tasks.create",
        tool_version="1",
        arguments={"title": "Call Mike", "project": "Does Not Exist"},
        conversation_id=None,
        project=None,
    )

    approved = approve_operation(operation["id"])

    assert approved["status"] == "failed"
    assert approved["error_class"] == "ToolExecutionError"
    assert list_tasks() == []


# --- Frozen tool-version enforcement (Grok audit remediation) ------------------


def test_approval_executes_when_frozen_version_matches_the_registered_one(clean_db):
    """tasks.create is registered at version "1" in this build; an operation
    frozen at that same version must still execute normally."""
    operation = _create_task_operation(tool_version="1", arguments={"title": "Call Mike"})

    approved = approve_operation(operation["id"])

    assert approved["status"] == OPERATION_STATUS_SUCCEEDED
    assert len(list_tasks()) == 1


def test_approval_refuses_a_changed_tool_version_and_executes_nothing(clean_db):
    """The frozen operation names a version ("99") that no longer matches
    the currently registered tool ("1"). Approval must execute nothing."""
    operation = _create_task_operation(tool_version="99", arguments={"title": "Should never run"})

    approved = approve_operation(operation["id"])

    assert approved["status"] == "failed"
    assert approved["error_class"] == "ToolVersionMismatchError"
    assert list_tasks() == []


def test_approval_refuses_a_removed_or_unregistered_tool_and_executes_nothing(clean_db):
    operation = _create_task_operation(
        tool_name="tasks.no_longer_exists",
        tool_version="1",
        arguments={"title": "Should never run"},
    )

    approved = approve_operation(operation["id"])

    assert approved["status"] == "failed"
    assert approved["error_class"] == "ToolNotFoundError"
    assert list_tasks() == []


def test_version_mismatch_and_unregistered_rejections_still_leave_an_audit_run(clean_db):
    from backend.runs import RUN_TYPE_TOOL, list_runs

    mismatched = _create_task_operation(tool_version="99", arguments={"title": "A"})
    approve_operation(mismatched["id"])

    unregistered = _create_task_operation(
        tool_name="tasks.no_longer_exists", tool_version="1", arguments={"title": "B"}
    )
    approve_operation(unregistered["id"])

    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    assert len(tool_runs) == 2
    assert {run["status"] for run in tool_runs} == {"failed"}
    error_classes = {run["error_class"] for run in tool_runs}
    assert error_classes == {"ToolVersionMismatchError", "ToolNotFoundError"}
