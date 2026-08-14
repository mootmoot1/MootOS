"""Pure frozen-scope-to-worker-brief adapter for V0.4B Slice 7.

This module renders one in-memory worker brief from explicit approved data
and records only the ``brief_ready`` workflow step. It does not dispatch a
worker, create workspace directories, access files or networks, invoke Git,
execute code, register or install capabilities, deploy, or exercise runtime
or autonomous authority.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.capability_build.brief import BriefError, render_worker_brief
from scripts.capability_build.job import BuildJob
from scripts.capability_build.scope import FrozenScope
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    STEP_WORKER_RETURNED,
    WorkflowPlan,
    record_workflow_step,
)
from scripts.capability_build.workflow_scope import (
    STATUS_SCOPE_FROZEN,
    WorkflowScopeFreeze,
)


class WorkflowBriefError(ValueError):
    """Raised when workflow-to-brief state cannot be represented safely."""


SCHEMA_VERSION = 1
STATUS_BRIEF_READY = "brief_ready"
STATUS_NOT_READY = "not_ready"
RESULT_STATUSES = (
    STATUS_BRIEF_READY,
    STATUS_NOT_READY,
)
MAX_WORKFLOW_BRIEF_SUMMARY_BYTES = 32 * 1024

_INVALID_BRIEF_REASON = "Approved worker brief input is invalid."


def _stable_reasons(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowBriefError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowBriefError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowBriefError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _scope_is_ready(scope_freeze: WorkflowScopeFreeze) -> bool:
    return (
        scope_freeze.status == STATUS_SCOPE_FROZEN
        and scope_freeze.frozen
        and isinstance(scope_freeze.scope, FrozenScope)
        and isinstance(scope_freeze.creation.job, BuildJob)
        and scope_freeze.workflow.completed_steps
        == (
            STEP_REQUEST_RECEIVED,
            STEP_JOB_CREATED,
            STEP_SCOPE_FROZEN,
        )
        and scope_freeze.workflow.next_allowed_steps
        == (STEP_BRIEF_READY,)
    )


def _expected_reasons(
    scope_freeze: WorkflowScopeFreeze,
    brief: Optional[str],
) -> tuple:
    if not _scope_is_ready(scope_freeze):
        return _stable_reasons(scope_freeze.blocking_reasons)
    if brief is None:
        return (_INVALID_BRIEF_REASON,)
    return ()


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


def _validate_brief_binding(
    brief: str,
    job: BuildJob,
    scope: FrozenScope,
) -> None:
    required_fragments = (
        "# MootOS Capability Build Worker Brief",
        f"- Job ID: `{job.job_id}`",
        f"- Capability ID: `{job.capability_id}`",
        f"- Base SHA: `{job.base_sha}`",
        f"- Spec SHA-256: `{job.spec_sha256}`",
        f"- Fix round: `{job.fix_round}`",
    ) + scope.allowed_new_files + scope.allowed_existing_files
    if any(fragment not in brief for fragment in required_fragments):
        raise WorkflowBriefError(
            "worker brief does not match authoritative job and scope"
        )


@dataclass(frozen=True)
class WorkflowBriefReady:
    """Immutable result of one guarded worker-brief render attempt."""

    scope_freeze: WorkflowScopeFreeze
    brief: Optional[str]
    workflow: WorkflowPlan
    status: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    ready: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    job_id: Optional[str] = field(init=False)
    capability_id: Optional[str] = field(init=False)
    spec_sha256: Optional[str] = field(init=False)
    base_sha: Optional[str] = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.scope_freeze, WorkflowScopeFreeze):
            raise WorkflowBriefError(
                "scope_freeze must be a WorkflowScopeFreeze"
            )
        if self.brief is not None and not isinstance(self.brief, str):
            raise WorkflowBriefError("brief must be text or None")
        if self.brief == "":
            raise WorkflowBriefError("brief cannot be blank")
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowBriefError("workflow must be a WorkflowPlan")
        if self.status not in RESULT_STATUSES:
            raise WorkflowBriefError(
                f"unsupported workflow-brief status: {self.status!r}"
            )

        scope_ready = _scope_is_ready(self.scope_freeze)
        ready = scope_ready and self.brief is not None
        expected_status = STATUS_BRIEF_READY if ready else STATUS_NOT_READY
        if self.status != expected_status:
            raise WorkflowBriefError(
                "result status does not match input readiness"
            )

        expected_reasons = _expected_reasons(
            self.scope_freeze,
            self.brief,
        )
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != expected_reasons:
            raise WorkflowBriefError(
                "blocking reasons do not match input readiness"
            )

        if ready:
            expected_workflow = record_workflow_step(
                self.scope_freeze.workflow,
                STEP_BRIEF_READY,
            )
            if self.workflow != expected_workflow:
                raise WorkflowBriefError(
                    "ready workflow must record exactly brief_ready"
                )
            if self.workflow.next_allowed_steps != (STEP_WORKER_RETURNED,):
                raise WorkflowBriefError(
                    "ready workflow must allow only worker_returned next"
                )
            _validate_brief_binding(
                self.brief,
                self.scope_freeze.creation.job,
                self.scope_freeze.scope,
            )
        else:
            if self.brief is not None:
                raise WorkflowBriefError(
                    "unfrozen scope cannot contain a worker brief"
                )
            if self.workflow != self.scope_freeze.workflow:
                raise WorkflowBriefError(
                    "blocked brief input cannot advance the workflow"
                )

        job = self.scope_freeze.creation.job
        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "ready", ready)
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
            MAX_WORKFLOW_BRIEF_SUMMARY_BYTES
        ):
            raise WorkflowBriefError(
                "workflow-brief summary exceeds "
                f"{MAX_WORKFLOW_BRIEF_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic metadata without worker-brief prose."""
        return {
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "brief": (
                None
                if self.brief is None
                else {
                    "bytes": len(self.brief.encode("utf-8")),
                    "format": "markdown",
                    "prose_included": False,
                }
            ),
            "input_status": {
                "workflow_scope": self.scope_freeze.status,
            },
            "job": _job_metadata(self.scope_freeze.creation.job),
            "next_allowed_steps": list(self.next_allowed_steps),
            "ready": self.ready,
            "schema_version": self.schema_version,
            "scope": _scope_metadata(self.scope_freeze.scope),
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


def render_brief_from_workflow_scope(
    scope_freeze: WorkflowScopeFreeze,
    goal: Any,
    constraints: Any = (),
) -> WorkflowBriefReady:
    """Render an approved brief and record brief_ready when scope is ready."""
    if not isinstance(scope_freeze, WorkflowScopeFreeze):
        raise WorkflowBriefError(
            "scope_freeze must be a WorkflowScopeFreeze"
        )

    if not _scope_is_ready(scope_freeze):
        return WorkflowBriefReady(
            scope_freeze=scope_freeze,
            brief=None,
            workflow=scope_freeze.workflow,
            status=STATUS_NOT_READY,
            blocking_reasons=scope_freeze.blocking_reasons,
        )

    try:
        brief = render_worker_brief(
            scope_freeze.creation.job,
            scope_freeze.scope,
            goal,
            constraints,
        )
    except (BriefError, TypeError, ValueError):
        return WorkflowBriefReady(
            scope_freeze=scope_freeze,
            brief=None,
            workflow=scope_freeze.workflow,
            status=STATUS_NOT_READY,
            blocking_reasons=(_INVALID_BRIEF_REASON,),
        )

    workflow = record_workflow_step(
        scope_freeze.workflow,
        STEP_BRIEF_READY,
    )
    return WorkflowBriefReady(
        scope_freeze=scope_freeze,
        brief=brief,
        workflow=workflow,
        status=STATUS_BRIEF_READY,
        blocking_reasons=(),
    )
