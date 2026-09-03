"""Authoritative PR review decision binding for MootOS V0.4C Slice 7."""

import json
from dataclasses import dataclass, field
from typing import Optional

from scripts.capability_build.handoff import DECISION_APPROVE_FOR_PR
from scripts.capability_build.pr_review_decision import PRReviewDecisionInput
from scripts.capability_build.workflow import WorkflowPlan
from scripts.capability_build.workflow_pr_review import (
    STATUS_HUMAN_REVIEW_PENDING,
    WorkflowPRReviewPending,
)


class WorkflowPRDecisionError(ValueError):
    """Raised when decision binding metadata is inconsistent."""


STATUS_DECISION_RECORDED = "decision_recorded"
STATUS_NOT_RECORDED = "not_recorded"
MAX_WORKFLOW_PR_DECISION_SUMMARY_BYTES = 128 * 1024
_IDENTITY_REASON = "Decision source identity does not match review."
_UNAVAILABLE_REASON = "Supplied decision is not available for this review."
_NOT_PENDING_REASON = "Human review is not pending."


def _identity(review, supplied):
    package = review.source_rendering.pr_package_creation.pr_package
    if package is None:
        return False
    return (
        supplied.job_id == package.job_id
        and supplied.package_id == package.package_id
        and supplied.proposal_base_sha == package.base_sha
    )


def _reason(review, supplied):
    if review.status != STATUS_HUMAN_REVIEW_PENDING or not review.pending:
        return _NOT_PENDING_REASON
    if not _identity(review, supplied):
        return _IDENTITY_REASON
    if supplied.decision not in review.decision_options:
        return _UNAVAILABLE_REASON
    return None


@dataclass(frozen=True)
class WorkflowPRDecisionRecording:
    """Immutable allowed human choice bound to an exact review chain."""

    review: WorkflowPRReviewPending
    supplied: PRReviewDecisionInput
    decision: Optional[str]
    status: str
    blocking_reasons: tuple
    workflow: WorkflowPlan
    decision_recorded: bool = field(init=False)
    eligible_for_pr_authorization: bool = field(init=False)
    publication_authorized: bool = field(default=False, init=False)
    action_prepared: bool = field(default=False, init=False)
    git_action_performed: bool = field(default=False, init=False)
    github_action_performed: bool = field(default=False, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(self.review, WorkflowPRReviewPending):
            raise WorkflowPRDecisionError(
                "review must be a WorkflowPRReviewPending"
            )
        if not isinstance(self.supplied, PRReviewDecisionInput):
            raise WorkflowPRDecisionError(
                "supplied must be a PRReviewDecisionInput"
            )
        reason = _reason(self.review, self.supplied)
        expected_status = (
            STATUS_DECISION_RECORDED if reason is None else STATUS_NOT_RECORDED
        )
        expected_decision = self.supplied.decision if reason is None else None
        expected_reasons = () if reason is None else (reason,)
        if self.status != expected_status:
            raise WorkflowPRDecisionError("status does not match binding")
        if self.decision != expected_decision:
            raise WorkflowPRDecisionError("decision does not match binding")
        if tuple(self.blocking_reasons) != expected_reasons:
            raise WorkflowPRDecisionError(
                "blocking reasons do not match binding"
            )
        if self.workflow is not self.review.workflow:
            raise WorkflowPRDecisionError("workflow must remain unchanged")
        recorded = reason is None
        object.__setattr__(self, "decision_recorded", recorded)
        object.__setattr__(
            self,
            "eligible_for_pr_authorization",
            recorded and self.decision == DECISION_APPROVE_FOR_PR,
        )
        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_PR_DECISION_SUMMARY_BYTES
        ):
            raise WorkflowPRDecisionError("decision summary exceeds bound")

    def to_dict(self):
        package = self.review.source_rendering.pr_package_creation.pr_package
        return {
            "authority": {
                "action_prepared": self.action_prepared,
                "autonomous": self.autonomous,
                "github_action_performed": self.github_action_performed,
                "git_action_performed": self.git_action_performed,
                "publication_authorized": self.publication_authorized,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "decision": self.decision,
            "decision_id": self.supplied.decision_id,
            "decision_recorded": self.decision_recorded,
            "eligible_for_pr_authorization": (
                self.eligible_for_pr_authorization
            ),
            "rationale": (
                self.supplied.rationale if self.decision_recorded else None
            ),
            "reviewer_id": (
                self.supplied.reviewer_id if self.decision_recorded else None
            ),
            "source_binding": {
                "job_id": None if package is None else package.job_id,
                "package_id": None if package is None else package.package_id,
                "proposal_base_sha": (
                    None if package is None else package.base_sha
                ),
                "review_disposition": self.review.disposition,
            },
            "status": self.status,
            "workflow": self.workflow.to_dict(),
        }

    def summary(self):
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False
        ) + "\n"


def record_pr_review_decision(review, supplied):
    if not isinstance(review, WorkflowPRReviewPending):
        raise WorkflowPRDecisionError(
            "review must be a WorkflowPRReviewPending"
        )
    if not isinstance(supplied, PRReviewDecisionInput):
        raise WorkflowPRDecisionError(
            "supplied must be a PRReviewDecisionInput"
        )
    reason = _reason(review, supplied)
    return WorkflowPRDecisionRecording(
        review=review,
        supplied=supplied,
        decision=supplied.decision if reason is None else None,
        status=(
            STATUS_DECISION_RECORDED
            if reason is None
            else STATUS_NOT_RECORDED
        ),
        blocking_reasons=() if reason is None else (reason,),
        workflow=review.workflow,
    )
