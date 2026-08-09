"""Authenticated HTTP API for reviewing and deciding MootOS Tool operations.

These routes never accept tool arguments. Approval can only ever run the
exact frozen operation created by the model conversation loop
(``backend/tool_conversation.py``); rejection can only ever mark it
rejected. See ``backend/tool_operations.py`` for the state machine and its
duplicate-safety guarantees.
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.tool_operations import (
    OperationExpiredError,
    OperationNotFoundError,
    OperationNotPendingError,
    approve_operation,
    get_operation,
    list_pending_operations,
    reject_operation,
)


router = APIRouter(prefix="/tool-operations", tags=["tool-operations"])


@router.get("")
def list_pending_tool_operations(
    conversation_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List pending tool operations awaiting approval, newest first."""
    operations = list_pending_operations(conversation_id=conversation_id, limit=limit)
    return {"success": True, "data": operations}


@router.get("/{operation_id}")
def get_tool_operation(operation_id: str) -> dict[str, Any]:
    """Return one tool operation and its current state."""
    operation = get_operation(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    return {"success": True, "data": operation}


@router.post("/{operation_id}/approve")
def approve_tool_operation(operation_id: str) -> dict[str, Any]:
    """Execute the exact frozen tool call a pending operation represents.

    A retry or double-click on an already-decided operation returns 409
    rather than executing again -- see ``backend.tool_operations`` for the
    atomic claim that makes this safe.
    """
    try:
        operation = approve_operation(operation_id)
    except OperationNotFoundError as error:
        raise HTTPException(status_code=404, detail="Operation not found") from error
    except OperationExpiredError as error:
        raise HTTPException(status_code=409, detail="Operation has expired") from error
    except OperationNotPendingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "data": operation}


@router.post("/{operation_id}/reject")
def reject_tool_operation(operation_id: str) -> dict[str, Any]:
    """Reject one pending tool operation. Executes nothing."""
    try:
        operation = reject_operation(operation_id)
    except OperationNotFoundError as error:
        raise HTTPException(status_code=404, detail="Operation not found") from error
    except OperationExpiredError as error:
        raise HTTPException(status_code=409, detail="Operation has expired") from error
    except OperationNotPendingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "data": operation}
