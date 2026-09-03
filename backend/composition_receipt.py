"""Read-only V0.4D mission receipts derived from existing audit state."""

import hashlib
import json
from dataclasses import dataclass, field, replace

from backend.composition_runtime import (
    STATUS_APPROVAL_PENDING,
    STATUS_BLOCKED,
    STATUS_FAILED,
    CompositionMissionRun,
    CompositionRuntimeError,
)
from backend.runs import RUN_STATUS_SUCCEEDED, get_run
from backend.tool_operations import (
    OPERATION_STATUS_EXECUTING,
    OPERATION_STATUS_EXPIRED,
    OPERATION_STATUS_FAILED,
    OPERATION_STATUS_PENDING,
    OPERATION_STATUS_REJECTED,
    OPERATION_STATUS_SUCCEEDED,
    get_operation,
)


class CompositionReceiptError(ValueError):
    """Raised when mission or durable audit metadata cannot be bound."""


STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
MAX_RECEIPT_BYTES = 128 * 1024
_OPERATION_TO_MISSION_STATUS = {
    OPERATION_STATUS_PENDING: STATUS_APPROVAL_PENDING,
    OPERATION_STATUS_EXECUTING: STATUS_RUNNING,
    OPERATION_STATUS_SUCCEEDED: STATUS_COMPLETED,
    OPERATION_STATUS_REJECTED: STATUS_REJECTED,
    OPERATION_STATUS_FAILED: STATUS_FAILED,
    OPERATION_STATUS_EXPIRED: STATUS_EXPIRED,
}


