"""Pure handoff-to-PR-package adapter for MootOS V0.4C Slice 2.

This module prepares bounded, offline PR package proposal metadata from an
existing V0.4B human handoff result. It does not create branches, commits,
pull requests, approvals, registry changes, installations, deployments, files,
processes, network calls, or runtime actions.
"""

from dataclasses import dataclass, field
from typing import Optional

from scripts.capability_build.pr_package import (
    BLOCKED,
    READY,
    EVIDENCE_INCOMPLETE,
    PRChecklistItem,
    PREvidenceSummary,
    PRFileSummary,
    PRPackageError,
    PRPackageProposal,
    PRRiskSummary,
    PRRollbackNote,
)
from scripts.capability_build.workflow import (
    STEP_HANDOFF_CREATED,
    STEP_HUMAN_DECISION_PENDING,
    WorkflowPlan,
)
from scripts.capability_build.workflow_handoff import (
    STATUS_HANDOFF_CREATED,
    WorkflowHandoffCreation,
)


class WorkflowPRPackageError(ValueError):
    """Raised when PR package creation state is unsafe or inconsistent."""


SCHEMA_VERSION = 1
STATUS_PR_PACKAGE_CREATED = "pr_package_created"
STATUS_NOT_CREATED = "not_created"
RESULT_STATUSES = (
    STATUS_PR_PACKAGE_CREATED,
    STATUS_NOT_CREATED,
)
MAX_WORKFLOW_PR_PACKAGE_SUMMARY_BYTES = 256 * 1024

_INVALID_HANDOFF_REASON = "Human handoff is not ready for PR packaging."


def _stable_reasons(values: object) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowPRPackageError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowPRPackageError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowPRPackageError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _slug(value: str, *, maximum: int = 64) -> str:
    characters = []
    previous_dash = False
    for character in value.strip().casefold():
        allowed = character.isalnum() or character in "._-"
        replacement = character if allowed else "-"
        if replacement == "-" and previous_dash:
            continue
        characters.append(replacement)
        previous_dash = replacement == "-"
    slug = "".join(characters).strip(".-/")
    return (slug or "package")[:maximum].rstrip(".-/") or "package"


def _handoff_is_created(handoff_creation: WorkflowHandoffCreation) -> bool:
    return (
        handoff_creation.status == STATUS_HANDOFF_CREATED
        and handoff_creation.created
        and handoff_creation.handoff is not None
        and handoff_creation.workflow.current_step == STEP_HANDOFF_CREATED
        and handoff_creation.workflow.next_allowed_steps
        == (STEP_HUMAN_DECISION_PENDING,)
        and handoff_creation.next_allowed_steps
        == (STEP_HUMAN_DECISION_PENDING,)
    )


def _changed_files(handoff_creation: WorkflowHandoffCreation) -> tuple:
    bundle = handoff_creation.bundle_creation.bundle
    handoff = handoff_creation.handoff
    created_paths = set(bundle.frozen_scope.allowed_new_files)
    existing_paths = set(bundle.frozen_scope.allowed_existing_files)
    files = []
    for path in handoff.touched_files:
        if path in created_paths:
            operation = "create"
            summary = "Create scoped file accepted by the human handoff."
        elif path in existing_paths:
            operation = "modify"
            summary = "Modify scoped file accepted by the human handoff."
        else:
            operation = "modify"
            summary = "Touch scoped file accepted by the human handoff."
        files.append(PRFileSummary(path, operation, summary))
    return tuple(files)


def _evidence(handoff_creation: WorkflowHandoffCreation) -> tuple:
    bundle = handoff_creation.bundle_creation.bundle
    if bundle.evidence is None or not bundle.evidence.records:
        return (
            PREvidenceSummary(
                check_name="verification",
                status=EVIDENCE_INCOMPLETE,
            ),
        )
    return tuple(
        PREvidenceSummary(
            check_name=record.command_name,
            status=record.status,
        )
        for record in bundle.evidence.records
    )


def _risks() -> tuple:
    return (
        PRRiskSummary(
            risk_id="authority",
            level="low",
            summary=(
                "The package is proposal-only metadata with no GitHub or "
                "runtime action."
            ),
            mitigation=(
                "Require a later explicit human decision before any external "
                "action."
            ),
        ),
        PRRiskSummary(
            risk_id="scope",
            level="low",
            summary="The package is derived only from the frozen handoff.",
            mitigation="Review touched files against the frozen scope.",
        ),
    )


