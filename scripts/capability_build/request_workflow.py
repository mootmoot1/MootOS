"""Pure request-to-workflow-start adapter for MootOS V0.4B Slice 3.

The adapter records only ``request_received`` for a ready request. It does
not create jobs, freeze scope, build artifacts, execute anything, access
files or networks, invoke Git or GitHub, register or install capabilities,
or exercise runtime, deployment, or autonomous authority.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from scripts.capability_build.request import (
    MAX_CAPABILITY_NAME_BYTES,
    MAX_REQUEST_ID_BYTES,
    STATUS_BLOCKED as REQUEST_BLOCKED,
    STATUS_DRAFT as REQUEST_DRAFT,
    STATUS_READY_FOR_WORKFLOW,
    CapabilityBuildRequest,
)
from scripts.capability_build.workflow import (
    STATUS_NOT_STARTED as WORKFLOW_NOT_STARTED,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    WorkflowPlan,
    new_workflow,
    record_workflow_step,
)


class RequestWorkflowError(ValueError):
    """Raised when workflow start input or derived state is invalid."""


SCHEMA_VERSION = 1
STATUS_WORKFLOW_STARTED = "workflow_started"
STATUS_NOT_STARTED = "not_started"
RESULT_STATUSES = (
    STATUS_WORKFLOW_STARTED,
    STATUS_NOT_STARTED,
)
MAX_START_SUMMARY_BYTES = 16 * 1024

_DRAFT_REASON = "Requester decision is still required."


@dataclass(frozen=True)
class RequestMetadata:
    """Bounded request identity only; human intent prose is omitted."""

    request_id: str
    capability_name: str
    request_status: str
    requester_decision_required: bool

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str):
            raise RequestWorkflowError("request_id must be text")
        if not isinstance(self.capability_name, str):
            raise RequestWorkflowError("capability_name must be text")
        if self.request_status not in (
            REQUEST_DRAFT,
            STATUS_READY_FOR_WORKFLOW,
            REQUEST_BLOCKED,
        ):
            raise RequestWorkflowError(
                f"unsupported request status: {self.request_status!r}"
            )
        if not isinstance(self.requester_decision_required, bool):
            raise RequestWorkflowError(
                "requester_decision_required must be a boolean"
            )
        if len(self.request_id.encode("utf-8")) > MAX_REQUEST_ID_BYTES:
            raise RequestWorkflowError("request_id is too large")
        if (
            len(self.capability_name.encode("utf-8"))
            > MAX_CAPABILITY_NAME_BYTES
        ):
            raise RequestWorkflowError("capability_name is too large")
        if self.request_status != REQUEST_BLOCKED and (
            not self.request_id or not self.capability_name
        ):
            raise RequestWorkflowError(
                "ready or draft metadata requires request identity"
            )
        if self.request_status == STATUS_READY_FOR_WORKFLOW and (
            self.requester_decision_required
        ):
            raise RequestWorkflowError(
                "ready request cannot require a requester decision"
            )
        if self.request_status == REQUEST_DRAFT and not (
            self.requester_decision_required
        ):
            raise RequestWorkflowError(
                "draft request must require a requester decision"
            )

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "request_id": self.request_id,
            "request_status": self.request_status,
            "requester_decision_required": (
                self.requester_decision_required
            ),
        }


def _stable_reasons(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise RequestWorkflowError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise RequestWorkflowError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise RequestWorkflowError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _expected_reasons(
    request_status: str,
    request_reasons: tuple,
) -> tuple:
    if request_status == STATUS_READY_FOR_WORKFLOW:
        return ()
    if request_status == REQUEST_DRAFT:
        return (_DRAFT_REASON,)
    if request_status == REQUEST_BLOCKED:
        if not request_reasons:
            raise RequestWorkflowError(
                "blocked request must contain blocking reasons"
            )
        return _stable_reasons(request_reasons)
    raise RequestWorkflowError(
        f"unsupported request status: {request_status!r}"
    )


@dataclass(frozen=True)
class RequestWorkflowStart:
    """Immutable result describing whether request intake started workflow."""

    request: RequestMetadata
    request_blocking_reasons: tuple
    workflow: WorkflowPlan
    status: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    started: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, RequestMetadata):
            raise RequestWorkflowError("request metadata is required")
        request_reasons = _stable_reasons(self.request_blocking_reasons)
        if self.request.request_status != REQUEST_BLOCKED and request_reasons:
            raise RequestWorkflowError(
                "ready or draft request cannot contain blocking reasons"
            )
        expected_reasons = _expected_reasons(
            self.request.request_status,
            request_reasons,
        )
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != expected_reasons:
            raise RequestWorkflowError(
                "blocking reasons do not match request status"
            )
        if not isinstance(self.workflow, WorkflowPlan):
            raise RequestWorkflowError("workflow must be a WorkflowPlan")

        should_start = self.request.request_status == STATUS_READY_FOR_WORKFLOW
        expected_status = (
            STATUS_WORKFLOW_STARTED if should_start else STATUS_NOT_STARTED
        )
        if self.status != expected_status:
            raise RequestWorkflowError(
                "result status does not match request readiness"
            )
        if should_start:
            if self.workflow.completed_steps != (STEP_REQUEST_RECEIVED,):
                raise RequestWorkflowError(
                    "started workflow must record only request_received"
                )
            if self.workflow.next_allowed_steps != (STEP_JOB_CREATED,):
                raise RequestWorkflowError(
                    "started workflow must allow only job_created next"
                )
        else:
            if self.workflow.status != WORKFLOW_NOT_STARTED:
                raise RequestWorkflowError(
                    "blocked request workflow must remain not_started"
                )
            if self.workflow.completed_steps:
                raise RequestWorkflowError(
                    "blocked request cannot record workflow steps"
                )
            if self.workflow.next_allowed_steps != (STEP_REQUEST_RECEIVED,):
                raise RequestWorkflowError(
                    "unstarted workflow must allow request_received next"
                )

        object.__setattr__(
            self, "request_blocking_reasons", request_reasons
        )
        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "started", should_start)
        object.__setattr__(
            self, "next_allowed_steps", self.workflow.next_allowed_steps
        )

        if len(self.summary().encode("utf-8")) > MAX_START_SUMMARY_BYTES:
            raise RequestWorkflowError(
                "workflow-start summary exceeds "
                f"{MAX_START_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic review-safe workflow-start information."""
        return {
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "next_allowed_steps": list(self.next_allowed_steps),
            "request": self.request.to_dict(),
            "schema_version": self.schema_version,
            "started": self.started,
            "status": self.status,
            "workflow": self.workflow.to_dict(),
        }

    def summary(self) -> str:
        """Return stable bounded JSON without request prose or artifacts."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"


def start_workflow_from_request(
    request: CapabilityBuildRequest,
) -> RequestWorkflowStart:
    """Record request_received only when a normalized request is ready."""
    if not isinstance(request, CapabilityBuildRequest):
        raise RequestWorkflowError(
            "request must be a CapabilityBuildRequest"
        )

    metadata = RequestMetadata(
        request_id=request.request_id,
        capability_name=request.capability_name,
        request_status=request.status,
        requester_decision_required=request.requester_decision_required,
    )
    request_reasons = _stable_reasons(request.blocking_reasons)
    reasons = _expected_reasons(request.status, request_reasons)
    workflow = new_workflow()
    if request.status == STATUS_READY_FOR_WORKFLOW:
        workflow = record_workflow_step(workflow, STEP_REQUEST_RECEIVED)
        status = STATUS_WORKFLOW_STARTED
    else:
        status = STATUS_NOT_STARTED
    return RequestWorkflowStart(
        request=metadata,
        request_blocking_reasons=request_reasons,
        workflow=workflow,
        status=status,
        blocking_reasons=reasons,
    )
