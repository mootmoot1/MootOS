"""Pure human-review-pending transition for MootOS V0.4C Slice 5.

This adapter records only the existing ``human_decision_pending`` workflow
step. It never records a human choice or performs filesystem, process,
network, Git, GitHub, backend, deployment, approval-execution, or runtime
actions.
"""

import json
from dataclasses import dataclass, field

from scripts.capability_build.handoff import (
    DECISION_APPROVE_FOR_PR,
    DECISION_REJECT,
    DECISION_REQUEST_CHANGES,
)
from scripts.capability_build.workflow import (
    STEP_HUMAN_DECISION_PENDING,
    WorkflowError,
    WorkflowPlan,
    record_workflow_step,
)
from scripts.capability_build.workflow_pr_package_renderer import (
    DISPOSITION_BLOCKED_INSPECTION_ONLY,
    DISPOSITION_NOT_RENDERED,
    DISPOSITION_READY_FOR_HUMAN_REVIEW,
    STATUS_PR_PACKAGE_RENDERED,
    WorkflowPRPackageRendering,
)


class WorkflowPRReviewError(ValueError):
    """Raised when a human-review-pending result is inconsistent."""


SCHEMA_VERSION = 1
STATUS_HUMAN_REVIEW_PENDING = "human_review_pending"
STATUS_NOT_PENDING = "not_pending"
RESULT_STATUSES = (
    STATUS_HUMAN_REVIEW_PENDING,
    STATUS_NOT_PENDING,
)

READY_DECISION_OPTIONS = (
    DECISION_APPROVE_FOR_PR,
    DECISION_REQUEST_CHANGES,
    DECISION_REJECT,
)
BLOCKED_DECISION_OPTIONS = (
    DECISION_REQUEST_CHANGES,
    DECISION_REJECT,
)
NO_DECISION_OPTIONS = ()

MAX_WORKFLOW_PR_REVIEW_SUMMARY_BYTES = 128 * 1024
_NOT_RENDERED_REASON = "PR package was not rendered for human review."
_TRANSITION_FAILED_REASON = "Human review pending transition failed closed."


def _stable_reasons(values: object) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowPRReviewError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowPRReviewError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowPRReviewError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _is_rendered(source: WorkflowPRPackageRendering) -> bool:
    return (
        source.status == STATUS_PR_PACKAGE_RENDERED
        and source.rendered
        and source.rendering is not None
        and source.disposition
        in (
            DISPOSITION_READY_FOR_HUMAN_REVIEW,
            DISPOSITION_BLOCKED_INSPECTION_ONLY,
        )
    )


def _expected_options(source: WorkflowPRPackageRendering) -> tuple:
    if not _is_rendered(source):
        return NO_DECISION_OPTIONS
    if source.disposition == DISPOSITION_READY_FOR_HUMAN_REVIEW:
        return READY_DECISION_OPTIONS
    return BLOCKED_DECISION_OPTIONS


def _transition(
    source: WorkflowPRPackageRendering,
) -> tuple:
    prior = source.workflow
    if not _is_rendered(source):
        return prior, STATUS_NOT_PENDING
    try:
        workflow = record_workflow_step(
            prior,
            STEP_HUMAN_DECISION_PENDING,
        )
    except (WorkflowError, TypeError, ValueError):
        return prior, STATUS_NOT_PENDING
    return workflow, STATUS_HUMAN_REVIEW_PENDING


def _expected_reasons(
    source: WorkflowPRPackageRendering,
    status: str,
) -> tuple:
    if status == STATUS_HUMAN_REVIEW_PENDING:
        return _stable_reasons(source.blocking_reasons)
    if not _is_rendered(source):
        return _stable_reasons(
            source.blocking_reasons or (_NOT_RENDERED_REASON,)
        )
    return (_TRANSITION_FAILED_REASON,)


def _source_binding(source: WorkflowPRPackageRendering) -> dict:
    creation = source.pr_package_creation
    package = creation.pr_package
    return {
        "job_id": None if package is None else package.job_id,
        "package_id": None if package is None else package.package_id,
        "package_rendering": {
            "disposition": source.disposition,
            "rendered": source.rendered,
            "schema_version": source.schema_version,
            "status": source.status,
        },
        "proposal_base_sha": None if package is None else package.base_sha,
    }


