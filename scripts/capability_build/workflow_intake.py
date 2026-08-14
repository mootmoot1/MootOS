"""Pure worker-return intake adapter for MootOS V0.4B Slice 8.

This module validates explicit inert returned-file models against the
authoritative frozen scope, then records only ``worker_returned`` and
``intake_checked``. It does not read or write files, execute returned code,
attach evidence, use Git or networks, register capabilities, deploy, or
exercise backend, runtime, or autonomous authority.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.capability_build.intake import (
    IntakeError,
    IntakeResult,
    WorkerSummary,
    validate_returned_files,
)
from scripts.capability_build.job import BuildJob
from scripts.capability_build.scope import FrozenScope
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_EVIDENCE_ATTACHED,
    STEP_INTAKE_CHECKED,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    STEP_WORKER_RETURNED,
    WorkflowPlan,
    record_workflow_step,
)
from scripts.capability_build.workflow_brief import (
    STATUS_BRIEF_READY,
    WorkflowBriefReady,
)


class WorkflowIntakeError(ValueError):
    """Raised when workflow-intake state cannot be represented safely."""


SCHEMA_VERSION = 1
STATUS_INTAKE_CHECKED = "intake_checked"
STATUS_NOT_CHECKED = "not_checked"
RESULT_STATUSES = (
    STATUS_INTAKE_CHECKED,
    STATUS_NOT_CHECKED,
)
MAX_WORKFLOW_INTAKE_SUMMARY_BYTES = 128 * 1024

_INVALID_RETURN_REASON = "Returned worker input is missing or invalid."


def _stable_reasons(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowIntakeError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowIntakeError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowIntakeError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _brief_is_ready(brief_ready: WorkflowBriefReady) -> bool:
    return (
        brief_ready.status == STATUS_BRIEF_READY
        and brief_ready.ready
        and isinstance(brief_ready.brief, str)
        and isinstance(brief_ready.scope_freeze.scope, FrozenScope)
        and isinstance(brief_ready.scope_freeze.creation.job, BuildJob)
        and brief_ready.workflow.completed_steps
        == (
            STEP_REQUEST_RECEIVED,
            STEP_JOB_CREATED,
            STEP_SCOPE_FROZEN,
            STEP_BRIEF_READY,
        )
        and brief_ready.workflow.next_allowed_steps
        == (STEP_WORKER_RETURNED,)
    )


def _expected_reasons(
    brief_ready: WorkflowBriefReady,
    intake: Optional[IntakeResult],
) -> tuple:
    if not _brief_is_ready(brief_ready):
        return _stable_reasons(brief_ready.blocking_reasons)
    if intake is None:
        return (_INVALID_RETURN_REASON,)
    return _stable_reasons(intake.blocking_findings)


def _job_metadata(job: Optional[BuildJob]) -> Optional[dict]:
    if job is None:
        return None
    return {
        "base_sha": job.base_sha,
        "capability_id": job.capability_id,
        "fix_round": job.fix_round,
        "job_id": job.job_id,
        "spec_sha256": job.spec_sha256,
    }


def _scope_metadata(scope: Optional[FrozenScope]) -> Optional[dict]:
    if scope is None:
        return None
    return {
        "allowed_existing_files": list(scope.allowed_existing_files),
        "allowed_new_files": list(scope.allowed_new_files),
        "forbidden_paths": list(scope.forbidden_paths),
        "justified_paths": list(scope.justifications),
        "protected_files": list(scope.protected_files),
    }


def _intake_metadata(intake: Optional[IntakeResult]) -> Optional[dict]:
    if intake is None:
        return None
    return {
        "accepted": intake.accepted,
        "blocking_findings": list(intake.blocking_findings),
        "file_decisions": [
            {
                "accepted": decision.accepted,
                "blocking_findings": list(decision.blocking_findings),
                "operation": decision.operation,
                "path": decision.path,
                "scope_category": decision.scope_category,
            }
            for decision in intake.file_decisions
        ],
        "touched_files": list(intake.touched_files),
        "warnings": list(intake.warnings),
    }


@dataclass(frozen=True)
class WorkflowIntakeCheck:
    """Immutable result of one guarded returned-worker intake attempt."""

    brief_ready: WorkflowBriefReady
    intake: Optional[IntakeResult]
    workflow: WorkflowPlan
    status: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    worker_returned: bool = field(init=False)
    checked: bool = field(init=False)
    accepted: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    job_id: Optional[str] = field(init=False)
    capability_id: Optional[str] = field(init=False)
    spec_sha256: Optional[str] = field(init=False)
    base_sha: Optional[str] = field(init=False)
    scope: Optional[FrozenScope] = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.brief_ready, WorkflowBriefReady):
            raise WorkflowIntakeError(
                "brief_ready must be a WorkflowBriefReady"
            )
        if self.intake is not None and not isinstance(
            self.intake, IntakeResult
        ):
            raise WorkflowIntakeError(
                "intake must be an IntakeResult or None"
            )
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowIntakeError("workflow must be a WorkflowPlan")
        if self.status not in RESULT_STATUSES:
            raise WorkflowIntakeError(
                f"unsupported workflow-intake status: {self.status!r}"
            )

        brief_ready = _brief_is_ready(self.brief_ready)
        checked = brief_ready and self.intake is not None
        expected_status = (
            STATUS_INTAKE_CHECKED if checked else STATUS_NOT_CHECKED
        )
        if self.status != expected_status:
            raise WorkflowIntakeError(
                "result status does not match input readiness"
            )

        expected_reasons = _expected_reasons(
            self.brief_ready,
            self.intake,
        )
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != expected_reasons:
            raise WorkflowIntakeError(
                "blocking reasons do not match intake result"
            )

        if checked:
            returned_workflow = record_workflow_step(
                self.brief_ready.workflow,
                STEP_WORKER_RETURNED,
            )
            expected_workflow = record_workflow_step(
                returned_workflow,
                STEP_INTAKE_CHECKED,
            )
            if self.workflow != expected_workflow:
                raise WorkflowIntakeError(
                    "checked workflow must record worker_returned then "
                    "intake_checked"
                )
            if self.workflow.next_allowed_steps != (
                STEP_EVIDENCE_ATTACHED,
            ):
                raise WorkflowIntakeError(
                    "checked workflow must allow only evidence_attached next"
                )
        else:
            if self.intake is not None:
                raise WorkflowIntakeError(
                    "unready brief cannot contain an intake result"
                )
            if self.workflow != self.brief_ready.workflow:
                raise WorkflowIntakeError(
                    "invalid returned input cannot advance the workflow"
                )

        job = self.brief_ready.scope_freeze.creation.job
        scope = self.brief_ready.scope_freeze.scope
        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "worker_returned", checked)
        object.__setattr__(self, "checked", checked)
        object.__setattr__(
            self,
            "accepted",
            bool(self.intake and self.intake.accepted),
        )
        object.__setattr__(
            self,
            "next_allowed_steps",
            self.workflow.next_allowed_steps,
        )
        object.__setattr__(self, "job_id", job.job_id if job else None)
        object.__setattr__(
            self,
            "capability_id",
            job.capability_id if job else None,
        )
        object.__setattr__(
            self,
            "spec_sha256",
            job.spec_sha256 if job else None,
        )
        object.__setattr__(
            self,
            "base_sha",
            job.base_sha if job else None,
        )
        object.__setattr__(self, "scope", scope)

        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_INTAKE_SUMMARY_BYTES
        ):
            raise WorkflowIntakeError(
                "workflow-intake summary exceeds "
                f"{MAX_WORKFLOW_INTAKE_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic intake metadata without returned content."""
        return {
            "accepted": self.accepted,
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "checked": self.checked,
            "input_status": {
                "workflow_brief": self.brief_ready.status,
            },
            "intake": _intake_metadata(self.intake),
            "job": _job_metadata(
                self.brief_ready.scope_freeze.creation.job
            ),
            "next_allowed_steps": list(self.next_allowed_steps),
            "schema_version": self.schema_version,
            "scope": _scope_metadata(self.scope),
            "status": self.status,
            "worker_returned": self.worker_returned,
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


def _returned_items(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise IntakeError("returned_files must be a sequence")
    try:
        items = tuple(values)
    except TypeError as error:
        raise IntakeError("returned_files must be a sequence") from error
    if not items:
        raise IntakeError("returned_files cannot be empty")
    return items


def check_returned_worker_from_workflow_brief(
    brief_ready: WorkflowBriefReady,
    returned_files: Any,
    worker_summary: Optional[WorkerSummary] = None,
) -> WorkflowIntakeCheck:
    """Validate explicit returned files and record the two intake steps."""
    if not isinstance(brief_ready, WorkflowBriefReady):
        raise WorkflowIntakeError(
            "brief_ready must be a WorkflowBriefReady"
        )

    if not _brief_is_ready(brief_ready):
        return WorkflowIntakeCheck(
            brief_ready=brief_ready,
            intake=None,
            workflow=brief_ready.workflow,
            status=STATUS_NOT_CHECKED,
            blocking_reasons=brief_ready.blocking_reasons,
        )

    try:
        items = _returned_items(returned_files)
        intake = validate_returned_files(
            brief_ready.scope_freeze.scope,
            items,
            worker_summary=worker_summary,
        )
    except (IntakeError, TypeError, ValueError):
        return WorkflowIntakeCheck(
            brief_ready=brief_ready,
            intake=None,
            workflow=brief_ready.workflow,
            status=STATUS_NOT_CHECKED,
            blocking_reasons=(_INVALID_RETURN_REASON,),
        )

    returned_workflow = record_workflow_step(
        brief_ready.workflow,
        STEP_WORKER_RETURNED,
    )
    workflow = record_workflow_step(
        returned_workflow,
        STEP_INTAKE_CHECKED,
    )
    return WorkflowIntakeCheck(
        brief_ready=brief_ready,
        intake=intake,
        workflow=workflow,
        status=STATUS_INTAKE_CHECKED,
        blocking_reasons=intake.blocking_findings,
    )