def _rollback_notes() -> tuple:
    return (
        PRRollbackNote(
            1,
            "Discard the offline PR package proposal.",
        ),
        PRRollbackNote(
            2,
            "Return to the existing human handoff state.",
        ),
    )


def _checklist(handoff_creation: WorkflowHandoffCreation) -> tuple:
    return tuple(
        PRChecklistItem(
            item_id=f"handoff_check_{index:03d}",
            description=item,
        )
        for index, item in enumerate(
            handoff_creation.handoff.checklist,
            start=1,
        )
    )


def _pr_body(handoff_creation: WorkflowHandoffCreation) -> str:
    handoff = handoff_creation.handoff
    bundle = handoff_creation.bundle_creation.bundle
    touched = "\n".join(f"- {path}" for path in handoff.touched_files)
    checks = "\n".join(
        f"- {record.command_name}: {record.status}"
        for record in bundle.evidence.records
    ) if bundle.evidence is not None else "- verification: incomplete"
    blockers = (
        "None"
        if handoff.approvable
        else "\n".join(f"- {reason}" for reason in handoff.blocking_reasons)
    )
    return (
        "## Summary\n\n"
        "Prepare an offline PR package proposal from the V0.4B human "
        "handoff state.\n\n"
        "## Source\n\n"
        f"- Job: {handoff.job.job_id}\n"
        f"- Capability: {handoff.job.capability_id}\n"
        f"- Base SHA: {handoff.job.base_sha}\n"
        f"- Handoff approvable: {handoff.approvable}\n\n"
        "## Touched Files\n\n"
        f"{touched}\n\n"
        "## Evidence\n\n"
        f"{checks}\n\n"
        "## Blocking Reasons\n\n"
        f"{blockers}\n\n"
        "## Safety\n\n"
        "- Offline proposal only.\n"
        "- No Git, GitHub, filesystem, registry, install, deploy, approval, "
        "or runtime action performed.\n"
    )


def _authoritative_package(
    handoff_creation: WorkflowHandoffCreation,
) -> PRPackageProposal:
    handoff = handoff_creation.handoff
    job = handoff.job
    capability_slug = _slug(job.capability_id)
    job_slug = _slug(job.job_id)
    readiness = READY if handoff.approvable else BLOCKED
    blockers = () if handoff.approvable else handoff.blocking_reasons
    return PRPackageProposal(
        package_id=f"{job_slug}-pr-package",
        job_id=job.job_id,
        capability_id=job.capability_id,
        base_sha=job.base_sha,
        target_branch="main",
        proposed_branch_name=(
            f"codex/v0.4c/{capability_slug}/{job_slug}-pr-package"
        ),
        proposed_commit_title=(
            f"feat({job.capability_id}): package human handoff"
        ),
        proposed_pr_title=(
            f"feat({job.capability_id}): package human handoff"
        ),
        proposed_pr_body=_pr_body(handoff_creation),
        changed_files=_changed_files(handoff_creation),
        evidence=_evidence(handoff_creation),
        risks=_risks(),
        rollback_notes=_rollback_notes(),
        human_checklist=_checklist(handoff_creation),
        readiness_status=readiness,
        blocking_reasons=blockers,
    )


def _expected_reasons(
    handoff_creation: WorkflowHandoffCreation,
    pr_package: Optional[PRPackageProposal],
) -> tuple:
    if not _handoff_is_created(handoff_creation):
        reasons = handoff_creation.blocking_reasons
        return _stable_reasons(reasons or (_INVALID_HANDOFF_REASON,))
    if pr_package is None:
        return (_INVALID_HANDOFF_REASON,)
    return _stable_reasons(pr_package.blocking_reasons)


def _source_binding(handoff_creation: WorkflowHandoffCreation) -> dict:
    handoff = handoff_creation.handoff
    return {
        "handoff": None if handoff is None else handoff.to_dict(),
        "workflow_handoff": {
            "approvable": handoff_creation.approvable,
            "created": handoff_creation.created,
            "schema_version": handoff_creation.schema_version,
            "status": handoff_creation.status,
        },
    }


