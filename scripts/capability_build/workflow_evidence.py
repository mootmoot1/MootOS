"""Pure intake-to-evidence attachment adapter for V0.4B Slice 9.

This module builds an inert verification plan from accepted intake,
evaluates explicit already-collected evidence records, and records only the
``evidence_attached`` workflow step. It never runs commands or tests, reads
logs or files, uses Git or networks, creates later artifacts, deploys, or
exercises backend, runtime, or autonomous authority.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.capability_build.evidence import (
    EvidenceBundle,
    VerificationError,
    build_default_verification_plan,
    evaluate_evidence,
)
from scripts.capability_build.intake import IntakeResult
from scripts.capability_build.job import BuildJob
from scripts.capability_build.scope import FrozenScope
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_BUNDLE_CREATED,
    STEP_EVIDENCE_ATTACHED,
    STEP_INTAKE_CHECKED,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    STEP_WORKER_RETURNED,
    WorkflowPlan,
    record_workflow_step,
)
from scripts.capability_build.workflow_intake import (
    STATUS_INTAKE_CHECKED,
    WorkflowIntakeCheck,
)


class WorkflowEvidenceError(ValueError):
    """Raised when workflow-evidence state cannot be represented safely."""


SCHEMA_VERSION = 1
STATUS_EVIDENCE_ATTACHED = "evidence_attached"
STATUS_NOT_ATTACHED = "not_attached"
RESULT_STATUSES = (
    STATUS_EVIDENCE_ATTACHED,
    STATUS_NOT_ATTACHED,
)
MAX_WORKFLOW_EVIDENCE_SUMMARY_BYTES = 128 * 1024

_INVALID_EVIDENCE_REASON = "Explicit evidence input is invalid."
_INTAKE_NOT_ACCEPTED_REASON = "Evidence requires accepted intake."


def _stable_reasons(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowEvidenceError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowEvidenceError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowEvidenceError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _intake_is_checked(intake_check: WorkflowIntakeCheck) -> bool:
    return (
        intake_check.status == STATUS_INTAKE_CHECKED
        and intake_check.checked
        and isinstance(intake_check.intake, IntakeResult)
        and isinstance(
            intake_check.brief_ready.scope_freeze.creation.job,
            BuildJob,
        )
        and isinstance(intake_check.scope, FrozenScope)
        and intake_check.workflow.completed_steps
        == (
            STEP_REQUEST_RECEIVED,
            STEP_JOB_CREATED,
            STEP_SCOPE_FROZEN,
            STEP_BRIEF_READY,
            STEP_WORKER_RETURNED,
            STEP_INTAKE_CHECKED,
        )
        and intake_check.workflow.next_allowed_steps
        == (STEP_EVIDENCE_ATTACHED,)
    )


def _intake_allows_evidence(intake_check: WorkflowIntakeCheck) -> bool:
    return (
        _intake_is_checked(intake_check)
        and intake_check.accepted
        and intake_check.intake.accepted
        and not intake_check.intake.blocking_findings
    )


def _evidence_reasons(evidence: EvidenceBundle) -> tuple:
    if evidence.accepted:
        return ()
    return (f"Verification evidence is {evidence.status}.",)


def _expected_reasons(
    intake_check: WorkflowIntakeCheck,
    evidence: Optional[EvidenceBundle],
) -> tuple:
    if not _intake_is_checked(intake_check):
        return _stable_reasons(intake_check.blocking_reasons)
    if not _intake_allows_evidence(intake_check):
        reasons = intake_check.blocking_reasons or (
            _INTAKE_NOT_ACCEPTED_REASON,
        )
        return _stable_reasons(reasons)
    if evidence is None:
        return (_INVALID_EVIDENCE_REASON,)
    return _evidence_reasons(evidence)


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
        "touched_files": list(intake.touched_files),
        "warnings": list(intake.warnings),
    }


def _evidence_metadata(
    evidence: Optional[EvidenceBundle],
) -> Optional[dict]:
    if evidence is None:
        return None
    return {
        "accepted": evidence.accepted,
        "commands": [
            {
                "kind": command.kind,
                "name": command.name,
            }
            for command in evidence.plan.commands
        ],
        "missing_commands": list(evidence.missing_commands),
        "records": [
            {
                "command_name": record.command_name,
                "exit_code": record.exit_code,
                "status": record.status,
            }
            for record in evidence.records
        ],
        "status": evidence.status,
        "touched_files": list(evidence.plan.touched_files),
    }


def _validate_evidence_binding(
    evidence: EvidenceBundle,
    intake: IntakeResult,
) -> None:
    if evidence.plan.intake_accepted is not True:
        raise WorkflowEvidenceError(
            "evidence plan must be bound to accepted intake"
        )
    if evidence.plan.blocking_findings:
        raise WorkflowEvidenceError(
            "evidence plan cannot contain intake blocking findings"
        )
    if evidence.plan.touched_files != intake.touched_files:
        raise WorkflowEvidenceError(
            "evidence plan touched files do not match authoritative intake"
        )


@dataclass(frozen=True)
class WorkflowEvidenceAttachment:
    """Immutable result of one guarded explicit-evidence attachment."""

    intake_check: WorkflowIntakeCheck
    evidence: Optional[EvidenceBundle]
    workflow: WorkflowPlan
    status: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    attached: bool = field(init=False)
    accepted: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    job_id: Optional[str] = field(init=False)
    capability_id: Optional[str] = field(init=False)
    spec_sha256: Optional[str] = field(init=False)
    base_sha: Optional[str] = field(init=False)
    scope: Optional[FrozenScope] = field(init=False)
    intake: Optional[IntakeResult] = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.intake_check, WorkflowIntakeCheck):
            raise WorkflowEvidenceError(
                "intake_check must be a WorkflowIntakeCheck"
            )
        if self.evidence is not None and not isinstance(
            self.evidence, EvidenceBundle
        ):
            raise WorkflowEvidenceError(
                "evidence must be an EvidenceBundle or None"
            )
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowEvidenceError("workflow must be a WorkflowPlan")
        if self.status not in RESULT_STATUSES:
            raise WorkflowEvidenceError(
                f"unsupported workflow-evidence status: {self.status!r}"
            )

        eligible = _intake_allows_evidence(self.intake_check)
        attached = eligible and self.evidence is not None
        expected_status = (
            STATUS_EVIDENCE_ATTACHED if attached else STATUS_NOT_ATTACHED
        )
        if self.status != expected_status:
            raise WorkflowEvidenceError(
                "result status does not match input readiness"
            )

        expected_reasons = _expected_reasons(
            self.intake_check,
            self.evidence,
        )
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != expected_reasons:
            raise WorkflowEvidenceError(
                "blocking reasons do not match evidence result"
            )

        if attached:
            _validate_evidence_binding(
                self.evidence,
                self.intake_check.intake,
            )
            expected_workflow = record_workflow_step(
                self.intake_check.workflow,
                STEP_EVIDENCE_ATTACHED,
            )
            if self.workflow != expected_workflow:
                raise WorkflowEvidenceError(
                    "attached workflow must record exactly evidence_attached"
                )
            if self.workflow.next_allowed_steps != (STEP_BUNDLE_CREATED,):
                raise WorkflowEvidenceError(
                    "attached workflow must allow only bundle_created next"
                )
        else:
            if self.evidence is not None:
                raise WorkflowEvidenceError(
                    "ineligible intake cannot contain attached evidence"
                )
            if self.workflow != self.intake_check.workflow:
                raise WorkflowEvidenceError(
                    "invalid evidence input cannot advance the workflow"
                )

        job = self.intake_check.brief_ready.scope_freeze.creation.job
        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "attached", attached)
        object.__setattr__(
            self,
            "accepted",
            bool(self.evidence and self.evidence.accepted),
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
        object.__setattr__(self, "scope", self.intake_check.scope)
        object.__setattr__(self, "intake", self.intake_check.intake)

        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_EVIDENCE_SUMMARY_BYTES
        ):
            raise WorkflowEvidenceError(
                "workflow-evidence summary exceeds "
                f"{MAX_WORKFLOW_EVIDENCE_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic evidence metadata without logs or prose."""
        job = self.intake_check.brief_ready.scope_freeze.creation.job
        return {
            "accepted": self.accepted,
            "attached": self.attached,
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "evidence": _evidence_metadata(self.evidence),
            "input_status": {
                "workflow_intake": self.intake_check.status,
            },
            "intake": _intake_metadata(self.intake),
            "job": _job_metadata(job),
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


def attach_evidence_from_workflow_intake(
    intake_check: WorkflowIntakeCheck,
    evidence_records: Any,
) -> WorkflowEvidenceAttachment:
    """Attach explicit evidence records without executing their plan."""
    if not isinstance(intake_check, WorkflowIntakeCheck):
        raise WorkflowEvidenceError(
            "intake_check must be a WorkflowIntakeCheck"
        )

    if not _intake_allows_evidence(intake_check):
        reasons = _expected_reasons(intake_check, None)
        return WorkflowEvidenceAttachment(
            intake_check=intake_check,
            evidence=None,
            workflow=intake_check.workflow,
            status=STATUS_NOT_ATTACHED,
            blocking_reasons=reasons,
        )

    try:
        plan = build_default_verification_plan(intake_check.intake)
        evidence = evaluate_evidence(plan, evidence_records)
    except (VerificationError, TypeError, ValueError):
        return WorkflowEvidenceAttachment(
            intake_check=intake_check,
            evidence=None,
            workflow=intake_check.workflow,
            status=STATUS_NOT_ATTACHED,
            blocking_reasons=(_INVALID_EVIDENCE_REASON,),
        )

    workflow = record_workflow_step(
        intake_check.workflow,
        STEP_EVIDENCE_ATTACHED,
    )
    return WorkflowEvidenceAttachment(
        intake_check=intake_check,
        evidence=evidence,
        workflow=workflow,
        status=STATUS_EVIDENCE_ATTACHED,
        blocking_reasons=_evidence_reasons(evidence),
    )