@dataclass(frozen=True)
class WorkflowPRReviewPending:
    """Immutable result of entering the existing human-review boundary."""

    source_rendering: WorkflowPRPackageRendering
    prior_workflow: WorkflowPlan
    workflow: WorkflowPlan
    status: str
    disposition: str
    decision_options: tuple
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    pending: bool = field(init=False)
    inspection_only: bool = field(init=False)
    human_decision_recorded: bool = field(default=False, init=False)
    approved: bool = field(default=False, init=False)
    offline_only: bool = field(default=True, init=False)
    proposal_only: bool = field(default=True, init=False)
    git_action_performed: bool = field(default=False, init=False)
    github_action_performed: bool = field(default=False, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(
            self.source_rendering,
            WorkflowPRPackageRendering,
        ):
            raise WorkflowPRReviewError(
                "source_rendering must be a WorkflowPRPackageRendering"
            )
        if not isinstance(self.prior_workflow, WorkflowPlan):
            raise WorkflowPRReviewError(
                "prior_workflow must be a WorkflowPlan"
            )
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowPRReviewError("workflow must be a WorkflowPlan")
        if self.status not in RESULT_STATUSES:
            raise WorkflowPRReviewError(
                f"unsupported human review status: {self.status!r}"
            )
        if self.disposition not in (
            DISPOSITION_READY_FOR_HUMAN_REVIEW,
            DISPOSITION_BLOCKED_INSPECTION_ONLY,
            DISPOSITION_NOT_RENDERED,
        ):
            raise WorkflowPRReviewError(
                f"unsupported review disposition: {self.disposition!r}"
            )
        if self.prior_workflow is not self.source_rendering.workflow:
            raise WorkflowPRReviewError(
                "prior workflow does not match source rendering"
            )

        expected_workflow, expected_status = _transition(
            self.source_rendering
        )
        if self.status != expected_status:
            raise WorkflowPRReviewError(
                "status does not match human review transition"
            )
        if self.workflow != expected_workflow:
            raise WorkflowPRReviewError(
                "workflow does not match the exact pending transition"
            )
        if self.disposition != self.source_rendering.disposition:
            raise WorkflowPRReviewError(
                "disposition does not match source rendering"
            )

        try:
            options = tuple(self.decision_options)
        except TypeError as error:
            raise WorkflowPRReviewError(
                "decision_options must be a sequence"
            ) from error
        if options != _expected_options(self.source_rendering):
            raise WorkflowPRReviewError(
                "decision options do not match review disposition"
            )
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != _expected_reasons(self.source_rendering, self.status):
            raise WorkflowPRReviewError(
                "blocking reasons do not match review transition"
            )

        object.__setattr__(self, "decision_options", options)
        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(
            self,
            "pending",
            self.status == STATUS_HUMAN_REVIEW_PENDING,
        )
        object.__setattr__(
            self,
            "inspection_only",
            self.disposition == DISPOSITION_BLOCKED_INSPECTION_ONLY,
        )

        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_PR_REVIEW_SUMMARY_BYTES
        ):
            raise WorkflowPRReviewError(
                "workflow PR review summary exceeds "
                f"{MAX_WORKFLOW_PR_REVIEW_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic sanitized human-review metadata."""
        return {
            "authority": {
                "approved": self.approved,
                "autonomous": self.autonomous,
                "git_action_performed": self.git_action_performed,
                "github_action_performed": self.github_action_performed,
                "human_decision_recorded": self.human_decision_recorded,
                "offline_only": self.offline_only,
                "proposal_only": self.proposal_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "decision_options": list(self.decision_options),
            "disposition": self.disposition,
            "inspection_only": self.inspection_only,
            "pending": self.pending,
            "prior_workflow": self.prior_workflow.to_dict(),
            "schema_version": self.schema_version,
            "source_binding": _source_binding(self.source_rendering),
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


def enter_human_review_pending(
    source: WorkflowPRPackageRendering,
) -> WorkflowPRReviewPending:
    """Record only the existing human-decision-pending workflow step."""
    if not isinstance(source, WorkflowPRPackageRendering):
        raise WorkflowPRReviewError(
            "source must be a WorkflowPRPackageRendering"
        )

    workflow, status = _transition(source)
    return WorkflowPRReviewPending(
        source_rendering=source,
        prior_workflow=source.workflow,
        workflow=workflow,
        status=status,
        disposition=source.disposition,
        decision_options=_expected_options(source),
        blocking_reasons=_expected_reasons(source, status),
    )
