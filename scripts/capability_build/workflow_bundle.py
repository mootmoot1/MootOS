"""Pure evidence-to-review-bundle adapter for MootOS V0.4B Slice 10.

This module packages authoritative, already-produced records with the
existing review-bundle model and records only ``bundle_created``. It does
not create a handoff, read or write files, execute anything, use Git or
networks, register or install capabilities, deploy, or exercise backend,
runtime, or autonomous authority.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.capability_build.bundle import (
    READINESS_READY,
    BuildReviewBundle,
    BundleError,
    build_review_bundle,
)
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_BUNDLE_CREATED,
    STEP_EVIDENCE_ATTACHED,
    STEP_HANDOFF_CREATED,
    STEP_INTAKE_CHECKED,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    STEP_WORKER_RETURNED,
    WorkflowPlan,
    record_workflow_step,
)
from scripts.capability_build.workflow_evidence import (
    STATUS_EVIDENCE_ATTACHED,
    WorkflowEvidenceAttachment,
)


class WorkflowBundleError(ValueError):
    """Raised when workflow-bundle state cannot be represented safely."""


SCHEMA_VERSION = 1
STATUS_BUNDLE_CREATED = "bundle_created"
STATUS_NOT_CREATED = "not_created"
RESULT_STATUSES = (
    STATUS_BUNDLE_CREATED,
    STATUS_NOT_CREATED,
)
MAX_WORKFLOW_BUNDLE_SUMMARY_BYTES = 128 * 1024

_INVALID_BUNDLE_REASON = "Review bundle creation failed closed."


def _stable_reasons(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowBundleError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowBundleError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowBundleError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _evidence_is_attached(
    evidence_attachment: WorkflowEvidenceAttachment,
) -> bool:
    return (
        evidence_attachment.status == STATUS_EVIDENCE_ATTACHED
        and evidence_attachment.attached
        and evidence_attachment.evidence is not None
        and evidence_attachment.workflow.completed_steps
        == (
            STEP_REQUEST_RECEIVED,
            STEP_JOB_CREATED,
            STEP_SCOPE_FROZEN,
            STEP_BRIEF_READY,
            STEP_WORKER_RETURNED,
            STEP_INTAKE_CHECKED,
            STEP_EVIDENCE_ATTACHED,
        )
        and evidence_attachment.workflow.next_allowed_steps
        == (STEP_BUNDLE_CREATED,)
    )


def _bundle_reasons(
    evidence_attachment: WorkflowEvidenceAttachment,
    bundle: BuildReviewBundle,
) -> tuple:
    if bundle.readiness_status == READINESS_READY:
        return ()
    if evidence_attachment.blocking_reasons:
        return _stable_reasons(evidence_attachment.blocking_reasons)
    return (f"Review bundle is {bundle.readiness_status}.",)


def _expected_reasons(
    evidence_attachment: WorkflowEvidenceAttachment,
    bundle: Optional[BuildReviewBundle],
) -> tuple:
    if not _evidence_is_attached(evidence_attachment):
        return _stable_reasons(evidence_attachment.blocking_reasons)
    if bundle is None:
        return (_INVALID_BUNDLE_REASON,)
    return _bundle_reasons(evidence_attachment, bundle)


def _authoritative_bundle(
    evidence_attachment: WorkflowEvidenceAttachment,
) -> BuildReviewBundle:
    intake_check = evidence_attachment.intake_check
    job = intake_check.brief_ready.scope_freeze.creation.job
    return build_review_bundle(
        job,
        evidence_attachment.scope,
        evidence_attachment.intake,
        evidence_attachment.evidence.plan,
        evidence_attachment.evidence,
    )


@dataclass(frozen=True)
class WorkflowBundleCreation:
    """Immutable result of one guarded review-bundle creation attempt."""

    evidence_attachment: WorkflowEvidenceAttachment
    bundle: Optional[BuildReviewBundle]
    workflow: WorkflowPlan
    status: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    created: bool = field(init=False)
    ready_for_human_review: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(
            self.evidence_attachment,
            WorkflowEvidenceAttachment,
        ):
            raise WorkflowBundleError(
                "evidence_attachment must be a "
                "WorkflowEvidenceAttachment"
            )
        if self.bundle is not None and not isinstance(
            self.bundle, BuildReviewBundle
        ):
            raise WorkflowBundleError(
                "bundle must be a BuildReviewBundle or None"
            )
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowBundleError("workflow must be a WorkflowPlan")
        if self.status not in RESULT_STATUSES:
            raise WorkflowBundleError(
                f"unsupported workflow-bundle status: {self.status!r}"
            )

        eligible = _evidence_is_attached(self.evidence_attachment)
        created = eligible and self.bundle is not None
        expected_status = (
            STATUS_BUNDLE_CREATED if created else STATUS_NOT_CREATED
        )
        if self.status != expected_status:
            raise WorkflowBundleError(
                "result status does not match input readiness"
            )

        expected_reasons = _expected_reasons(
            self.evidence_attachment,
            self.bundle,
        )
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != expected_reasons:
            raise WorkflowBundleError(
                "blocking reasons do not match bundle result"
            )

        if created:
            if self.bundle != _authoritative_bundle(
                self.evidence_attachment
            ):
                raise WorkflowBundleError(
                    "bundle does not match authoritative workflow records"
                )
            expected_workflow = record_workflow_step(
                self.evidence_attachment.workflow,
                STEP_BUNDLE_CREATED,
            )
            if self.workflow != expected_workflow:
                raise WorkflowBundleError(
                    "created workflow must record exactly bundle_created"
                )
            if self.workflow.next_allowed_steps != (STEP_HANDOFF_CREATED,):
                raise WorkflowBundleError(
                    "created workflow must allow only handoff_created next"
                )
        else:
            if self.bundle is not None:
                raise WorkflowBundleError(
                    "unattached evidence cannot contain a review bundle"
                )
            if self.workflow != self.evidence_attachment.workflow:
                raise WorkflowBundleError(
                    "failed bundle creation cannot advance the workflow"
                )

        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "created", created)
        object.__setattr__(
            self,
            "ready_for_human_review",
            bool(
                self.bundle
                and self.bundle.readiness_status == READINESS_READY
            ),
        )
        object.__setattr__(
            self,
            "next_allowed_steps",
            self.workflow.next_allowed_steps,
        )

        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_BUNDLE_SUMMARY_BYTES
        ):
            raise WorkflowBundleError(
                "workflow-bundle summary exceeds "
                f"{MAX_WORKFLOW_BUNDLE_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic existing bundle data and workflow metadata."""
        return {
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "bundle": None if self.bundle is None else self.bundle.to_dict(),
            "created": self.created,
            "input_status": {
                "workflow_evidence": self.evidence_attachment.status,
            },
            "next_allowed_steps": list(self.next_allowed_steps),
            "ready_for_human_review": self.ready_for_human_review,
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


def create_bundle_from_workflow_evidence(
    evidence_attachment: WorkflowEvidenceAttachment,
) -> WorkflowBundleCreation:
    """Create the existing review bundle and record bundle_created."""
    if not isinstance(
        evidence_attachment,
        WorkflowEvidenceAttachment,
    ):
        raise WorkflowBundleError(
            "evidence_attachment must be a WorkflowEvidenceAttachment"
        )

    if not _evidence_is_attached(evidence_attachment):
        return WorkflowBundleCreation(
            evidence_attachment=evidence_attachment,
            bundle=None,
            workflow=evidence_attachment.workflow,
            status=STATUS_NOT_CREATED,
            blocking_reasons=evidence_attachment.blocking_reasons,
        )

    try:
        bundle = _authoritative_bundle(evidence_attachment)
    except (BundleError, TypeError, ValueError):
        return WorkflowBundleCreation(
            evidence_attachment=evidence_attachment,
            bundle=None,
            workflow=evidence_attachment.workflow,
            status=STATUS_NOT_CREATED,
            blocking_reasons=(_INVALID_BUNDLE_REASON,),
        )

    workflow = record_workflow_step(
        evidence_attachment.workflow,
        STEP_BUNDLE_CREATED,
    )
    return WorkflowBundleCreation(
        evidence_attachment=evidence_attachment,
        bundle=bundle,
        workflow=workflow,
        status=STATUS_BUNDLE_CREATED,
        blocking_reasons=_bundle_reasons(evidence_attachment, bundle),
    )