@dataclass(frozen=True)
class WorkflowPRPackageCreation:
    """Immutable result of one guarded PR package proposal attempt."""

    handoff_creation: WorkflowHandoffCreation
    pr_package: Optional[PRPackageProposal]
    workflow: WorkflowPlan
    status: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    created: bool = field(init=False)
    ready_for_pr: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    offline_only: bool = field(default=True, init=False)
    proposal_only: bool = field(default=True, init=False)
    github_action_performed: bool = field(default=False, init=False)
    git_action_performed: bool = field(default=False, init=False)
    human_decision_recorded: bool = field(default=False, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.handoff_creation, WorkflowHandoffCreation):
            raise WorkflowPRPackageError(
                "handoff_creation must be a WorkflowHandoffCreation"
            )
        if self.pr_package is not None and not isinstance(
            self.pr_package,
            PRPackageProposal,
        ):
            raise WorkflowPRPackageError(
                "pr_package must be a PRPackageProposal or None"
            )
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowPRPackageError("workflow must be a WorkflowPlan")
        if self.status not in RESULT_STATUSES:
            raise WorkflowPRPackageError(
                f"unsupported workflow PR package status: {self.status!r}"
            )

        eligible = _handoff_is_created(self.handoff_creation)
        created = eligible and self.pr_package is not None
        expected_status = (
            STATUS_PR_PACKAGE_CREATED if created else STATUS_NOT_CREATED
        )
        if self.status != expected_status:
            raise WorkflowPRPackageError(
                "result status does not match input readiness"
            )

        expected_reasons = _expected_reasons(
            self.handoff_creation,
            self.pr_package,
        )
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != expected_reasons:
            raise WorkflowPRPackageError(
                "blocking reasons do not match PR package result"
            )

        if self.workflow != self.handoff_creation.workflow:
            raise WorkflowPRPackageError(
                "PR package creation cannot advance the workflow"
            )

        if created:
            if self.pr_package != _authoritative_package(
                self.handoff_creation
            ):
                raise WorkflowPRPackageError(
                    "PR package does not match the authoritative handoff"
                )
        elif self.pr_package is not None:
            raise WorkflowPRPackageError(
                "ineligible handoff cannot contain a PR package"
            )

        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "created", created)
        object.__setattr__(
            self,
            "ready_for_pr",
            bool(
                self.pr_package
                and self.pr_package.readiness_status == READY
                and not self.pr_package.blocking_reasons
            ),
        )
        object.__setattr__(
            self,
            "next_allowed_steps",
            self.workflow.next_allowed_steps,
        )

        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_PR_PACKAGE_SUMMARY_BYTES
        ):
            raise WorkflowPRPackageError(
                "workflow PR package summary exceeds "
                f"{MAX_WORKFLOW_PR_PACKAGE_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic sanitized PR package creation metadata."""
        return {
            "authority": {
                "autonomous": self.autonomous,
                "git_action_performed": self.git_action_performed,
                "github_action_performed": self.github_action_performed,
                "human_decision_recorded": self.human_decision_recorded,
                "offline_only": self.offline_only,
                "proposal_only": self.proposal_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "created": self.created,
            "input_status": {
                "workflow_handoff": self.handoff_creation.status,
            },
            "next_allowed_steps": list(self.next_allowed_steps),
            "pr_package": (
                None if self.pr_package is None else self.pr_package.to_dict()
            ),
            "ready_for_pr": self.ready_for_pr,
            "schema_version": self.schema_version,
            "source_binding": _source_binding(self.handoff_creation),
            "status": self.status,
            "workflow": self.workflow.to_dict(),
        }

    def summary(self) -> str:
        """Return stable bounded JSON for offline human inspection."""
        import json

        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"


def create_pr_package_from_workflow_handoff(
    handoff_creation: WorkflowHandoffCreation,
) -> WorkflowPRPackageCreation:
    """Create an offline PR package proposal from a human handoff result."""
    if not isinstance(handoff_creation, WorkflowHandoffCreation):
        raise WorkflowPRPackageError(
            "handoff_creation must be a WorkflowHandoffCreation"
        )

    if not _handoff_is_created(handoff_creation):
        return WorkflowPRPackageCreation(
            handoff_creation=handoff_creation,
            pr_package=None,
            workflow=handoff_creation.workflow,
            status=STATUS_NOT_CREATED,
            blocking_reasons=handoff_creation.blocking_reasons
            or (_INVALID_HANDOFF_REASON,),
        )

    try:
        pr_package = _authoritative_package(handoff_creation)
    except (PRPackageError, TypeError):
        return WorkflowPRPackageCreation(
            handoff_creation=handoff_creation,
            pr_package=None,
            workflow=handoff_creation.workflow,
            status=STATUS_NOT_CREATED,
            blocking_reasons=(_INVALID_HANDOFF_REASON,),
        )

    return WorkflowPRPackageCreation(
        handoff_creation=handoff_creation,
        pr_package=pr_package,
        workflow=handoff_creation.workflow,
        status=STATUS_PR_PACKAGE_CREATED,
        blocking_reasons=pr_package.blocking_reasons,
    )
