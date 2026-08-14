"""Pure workflow-to-BuildJob adapter for MootOS V0.4B Slice 5.

This module creates only an in-memory ``BuildJob`` and records only the
``job_created`` workflow step. It performs no persistence, scope freezing,
workspace or artifact creation, execution, network access, Git or GitHub
operation, registration, installation, deployment, or runtime action.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.capability_build.job import (
    STATE_DRAFTED,
    BuildJob,
    new_job,
)
from scripts.capability_build.job_binding import (
    STATUS_READY_FOR_JOB_CREATION,
    BuildJobBinding,
)
from scripts.capability_build.request_workflow import (
    STATUS_WORKFLOW_STARTED,
    RequestWorkflowStart,
)
from scripts.capability_build.workflow import (
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    WorkflowPlan,
    record_workflow_step,
)


class WorkflowJobError(ValueError):
    """Raised when workflow-to-job state cannot be represented safely."""


SCHEMA_VERSION = 1
STATUS_JOB_CREATED = "job_created"
STATUS_NOT_CREATED = "not_created"
RESULT_STATUSES = (
    STATUS_JOB_CREATED,
    STATUS_NOT_CREATED,
)
MAX_WORKFLOW_JOB_SUMMARY_BYTES = 16 * 1024


def _stable_reasons(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowJobError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowJobError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowJobError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _start_is_ready(start: RequestWorkflowStart) -> bool:
    return (
        start.status == STATUS_WORKFLOW_STARTED
        and start.started
        and start.workflow.completed_steps == (STEP_REQUEST_RECEIVED,)
        and start.workflow.next_allowed_steps == (STEP_JOB_CREATED,)
    )


def _binding_is_ready(binding: BuildJobBinding) -> bool:
    return (
        binding.status == STATUS_READY_FOR_JOB_CREATION
        and binding.ready_for_job_creation
        and not binding.blocking_reasons
    )


def _expected_reasons(
    start: RequestWorkflowStart,
    binding: BuildJobBinding,
) -> tuple:
    reasons = ()
    if not _start_is_ready(start):
        reasons += start.blocking_reasons
    if not _binding_is_ready(binding):
        reasons += binding.blocking_reasons
    return _stable_reasons(reasons)


def _validate_created_job(job: BuildJob, binding: BuildJobBinding) -> None:
    if job.state != STATE_DRAFTED or job.fix_round != 0:
        raise WorkflowJobError("created job must remain in drafted state")
    expected_identity = (
        binding.job_id,
        binding.capability_id,
        binding.spec_sha256,
        binding.base_sha,
    )
    actual_identity = (
        job.job_id,
        job.capability_id,
        job.spec_sha256,
        job.base_sha,
    )
    if actual_identity != expected_identity:
        raise WorkflowJobError(
            "created job identity does not match authoritative binding"
        )
    if len(job.history) != 1:
        raise WorkflowJobError("created job must contain one drafted event")
    event = job.history[0]
    if event.actor != binding.actor or event.note != binding.note:
        raise WorkflowJobError(
            "created job attribution does not match authoritative binding"
        )


def _job_metadata(job: Optional[BuildJob]) -> Optional[dict]:
    if job is None:
        return None
    return {
        "base_sha": job.base_sha,
        "capability_id": job.capability_id,
        "fix_round": job.fix_round,
        "job_id": job.job_id,
        "schema_version": job.schema_version,
        "spec_sha256": job.spec_sha256,
        "state": job.state,
    }


@dataclass(frozen=True)
class WorkflowJobCreation:
    """Immutable result of one guarded workflow-to-job creation attempt."""

    start: RequestWorkflowStart
    binding: BuildJobBinding
    job: Optional[BuildJob]
    workflow: WorkflowPlan
    status: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    created: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.start, RequestWorkflowStart):
            raise WorkflowJobError(
                "start must be a RequestWorkflowStart"
            )
        if not isinstance(self.binding, BuildJobBinding):
            raise WorkflowJobError("binding must be a BuildJobBinding")
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowJobError("workflow must be a WorkflowPlan")
        if self.job is not None and not isinstance(self.job, BuildJob):
            raise WorkflowJobError("job must be a BuildJob or None")
        if self.status not in RESULT_STATUSES:
            raise WorkflowJobError(
                f"unsupported workflow-job status: {self.status!r}"
            )

        expected_reasons = _expected_reasons(self.start, self.binding)
        reasons = _stable_reasons(self.blocking_reasons)
        ready = _start_is_ready(self.start) and _binding_is_ready(
            self.binding
        )
        expected_status = STATUS_JOB_CREATED if ready else STATUS_NOT_CREATED
        if self.status != expected_status:
            raise WorkflowJobError(
                "result status does not match input readiness"
            )
        if reasons != expected_reasons:
            raise WorkflowJobError(
                "blocking reasons do not match input readiness"
            )

        if ready:
            if self.job is None:
                raise WorkflowJobError("ready inputs require a created job")
            expected_workflow = record_workflow_step(
                self.start.workflow,
                STEP_JOB_CREATED,
            )
            if self.workflow != expected_workflow:
                raise WorkflowJobError(
                    "created workflow must record exactly job_created"
                )
            if self.workflow.next_allowed_steps != (STEP_SCOPE_FROZEN,):
                raise WorkflowJobError(
                    "created workflow must allow only scope_frozen next"
                )
            _validate_created_job(self.job, self.binding)
        else:
            if self.job is not None:
                raise WorkflowJobError(
                    "blocked inputs cannot contain a created job"
                )
            if self.workflow != self.start.workflow:
                raise WorkflowJobError(
                    "blocked inputs cannot advance the workflow"
                )

        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "created", ready)
        object.__setattr__(
            self,
            "next_allowed_steps",
            self.workflow.next_allowed_steps,
        )

        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_JOB_SUMMARY_BYTES
        ):
            raise WorkflowJobError(
                "workflow-job summary exceeds "
                f"{MAX_WORKFLOW_JOB_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic stable fields without timestamped history."""
        return {
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "created": self.created,
            "input_status": {
                "binding": self.binding.status,
                "workflow_start": self.start.status,
            },
            "job": _job_metadata(self.job),
            "next_allowed_steps": list(self.next_allowed_steps),
            "request": self.start.request.to_dict(),
            "schema_version": self.schema_version,
            "status": self.status,
            "workflow": self.workflow.to_dict(),
        }

    def summary(self) -> str:
        """Return stable bounded JSON for offline human inspection."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"


def create_job_from_workflow_start(
    start: RequestWorkflowStart,
    binding: BuildJobBinding,
) -> WorkflowJobCreation:
    """Create one drafted job and record job_created when inputs are ready."""
    if not isinstance(start, RequestWorkflowStart):
        raise WorkflowJobError("start must be a RequestWorkflowStart")
    if not isinstance(binding, BuildJobBinding):
        raise WorkflowJobError("binding must be a BuildJobBinding")

    reasons = _expected_reasons(start, binding)
    if reasons:
        return WorkflowJobCreation(
            start=start,
            binding=binding,
            job=None,
            workflow=start.workflow,
            status=STATUS_NOT_CREATED,
            blocking_reasons=reasons,
        )

    job = new_job(
        binding.capability_id,
        binding.spec_sha256,
        binding.base_sha,
        actor=binding.actor,
        note=binding.note,
        job_id=binding.job_id,
    )
    workflow = record_workflow_step(start.workflow, STEP_JOB_CREATED)
    return WorkflowJobCreation(
        start=start,
        binding=binding,
        job=job,
        workflow=workflow,
        status=STATUS_JOB_CREATED,
        blocking_reasons=(),
    )
