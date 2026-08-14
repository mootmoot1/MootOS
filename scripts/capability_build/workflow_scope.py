"""Pure workflow-to-frozen-scope adapter for MootOS V0.4B Slice 6.

This module validates explicit approved scope data, binds the resulting
``FrozenScope`` to an already-created ``BuildJob``, and records only the
``scope_frozen`` workflow step. It performs no filesystem, workspace,
execution, network, Git, registry, installation, deployment, or runtime
operation.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.capability_build.job import BuildJob
from scripts.capability_build.scope import FrozenScope, ScopeError
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    WorkflowPlan,
    record_workflow_step,
)
from scripts.capability_build.workflow_job import (
    STATUS_JOB_CREATED,
    WorkflowJobCreation,
)


class WorkflowScopeError(ValueError):
    """Raised when workflow-to-scope state cannot be represented safely."""


SCHEMA_VERSION = 1
STATUS_SCOPE_FROZEN = "scope_frozen"
STATUS_NOT_FROZEN = "not_frozen"
RESULT_STATUSES = (
    STATUS_SCOPE_FROZEN,
    STATUS_NOT_FROZEN,
)
MAX_WORKFLOW_SCOPE_SUMMARY_BYTES = 32 * 1024

_INVALID_SCOPE_REASON = "Approved scope input is invalid."


def _stable_reasons(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowScopeError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowScopeError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowScopeError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _creation_is_ready(creation: WorkflowJobCreation) -> bool:
    return (
        creation.status == STATUS_JOB_CREATED
        and creation.created
        and isinstance(creation.job, BuildJob)
        and creation.workflow.completed_steps
        == (STEP_REQUEST_RECEIVED, STEP_JOB_CREATED)
        and creation.workflow.next_allowed_steps == (STEP_SCOPE_FROZEN,)
    )


def _expected_reasons(
    creation: WorkflowJobCreation,
    scope: Optional[FrozenScope],
) -> tuple:
    if not _creation_is_ready(creation):
        return _stable_reasons(creation.blocking_reasons)
    if scope is None:
        return (_INVALID_SCOPE_REASON,)
    return ()


def _job_metadata(job: Optional[BuildJob]) -> Optional[dict]:
    if job is None:
        return None
    return {
        "base_sha": job.base_sha,
        "capability_id": job.capability_id,
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


@dataclass(frozen=True)
class WorkflowScopeFreeze:
    """Immutable result of one guarded approved-scope freeze attempt."""

    creation: WorkflowJobCreation
    scope: Optional[FrozenScope]
    workflow: WorkflowPlan
    status: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    frozen: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    job_id: Optional[str] = field(init=False)
    capability_id: Optional[str] = field(init=False)
    spec_sha256: Optional[str] = field(init=False)
    base_sha: Optional[str] = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.creation, WorkflowJobCreation):
            raise WorkflowScopeError(
                "creation must be a WorkflowJobCreation"
            )
        if self.scope is not None and not isinstance(
            self.scope, FrozenScope
        ):
            raise WorkflowScopeError("scope must be a FrozenScope or None")
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowScopeError("workflow must be a WorkflowPlan")
        if self.status not in RESULT_STATUSES:
            raise WorkflowScopeError(
                f"unsupported workflow-scope status: {self.status!r}"
            )

        creation_ready = _creation_is_ready(self.creation)
        frozen = creation_ready and self.scope is not None
        expected_status = (
            STATUS_SCOPE_FROZEN if frozen else STATUS_NOT_FROZEN
        )
        if self.status != expected_status:
            raise WorkflowScopeError(
                "result status does not match input readiness"
            )

        expected_reasons = _expected_reasons(self.creation, self.scope)
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != expected_reasons:
            raise WorkflowScopeError(
                "blocking reasons do not match input readiness"
            )

        if frozen:
            expected_workflow = record_workflow_step(
                self.creation.workflow,
                STEP_SCOPE_FROZEN,
            )
            if self.workflow != expected_workflow:
                raise WorkflowScopeError(
                    "frozen workflow must record exactly scope_frozen"
                )
            if self.workflow.next_allowed_steps != (STEP_BRIEF_READY,):
                raise WorkflowScopeError(
                    "frozen workflow must allow only brief_ready next"
                )
        else:
            if self.scope is not None:
                raise WorkflowScopeError(
                    "incomplete job creation cannot contain frozen scope"
                )
            if self.workflow != self.creation.workflow:
                raise WorkflowScopeError(
                    "blocked scope input cannot advance the workflow"
                )

        job = self.creation.job
        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "frozen", frozen)
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

        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_SCOPE_SUMMARY_BYTES
        ):
            raise WorkflowScopeError(
                "workflow-scope summary exceeds "
                f"{MAX_WORKFLOW_SCOPE_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic scope and job identity without raw prose."""
        return {
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "frozen": self.frozen,
            "input_status": {
                "workflow_job": self.creation.status,
            },
            "job": _job_metadata(self.creation.job),
            "next_allowed_steps": list(self.next_allowed_steps),
            "schema_version": self.schema_version,
            "scope": _scope_metadata(self.scope),
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


def _validated_scope(scope_input: Any) -> FrozenScope:
    if isinstance(scope_input, FrozenScope):
        return FrozenScope.from_dict(scope_input.to_dict())
    return FrozenScope.from_dict(scope_input)


def freeze_scope_from_workflow_job(
    creation: WorkflowJobCreation,
    scope_input: Any,
) -> WorkflowScopeFreeze:
    """Freeze explicit approved scope and record scope_frozen if ready."""
    if not isinstance(creation, WorkflowJobCreation):
        raise WorkflowScopeError(
            "creation must be a WorkflowJobCreation"
        )

    if not _creation_is_ready(creation):
        return WorkflowScopeFreeze(
            creation=creation,
            scope=None,
            workflow=creation.workflow,
            status=STATUS_NOT_FROZEN,
            blocking_reasons=creation.blocking_reasons,
        )

    try:
        scope = _validated_scope(scope_input)
    except (ScopeError, TypeError, ValueError):
        return WorkflowScopeFreeze(
            creation=creation,
            scope=None,
            workflow=creation.workflow,
            status=STATUS_NOT_FROZEN,
            blocking_reasons=(_INVALID_SCOPE_REASON,),
        )

    workflow = record_workflow_step(
        creation.workflow,
        STEP_SCOPE_FROZEN,
    )
    return WorkflowScopeFreeze(
        creation=creation,
        scope=scope,
        workflow=workflow,
        status=STATUS_SCOPE_FROZEN,
        blocking_reasons=(),
    )
