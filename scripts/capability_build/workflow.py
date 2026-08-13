"""Pure offline workflow state for MootOS V0.4B Slice 1.

This module describes which capability-build orchestration steps have been
recorded and which step may be recorded next. It performs no orchestration:
there is no execution, filesystem, network, Git, registry, installation,
deployment, worker-dispatch, or runtime authority.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional


class WorkflowError(ValueError):
    """Raised when workflow state or a requested step is invalid."""


SCHEMA_VERSION = 1
MAX_WORKFLOW_SUMMARY_BYTES = 16 * 1024

STEP_REQUEST_RECEIVED = "request_received"
STEP_JOB_CREATED = "job_created"
STEP_SCOPE_FROZEN = "scope_frozen"
STEP_BRIEF_READY = "brief_ready"
STEP_WORKER_RETURNED = "worker_returned"
STEP_INTAKE_CHECKED = "intake_checked"
STEP_EVIDENCE_ATTACHED = "evidence_attached"
STEP_BUNDLE_CREATED = "bundle_created"
STEP_HANDOFF_CREATED = "handoff_created"
STEP_HUMAN_DECISION_PENDING = "human_decision_pending"

WORKFLOW_STEPS = (
    STEP_REQUEST_RECEIVED,
    STEP_JOB_CREATED,
    STEP_SCOPE_FROZEN,
    STEP_BRIEF_READY,
    STEP_WORKER_RETURNED,
    STEP_INTAKE_CHECKED,
    STEP_EVIDENCE_ATTACHED,
    STEP_BUNDLE_CREATED,
    STEP_HANDOFF_CREATED,
    STEP_HUMAN_DECISION_PENDING,
)

STATUS_NOT_STARTED = "not_started"
STATUS_IN_PROGRESS = "in_progress"
STATUS_BLOCKED = "blocked"
STATUS_COMPLETE = "complete"
WORKFLOW_STATUSES = (
    STATUS_NOT_STARTED,
    STATUS_IN_PROGRESS,
    STATUS_BLOCKED,
    STATUS_COMPLETE,
)

_STEP_INDEX = {step: index for index, step in enumerate(WORKFLOW_STEPS)}


def _step(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or value not in _STEP_INDEX:
        raise WorkflowError(f"unknown {field_name}: {value!r}")
    return value


def _completed_steps(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowError("completed_steps must be a sequence")
    try:
        completed = tuple(values)
    except TypeError as error:
        raise WorkflowError(
            "completed_steps must be a sequence"
        ) from error
    for value in completed:
        _step(value, "completed step")
    expected_prefix = WORKFLOW_STEPS[:len(completed)]
    if completed != expected_prefix:
        raise WorkflowError(
            "completed_steps must be the ordered prerequisite prefix"
        )
    return completed


def _blocked_reasons(
    completed_steps: tuple,
    blocked_step: Optional[str],
) -> tuple:
    if blocked_step is None:
        return ()
    required_step = WORKFLOW_STEPS[len(completed_steps)]
    return (
        f"Cannot record {blocked_step!r} before prerequisite "
        f"{required_step!r}.",
    )


@dataclass(frozen=True)
class WorkflowPlan:
    """Immutable description of recorded and next-allowed workflow steps."""

    completed_steps: tuple = ()
    blocked_step: Optional[str] = None
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    status: str = field(init=False)
    current_step: Optional[str] = field(init=False)
    blocked_reasons: tuple = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        completed = _completed_steps(self.completed_steps)
        if self.blocked_step is not None:
            blocked_step = _step(self.blocked_step, "blocked step")
            if len(completed) == len(WORKFLOW_STEPS):
                raise WorkflowError("a complete workflow cannot be blocked")
            required_index = len(completed)
            if _STEP_INDEX[blocked_step] <= required_index:
                raise WorkflowError(
                    "blocked_step must be later than its missing prerequisite"
                )
        else:
            blocked_step = None

        if blocked_step is not None:
            status = STATUS_BLOCKED
        elif not completed:
            status = STATUS_NOT_STARTED
        elif len(completed) == len(WORKFLOW_STEPS):
            status = STATUS_COMPLETE
        else:
            status = STATUS_IN_PROGRESS

        current_step = completed[-1] if completed else None
        next_allowed = (
            ()
            if len(completed) == len(WORKFLOW_STEPS)
            else (WORKFLOW_STEPS[len(completed)],)
        )
        reasons = _blocked_reasons(completed, blocked_step)

        object.__setattr__(self, "completed_steps", completed)
        object.__setattr__(self, "blocked_step", blocked_step)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "current_step", current_step)
        object.__setattr__(self, "blocked_reasons", reasons)
        object.__setattr__(self, "next_allowed_steps", next_allowed)

        if len(self.summary().encode("utf-8")) > MAX_WORKFLOW_SUMMARY_BYTES:
            raise WorkflowError(
                "workflow summary exceeds "
                f"{MAX_WORKFLOW_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic descriptive data with no raw user content."""
        return {
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocked_reasons": list(self.blocked_reasons),
            "blocked_step": self.blocked_step,
            "completed_steps": list(self.completed_steps),
            "current_step": self.current_step,
            "next_allowed_steps": list(self.next_allowed_steps),
            "schema_version": self.schema_version,
            "status": self.status,
        }

    def summary(self) -> str:
        """Return stable bounded JSON for offline human inspection."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"


def new_workflow() -> WorkflowPlan:
    """Return a new, inert workflow description with no recorded steps."""
    return WorkflowPlan()


def record_workflow_step(
    workflow: WorkflowPlan,
    step: str,
) -> WorkflowPlan:
    """Return new state recording a step or a missing-prerequisite block."""
    if not isinstance(workflow, WorkflowPlan):
        raise WorkflowError("workflow must be a WorkflowPlan")
    requested = _step(step, "workflow step")
    if workflow.status == STATUS_COMPLETE:
        raise WorkflowError("a complete workflow cannot record more steps")

    required = WORKFLOW_STEPS[len(workflow.completed_steps)]
    requested_index = _STEP_INDEX[requested]
    required_index = _STEP_INDEX[required]
    if requested_index < required_index:
        raise WorkflowError(f"workflow step already completed: {requested!r}")
    if requested_index > required_index:
        return WorkflowPlan(
            completed_steps=workflow.completed_steps,
            blocked_step=requested,
        )
    return WorkflowPlan(
        completed_steps=workflow.completed_steps + (requested,),
    )
