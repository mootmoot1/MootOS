"""Pure review-bundle-to-handoff adapter for MootOS V0.4B Slice 11.

This module creates the existing inert human handoff package from an
authoritative Slice 10 result and records only ``handoff_created``. It does
not make a human decision, create a PR, use Git or networks, read or write
files, register or install capabilities, deploy, or exercise backend,
runtime, approval, or autonomous authority.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.capability_build.handoff import (
    HandoffError,
    HumanHandoffPackage,
    build_human_handoff,
)
from scripts.capability_build.workflow import (
    STEP_BRIEF_READY,
    STEP_BUNDLE_CREATED,
    STEP_EVIDENCE_ATTACHED,
    STEP_HANDOFF_CREATED,
    STEP_HUMAN_DECISION_PENDING,
    STEP_INTAKE_CHECKED,
    STEP_JOB_CREATED,
    STEP_REQUEST_RECEIVED,
    STEP_SCOPE_FROZEN,
    STEP_WORKER_RETURNED,
    WorkflowPlan,
    record_workflow_step,
)
from scripts.capability_build.workflow_bundle import (
    STATUS_BUNDLE_CREATED,
    WorkflowBundleCreation,
)


class WorkflowHandoffError(ValueError):
    """Raised when workflow-handoff state cannot be represented safely."""


SCHEMA_VERSION = 1
STATUS_HANDOFF_CREATED = "handoff_created"
STATUS_NOT_CREATED = "not_created"
RESULT_STATUSES = (
    STATUS_HANDOFF_CREATED,
    STATUS_NOT_CREATED,
)
MAX_WORKFLOW_HANDOFF_SUMMARY_BYTES = 128 * 1024

_INVALID_HANDOFF_REASON = "Human handoff creation failed closed."


def _stable_reasons(values: Any) -> tuple:
    if isinstance(values, (str, bytes)):
        raise WorkflowHandoffError("blocking_reasons must be a sequence")
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise WorkflowHandoffError(
            "blocking_reasons must be a sequence"
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise WorkflowHandoffError(
            "blocking_reasons must contain nonblank text"
        )
    return tuple(
        sorted(set(reasons), key=lambda reason: (reason.casefold(), reason))
    )


def _bundle_is_created(bundle_creation: WorkflowBundleCreation) -> bool:
    return (
        bundle_creation.status == STATUS_BUNDLE_CREATED
        and bundle_creation.created
        and bundle_creation.bundle is not None
        and bundle_creation.workflow.completed_steps
        == (
            STEP_REQUEST_RECEIVED,
            STEP_JOB_CREATED,
            STEP_SCOPE_FROZEN,
            STEP_BRIEF_READY,
            STEP_WORKER_RETURNED,
            STEP_INTAKE_CHECKED,
            STEP_EVIDENCE_ATTACHED,
            STEP_BUNDLE_CREATED,
        )
        and bundle_creation.workflow.next_allowed_steps
        == (STEP_HANDOFF_CREATED,)
    )


def _expected_reasons(
    bundle_creation: WorkflowBundleCreation,
    handoff: Optional[HumanHandoffPackage],
) -> tuple:
    if not _bundle_is_created(bundle_creation):
        return _stable_reasons(bundle_creation.blocking_reasons)
    if handoff is None:
        return (_INVALID_HANDOFF_REASON,)
    return _stable_reasons(handoff.blocking_reasons)


def _authoritative_handoff(
    bundle_creation: WorkflowBundleCreation,
) -> HumanHandoffPackage:
    return build_human_handoff(bundle_creation.bundle)


def _source_binding(
    bundle_creation: WorkflowBundleCreation,
) -> Optional[dict]:
    bundle = bundle_creation.bundle
    if bundle is None:
        return None
    return {
        "bundle": {
            "readiness_status": bundle.readiness_status,
            "review_only": bundle.review_only,
            "runtime_authority": bundle.runtime_authority,
            "schema_version": bundle.schema_version,
        },
        "evidence": (
            None if bundle.evidence is None else bundle.evidence.to_dict()
        ),
        "frozen_scope": bundle.frozen_scope.to_dict(),
        "intake": bundle.intake.to_dict(),
        "job": bundle.job.to_dict(),
    }


@dataclass(frozen=True)
class WorkflowHandoffCreation:
    """Immutable result of one guarded human-handoff creation attempt."""

    bundle_creation: WorkflowBundleCreation
    handoff: Optional[HumanHandoffPackage]
    workflow: WorkflowPlan
    status: str
    blocking_reasons: tuple
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    created: bool = field(init=False)
    approvable: bool = field(init=False)
    next_allowed_steps: tuple = field(init=False)
    handoff_only: bool = field(default=True, init=False)
    human_decision_recorded: bool = field(default=False, init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bundle_creation, WorkflowBundleCreation):
            raise WorkflowHandoffError(
                "bundle_creation must be a WorkflowBundleCreation"
            )
        if self.handoff is not None and not isinstance(
            self.handoff, HumanHandoffPackage
        ):
            raise WorkflowHandoffError(
                "handoff must be a HumanHandoffPackage or None"
            )
        if not isinstance(self.workflow, WorkflowPlan):
            raise WorkflowHandoffError("workflow must be a WorkflowPlan")
        if self.status not in RESULT_STATUSES:
            raise WorkflowHandoffError(
                f"unsupported workflow-handoff status: {self.status!r}"
            )

        eligible = _bundle_is_created(self.bundle_creation)
        created = eligible and self.handoff is not None
        expected_status = (
            STATUS_HANDOFF_CREATED if created else STATUS_NOT_CREATED
        )
        if self.status != expected_status:
            raise WorkflowHandoffError(
                "result status does not match input readiness"
            )

        expected_reasons = _expected_reasons(
            self.bundle_creation,
            self.handoff,
        )
        reasons = _stable_reasons(self.blocking_reasons)
        if reasons != expected_reasons:
            raise WorkflowHandoffError(
                "blocking reasons do not match handoff result"
            )

        if created:
            if self.handoff != _authoritative_handoff(
                self.bundle_creation
            ):
                raise WorkflowHandoffError(
                    "handoff does not match the authoritative review bundle"
                )
            expected_workflow = record_workflow_step(
                self.bundle_creation.workflow,
                STEP_HANDOFF_CREATED,
            )
            if self.workflow != expected_workflow:
                raise WorkflowHandoffError(
                    "created workflow must record exactly handoff_created"
                )
            if self.workflow.next_allowed_steps != (
                STEP_HUMAN_DECISION_PENDING,
            ):
                raise WorkflowHandoffError(
                    "created workflow must allow only "
                    "human_decision_pending next"
                )
        else:
            if self.handoff is not None:
                raise WorkflowHandoffError(
                    "ineligible bundle cannot contain a human handoff"
                )
            if self.workflow != self.bundle_creation.workflow:
                raise WorkflowHandoffError(
                    "failed handoff creation cannot advance the workflow"
                )

        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "created", created)
        object.__setattr__(
            self,
            "approvable",
            bool(self.handoff and self.handoff.approvable),
        )
        object.__setattr__(
            self,
            "next_allowed_steps",
            self.workflow.next_allowed_steps,
        )

        if len(self.summary().encode("utf-8")) > (
            MAX_WORKFLOW_HANDOFF_SUMMARY_BYTES
        ):
            raise WorkflowHandoffError(
                "workflow-handoff summary exceeds "
                f"{MAX_WORKFLOW_HANDOFF_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic sanitized handoff and source metadata."""
        return {
            "approvable": self.approvable,
            "authority": {
                "autonomous": self.autonomous,
                "handoff_only": self.handoff_only,
                "human_decision_recorded": (
                    self.human_decision_recorded
                ),
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "created": self.created,
            "handoff": (
                None if self.handoff is None else self.handoff.to_dict()
            ),
            "input_status": {
                "workflow_bundle": self.bundle_creation.status,
            },
            "next_allowed_steps": list(self.next_allowed_steps),
            "schema_version": self.schema_version,
            "source_binding": _source_binding(self.bundle_creation),
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


def create_handoff_from_workflow_bundle(
    bundle_creation: WorkflowBundleCreation,
) -> WorkflowHandoffCreation:
    """Create the existing human handoff and record handoff_created."""
    if not isinstance(bundle_creation, WorkflowBundleCreation):
        raise WorkflowHandoffError(
            "bundle_creation must be a WorkflowBundleCreation"
        )

    if not _bundle_is_created(bundle_creation):
        return WorkflowHandoffCreation(
            bundle_creation=bundle_creation,
            handoff=None,
            workflow=bundle_creation.workflow,
            status=STATUS_NOT_CREATED,
            blocking_reasons=bundle_creation.blocking_reasons,
        )

    try:
        handoff = _authoritative_handoff(bundle_creation)
    except (HandoffError, TypeError):
        return WorkflowHandoffCreation(
            bundle_creation=bundle_creation,
            handoff=None,
            workflow=bundle_creation.workflow,
            status=STATUS_NOT_CREATED,
            blocking_reasons=(_INVALID_HANDOFF_REASON,),
        )

    workflow = record_workflow_step(
        bundle_creation.workflow,
        STEP_HANDOFF_CREATED,
    )
    return WorkflowHandoffCreation(
        bundle_creation=bundle_creation,
        handoff=handoff,
        workflow=workflow,
        status=STATUS_HANDOFF_CREATED,
        blocking_reasons=handoff.blocking_reasons,
    )