def _digest(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_is_authoritative(runtime):
    try:
        return replace(runtime) == runtime
    except (CompositionRuntimeError, TypeError, ValueError):
        return False


def _safe_identity(value, name, *, optional=False):
    if optional and not value:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise CompositionReceiptError(f"{name} is missing")
    text = value.strip()
    if len(text.encode("utf-8")) > 200:
        raise CompositionReceiptError(f"{name} exceeds its byte limit")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise CompositionReceiptError(f"{name} contains controls")
    return text


def _validate_read_runs(runtime):
    run_ids = []
    for step in runtime.step_runs:
        if not step.run_id:
            continue
        run = get_run(step.run_id)
        if run is None:
            raise CompositionReceiptError("bound tool Run is missing")
        if (
            run["tool_name"] != step.tool_name
            or run["tool_version"] != step.tool_version
            or run["status"] != RUN_STATUS_SUCCEEDED
        ):
            raise CompositionReceiptError("bound tool Run is inconsistent")
        run_ids.append(step.run_id)
    return tuple(run_ids)


def _validate_operation(runtime, operation):
    if operation is None:
        raise CompositionReceiptError("pending operation is missing")
    if (
        operation.get("id") != runtime.pending_operation_id
        or operation.get("tool_name") != runtime.pending_tool_name
        or operation.get("tool_version") != runtime.pending_tool_version
        or _digest(operation.get("arguments"))
        != runtime.pending_arguments_sha256
        or operation.get("project") != runtime.selected_project
    ):
        raise CompositionReceiptError("pending operation binding differs")
    status = operation.get("status")
    if status not in _OPERATION_TO_MISSION_STATUS:
        raise CompositionReceiptError("operation status is unsupported")
    if status == OPERATION_STATUS_SUCCEEDED:
        result_run_id = operation.get("result_run_id")
        result_run = get_run(result_run_id) if result_run_id else None
        if (
            result_run is None
            or result_run["tool_name"] != runtime.pending_tool_name
            or result_run["tool_version"] != runtime.pending_tool_version
            or result_run["status"] != RUN_STATUS_SUCCEEDED
        ):
            raise CompositionReceiptError(
                "terminal write Run is missing or inconsistent"
            )
    return status


@dataclass(frozen=True)
class CompositionMissionReceipt:
    """Bounded audit view; it owns no execution or approval behavior."""

    runtime: CompositionMissionRun
    status: str
    plan_sha256: str
    read_run_ids: tuple
    operation_id: str = ""
    operation_status: str = ""
    terminal_write_run_id: str = ""
    terminal_result_reference: str = ""
    failure_class: str = ""
    mission_persisted: bool = field(default=False, init=False)
    generalized_resume_supported: bool = field(default=False, init=False)
    automatic_approval_performed: bool = field(default=False, init=False)
    external_identity_authenticated: bool = field(default=False, init=False)
    write_executed: bool = field(init=False)

    def __post_init__(self):
        if not isinstance(self.runtime, CompositionMissionRun):
            raise CompositionReceiptError("invalid mission runtime")
        run_ids = tuple(self.read_run_ids)
        if any(not isinstance(item, str) or not item for item in run_ids):
            raise CompositionReceiptError("read Run identities are malformed")
        expected_plan_digest = _digest(self.runtime.plan.to_dict())
        if self.plan_sha256 != expected_plan_digest:
            raise CompositionReceiptError("plan binding is forged")
        if self.operation_status:
            expected_status = _OPERATION_TO_MISSION_STATUS.get(
                self.operation_status
            )
            if expected_status is None or self.status != expected_status:
                raise CompositionReceiptError("receipt status is forged")
            if self.operation_id != self.runtime.pending_operation_id:
                raise CompositionReceiptError("operation identity is forged")
        elif self.status != self.runtime.status or self.operation_id:
            raise CompositionReceiptError("receipt source status is forged")
        write_executed = self.operation_status == OPERATION_STATUS_SUCCEEDED
        if write_executed and not self.terminal_write_run_id:
            raise CompositionReceiptError("completed receipt lacks write Run")
        if not write_executed and self.terminal_write_run_id:
            raise CompositionReceiptError(
                "unexecuted receipt claims write Run"
            )
        if self.failure_class:
            _safe_identity(self.failure_class, "failure_class")
        if self.terminal_result_reference:
            _safe_identity(
                self.terminal_result_reference,
                "terminal_result_reference",
                optional=True,
            )
        object.__setattr__(self, "read_run_ids", run_ids)
        object.__setattr__(self, "write_executed", write_executed)
        if len(self.summary().encode("utf-8")) > MAX_RECEIPT_BYTES:
            raise CompositionReceiptError("mission receipt exceeds byte limit")

    def to_dict(self):
        return {
            "authority": {
                "automatic_approval_performed": (
                    self.automatic_approval_performed
                ),
                "external_identity_authenticated": (
                    self.external_identity_authenticated
                ),
                "generalized_resume_supported": (
                    self.generalized_resume_supported
                ),
                "mission_persisted": self.mission_persisted,
                "write_executed": self.write_executed,
            },
            "audit": {
                "failure_class": self.failure_class,
                "operation_id": self.operation_id,
                "operation_status": self.operation_status,
                "read_run_ids": list(self.read_run_ids),
                "terminal_result_reference": (
                    self.terminal_result_reference
                ),
                "terminal_write_run_id": self.terminal_write_run_id,
            },
            "budget": {
                "executed_requests": self.runtime.executed_requests,
                "processed_requests": self.runtime.processed_requests,
                "request_signatures": list(
                    self.runtime.request_signatures
                ),
            },
            "data_flow": {
                "listed_open_task_count": (
                    self.runtime.listed_open_task_count
                ),
                "memory_match_count": self.runtime.memory_match_count,
                "open_task_count": self.runtime.open_task_count,
                "selected_project": self.runtime.selected_project,
            },
            "goal_sha256": self.runtime.plan.proposal.goal_sha256,
            "mission_id": self.runtime.plan.proposal.mission_id,
            "plan_sha256": self.plan_sha256,
            "registry_snapshot_sha256": (
                self.runtime.plan.registry_snapshot_sha256
            ),
            "status": self.status,
            "steps": [item.to_dict() for item in self.runtime.step_runs],
        }

    def summary(self):
        return json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, indent=2
        ) + "\n"


def create_composition_mission_receipt(runtime):
    """Read existing Run/operation state and derive one audit receipt."""
    if (
        not isinstance(runtime, CompositionMissionRun)
        or not _runtime_is_authoritative(runtime)
    ):
        raise CompositionReceiptError("runtime must be authoritative")
    read_run_ids = _validate_read_runs(runtime)
    operation = None
    operation_status = ""
    status = runtime.status
    if runtime.status == STATUS_APPROVAL_PENDING:
        operation = get_operation(runtime.pending_operation_id)
        operation_status = _validate_operation(runtime, operation)
        status = _OPERATION_TO_MISSION_STATUS[operation_status]
    elif runtime.status not in (STATUS_BLOCKED, STATUS_FAILED):
        raise CompositionReceiptError("runtime status is unsupported")

    return CompositionMissionReceipt(
        runtime=runtime,
        status=status,
        plan_sha256=_digest(runtime.plan.to_dict()),
        read_run_ids=read_run_ids,
        operation_id=runtime.pending_operation_id if operation else "",
        operation_status=operation_status,
        terminal_write_run_id=(
            operation.get("result_run_id") or "" if operation else ""
        ),
        terminal_result_reference=(
            operation.get("result_reference") or "" if operation else ""
        ),
        failure_class=(
            operation.get("error_class") or ""
            if operation
            else runtime.failure_class
        ),
    )
